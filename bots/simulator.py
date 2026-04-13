"""Head-to-head bot simulation on a shared board with a virtual clock.

Both bots see the same board and starting square. The simulator
interleaves their moves by picking whichever runner has the earlier
`next_action_at`, stepping it, and repeating until one wins (at which
point the other is cancelled). No real sleeps — a 1000-match tournament
runs in seconds.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from board_generator import generate_solvable_board
from config import ROWS, COLS, MINE_COUNT

from .brain import BotBrain
from .config import BotConfig
from .runner import BotRunner, SimTransport


@dataclass(frozen=True)
class SimMatchResult:
    winner: str
    loser: str
    time_winner_ms: int
    time_loser_ms: int
    deaths_winner: int
    deaths_loser: int
    moves_winner: int
    moves_loser: int


def simulate_match(
    cfg_a: BotConfig,
    cfg_b: BotConfig,
    *,
    difficulty: str = "expert",
    seed: int | None = None,
    board: list[list[dict]] | None = None,
    start_cell: tuple[int, int] | None = None,
) -> SimMatchResult:
    """Generate one board and run two bots against it on a virtual clock.

    Returns a `SimMatchResult` describing who won, elapsed virtual times,
    death counts, and move counts.

    If *board* and *start_cell* are provided, they are used directly
    (skipping board generation). This makes the result fully deterministic
    when combined with a fixed *seed*.
    """
    rng = random.Random(seed)

    if board is not None and start_cell is not None:
        start_row, start_col = start_cell
    else:
        start_row = rng.randrange(ROWS)
        start_col = rng.randrange(COLS)
        board, (start_row, start_col) = generate_solvable_board(
            start_row, start_col, difficulty=difficulty
        )

    # Derive independent RNGs so each bot's randomness is isolated but the
    # overall match is deterministic when seeded.
    rng_a = random.Random(rng.randint(0, 2**64))
    rng_b = random.Random(rng.randint(0, 2**64))

    brain_a = BotBrain(cfg_a, board, (start_row, start_col), ROWS, COLS, MINE_COUNT, rng=rng_a)
    brain_b = BotBrain(cfg_b, board, (start_row, start_col), ROWS, COLS, MINE_COUNT, rng=rng_b)

    transport_a = SimTransport()
    transport_b = SimTransport()

    runner_a = BotRunner(brain_a, transport_a, rng_a)
    runner_b = BotRunner(brain_b, transport_b, rng_b)

    # Virtual clock loop: always step the runner whose next action is sooner.
    while not runner_a.finished and not runner_b.finished:
        if runner_a.next_action_at <= runner_b.next_action_at:
            runner_a.step()
        else:
            runner_b.step()

    # One (or both, in a tie) finished. If one won, cancel the other.
    if runner_a.won:
        runner_b.cancel()
    elif runner_b.won:
        runner_a.cancel()
    else:
        # Both ran out of moves without winning — shouldn't happen on a
        # solvable board, but handle gracefully.
        if not runner_a.done:
            runner_a.cancel()
        if not runner_b.done:
            runner_b.cancel()

    res_a = runner_a.result()
    res_b = runner_b.result()

    if res_a.won:
        return SimMatchResult(
            winner=cfg_a.name,
            loser=cfg_b.name,
            time_winner_ms=res_a.time_ms,
            time_loser_ms=res_b.time_ms,
            deaths_winner=res_a.deaths,
            deaths_loser=res_b.deaths,
            moves_winner=res_a.moves,
            moves_loser=res_b.moves,
        )
    else:
        return SimMatchResult(
            winner=cfg_b.name,
            loser=cfg_a.name,
            time_winner_ms=res_b.time_ms,
            time_loser_ms=res_a.time_ms,
            deaths_winner=res_b.deaths,
            deaths_loser=res_a.deaths,
            moves_winner=res_b.moves,
            moves_loser=res_a.moves,
        )
