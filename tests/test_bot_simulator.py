"""Integration tests for `bots.simulator.simulate_match`."""

from board_generator import generate_solvable_board
from bots.config import BotConfig
from bots.simulator import simulate_match
from config import DEATH_COOLDOWN_BASE_MS, DEATH_COOLDOWN_STEP_MS


def test_simulate_match_is_deterministic():
    board, start = generate_solvable_board(8, 15, difficulty="expert")
    cfg = BotConfig(
        name="perfect",
        username="perfect_bot",
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
        username="expert_bot",
        solver_tier="perfect",
        min_move_delay=0.1,
        max_move_delay=0.1,
    )
    beginner = BotConfig(
        name="beginner",
        username="beginner_bot",
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


def test_death_cooldown_accumulates_on_virtual_clock():
    """A bot that dies N times must eat at least the escalating cooldown
    sum on its virtual clock (mirroring the frontend penalty).
    """
    perfect = BotConfig(
        name="perfect",
        username="perfect_bot",
        solver_tier="perfect",
        min_move_delay=0.01,
        max_move_delay=0.01,
    )
    # p_random_cell=1.0 forces a uniformly-random unknown click every tick,
    # so this bot will rack up deaths quickly.
    kamikaze = BotConfig(
        name="kamikaze",
        username="kamikaze_bot",
        solver_tier="basic",
        min_move_delay=0.01,
        max_move_delay=0.01,
        p_random_cell=1.0,
    )

    # Try several seeds to find a match where the kamikaze bot dies at
    # least once. It almost always will, but be defensive.
    for seed in range(20):
        result = simulate_match(perfect, kamikaze, difficulty="beginner", seed=seed)
        # Pull kamikaze's deaths and virtual time regardless of who won.
        if result.winner == kamikaze.name:
            kamikaze_deaths = result.deaths_winner
            kamikaze_time_ms = result.time_winner_ms
        else:
            kamikaze_deaths = result.deaths_loser
            kamikaze_time_ms = result.time_loser_ms

        if kamikaze_deaths == 0:
            continue

        # Minimum cooldown time for N deaths: sum_{k=0..N-1} (BASE + k*STEP).
        expected_cooldown_ms = sum(
            DEATH_COOLDOWN_BASE_MS + k * DEATH_COOLDOWN_STEP_MS
            for k in range(kamikaze_deaths)
        )
        assert kamikaze_time_ms >= expected_cooldown_ms, (
            f"Kamikaze virtual time ({kamikaze_time_ms}ms) did not absorb the "
            f"full cooldown penalty for {kamikaze_deaths} deaths "
            f"(expected >= {expected_cooldown_ms}ms)"
        )
        return

    raise AssertionError("Never observed a death across 20 seeds — test setup broken")
