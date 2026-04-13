"""Unit tests for `bots.brain.BotBrain`."""

import random

from board_generator import generate_solvable_board
from bots.brain import BotBrain, MoveOutcome
from bots.config import BotConfig
from config import COLS, MINE_COUNT, ROWS


def _drive_to_completion(brain: BotBrain, max_moves: int = 10_000):
    """Loop next_move/observe_result until won or out of moves.

    Returns (won, deaths, moves).
    """
    deaths = 0
    moves = 0
    for _ in range(max_moves):
        cell = brain.next_move()
        if cell is None:
            return True, deaths, moves
        outcome = brain.observe_result(cell)
        moves += 1
        if outcome.kind == "hit_mine":
            deaths += 1
        elif outcome.kind == "won":
            return True, deaths, moves
    return False, deaths, moves


def test_perfect_bot_solves_expert_board():
    board, (sr, sc) = generate_solvable_board(8, 15, difficulty="expert")
    cfg = BotConfig(name="perfect", solver_tier="perfect")
    brain = BotBrain(cfg, board, (sr, sc), ROWS, COLS, MINE_COUNT, rng=random.Random(0))

    won, deaths, moves = _drive_to_completion(brain)

    assert won, "Perfect bot failed to solve an expert-tier solvable board"
    assert deaths == 0, f"Perfect bot hit {deaths} mines on a solvable board"
    assert moves > 0


def test_p_random_cell_forces_random_pick():
    board, (sr, sc) = generate_solvable_board(8, 15, difficulty="expert")
    cfg = BotConfig(name="chaotic", solver_tier="perfect", p_random_cell=1.0)
    brain = BotBrain(cfg, board, (sr, sc), ROWS, COLS, MINE_COUNT, rng=random.Random(0))

    cell = brain.next_move()
    assert cell is not None
    r, c = cell
    # The returned cell must be one the brain considers unknown (not already
    # revealed by the seed flood-fill and not a cell the brain has marked as
    # a known mine).
    assert brain.state[r][c] == "unknown"
    assert cell not in brain._bot_known_mines

    # Stepping should continue to produce legal moves.
    outcome = brain.observe_result(cell)
    assert outcome.kind in ("hit_mine", "revealed", "won")

    second = brain.next_move()
    if second is not None:
        sr2, sc2 = second
        assert brain.state[sr2][sc2] == "unknown"


def test_p_skip_deduction_drops_all_safe_cells():
    board, (sr, sc) = generate_solvable_board(8, 15, difficulty="expert")
    cfg = BotConfig(name="forgetful", solver_tier="perfect", p_skip_deduction=1.0)
    brain = BotBrain(cfg, board, (sr, sc), ROWS, COLS, MINE_COUNT, rng=random.Random(0))

    move = brain.next_move()
    assert move is not None
    # Every deduction should have been skipped, so the queue is empty and the
    # brain was forced to guess.
    assert len(brain.safe_queue) == 0
    # Sanity check: the solver actually ran (probs populated for probabilistic
    # tiers; for perfect solver `_last_probs` is filled during find_solved_squares).
    assert isinstance(brain._last_probs, dict)


def test_off_frontier_pick_selects_chosen_region_when_density_lower():
    """With frontier_min > off-frontier density, the brain must pick from the
    region configured by `off_frontier_pick`. We stub `_partitioned_regions`
    and `_last_probs` to isolate the branching in `_guess_probabilistic` from
    any specific board topology."""
    board, (sr, sc) = generate_solvable_board(8, 15, difficulty="expert")

    def _make_brain(off_pick: str) -> BotBrain:
        cfg = BotConfig(
            name=f"probe_{off_pick}",
            solver_tier="probabilistic",
            off_frontier_pick=off_pick,  # type: ignore[arg-type]
        )
        brain = BotBrain(
            cfg, board, (sr, sc), ROWS, COLS, MINE_COUNT, rng=random.Random(0)
        )
        # Replace the real partition with a synthetic one: three disjoint
        # single-cell regions so the test has a known correct answer.
        brain._partitioned_regions = lambda: (  # type: ignore[method-assign]
            [(0, 0)],
            [(0, 1)],
            [(0, 2)],
        )
        # Frontier min (0.9) > off-frontier density (0.1) → must go off-frontier.
        brain._last_probs = {(0, 0): 0.9, (0, 1): 0.1, (0, 2): 0.1}
        return brain

    brain_deep = _make_brain("deep")
    assert brain_deep._choose_guess() == (0, 2)

    brain_near = _make_brain("near_frontier")
    assert brain_near._choose_guess() == (0, 1)

    brain_any = _make_brain("any")
    pick = brain_any._choose_guess()
    assert pick in {(0, 1), (0, 2)}
