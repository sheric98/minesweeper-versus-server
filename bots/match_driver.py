"""Live-match driver for a single bot.

A `BotMatchDriver` attaches a duck-typed `BotConnection` to a real
`Match` in place of a WebSocket, then drives one or more games against a
human (or another bot) in a background thread. The driver's job is the
real-time glue between:

- The existing decision/event stack (`BotBrain` + `BotRunner`) which was
  built for the offline simulator with a virtual clock.
- The live `Match` object, which expects wire messages to arrive the same
  way a WebSocket handler would deliver them.

Unlike the simulator, the driver sleeps in wall-clock time between moves
— that is what makes bots feel human-paced rather than instant.

The driver is started from one of two call sites (wired up in parts 4/5
of the plan):

- `invite_responder.py` when a bot accepts a human invite.
- `queue_injector.py` when a human sits in the matchmaking queue long
  enough to be paired with a bot.

Part 3 intentionally does not wire those entry points; the driver is
exercised end-to-end from a REPL by constructing a `Match` by hand,
calling `driver.start()`, then attaching a real WebSocket for the human.
"""

from __future__ import annotations

import json
import queue
import random
import threading
import time
from typing import TYPE_CHECKING, Optional

from config import COLS, MINE_COUNT, ROWS
from session_tracker import tracker

from .brain import BotBrain
from .live_config import BOT_MATCH_START_TIMEOUT_S, BOT_REMATCH_P
from .registry import BotEntry
from .runner import BotRunner
from .ws_transport import WsTransport

if TYPE_CHECKING:
    from match import Match


# How long to wait for the match's broadcast of `game_over` after the
# runner has emitted its own `game_complete`. This is a pure safety net —
# in practice the broadcast happens synchronously during the transport
# call so the message is already enqueued by the time the runner returns.
_POST_WIN_DRAIN_TIMEOUT_S = 2.0

# Post-game window during which we wait for rematch resolution before
# giving up and detaching. Matches the "a few seconds of post-game lobby"
# that a human would see before closing the tab.
_POST_GAME_REMATCH_WAIT_S = 20.0


class BotConnection:
    """Duck-typed stand-in for a flask-sock WebSocket.

    `Match._send` only ever calls `ws.send(json_str)` and catches any
    exception, so implementing `send` is sufficient — no `receive`, no
    `close`, no framing. All messages are pushed onto the driver's queue
    for its worker thread to consume.
    """

    __slots__ = ("_driver",)

    def __init__(self, driver: "BotMatchDriver") -> None:
        self._driver = driver

    def send(self, payload: str) -> None:
        try:
            msg = json.loads(payload)
        except (TypeError, ValueError):
            return
        self._driver._enqueue_from_match(msg)


class BotMatchDriver:
    """One instance per bot-in-match.

    Lifecycle:
      1. Caller builds the driver and calls `start()`. This attaches the
         `BotConnection` to the match and spawns a daemon worker thread.
      2. The worker blocks on its inbound queue for `game_start`,
         enforcing a hard timeout so we don't deadlock if the human never
         connects.
      3. On `game_start` the worker builds a `BotBrain` + `BotRunner` +
         `WsTransport` and drives moves at real-time cadence, interrupted
         by any terminal messages from the match.
      4. On `game_over` / `opponent_disconnected` the runner is cancelled
         and the driver decides whether to request a rematch (§BOT_REMATCH_P).
      5. When the driver is done it detaches: returns the bot to the
         online tracker state and tells the match to treat the bot as
         disconnected, so match-level state (`finished`, opponent
         notification) converges on the same code path a real WS would
         hit.
    """

    def __init__(
        self,
        match: "Match",
        bot: BotEntry,
        *,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.match = match
        self.bot = bot
        self.username = bot.username
        self.rng = rng if rng is not None else random.Random()

        self._queue: "queue.Queue[dict]" = queue.Queue()
        self._conn = BotConnection(self)
        self._started = False
        self._detached = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ API

    def start(self) -> None:
        """Attach to the match and begin driving. Non-blocking."""
        if self._started:
            return
        self._started = True
        # Attach first so that when the human's real WebSocket arrives
        # next, `add_connection` sees both and kicks off `_run_match`.
        self.match.add_connection(
            self.username, self._conn, user_id=self.bot.user_id
        )
        self._thread = threading.Thread(
            target=self._run, name=f"bot-match-{self.username}", daemon=True
        )
        self._thread.start()

    def detach(self) -> None:
        """Best-effort cleanup. Safe to call more than once."""
        if self._detached:
            return
        self._detached = True
        try:
            self.match.handle_disconnect(self.username)
        except Exception:
            pass
        # `handle_disconnect` already flips both players to online via
        # `tracker.set_online`, but in the pre-`_run_match` window (only
        # the bot is attached) it may be a no-op for the opponent. This
        # defensive call is cheap and idempotent.
        try:
            tracker.set_online(self.username)
        except Exception:
            pass

    # -------------------------------------------------------- Match → driver

    def _enqueue_from_match(self, msg: dict) -> None:
        self._queue.put(msg)

    # ------------------------------------------------------------- Worker

    def _run(self) -> None:
        try:
            self._drive()
        except Exception:
            # Swallow — we don't want a driver crash to take the server
            # down. The bot will just detach and go back online.
            pass
        finally:
            self.detach()

    def _drive(self) -> None:
        # First game: wait for countdown + game_start (≈COUNTDOWN_SECONDS
        # after the human's WS connects). Budget the full start-timeout.
        while True:
            game_start = self._wait_for_game_start(BOT_MATCH_START_TIMEOUT_S)
            if game_start is None:
                return  # timed out or match aborted before starting

            outcome = self._play_one_game()
            if outcome == "opponent_disconnected":
                return

            # Decide whether to try for a rematch. Sending the decline
            # explicitly (rather than doing nothing) matches human
            # behavior — the opponent sees a clean "rematch declined"
            # notice instead of a stale post-game lobby.
            wants_rematch = self.rng.random() < BOT_REMATCH_P
            if not wants_rematch:
                try:
                    self.match.handle_message(
                        self.username, {"type": "rematch_decline"}
                    )
                except Exception:
                    pass
                return

            try:
                self.match.handle_message(
                    self.username, {"type": "rematch_request"}
                )
            except Exception:
                return
            # Loop around; `_wait_for_game_start` absorbs the interim
            # rematch_requested/accepted chatter and short-circuits on
            # decline or disconnect.

    # ------------------------------------------------------ Game-start wait

    def _wait_for_game_start(self, timeout: float) -> Optional[dict]:
        """Pull messages from the match until a `game_start` arrives or
        the match is aborted. Returns the game_start message, or None
        on timeout/abort."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                msg = self._queue.get(timeout=remaining)
            except queue.Empty:
                return None
            t = msg.get("type")
            if t == "game_start":
                return msg
            if t in ("opponent_disconnected", "rematch_declined"):
                return None
            # Ignore: match_found, countdown, rematch_requested, etc.

    # ----------------------------------------------------------- Game loop

    def _play_one_game(self) -> str:
        """Run the brain+runner against the live match until it ends.

        Returns one of:
          - "game_over": match broadcast game_over (either player won).
          - "opponent_disconnected": opponent (human) dropped.
          - "finished": runner reported a win but no terminal message
            arrived within the drain window (shouldn't happen in
            practice; defensive).
        """
        board = self.match.board
        starting_square = self.match.starting_square
        if board is None or starting_square is None:
            # Should not happen: game_start implies both are set by
            # `_run_match` before the broadcast. Abort defensively.
            return "game_over"

        brain = BotBrain(
            self.bot.cfg,
            board,
            tuple(starting_square),
            ROWS,
            COLS,
            MINE_COUNT,
            rng=self.rng,
        )
        transport = WsTransport(self.match, self.username)
        runner = BotRunner(brain, transport, self.rng, start_time=0.0)

        start_mono = time.monotonic()

        while True:
            terminal = self._drain_terminal()
            if terminal is not None:
                runner.cancel()
                return terminal

            more = runner.step()
            if not more:
                # Runner finished normally: it already called
                # `send_game_complete`, which synchronously went through
                # `_handle_completion` and broadcast game_over back to
                # us, so the terminal message should already be in the
                # queue.
                terminal = self._wait_terminal(_POST_WIN_DRAIN_TIMEOUT_S)
                return terminal or "finished"

            # Real-time pacing: the runner's virtual clock tracks when
            # it wants to fire next; we sleep wall-clock time until then,
            # but on the queue so a match message (e.g. opponent won)
            # interrupts us immediately.
            target = runner.next_action_at
            elapsed = time.monotonic() - start_mono
            wait_s = target - elapsed
            if wait_s <= 0:
                continue
            terminal = self._wait_terminal(wait_s)
            if terminal is not None:
                runner.cancel()
                return terminal

    # ------------------------------------------------------- Queue helpers

    @staticmethod
    def _classify_terminal(msg: dict) -> Optional[str]:
        t = msg.get("type")
        if t == "game_over":
            return "game_over"
        if t == "opponent_disconnected":
            return "opponent_disconnected"
        return None

    def _drain_terminal(self) -> Optional[str]:
        """Non-blocking: return a terminal tag if one is already queued."""
        while True:
            try:
                msg = self._queue.get_nowait()
            except queue.Empty:
                return None
            tag = self._classify_terminal(msg)
            if tag is not None:
                return tag
            # Non-terminal chatter (opponent_progress, opponent_hit_mine,
            # rematch_requested, etc.) — discard and keep draining.

    def _wait_terminal(self, timeout: float) -> Optional[str]:
        """Blocking: pull messages up to `timeout` seconds; return a
        terminal tag if one arrives, else None."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                msg = self._queue.get(timeout=remaining)
            except queue.Empty:
                return None
            tag = self._classify_terminal(msg)
            if tag is not None:
                return tag
