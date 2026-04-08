DEFAULT_RATING = 1200
K_FACTOR = 32


def expected_score(rating_a: int, rating_b: int) -> float:
    """Probability that player A wins against player B."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def compute_rating_changes(winner_rating: int, loser_rating: int) -> tuple[int, int]:
    """Return (winner_new_rating, loser_new_rating)."""
    e_winner = expected_score(winner_rating, loser_rating)
    winner_new = round(winner_rating + K_FACTOR * (1.0 - e_winner))
    loser_new = round(loser_rating + K_FACTOR * (0.0 - (1.0 - e_winner)))
    return winner_new, loser_new
