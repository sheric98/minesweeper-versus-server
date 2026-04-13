"""CLI tournament for ELO calibration of bot profiles.

Usage:
    python -m bots.tournament --profiles bots/profiles.json --rounds 200 --difficulty expert

Loads all profiles, seeds them at the default ELO rating, then runs
head-to-head matches (round-robin pairing) and applies rating changes
after each. Prints a final leaderboard sorted by rating.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from elo import DEFAULT_RATING, compute_rating_changes

from .config import BotConfig, load_profiles
from .simulator import simulate_match


def run_tournament(
    profiles: dict[str, BotConfig],
    rounds: int,
    difficulty: str,
    seed: int | None = None,
    verbose: bool = False,
) -> dict[str, int]:
    """Run *rounds* matches among *profiles* and return final ratings."""
    rng = random.Random(seed)
    names = sorted(profiles)
    ratings: dict[str, int] = {n: DEFAULT_RATING for n in names}

    if len(names) < 2:
        print("Need at least 2 profiles to run a tournament.", file=sys.stderr)
        sys.exit(1)

    for r in range(1, rounds + 1):
        # Round-robin pairing: cycle through all ordered pairs.
        # Each round picks the next pair in the cycle.
        idx = (r - 1) % (len(names) * (len(names) - 1))
        pairs = [(a, b) for a in names for b in names if a != b]
        name_a, name_b = pairs[idx]

        match_seed = rng.randint(0, 2**64)
        result = simulate_match(
            profiles[name_a],
            profiles[name_b],
            difficulty=difficulty,
            seed=match_seed,
        )

        winner_new, loser_new = compute_rating_changes(
            ratings[result.winner], ratings[result.loser]
        )
        ratings[result.winner] = winner_new
        ratings[result.loser] = loser_new

        if verbose:
            print(
                f"[{r:>4}] {result.winner} beat {result.loser}  "
                f"({result.time_winner_ms}ms vs {result.time_loser_ms}ms, "
                f"deaths {result.deaths_winner}/{result.deaths_loser})  "
                f"ratings: {result.winner}={ratings[result.winner]} "
                f"{result.loser}={ratings[result.loser]}"
            )

    return ratings


def print_leaderboard(ratings: dict[str, int]) -> None:
    ranked = sorted(ratings.items(), key=lambda x: x[1], reverse=True)
    print()
    print("=" * 40)
    print(f"{'Rank':<6}{'Bot':<28}{'ELO':>6}")
    print("-" * 40)
    for i, (name, elo) in enumerate(ranked, 1):
        print(f"{i:<6}{name:<28}{elo:>6}")
    print("=" * 40)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Bot ELO calibration tournament")
    parser.add_argument(
        "--profiles",
        type=str,
        default="bots/profiles.json",
        help="Path to bot profiles JSON (default: bots/profiles.json)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=200,
        help="Number of matches to play (default: 200)",
    )
    parser.add_argument(
        "--difficulty",
        type=str,
        default="expert",
        help="Board difficulty (default: expert)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write final ratings to this JSON file (e.g. bots/ratings.json)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print each match result",
    )

    args = parser.parse_args(argv)

    profiles = load_profiles(args.profiles)
    print(f"Loaded {len(profiles)} profiles: {', '.join(sorted(profiles))}")
    print(f"Running {args.rounds} matches on {args.difficulty} boards...")

    ratings = run_tournament(
        profiles,
        rounds=args.rounds,
        difficulty=args.difficulty,
        seed=args.seed,
        verbose=args.verbose,
    )

    print_leaderboard(ratings)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(ratings, indent=2, sort_keys=True) + "\n")
        print(f"\nRatings written to {out_path}")


if __name__ == "__main__":
    main()
