"""Runner layer: drives a `BotBrain` through a match via a pluggable `Transport`.

The runner is intentionally step-based rather than blocking. Each call to
`step()` executes the next move at the runner's own virtual timestamp and
advances `next_action_at` by a fresh per-move delay. The simulator picks
whichever runner has the earliest `next_action_at` and steps it, interleaving
both bots on a single virtual clock with zero real sleeps. A future real-time
wrapper (e.g. `WsTransport`) can simply sleep until `next_action_at` before
each step.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

from config import DEATH_COOLDOWN_BASE_MS, DEATH_COOLDOWN_STEP_MS
from solver.solver_types import Cell

from .brain import BotBrain


class Transport(Protocol):
    """Match-protocol sink. Concrete implementations map these calls onto a
    SimTransport recorder, a WebSocket client, or anything else."""

    def send_reveal(self, cells: list[Cell]) -> None: ...
    def send_hit_mine(self) -> None: ...
    def send_game_complete(self, time_ms: int) -> None: ...


class SimTransport:
    """In-memory transport that records every event. Used by the simulator
    and unit tests; has no logic beyond append/assign."""

    def __init__(self) -> None:
        self.reveals: list[list[Cell]] = []
        self.hit_mine_count: int = 0
        self.completed_at_ms: int | None = None

    def send_reveal(self, cells: list[Cell]) -> None:
        self.reveals.append(list(cells))

    def send_hit_mine(self) -> None:
        self.hit_mine_count += 1

    def send_game_complete(self, time_ms: int) -> None:
        self.completed_at_ms = time_ms


@dataclass(frozen=True)
class BotMatchResult:
    won: bool
    time_ms: int
    deaths: int
    moves: int


class BotRunner:
    """Event-loop wrapper around a `BotBrain`.

    Holds no game logic of its own — it just schedules moves on a virtual
    clock, asks the brain what to click, applies the outcome, and forwards
    events to the `Transport`.
    """

    def __init__(
        self,
        brain: BotBrain,
        transport: Transport,
        rng: random.Random,
        *,
        start_time: float = 0.0,
    ) -> None:
        self.brain = brain
        self.transport = transport
        self.rng = rng
        self.next_action_at: float = start_time
        self.deaths: int = 0
        self.moves: int = 0
        self.done: bool = False
        self.won: bool = False
        self._finished_at: float | None = None

    @property
    def finished(self) -> bool:
        return self.done

    # ------------------------------------------------------------------ API

    def step(self) -> bool:
        """Execute one move at the currently scheduled time. Returns True if
        the runner wants to be stepped again, False once it is finished."""
        if self.done:
            return False

        cell = self.brain.next_move()
        if cell is None:
            # Board already fully revealed — treat as an immediate win.
            self._finish(won=True, at=self.next_action_at)
            return False

        outcome = self.brain.observe_result(cell)
        self.moves += 1

        if outcome.kind == "hit_mine":
            self.deaths += 1
            self.transport.send_hit_mine()
            # Escalating cooldown mirroring cooldownDuration() in the
            # frontend (minesweeper-web/app/lib/multiplayer-utils.ts).
            # Uses (self.deaths - 1) because self.deaths was just
            # incremented and the formula expects the pre-increment count.
            cooldown_s = (
                DEATH_COOLDOWN_BASE_MS
                + (self.deaths - 1) * DEATH_COOLDOWN_STEP_MS
            ) / 1000.0
            self.next_action_at += cooldown_s
        elif outcome.kind == "revealed":
            if outcome.revealed:
                self.transport.send_reveal(list(outcome.revealed.keys()))
        else:  # "won"
            if outcome.revealed:
                self.transport.send_reveal(list(outcome.revealed.keys()))
            self._finish(won=True, at=self.next_action_at)
            return False

        self.next_action_at += self.brain.sample_delay(self.rng)
        return True

    def cancel(self) -> None:
        """External stop (e.g. opponent already won). Does NOT emit any
        transport events — broadcasting the opponent's win is the caller's
        responsibility, not the loser's runner."""
        if self.done:
            return
        self.done = True
        self.won = False
        self._finished_at = self.next_action_at

    def run(self) -> BotMatchResult:
        """Drive `step()` in a tight loop until finished. Used for single-bot
        plays where no interleaving with another runner is needed."""
        while self.step():
            pass
        return self.result()

    def result(self) -> BotMatchResult:
        assert self.done, "BotRunner.result() called before the run finished"
        return BotMatchResult(
            won=self.won,
            time_ms=int((self._finished_at or 0.0) * 1000),
            deaths=self.deaths,
            moves=self.moves,
        )

    # ------------------------------------------------------------- Internals

    def _finish(self, *, won: bool, at: float) -> None:
        self.done = True
        self.won = won
        self._finished_at = at
        self.transport.send_game_complete(int(at * 1000))
