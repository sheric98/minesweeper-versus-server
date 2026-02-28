import json
import threading
import time

from board_generator import generate_solvable_board
from board_encoder import encode_board
from session_tracker import tracker
from config import COUNTDOWN_SECONDS


class Match:
    def __init__(self, match_id: str, player1: str, player2: str):
        self.match_id = match_id
        self.player1 = player1
        self.player2 = player2
        self.connections: dict[str, object] = {}  # username -> websocket
        self.board = None
        self.starting_square = None
        self.start_time = None
        self.finished = False
        self.revealed_counts: dict[str, int] = {player1: 0, player2: 0}
        self.rematch_requests: set[str] = set()
        self.rematch_declined: bool = False
        self._lock = threading.Lock()

    def add_connection(self, username: str, ws):
        with self._lock:
            self.connections[username] = ws
            both_connected = len(self.connections) == 2

        if both_connected:
            threading.Thread(target=self._run_match, daemon=True).start()

    def _run_match(self):
        """Run the match lifecycle in a background thread."""
        self.board, self.starting_square = generate_solvable_board()
        encoded = encode_board(self.board, self.match_id)

        # Send match_found to both
        for username, ws in self.connections.items():
            opponent = self.player2 if username == self.player1 else self.player1
            self._send(ws, {
                "type": "match_found",
                "matchId": self.match_id,
                "opponent": opponent,
                "startingSquare": list(self.starting_square),
            })

        tracker.set_in_game(self.player1, self.match_id)
        tracker.set_in_game(self.player2, self.match_id)

        # Countdown
        for i in range(COUNTDOWN_SECONDS, 0, -1):
            time.sleep(1)
            self._broadcast({"type": "countdown", "secondsRemaining": i})

        # Game start
        self.start_time = time.time()
        self._broadcast({"type": "game_start", "board": encoded})

    def _reset_for_rematch(self):
        """Reset match state for a new game. Connections stay intact."""
        self.board = None
        self.starting_square = None
        self.start_time = None
        self.finished = False
        self.revealed_counts = {self.player1: 0, self.player2: 0}
        self.rematch_requests = set()
        self.rematch_declined = False

    def handle_message(self, username: str, msg: dict):
        """Route a client message to the opponent."""
        msg_type = msg.get("type")

        # Rematch messages work when finished
        if msg_type == "rematch_request":
            self._handle_rematch_request(username)
            return
        if msg_type == "rematch_decline":
            self._handle_rematch_decline(username)
            return

        # Gameplay messages are ignored when finished
        if self.finished:
            return

        opponent = self.player2 if username == self.player1 else self.player1
        opponent_ws = self.connections.get(opponent)
        if not opponent_ws:
            return

        if msg_type in ("reveal", "chord"):
            result_cells = msg.get("resultCells", [])
            with self._lock:
                self.revealed_counts[username] = self.revealed_counts.get(username, 0) + len(result_cells)
                count = self.revealed_counts[username]
            self._send(opponent_ws, {
                "type": "opponent_progress",
                "cells": result_cells,
                "revealedCount": count,
            })

        elif msg_type == "hit_mine":
            self._send(opponent_ws, {
                "type": "opponent_hit_mine",
                "deathCount": msg.get("deathCount", 0),
            })

        elif msg_type == "game_complete":
            self._handle_completion(username, msg)

    def _handle_rematch_request(self, username: str):
        with self._lock:
            if not self.finished:
                return
            if self.rematch_declined:
                return
            self.rematch_requests.add(username)
            both_requested = len(self.rematch_requests) == 2

        if both_requested:
            self._broadcast({"type": "rematch_accepted"})
            self._reset_for_rematch()
            threading.Thread(target=self._run_match, daemon=True).start()
        else:
            opponent = self.player2 if username == self.player1 else self.player1
            opponent_ws = self.connections.get(opponent)
            if opponent_ws:
                self._send(opponent_ws, {"type": "rematch_requested", "by": username})

    def _handle_rematch_decline(self, username: str):
        with self._lock:
            if not self.finished:
                return
            self.rematch_declined = True

        opponent = self.player2 if username == self.player1 else self.player1
        opponent_ws = self.connections.get(opponent)
        if opponent_ws:
            self._send(opponent_ws, {"type": "rematch_declined"})

    def _handle_completion(self, username: str, msg: dict):
        with self._lock:
            if self.finished:
                return
            self.finished = True
            winner = username

        opponent = self.player2 if username == self.player1 else self.player1

        # Send personalized game_over to each player
        for uname, ws in self.connections.items():
            other = self.player2 if uname == self.player1 else self.player1
            self._send(ws, {
                "type": "game_over",
                "winner": winner,
                "yourTimeMs": msg.get("timeMs", 0) if uname == username else 0,
                "opponentTimeMs": msg.get("timeMs", 0) if uname != username else 0,
            })

    def handle_disconnect(self, username: str):
        opponent = self.player2 if username == self.player1 else self.player1
        opponent_ws = self.connections.get(opponent)

        with self._lock:
            was_finished = self.finished
            self.finished = True

        if was_finished:
            # Post-game disconnect: notify opponent rematch is off
            if opponent_ws:
                self._send(opponent_ws, {"type": "rematch_declined"})
                self._send(opponent_ws, {"type": "opponent_disconnected"})
        else:
            # Mid-game disconnect: opponent wins
            if opponent_ws:
                self._send(opponent_ws, {"type": "opponent_disconnected"})

        tracker.set_online(self.player1)
        tracker.set_online(self.player2)

    def _broadcast(self, msg: dict):
        for ws in self.connections.values():
            self._send(ws, msg)

    def _send(self, ws, msg: dict):
        try:
            ws.send(json.dumps(msg))
        except Exception:
            pass


class MatchManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._matches: dict[str, Match] = {}

    def create_match(self, match_id: str, player1: str, player2: str):
        match = Match(match_id, player1, player2)
        with self._lock:
            self._matches[match_id] = match

    def get_match(self, match_id: str) -> Match | None:
        with self._lock:
            return self._matches.get(match_id)

    def remove_match(self, match_id: str):
        with self._lock:
            self._matches.pop(match_id, None)


match_manager = MatchManager()
