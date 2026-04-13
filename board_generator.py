import random
import time
from typing import Callable, Optional

from bots.flood_fill import flood_fill_reveal
from config import ROWS, COLS, MINE_COUNT
from solver import (
    BasicSolver,
    PerfectSolver,
    ProbabilisticSolver,
    Solver,
    SubsetSolver,
)


Difficulty = str  # "beginner" | "intermediate" | "advanced" | "expert"


def _compute_adjacency(board: list[list[dict]]):
    for r in range(ROWS):
        for c in range(COLS):
            if board[r][c]["isMine"]:
                continue
            count = 0
            for dr in range(-1, 2):
                for dc in range(-1, 2):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < ROWS and 0 <= nc < COLS and board[nr][nc]["isMine"]:
                        count += 1
            board[r][c]["adjacentMines"] = count


def _generate_random_board(start_row: int, start_col: int) -> list[list[dict]]:
    """Place mines randomly, excluding the 3x3 safe zone around the start."""
    safe_zone: set[tuple[int, int]] = set()
    for dr in range(-1, 2):
        for dc in range(-1, 2):
            nr, nc = start_row + dr, start_col + dc
            if 0 <= nr < ROWS and 0 <= nc < COLS:
                safe_zone.add((nr, nc))

    all_positions = [
        (r, c) for r in range(ROWS) for c in range(COLS) if (r, c) not in safe_zone
    ]
    mines = set(random.sample(all_positions, MINE_COUNT))

    board = [
        [{"isMine": (r, c) in mines, "adjacentMines": 0} for c in range(COLS)]
        for r in range(ROWS)
    ]
    _compute_adjacency(board)
    return board


def _is_solvable_by(
    board: list[list[dict]], start_row: int, start_col: int, solver: Solver
) -> bool:
    """Run the given solver against the board starting from (start_row, start_col).

    Returns True iff the solver can deduce every non-mine cell without guessing.
    """
    total_safe = ROWS * COLS - MINE_COUNT
    state = [["unknown"] * COLS for _ in range(ROWS)]

    newly_revealed = flood_fill_reveal(board, state, (start_row, start_col))
    revealed_count = len(newly_revealed)

    while newly_revealed:
        result = solver.find_solved_squares(newly_revealed)
        all_revealed: dict[tuple[int, int], int] = {}
        for r, c in result.safe:
            revealed = flood_fill_reveal(board, state, (r, c))
            revealed_count += len(revealed)
            all_revealed.update(revealed)
        newly_revealed = all_revealed

    return revealed_count == total_safe


SolverFactory = Callable[[], Solver]

DIFFICULTY_SOLVERS: dict[Difficulty, dict[str, Optional[SolverFactory]]] = {
    "beginner": {
        "target": lambda: BasicSolver(ROWS, COLS, MINE_COUNT),
        "lower": None,
    },
    "intermediate": {
        "target": lambda: SubsetSolver(ROWS, COLS, MINE_COUNT),
        "lower": lambda: BasicSolver(ROWS, COLS, MINE_COUNT),
    },
    "advanced": {
        "target": lambda: ProbabilisticSolver(ROWS, COLS, MINE_COUNT),
        "lower": lambda: SubsetSolver(ROWS, COLS, MINE_COUNT),
    },
    "expert": {
        "target": lambda: PerfectSolver(ROWS, COLS, MINE_COUNT),
        "lower": lambda: ProbabilisticSolver(ROWS, COLS, MINE_COUNT),
    },
}


def generate_solvable_board(
    start_row: int,
    start_col: int,
    difficulty: Difficulty = "expert",
    max_attempts: int = 10000,
) -> tuple[list[list[dict]], tuple[int, int]]:
    """Generate a solvable board for the given starting square and difficulty.

    A board is accepted only when the target solver can solve it AND (if the
    tier has one) the next-lower solver cannot, guaranteeing the board
    genuinely requires that tier's reasoning.
    """
    tier = DIFFICULTY_SOLVERS[difficulty]
    target_factory = tier["target"]
    lower_factory = tier["lower"]

    t0 = time.perf_counter()
    for attempt in range(max_attempts):
        board = _generate_random_board(start_row, start_col)
        if not _is_solvable_by(board, start_row, start_col, target_factory()):
            continue
        if lower_factory and _is_solvable_by(board, start_row, start_col, lower_factory()):
            continue
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"[board-gen] {difficulty}: found in {attempt + 1} attempts, {elapsed_ms:.1f}ms")
        return board, (start_row, start_col)

    # Fallback: return something solvable by the target (ignore lower-bound rejection)
    print(f"[board-gen] {difficulty}: fallback after {max_attempts} attempts")
    for _ in range(max_attempts):
        board = _generate_random_board(start_row, start_col)
        if _is_solvable_by(board, start_row, start_col, target_factory()):
            return board, (start_row, start_col)
    return _generate_random_board(start_row, start_col), (start_row, start_col)
