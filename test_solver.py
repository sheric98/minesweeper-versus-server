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


# ============================================================
# BasicSolver — single-cell constraint propagation
# ============================================================

def test_basic_solver_rule2_reveals_safes_on_zero():
    """Rule 2: revealing a '0' has adjacent==known_mine_count==0, so every
    unknown neighbor is marked safe."""
    solver = BasicSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(5, 5): 0})
    expected_safe = {
        (5 + dr, 5 + dc)
        for dr in (-1, 0, 1)
        for dc in (-1, 0, 1)
        if (dr, dc) != (0, 0)
    }
    assert expected_safe <= result.safe, (
        f"All 8 neighbors should be safe, missing: {expected_safe - result.safe}"
    )
    assert result.mines == set(), f"No mines should be deduced, got {result.mines}"
    print("test_basic_solver_rule2_reveals_safes_on_zero: PASS")


def test_basic_solver_chains_rule2_into_rule1():
    """Revealing (0,0)=1 alone is inconclusive (3 unknowns, 1 mine).
    Also revealing (0,2)=0 marks (0,1),(1,1),(1,2),(1,3) safe via Rule 2.
    The while-changed loop then revisits (0,0)=1: its only remaining unknown
    is (1,0), so Rule 1 flags it as a mine. This exercises the propagation
    loop, which is the whole point of BasicSolver over a one-pass version."""
    solver = BasicSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(0, 0): 1, (0, 2): 0})
    assert (1, 0) in result.mines, f"Expected (1,0) in mines, got {result.mines}"
    for cell in [(0, 1), (1, 1), (1, 2), (1, 3)]:
        assert cell in result.safe, f"{cell} should be safe, got safe={result.safe}"
    print("test_basic_solver_chains_rule2_into_rule1: PASS")


def test_basic_solver_cannot_solve_subset_pattern():
    """Negative capability test: BasicSolver has no cross-group reasoning, so
    the classic 1-1 subset pattern leaves (0,2) and (1,2) unresolved. This
    pins down what separates BasicSolver from SubsetSolver."""
    solver = BasicSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(0, 0): 1, (0, 1): 1})
    assert (0, 2) not in result.safe, "BasicSolver must not deduce (0,2) safe"
    assert (1, 2) not in result.safe, "BasicSolver must not deduce (1,2) safe"
    assert result.mines == set(), f"No mines deducible here, got {result.mines}"
    print("test_basic_solver_cannot_solve_subset_pattern: PASS")


def test_basic_solver_density_probs_cover_all_unknowns():
    """BasicSolver falls back to global-density probs for every cell that
    isn't revealed, isn't a known mine, and isn't a newly-found safe."""
    solver = BasicSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(0, 0): 3})
    # (0,0)=3 forces (0,1),(1,0),(1,1) all mines via Rule 1.
    assert result.mines == {(0, 1), (1, 0), (1, 1)}
    # Every other cell on the board should have a probability entry.
    unknown_count = ROWS * COLS - 1 - 3  # minus revealed, minus known mines
    assert len(result.probs) == unknown_count, (
        f"Expected {unknown_count} prob entries, got {len(result.probs)}"
    )
    # Known mines are excluded from probs.
    for m in result.mines:
        assert m not in result.probs
    # Density is (remaining_mines) / (unknown_count).
    expected_density = (MINE_COUNT - 3) / unknown_count
    sample = next(iter(result.probs.values()))
    assert abs(sample - expected_density) < 1e-12, (
        f"BasicSolver should use uniform density {expected_density}, got {sample}"
    )
    print("test_basic_solver_density_probs_cover_all_unknowns: PASS")


# ============================================================
# SubsetSolver — basic rules + subset splitting
# ============================================================

def test_subset_solver_solves_1_1_subset_pattern():
    """The distinguishing feature: {(0,0):1,(0,1):1} creates
    A={(1,0),(1,1)} with 1 mine as a proper subset of
    B={(0,2),(1,0),(1,1),(1,2)} with 1 mine. Splitting B into A and
    (B - A) yields {(0,2),(1,2)} with 0 mines — both proven safe."""
    solver = SubsetSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(0, 0): 1, (0, 1): 1})
    assert (0, 2) in result.safe, f"(0,2) should be safe, got {result.safe}"
    assert (1, 2) in result.safe, f"(1,2) should be safe, got {result.safe}"
    assert result.mines == set(), f"No mines deducible, got {result.mines}"
    print("test_subset_solver_solves_1_1_subset_pattern: PASS")


def test_subset_solver_deduces_mines_via_split():
    """{(0,0):1, (1,1):6}: (0,0)'s group A={(0,1),(1,0)} with 1 mine is a
    proper subset of (1,1)'s group B={(0,1),(0,2),(1,0),(1,2),(2,0),(2,1),
    (2,2)} with 6 mines. After splitting, B - A = {(0,2),(1,2),(2,0),(2,1),
    (2,2)} with 5 mines in 5 cells — every one is a mine."""
    solver = SubsetSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(0, 0): 1, (1, 1): 6})
    expected_mines = {(0, 2), (1, 2), (2, 0), (2, 1), (2, 2)}
    assert expected_mines <= result.mines, (
        f"Expected {expected_mines} in mines, got {result.mines}"
    )
    # (0,1) and (1,0) remain ambiguous (the "A" group with 1 mine among 2).
    assert (0, 1) not in result.mines
    assert (1, 0) not in result.mines
    assert (0, 1) not in result.safe
    assert (1, 0) not in result.safe
    print("test_subset_solver_deduces_mines_via_split: PASS")


def test_subset_solver_handles_plain_rule1_case():
    """SubsetSolver must still solve the trivial corner-3 case that
    BasicSolver handles (no subset split required, just group.all_mines())."""
    solver = SubsetSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(0, 0): 3})
    assert result.mines == {(0, 1), (1, 0), (1, 1)}
    print("test_subset_solver_handles_plain_rule1_case: PASS")


def test_subset_solver_density_probs_exclude_certainties():
    """Like BasicSolver, SubsetSolver uses uniform density for probs — but
    must exclude deduced mines AND newly-found safes from the map."""
    solver = SubsetSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(0, 0): 1, (0, 1): 1})
    # (0,2) and (1,2) are proven safe via subset split.
    for cell in [(0, 2), (1, 2)]:
        assert cell in result.probs, f"{cell} should still have an entry"
        assert result.probs[cell] == 0.0, f"{cell} proven safe → prob 0"
    # Revealed cells are excluded.
    assert (0, 0) not in result.probs
    assert (0, 1) not in result.probs
    print("test_subset_solver_density_probs_exclude_certainties: PASS")


# ============================================================
# ProbabilisticSolver — PerfectSolver minus global mine-count
# ============================================================

def test_probabilistic_solver_deduces_via_subset_split():
    """ProbabilisticSolver inherits PerfectSolver's permutation reasoning,
    so it must flag the same mines as SubsetSolver on the {(0,0):1,(1,1):6}
    subset-split case."""
    solver = ProbabilisticSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(0, 0): 1, (1, 1): 6})
    expected_mines = {(0, 2), (1, 2), (2, 0), (2, 1), (2, 2)}
    assert expected_mines <= result.mines, (
        f"Expected {expected_mines} in mines, got {result.mines}"
    )
    print("test_probabilistic_solver_deduces_via_subset_split: PASS")


def test_probabilistic_solver_two_disjoint_components():
    """Two far-apart '1' reveals create two disjoint fringe components.
    Each fringe cell has prob 1/3 (one mine among three neighbors), and the
    density applied to unconstrained tiles uses remaining_mines minus the
    expected fringe mines (2.0). This exercises component independence in
    the probability calculation without any global mine-count pruning."""
    solver = ProbabilisticSolver(ROWS, COLS, MINE_COUNT)
    result = solver.find_solved_squares({(0, 0): 1, (15, 29): 1})
    for cell in [(0, 1), (1, 0), (1, 1), (14, 29), (15, 28), (14, 28)]:
        assert abs(result.probs[cell] - 1 / 3) < 1e-9, (
            f"{cell} fringe prob = {result.probs[cell]}"
        )
    # Unconstrained tile count = ROWS*COLS - 2 revealed - 6 fringe = 472.
    uncertain = ROWS * COLS - 2 - 6
    expected_density = (MINE_COUNT - 2.0) / uncertain  # 2.0 = expected fringe mines
    assert abs(result.probs[(8, 15)] - expected_density) < 1e-12
    print("test_probabilistic_solver_two_disjoint_components: PASS")


# ============================================================
# Frontier set maintenance — shared across every solver tier
# ============================================================

_ALL_SOLVER_TIERS = [BasicSolver, SubsetSolver, ProbabilisticSolver, PerfectSolver]


def _compute_expected_frontier_sets(revealed: set, mines: set):
    """Ground-truth recomputation of the frontier partition from scratch,
    directly from the definitions in FrontierSets."""
    def neighbors(r, c):
        return [
            (r + dr, c + dc)
            for dr in (-1, 0, 1)
            for dc in (-1, 0, 1)
            if (dr, dc) != (0, 0)
            and 0 <= r + dr < ROWS
            and 0 <= c + dc < COLS
        ]

    unknown = {
        (r, c)
        for r in range(ROWS)
        for c in range(COLS)
        if (r, c) not in revealed and (r, c) not in mines
    }
    frontier = {u for u in unknown if any(n in revealed for n in neighbors(*u))}
    near_frontier = {
        u for u in unknown
        if u not in frontier and any(n in frontier for n in neighbors(*u))
    }
    deep = unknown - frontier - near_frontier
    return frontier, near_frontier, deep


def _solver_state(solver):
    """Pull (revealed_set, known_mines_set) from any solver tier."""
    if hasattr(solver, "mine_cells"):
        mines = set(solver.mine_cells)
    else:
        mines = set(solver.known_mines)
    revealed = (
        set(solver.revealed_cells.keys())
        if isinstance(solver.revealed_cells, dict)
        else set(solver.revealed_cells)
    )
    return revealed, mines


def _assert_frontier_matches(solver, label: str):
    revealed, mines = _solver_state(solver)
    exp_f, exp_n, exp_d = _compute_expected_frontier_sets(revealed, mines)
    sets = solver.get_frontier_sets()

    assert sets.frontier == exp_f, (
        f"{label}: frontier mismatch "
        f"missing={exp_f - sets.frontier} extra={sets.frontier - exp_f}"
    )
    assert sets.near_frontier == exp_n, (
        f"{label}: near_frontier mismatch "
        f"missing={exp_n - sets.near_frontier} extra={sets.near_frontier - exp_n}"
    )
    assert sets.deep == exp_d, (
        f"{label}: deep mismatch "
        f"missing={exp_d - sets.deep} extra={sets.deep - exp_d}"
    )
    # Partition invariants: three sets pairwise disjoint, and revealed/mine
    # cells are absent from every set.
    assert sets.frontier.isdisjoint(sets.near_frontier), f"{label}: f/nf overlap"
    assert sets.frontier.isdisjoint(sets.deep), f"{label}: f/deep overlap"
    assert sets.near_frontier.isdisjoint(sets.deep), f"{label}: nf/deep overlap"
    union = sets.frontier | sets.near_frontier | sets.deep
    assert revealed.isdisjoint(union), f"{label}: revealed leaked into partition"
    assert mines.isdisjoint(union), f"{label}: mines leaked into partition"
    # And the three sets must cover every unknown cell on the board.
    assert len(union) == ROWS * COLS - len(revealed) - len(mines), (
        f"{label}: partition does not cover all unknowns"
    )


def test_frontier_sets_initial_state():
    """Before any reveal, all three sets are correctly initialised: frontier
    and near_frontier empty, deep holding every cell on the board."""
    all_cells = {(r, c) for r in range(ROWS) for c in range(COLS)}
    for cls in _ALL_SOLVER_TIERS:
        solver = cls(ROWS, COLS, MINE_COUNT)
        sets = solver.get_frontier_sets()
        assert sets.frontier == set(), f"{cls.__name__}: initial frontier non-empty"
        assert sets.near_frontier == set(), f"{cls.__name__}: initial near_frontier non-empty"
        assert sets.deep == all_cells, f"{cls.__name__}: initial deep should be every cell"
    print("test_frontier_sets_initial_state: PASS")


def test_frontier_sets_after_interior_reveal():
    """After a single non-corner '3' reveal with no deductions possible, all
    three sets are non-empty with exactly the expected contents: 8 frontier
    cells (the 3x3 ring minus the reveal) and 16 near_frontier cells (the
    5x5 ring minus the 3x3 core)."""
    for cls in _ALL_SOLVER_TIERS:
        solver = cls(ROWS, COLS, MINE_COUNT)
        result = solver.find_solved_squares({(5, 5): 3})
        assert result.mines == set(), (
            f"{cls.__name__}: (5,5)=3 alone should flag no mines, got {result.mines}"
        )
        _assert_frontier_matches(solver, f"{cls.__name__}/interior-3")

        sets = solver.get_frontier_sets()
        expected_frontier = {
            (5 + dr, 5 + dc)
            for dr in (-1, 0, 1) for dc in (-1, 0, 1)
            if (dr, dc) != (0, 0)
        }
        expected_near = {
            (r, c)
            for r in range(3, 8) for c in range(3, 8)
        } - expected_frontier - {(5, 5)}
        assert sets.frontier == expected_frontier
        assert sets.near_frontier == expected_near
        assert len(sets.near_frontier) == 16
        # A far-away cell is still in deep.
        assert (0, 29) in sets.deep
    print("test_frontier_sets_after_interior_reveal: PASS")


def test_frontier_sets_mine_deduction_demotes_near_frontier():
    """Corner '3' forces all three neighbors to be mines. Once they are
    flagged, the only unknown neighbors of the revealed (0,0) are gone —
    frontier must be empty, and every cell that was in near_frontier only
    because of those freshly-flagged mines must be demoted back to deep.
    This exercises the _mark_mine → near_frontier demotion path."""
    for cls in _ALL_SOLVER_TIERS:
        solver = cls(ROWS, COLS, MINE_COUNT)
        result = solver.find_solved_squares({(0, 0): 3})
        assert result.mines == {(0, 1), (1, 0), (1, 1)}, (
            f"{cls.__name__}: corner-3 should flag 3 mines, got {result.mines}"
        )

        _assert_frontier_matches(solver, f"{cls.__name__}/corner-3")
        sets = solver.get_frontier_sets()
        assert sets.frontier == set(), (
            f"{cls.__name__}: frontier should be empty — every unknown neighbor "
            f"of the only revealed cell is a flagged mine"
        )
        assert sets.near_frontier == set(), (
            f"{cls.__name__}: near_frontier should fully demote to deep once "
            f"its only anchoring frontier cells became mines"
        )
        assert len(sets.deep) == ROWS * COLS - 4
        # Specifically the cells that used to be in near_frontier:
        for cell in [(0, 2), (1, 2), (2, 0), (2, 1), (2, 2)]:
            assert cell in sets.deep, f"{cls.__name__}: {cell} should demote to deep"
    print("test_frontier_sets_mine_deduction_demotes_near_frontier: PASS")


def test_frontier_sets_across_successive_calls():
    """Two disjoint interior '1' reveals delivered in separate calls. After
    the first call the partition holds one fringe; after the second it holds
    both fringes as independent clusters. Validates that the partition is
    maintained incrementally across calls, not rebuilt from scratch."""
    for cls in _ALL_SOLVER_TIERS:
        solver = cls(ROWS, COLS, MINE_COUNT)

        r1 = solver.find_solved_squares({(5, 5): 1})
        assert r1.mines == set()
        _assert_frontier_matches(solver, f"{cls.__name__}/after-first")
        sets1 = solver.get_frontier_sets()
        assert (4, 4) in sets1.frontier
        assert (3, 3) in sets1.near_frontier
        assert (10, 20) in sets1.deep

        r2 = solver.find_solved_squares({(10, 20): 1})
        assert r2.mines == set()
        _assert_frontier_matches(solver, f"{cls.__name__}/after-second")
        sets2 = solver.get_frontier_sets()
        # Original fringe still intact
        assert (4, 4) in sets2.frontier
        assert (3, 3) in sets2.near_frontier
        # New fringe added
        assert (9, 20) in sets2.frontier
        assert (8, 18) in sets2.near_frontier
        # A cell far from both is still deep
        assert (0, 29) in sets2.deep
    print("test_frontier_sets_across_successive_calls: PASS")


def test_frontier_sets_two_adjacent_reveals_merge_fringes():
    """Reveal two cells at distance 2 in a single call so their fringes
    interact: (3,3)=1 and (5,5)=1 share (4,4) as a common frontier cell,
    and cells like (4,3),(4,5),(3,4),(5,4) — which would have been in
    (5,5)'s near_frontier alone — are promoted into frontier by their
    adjacency to (3,3)'s reveal. Verifies correct frontier union, not
    double-counting, and that near_frontier excludes all such promotions."""
    for cls in _ALL_SOLVER_TIERS:
        solver = cls(ROWS, COLS, MINE_COUNT)
        result = solver.find_solved_squares({(5, 5): 1, (3, 3): 1})
        assert result.mines == set(), (
            f"{cls.__name__}: two 1-reveals should not flag any mines"
        )
        _assert_frontier_matches(solver, f"{cls.__name__}/two-adjacent-reveals")

        sets = solver.get_frontier_sets()
        # Every neighbor of (3,3) must be frontier (not merely near-frontier),
        # including cells that were near_frontier of (5,5) alone.
        for cell in [(2, 2), (2, 3), (2, 4), (3, 2), (3, 4), (4, 2), (4, 3), (4, 4)]:
            assert cell in sets.frontier, (
                f"{cls.__name__}: {cell} must be frontier (neighbor of (3,3))"
            )
        # (7,7) is distance 2 from (5,5) and 4 from (3,3) — still anchored
        # in near_frontier by (6,6).
        assert (7, 7) in sets.near_frontier
        # (3,3) and (5,5) themselves are revealed, not in any set.
        assert (3, 3) not in sets.frontier | sets.near_frontier | sets.deep
        assert (5, 5) not in sets.frontier | sets.near_frontier | sets.deep
    print("test_frontier_sets_two_adjacent_reveals_merge_fringes: PASS")


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
    print("-" * 50)
    print("BasicSolver tests")
    print("-" * 50)
    test_basic_solver_rule2_reveals_safes_on_zero()
    test_basic_solver_chains_rule2_into_rule1()
    test_basic_solver_cannot_solve_subset_pattern()
    test_basic_solver_density_probs_cover_all_unknowns()

    print()
    print("-" * 50)
    print("SubsetSolver tests")
    print("-" * 50)
    test_subset_solver_solves_1_1_subset_pattern()
    test_subset_solver_deduces_mines_via_split()
    test_subset_solver_handles_plain_rule1_case()
    test_subset_solver_density_probs_exclude_certainties()

    print()
    print("-" * 50)
    print("ProbabilisticSolver tests")
    print("-" * 50)
    test_probabilistic_solver_deduces_via_subset_split()
    test_probabilistic_solver_two_disjoint_components()

    print()
    print("-" * 50)
    print("Frontier-set maintenance tests")
    print("-" * 50)
    test_frontier_sets_initial_state()
    test_frontier_sets_after_interior_reveal()
    test_frontier_sets_mine_deduction_demotes_near_frontier()
    test_frontier_sets_across_successive_calls()
    test_frontier_sets_two_adjacent_reveals_merge_fringes()

    print()
    print("=" * 50)
    print("All tests complete.")
    print("=" * 50)
