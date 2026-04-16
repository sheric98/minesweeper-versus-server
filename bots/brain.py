from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from solver import (
    BasicSolver,
    PerfectSolver,
    ProbabilisticSolver,
    Solver,
    SubsetSolver,
)
from solver.solver_types import Cell

from .config import BotConfig
from .flood_fill import flood_fill_reveal


_PROBABILISTIC_TIERS: frozenset[str] = frozenset({"probabilistic", "perfect"})
_ALL_REGIONS: tuple[str, ...] = ("frontier", "near_frontier", "deep")


def _build_solver(tier: str, rows: int, cols: int, mine_count: int) -> Solver:
    if tier == "basic":
        return BasicSolver(rows, cols, mine_count)
    if tier == "subset":
        return SubsetSolver(rows, cols, mine_count)
    if tier == "probabilistic":
        return ProbabilisticSolver(rows, cols, mine_count)
    if tier == "perfect":
        return PerfectSolver(rows, cols, mine_count)
    raise ValueError(f"Unknown solver tier: {tier}")


@dataclass
class MoveOutcome:
    """Result of applying a click against the ground-truth board."""

    kind: Literal["hit_mine", "revealed", "won"]
    revealed: dict[Cell, int] = field(default_factory=dict)


class BotBrain:
    """Pure decision layer: given current knowledge, pick the next cell to click.

    Owns a solver instance and a private view of the board state. Callers
    drive the loop via `next_move()` / `observe_result()`; the brain performs
    no I/O and no sleeping.
    """

    def __init__(
        self,
        cfg: BotConfig,
        board: list[list[dict]],
        start_cell: Cell,
        rows: int,
        cols: int,
        mine_count: int,
        rng: random.Random | None = None,
    ):
        self.cfg = cfg
        self.board = board
        self.rows = rows
        self.cols = cols
        self.mine_count = mine_count
        self.rng = rng if rng is not None else random.Random()

        self.solver: Solver = _build_solver(cfg.solver_tier, rows, cols, mine_count)
        self.state: list[list] = [["unknown"] * cols for _ in range(rows)]
        self.safe_queue: deque[Cell] = deque()
        self._queued: set[Cell] = set()
        self._bot_known_mines: set[Cell] = set()
        self._last_probs: dict[Cell, float] = {}
        self._total_safe = rows * cols - mine_count
        self._revealed_count = 0

        # Seed from the match's starting square — treat exactly like a reveal.
        # `_pending_reveal` must exist before _apply_reveal runs.
        self._pending_reveal: dict[Cell, int] = {}
        initial = self._apply_reveal(start_cell)
        # Snapshot the starting cascade so the runner can emit it over the
        # transport on the first step (mirroring a human's first-click reveal).
        self.initial_reveal: list[Cell] = list(initial.keys())

    # ------------------------------------------------------------------ API

    def next_move(self) -> Cell | None:
        """Return the next cell to click, or None if the game is already won
        or the brain has no legal move left."""
        # 1. Feed reveals accumulated since the last tick into the solver and
        #    enqueue newly-deduced safe cells (modulo p_skip_deduction).
        if self._pending_reveal:
            result = self.solver.find_solved_squares(self._pending_reveal)
            self._pending_reveal = {}
            self._last_probs = result.probs
            for cell in result.safe:
                if cell in self._queued:
                    continue
                if (
                    self.cfg.p_skip_deduction > 0
                    and self.rng.random() < self.cfg.p_skip_deduction
                ):
                    # Drop this deduction — forces the brain to guess instead.
                    continue
                self.safe_queue.append(cell)
                self._queued.add(cell)

        if self._revealed_count >= self._total_safe:
            return None

        # 2. Mistake overrides run BEFORE consuming safe_queue. First one to
        #    fire wins; if it produces no cell, fall through.
        if self.cfg.p_random_cell > 0 and self.rng.random() < self.cfg.p_random_cell:
            cell = self._random_unknown()
            if cell is not None:
                return cell
        elif self.cfg.p_wrong_cell > 0 and self.rng.random() < self.cfg.p_wrong_cell:
            cell = self._wrong_cell_guess()
            if cell is not None:
                return cell

        # 3. Prefer a proven-safe cell if we have one.
        while self.safe_queue:
            cell = self.safe_queue.popleft()
            self._queued.discard(cell)
            r, c = cell
            if self.state[r][c] != "unknown":
                continue
            if cell in self._bot_known_mines:
                continue
            return cell

        # 4. Must guess.
        return self._choose_guess()

    def sample_delay(self, rng: random.Random | None = None) -> float:
        r = rng if rng is not None else self.rng
        return r.uniform(self.cfg.min_move_delay, self.cfg.max_move_delay)

    def observe_result(self, cell: Cell) -> MoveOutcome:
        """Apply the outcome of clicking `cell` against ground truth and
        update internal state so the next `next_move()` reflects it."""
        r, c = cell
        if self.board[r][c]["isMine"]:
            # Mimic the real game: bot dies but match continues. Remember the
            # mine internally so we never re-click it. We intentionally do
            # NOT feed this to the solver — solvers have no interface to
            # accept externally-learned mines, and excluding it from our
            # own candidate pool is enough for correctness.
            self._bot_known_mines.add(cell)
            self.state[r][c] = "mine"
            return MoveOutcome(kind="hit_mine")

        revealed = self._apply_reveal(cell)
        if self._revealed_count >= self._total_safe:
            return MoveOutcome(kind="won", revealed=revealed)
        return MoveOutcome(kind="revealed", revealed=revealed)

    # ------------------------------------------------------------- Internals

    def _apply_reveal(self, cell: Cell) -> dict[Cell, int]:
        """Flood-fill from `cell`, update state + pending-reveal buffer."""
        revealed = flood_fill_reveal(self.board, self.state, cell)
        self._revealed_count += len(revealed)
        self._pending_reveal.update(revealed)
        return revealed

    def _is_pickable(self, cell: Cell) -> bool:
        r, c = cell
        return self.state[r][c] == "unknown" and cell not in self._bot_known_mines

    def _filter_region(self, cells) -> list[Cell]:
        return [c for c in cells if self._is_pickable(c)]

    def _all_unknowns(self) -> list[Cell]:
        out: list[Cell] = []
        for r in range(self.rows):
            row = self.state[r]
            for c in range(self.cols):
                cell = (r, c)
                if row[c] == "unknown" and cell not in self._bot_known_mines:
                    out.append(cell)
        return out

    def _random_unknown(self) -> Cell | None:
        pool = self._all_unknowns()
        if not pool:
            return None
        return self.rng.choice(pool)

    def _partitioned_regions(self) -> tuple[list[Cell], list[Cell], list[Cell]]:
        """Snapshot of the solver's frontier partition, filtered to cells
        the brain is still willing to click."""
        fs = self.solver.get_frontier_sets()
        return (
            self._filter_region(fs.frontier),
            self._filter_region(fs.near_frontier),
            self._filter_region(fs.deep),
        )

    def _choose_guess(self) -> Cell | None:
        frontier, near_frontier, deep = self._partitioned_regions()
        if self.cfg.solver_tier in _PROBABILISTIC_TIERS:
            return self._guess_probabilistic(frontier, near_frontier, deep)
        return self._guess_non_probabilistic(frontier, near_frontier, deep)

    def _guess_probabilistic(
        self,
        frontier: list[Cell],
        near_frontier: list[Cell],
        deep: list[Cell],
    ) -> Cell | None:
        probs = self._last_probs
        off_frontier = near_frontier + deep

        # The probabilistic/perfect solvers fill `probs` for every currently
        # unknown cell, including non-frontier cells via the global density
        # fallback. So we can read the off-frontier density from any such
        # cell's entry in probs directly.
        if frontier:
            frontier_min = min(probs.get(c, 1.0) for c in frontier)
        else:
            frontier_min = float("inf")

        if off_frontier:
            # Any off-frontier cell has the density value.
            off_density = probs.get(off_frontier[0], 1.0)
        else:
            off_density = float("inf")

        if frontier and frontier_min <= off_density:
            best = [c for c in frontier if probs.get(c, 1.0) == frontier_min]
            return self.rng.choice(best)

        pick_region = self.cfg.off_frontier_pick
        if pick_region == "near_frontier" and near_frontier:
            return self.rng.choice(near_frontier)
        if pick_region == "deep" and deep:
            return self.rng.choice(deep)
        if off_frontier:
            return self.rng.choice(off_frontier)
        # Nothing off-frontier; fall back to frontier if any, else anywhere.
        if frontier:
            best = [c for c in frontier if probs.get(c, 1.0) == frontier_min]
            return self.rng.choice(best)
        return self._random_unknown()

    def _guess_non_probabilistic(
        self,
        frontier: list[Cell],
        near_frontier: list[Cell],
        deep: list[Cell],
    ) -> Cell | None:
        pools = {
            "frontier": frontier,
            "near_frontier": near_frontier,
            "deep": deep,
        }
        preferred = pools.get(self.cfg.blind_guess_region) or []
        if preferred:
            return self.rng.choice(preferred)
        # Preferred region empty → any unknown cell.
        return self._random_unknown()

    def _wrong_cell_guess(self) -> Cell | None:
        """p_wrong_cell: deliberately pick a worse-than-optimal cell.

        - Probabilistic tiers: sample a frontier cell weighted by its mine
          probability (so highly-dangerous cells are picked more often).
        - Non-probabilistic tiers: blind-guess from a non-preferred region.
        """
        frontier, near_frontier, deep = self._partitioned_regions()

        if self.cfg.solver_tier in _PROBABILISTIC_TIERS:
            if not frontier:
                return self._random_unknown()
            weights = [max(self._last_probs.get(c, 0.0), 0.0) for c in frontier]
            total = sum(weights)
            if total <= 0:
                return self.rng.choice(frontier)
            r = self.rng.random() * total
            acc = 0.0
            for cell, w in zip(frontier, weights):
                acc += w
                if r <= acc:
                    return cell
            return frontier[-1]

        # Non-probabilistic: pick uniformly from any region other than the
        # configured preferred one.
        pools = {
            "frontier": frontier,
            "near_frontier": near_frontier,
            "deep": deep,
        }
        other_regions = [r for r in _ALL_REGIONS if r != self.cfg.blind_guess_region]
        self.rng.shuffle(other_regions)
        for region in other_regions:
            if pools[region]:
                return self.rng.choice(pools[region])
        return self._random_unknown()
