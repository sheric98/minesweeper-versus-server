"""Transport adapter that wires a `BotRunner` into a live `Match`.

The offline simulator uses `SimTransport`, which just records events into
memory. When a bot is playing a real multiplayer match, we instead want
every bot action to look exactly like a wire message sent over a real
WebSocket — i.e. the same thing `websocket_handler.py` would do for a
human. `WsTransport` does that by calling `match.handle_message` directly
with the bot's username, bypassing the WS framing entirely.

The runner does not know it is talking to a live match; it only knows it
has a `Transport` to emit into. That keeps the decision layer (brain) and
the event loop (runner) unchanged between offline simulation and live
play.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from solver.solver_types import Cell

if TYPE_CHECKING:
    from match import Match


class WsTransport:
    """Concrete `Transport` that routes bot actions into a live Match.

    Death-count bookkeeping lives here (not on the brain) because the
    protocol requires a monotonically-increasing `deathCount` on each
    `hit_mine` message, mirroring the counter that the frontend keeps.
    """

    def __init__(self, match: "Match", bot_username: str) -> None:
        self.match = match
        self.bot_username = bot_username
        self._deaths = 0

    def send_reveal(self, cells: list[Cell]) -> None:
        if not cells:
            return
        result_cells = [{"row": r, "col": c} for (r, c) in cells]
        self.match.handle_message(
            self.bot_username,
            {"type": "reveal", "resultCells": result_cells},
        )

    def send_hit_mine(self) -> None:
        self._deaths += 1
        self.match.handle_message(
            self.bot_username,
            {"type": "hit_mine", "deathCount": self._deaths},
        )

    def send_game_complete(self, time_ms: int) -> None:
        self.match.handle_message(
            self.bot_username,
            {"type": "game_complete", "timeMs": time_ms},
        )
