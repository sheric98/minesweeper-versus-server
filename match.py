import json
import random
import threading
import time

from board_generator import generate_solvable_board
from board_cache import get_cached_board
from board_encoder import encode_board
from session_tracker import tracker
from config import COUNTDOWN_SECONDS, DATABASE_URL, DIFFICULTY_WEIGHTS, ROWS, COLS


class Match:
    def __init__(self, match_id: str, player1: str, player2: str):
        self.match_id = match_id
        self.player1 = player1
        self.player2 = player2
        self.connections: dict[str, object] = {}  # username -> websocket
        self.user_ids: dict[str, str | None] = {}  # username -> user_id
        self.board = None
        self.starting_square = None
        self.start_time = None
        self.finished = False
        self.revealed_counts: dict[str, int] = {player1: 0, player2: 0}
        self.rematch_requests: set[str] = set()
        self.rematch_declined: bool = False
        self._lock = threading.Lock()

    def add_connection(self, username: str, ws, user_id: str | None = None):
        with self._lock:
            self.connections[username] = ws
            self.user_ids[username] = user_id
            both_connected = len(self.connections) == 2

        if both_connected:
            threading.Thread(target=self._run_match, daemon=True).start()

    def _run_match(self):
        """Run the match lifecycle in a background thread."""
        start_row = random.randrange(ROWS)
        start_col = random.randrange(COLS)
        difficulties, weights = zip(*DIFFICULTY_WEIGHTS)
        difficulty = random.choices(difficulties, weights=weights, k=1)[0]
        cached = get_cached_board(difficulty, start_row, start_col)
        if cached is not None:
            self.board = cached
            self.starting_square = (start_row, start_col)
        else:
            self.board, self.starting_square = generate_solvable_board(
                start_row, start_col, difficulty=difficulty
            )
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

        from matchmaking import invite_store
        invite_store.cancel_pending_for_user(self.player1)
        invite_store.cancel_pending_for_user(self.player2)

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

        # Compute Elo changes before sending game_over
        elo_changes = self._update_elo_ratings(winner)

        # Send personalized game_over to each player
        for uname, ws in self.connections.items():
            payload = {
                "type": "game_over",
                "winner": winner,
                "yourTimeMs": msg.get("timeMs", 0) if uname == username else 0,
                "opponentTimeMs": msg.get("timeMs", 0) if uname != username else 0,
            }
            if elo_changes and uname in elo_changes:
                payload["eloChange"] = elo_changes[uname]
            self._send(ws, payload)

        # Record head-to-head result if both players are Google-authenticated
        self._record_h2h_result(winner)

    def _record_h2h_result(self, winner: str):
        if not DATABASE_URL:
            return
        winner_id = self.user_ids.get(winner)
        loser = self.player2 if winner == self.player1 else self.player1
        loser_id = self.user_ids.get(loser)
        if not winner_id or not loser_id:
            return
        # Canonical ordering: player1_id < player2_id
        if winner_id < loser_id:
            p1_id, p2_id = winner_id, loser_id
            win_col = "player1_wins"
        else:
            p1_id, p2_id = loser_id, winner_id
            win_col = "player2_wins"
        try:
            from db import get_conn
            conn = get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        INSERT INTO head_to_head_records (player1_id, player2_id, {win_col})
                        VALUES (%s, %s, 1)
                        ON CONFLICT (player1_id, player2_id)
                        DO UPDATE SET {win_col} = head_to_head_records.{win_col} + 1,
                                      updated_at = now()
                    """, (p1_id, p2_id))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    def _update_elo_ratings(self, winner: str) -> dict | None:
        """Update Elo ratings for both players. Returns rating change info or None."""
        if not DATABASE_URL:
            return None
        winner_id = self.user_ids.get(winner)
        loser = self.player2 if winner == self.player1 else self.player1
        loser_id = self.user_ids.get(loser)
        if not winner_id or not loser_id:
            return None

        from elo import compute_rating_changes, DEFAULT_RATING
        from db import get_conn

        try:
            conn = get_conn()
            try:
                with conn.cursor() as cur:
                    # Ensure both players have rating rows
                    cur.execute(
                        "INSERT INTO elo_ratings (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
                        (winner_id,),
                    )
                    cur.execute(
                        "INSERT INTO elo_ratings (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
                        (loser_id,),
                    )
                    # Fetch current ratings with lock
                    cur.execute(
                        "SELECT user_id, rating FROM elo_ratings WHERE user_id IN (%s, %s) FOR UPDATE",
                        (winner_id, loser_id),
                    )
                    rows = {str(r[0]): r[1] for r in cur.fetchall()}
                    old_winner = rows.get(winner_id, DEFAULT_RATING)
                    old_loser = rows.get(loser_id, DEFAULT_RATING)

                    new_winner, new_loser = compute_rating_changes(old_winner, old_loser)

                    cur.execute(
                        "UPDATE elo_ratings SET rating = %s, wins = wins + 1, updated_at = now() WHERE user_id = %s",
                        (new_winner, winner_id),
                    )
                    cur.execute(
                        "UPDATE elo_ratings SET rating = %s, losses = losses + 1, updated_at = now() WHERE user_id = %s",
                        (new_loser, loser_id),
                    )
                conn.commit()
                return {
                    winner: {"oldRating": old_winner, "newRating": new_winner, "change": new_winner - old_winner},
                    loser: {"oldRating": old_loser, "newRating": new_loser, "change": new_loser - old_loser},
                }
            finally:
                conn.close()
        except Exception:
            return None

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
            # Mid-game disconnect: opponent wins (only record if game started)
            if self.start_time is not None:
                self._record_h2h_result(opponent)
                elo_changes = self._update_elo_ratings(opponent)
            else:
                elo_changes = None
            if opponent_ws:
                payload = {"type": "opponent_disconnected"}
                if elo_changes and opponent in elo_changes:
                    payload["eloChange"] = elo_changes[opponent]
                self._send(opponent_ws, payload)

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
