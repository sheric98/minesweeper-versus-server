"""Tests for the minesweeper solver."""

import time

from board_generator import (
    _generate_random_board,
    _is_solvable_by,
    generate_solvable_board,
)
from config import ROWS, COLS, MINE_COUNT
from solver import PerfectSolver


def make_simple_board():
    """Create a board with mines packed at the far end, trivially solvable from (0,0)."""
    board = [[{"isMine": False, "adjacentMines": 0} for _ in range(COLS)] for _ in range(ROWS)]

    mine_positions = set()
    for r in range(ROWS):
        for c in range(COLS):
            if len(mine_positions) < MINE_COUNT:
                idx = r * COLS + c
                if idx >= (ROWS * COLS - MINE_COUNT):
                    board[r][c]["isMine"] = True
                    mine_positions.add((r, c))

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

    return board, mine_positions


def _perfect_solver() -> PerfectSolver:
    return PerfectSolver(ROWS, COLS, MINE_COUNT)


def test_known_solvable():
    """A board with all mines packed at the end should be trivially solvable from (0,0)."""
    board, _ = make_simple_board()

    assert board[0][0]["adjacentMines"] == 0, f"Expected zero cell at (0,0), got {board[0][0]['adjacentMines']}"
    assert not board[0][0]["isMine"]

    result = _is_solvable_by(board, 0, 0, _perfect_solver())
    print(f"test_known_solvable: {'PASS' if result else 'FAIL'}")
    assert result, "Board with mines packed at end should be solvable from (0,0)"


def test_solver_correctness():
    """Generate random boards with a fixed start + safe zone and run the perfect solver."""
    start_row, start_col = 8, 15
    solvable_count = 0
    tested = 0

    for _ in range(50):
        board = _generate_random_board(start_row, start_col)
        result = _is_solvable_by(board, start_row, start_col, _perfect_solver())
        tested += 1
        if result:
            solvable_count += 1
            total_safe = sum(1 for r in range(ROWS) for c in range(COLS) if not board[r][c]["isMine"])
            assert total_safe == ROWS * COLS - MINE_COUNT, "Mine count mismatch"

    print(f"test_solver_correctness: PASS ({solvable_count}/{tested} boards were solvable)")


def test_unsolvable_board():
    """Smoke test: board with an isolated ambiguous mine pair. Solver should not crash."""
    board = [[{"isMine": False, "adjacentMines": 0} for _ in range(COLS)] for _ in range(ROWS)]

    board[0][COLS - 1]["isMine"] = True
    board[0][COLS - 2]["isMine"] = True

    remaining = MINE_COUNT - 2
    for r in range(ROWS - 1, -1, -1):
        for c in range(COLS - 1, -1, -1):
            if remaining <= 0:
                break
            if not board[r][c]["isMine"]:
                board[r][c]["isMine"] = True
                remaining -= 1
        if remaining <= 0:
            break

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

    result = _is_solvable_by(board, 0, 0, _perfect_solver())
    print(f"test_unsolvable_board: PASS (solver returned {result}, no crash)")


def test_generate_solvable_board():
    """Test the full generation pipeline end-to-end with expert difficulty."""
    start_row, start_col = 8, 15
    start_t = time.time()
    board, starting_square = generate_solvable_board(start_row, start_col, difficulty="expert", max_attempts=200)
    elapsed = time.time() - start_t

    result = _is_solvable_by(board, starting_square[0], starting_square[1], _perfect_solver())
    mines = sum(1 for r in range(ROWS) for c in range(COLS) if board[r][c]["isMine"])

    print(f"test_generate_solvable_board: {'PASS' if result else 'FAIL'}")
    print(f"  Time: {elapsed:.2f}s, Start: {starting_square}, Mines: {mines}")
    assert result, "generate_solvable_board should return a solvable board"
    assert mines == MINE_COUNT, f"Expected {MINE_COUNT} mines, got {mines}"
    assert starting_square == (start_row, start_col), "Starting square should be returned as given"

    # Verify 3x3 safe zone around start contains no mines
    for dr in range(-1, 2):
        for dc in range(-1, 2):
            nr, nc = start_row + dr, start_col + dc
            if 0 <= nr < ROWS and 0 <= nc < COLS:
                assert not board[nr][nc]["isMine"], f"Safe zone violated at ({nr},{nc})"


def test_performance():
    """Benchmark solver speed on random boards."""
    start_row, start_col = 8, 15
    times = []
    solvable_count = 0

    for _ in range(30):
        board = _generate_random_board(start_row, start_col)
        t0 = time.time()
        result = _is_solvable_by(board, start_row, start_col, _perfect_solver())
        elapsed = time.time() - t0
        times.append(elapsed)
        if result:
            solvable_count += 1

    times.sort()
    print(f"test_performance: PASS")
    print(f"  Boards tested: {len(times)}, Solvable: {solvable_count}")
    print(f"  Min: {times[0]:.4f}s, Median: {times[len(times)//2]:.4f}s, Max: {times[-1]:.4f}s")
    print(f"  Avg: {sum(times)/len(times):.4f}s")


if __name__ == "__main__":
    print("=" * 50)
    print("Running solver tests...")
    print("=" * 50)

    test_known_solvable()
    print()
    test_solver_correctness()
    print()
    test_unsolvable_board()
    print()
    test_generate_solvable_board()
    print()
    test_performance()

    print()
    print("=" * 50)
    print("All tests complete.")
    print("=" * 50)
