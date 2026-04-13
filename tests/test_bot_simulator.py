"""Integration tests for `bots.simulator.simulate_match`."""

from board_generator import generate_solvable_board
from bots.config import BotConfig
from bots.simulator import simulate_match


def test_simulate_match_is_deterministic():
    board, start = generate_solvable_board(8, 15, difficulty="expert")
    cfg = BotConfig(
        name="perfect",
        solver_tier="perfect",
        min_move_delay=0.1,
        max_move_delay=0.2,
    )

    r1 = simulate_match(cfg, cfg, board=board, start_cell=start, seed=42)
    r2 = simulate_match(cfg, cfg, board=board, start_cell=start, seed=42)

    assert r1 == r2


def test_expert_beats_beginner_majority():
    expert = BotConfig(
        name="expert",
        solver_tier="perfect",
        min_move_delay=0.1,
        max_move_delay=0.1,
    )
    beginner = BotConfig(
        name="beginner",
        solver_tier="basic",
        min_move_delay=0.1,
        max_move_delay=0.1,
        blind_guess_region="frontier",
    )

    expert_wins = 0
    rounds = 50
    for seed in range(rounds):
        result = simulate_match(expert, beginner, difficulty="expert", seed=seed)
        if result.winner == "expert":
            expert_wins += 1

    assert expert_wins >= 40, (
        f"Expert bot won {expert_wins}/{rounds} against beginner — "
        f"expected at least 40 (80%)"
    )
