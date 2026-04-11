"""Tests for the minesweeper solver."""

import time

from board_generator import (
    _generate_random_board,
    _is_solvable_by,
    generate_solvable_board,
)
from config import ROWS, COLS, MINE_COUNT
from solver import (
    BasicSolver,
    PerfectSolver,
    ProbabilisticSolver,
    SubsetSolver,
)


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


def test_result_probs_keyset_matches_unknowns():
    """probs covers exactly all-cells - revealed - known_mines."""
    solver = PerfectSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(0, 0): 3})
    # After: revealed = {(0,0)}, known_mines = {(0,1),(1,0),(1,1)}.
    expected = {
        (r, c)
        for r in range(ROWS)
        for c in range(COLS)
        if (r, c) != (0, 0) and (r, c) not in {(0, 1), (1, 0), (1, 1)}
    }
    assert set(result.probs.keys()) == expected, "probs keyset should be all unknown cells"
    print("test_result_probs_keyset_matches_unknowns: PASS")


def test_result_mines_reports_newly_deduced():
    """Corner '3' deduces all 3 neighbors as mines and excludes them from probs."""
    solver = PerfectSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(0, 0): 3})
    expected_mines = {(0, 1), (1, 0), (1, 1)}
    assert result.mines == expected_mines, f"Expected mines {expected_mines}, got {result.mines}"
    for cell in expected_mines:
        assert cell not in result.probs, f"{cell} should be excluded from probs"
    print("test_result_mines_reports_newly_deduced: PASS")


def test_result_proven_safe_is_zero():
    """Subset splitting from {(0,0):1, (0,1):1} proves (0,2) and (1,2) safe."""
    solver = PerfectSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(0, 0): 1, (0, 1): 1})
    assert (0, 2) in result.safe, f"(0,2) should be in safe, got {result.safe}"
    assert (1, 2) in result.safe, f"(1,2) should be in safe, got {result.safe}"
    assert result.probs[(0, 2)] == 0.0
    assert result.probs[(1, 2)] == 0.0
    print("test_result_proven_safe_is_zero: PASS")


def test_result_ambiguous_pair_is_half():
    """{(0,0):1, (1,1):2} forces exactly one of (0,1),(1,0) to be a mine -> 0.5 each.

    Subset splitting from these two reveals produces:
      - group A = {(0,1),(1,0)} with 1 mine    (2 permutations)
      - group B = {(0,2),(1,2),(2,0),(2,1),(2,2)} with 1 mine  (5 permutations)
    Joint: 10 valid configurations. (0,1) and (1,0) each appear as mine in
    5 of the 10 -> probability 0.5. The B-group cells each appear in 2 of
    10 -> probability 0.2.
    """
    solver = ProbabilisticSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(0, 0): 1, (1, 1): 2})
    assert abs(result.probs[(0, 1)] - 0.5) < 1e-9, f"(0,1) prob = {result.probs[(0,1)]}"
    assert abs(result.probs[(1, 0)] - 0.5) < 1e-9, f"(1,0) prob = {result.probs[(1,0)]}"
    for cell in [(0, 2), (1, 2), (2, 0), (2, 1), (2, 2)]:
        assert abs(result.probs[cell] - 0.2) < 1e-9, f"{cell} prob = {result.probs[cell]}"
    print("test_result_ambiguous_pair_is_half: PASS")


def test_result_global_density_fallback():
    """Cells far from the constraint fringe use the global density estimate."""
    solver = ProbabilisticSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(0, 0): 1})
    # Fringe = {(0,1),(1,0),(1,1)} with 1 mine. Each fringe cell prob = 1/3.
    # expected_fringe_mines = 1.0.
    # tiles_without_information = 480 - 1 (revealed) - 3 (fringe) = 476.
    # density = (99 - 1) / 476.
    expected = (MINE_COUNT - 1) / 476
    far_cells = [(10, 20), (15, 29), (8, 15)]
    for cell in far_cells:
        assert abs(result.probs[cell] - expected) < 1e-12, (
            f"{cell} prob = {result.probs[cell]}, expected {expected}"
        )
    # And the fringe cells should each be 1/3.
    for cell in [(0, 1), (1, 0), (1, 1)]:
        assert abs(result.probs[cell] - 1 / 3) < 1e-9
    print("test_result_global_density_fallback: PASS")


def test_result_all_tiers_agree_on_certainty():
    """All four solver tiers report the same proven mines for a corner '3'."""
    expected_mines = {(0, 1), (1, 0), (1, 1)}
    for solver in [
        BasicSolver(ROWS, COLS, MINE_COUNT),
        SubsetSolver(ROWS, COLS, MINE_COUNT),
        ProbabilisticSolver(ROWS, COLS, MINE_COUNT),
        PerfectSolver(ROWS, COLS, MINE_COUNT),
    ]:
        result = solver.find_solved_squares({(0, 0): 3})
        assert result.mines == expected_mines, (
            f"{type(solver).__name__}: expected {expected_mines}, got {result.mines}"
        )
        for cell in expected_mines:
            assert cell not in result.probs
    print("test_result_all_tiers_agree_on_certainty: PASS")


def test_result_probs_empty_when_fully_solved():
    """After every non-mine cell is revealed, probs is empty."""
    board, mine_set = make_simple_board()
    solver = PerfectSolver(ROWS, COLS, MINE_COUNT)
    revealed: dict[tuple[int, int], int] = {}
    for r in range(ROWS):
        for c in range(COLS):
            if (r, c) not in mine_set:
                revealed[(r, c)] = board[r][c]["adjacentMines"]
    result = solver.find_solved_squares(revealed)
    # All non-mine cells revealed, all mines deduced -> nothing left to report.
    assert result.probs == {}, f"Expected empty probs, got {len(result.probs)} entries"
    assert solver.mine_cells == mine_set, "Solver should have deduced every mine"
    print("test_result_probs_empty_when_fully_solved: PASS")


def test_result_after_successive_reveals():
    """probs correctly drops cells revealed in subsequent calls."""
    solver = PerfectSolver(ROWS, COLS, MINE_COUNT)
    r1 = solver.find_solved_squares({(5, 5): 1})
    assert (5, 5) not in r1.probs
    assert (5, 5) in solver.revealed_cells

    r2 = solver.find_solved_squares({(5, 7): 1})
    assert (5, 5) not in r2.probs
    assert (5, 7) not in r2.probs
    # All previously-tracked unknowns are still unknowns now (no new deductions)
    assert (5, 6) in r2.probs
    print("test_result_after_successive_reveals: PASS")


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
    print("-" * 50)
    print("Probability API tests")
    print("-" * 50)
    test_result_probs_keyset_matches_unknowns()
    test_result_mines_reports_newly_deduced()
    test_result_proven_safe_is_zero()
    test_result_ambiguous_pair_is_half()
    test_result_global_density_fallback()
    test_result_all_tiers_agree_on_certainty()
    test_result_probs_empty_when_fully_solved()
    test_result_after_successive_reveals()

    print()
    print("=" * 50)
    print("All tests complete.")
    print("=" * 50)
