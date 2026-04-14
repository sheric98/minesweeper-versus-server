"""CLI tournament for ELO calibration of bot profiles.

Usage:
    python -m bots.tournament --rounds 5000 --output bots/ratings.json
    python -m bots.tournament --rounds 0 --resume --output bots/ratings.json

Loads all profiles, seeds them at the default ELO rating (or resumes from a
previous ratings file), then runs head-to-head matches and applies rating
changes after each. Supports random or round-robin pairing, periodic
checkpointing, and infinite runs terminated by SIGINT/SIGTERM.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import sys
from pathlib import Path

from elo import DEFAULT_RATING, compute_rating_changes

from .config import BotConfig, load_profiles
from .simulator import simulate_match


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def _load_ratings(path: Path, names: list[str]) -> dict[str, int]:
    ratings: dict[str, int] = {n: DEFAULT_RATING for n in names}
    if path.exists():
        loaded = json.loads(path.read_text())
        for k, v in loaded.items():
            if k in ratings:
                ratings[k] = int(v)
    return ratings


def _progress_line(match_no: int, total: int, ratings: dict[str, int]) -> str:
    ranked = sorted(ratings.values(), reverse=True)
    top1 = ranked[0]
    top5_mean = sum(ranked[:5]) / min(5, len(ranked))
    bottom1 = ranked[-1]
    total_str = str(total) if total > 0 else "inf"
    return (
        f"[match {match_no}/{total_str}] "
        f"top1={top1} top5_mean={top5_mean:.0f} bottom1={bottom1} "
        f"spread={top1 - bottom1}"
    )


def run_tournament(
    profiles: dict[str, BotConfig],
    rounds: int,
    difficulty: str,
    *,
    seed: int | None = None,
    pairing: str = "random",
    output: Path | None = None,
    checkpoint_interval: int = 1000,
    resume: bool = False,
    verbose: bool = False,
) -> dict[str, int]:
    """Run *rounds* matches among *profiles* and return final ratings.

    If *rounds* is 0, runs until interrupted by SIGINT/SIGTERM.
    """
    rng = random.Random(seed)
    names = sorted(profiles)

    if len(names) < 2:
        print("Need at least 2 profiles to run a tournament.", file=sys.stderr)
        sys.exit(1)

    if resume and output is not None:
        ratings = _load_ratings(output, names)
    else:
        ratings = {n: DEFAULT_RATING for n in names}

    # Precompute round-robin pair list only if needed.
    rr_pairs: list[tuple[str, str]] | None = None
    if pairing == "round-robin":
        rr_pairs = [(a, b) for a in names for b in names if a != b]

    # SIGINT/SIGTERM handler: flush a final checkpoint and stop the loop.
    stop = {"flag": False}

    def _handle_stop(signum, frame):  # noqa: ARG001
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    def _checkpoint() -> None:
        if output is not None:
            _atomic_write_json(output, ratings)

    infinite = rounds == 0
    r = 0
    try:
        while True:
            if stop["flag"]:
                break
            if not infinite and r >= rounds:
                break
            r += 1

            if pairing == "round-robin":
                assert rr_pairs is not None
                idx = (r - 1) % len(rr_pairs)
                name_a, name_b = rr_pairs[idx]
            else:  # random
                name_a, name_b = rng.sample(names, 2)

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
                    f"[{r:>6}] {result.winner} beat {result.loser}  "
                    f"({result.time_winner_ms}ms vs {result.time_loser_ms}ms, "
                    f"deaths {result.deaths_winner}/{result.deaths_loser})  "
                    f"ratings: {result.winner}={ratings[result.winner]} "
                    f"{result.loser}={ratings[result.loser]}"
                )

            if checkpoint_interval > 0 and r % checkpoint_interval == 0:
                _checkpoint()
                print(_progress_line(r, rounds, ratings), flush=True)
    finally:
        _checkpoint()

    return ratings


def print_leaderboard(ratings: dict[str, int], limit: int | None = None) -> None:
    ranked = sorted(ratings.items(), key=lambda x: x[1], reverse=True)
    if limit is not None:
        ranked = ranked[:limit]
    print()
    print("=" * 46)
    print(f"{'Rank':<6}{'Bot':<34}{'ELO':>6}")
    print("-" * 46)
    for i, (name, elo) in enumerate(ranked, 1):
        print(f"{i:<6}{name:<34}{elo:>6}")
    print("=" * 46)


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
        help="Number of matches to play. 0 = run until interrupted. (default: 200)",
    )
    parser.add_argument(
        "--difficulty",
        type=str,
        default="expert",
        help="Board difficulty (default: expert)",
    )
    parser.add_argument(
        "--pairing",
        type=str,
        choices=("random", "round-robin"),
        default="random",
        help="Pairing strategy (default: random)",
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
        help="Write final ratings to this JSON file (e.g. bots/ratings.json). "
             "Required if --resume or --checkpoint-interval > 0.",
    )
    parser.add_argument(
        "--checkpoint-interval",
        type=int,
        default=1000,
        help="Write a checkpoint every N matches. 0 to disable. (default: 1000)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Load existing --output file as starting ratings instead of seeding at DEFAULT_RATING",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print each match result",
    )
    parser.add_argument(
        "--leaderboard-limit",
        type=int,
        default=None,
        help="If set, only print the top N in the final leaderboard",
    )

    args = parser.parse_args(argv)

    output_path: Path | None = Path(args.output) if args.output else None

    if args.resume and output_path is None:
        parser.error("--resume requires --output")
    if args.checkpoint_interval > 0 and output_path is None and args.rounds == 0:
        parser.error("--rounds 0 requires --output for checkpointing")

    profiles = load_profiles(args.profiles)
    print(f"Loaded {len(profiles)} profiles")
    if args.rounds == 0:
        print(f"Running indefinitely on {args.difficulty} boards (pairing={args.pairing}). "
              f"Send SIGINT/SIGTERM to stop.")
    else:
        print(f"Running {args.rounds} matches on {args.difficulty} boards "
              f"(pairing={args.pairing})...")

    ratings = run_tournament(
        profiles,
        rounds=args.rounds,
        difficulty=args.difficulty,
        seed=args.seed,
        pairing=args.pairing,
        output=output_path,
        checkpoint_interval=args.checkpoint_interval,
        resume=args.resume,
        verbose=args.verbose,
    )

    print_leaderboard(ratings, limit=args.leaderboard_limit)

    if output_path is not None:
        print(f"\nRatings written to {output_path}")


if __name__ == "__main__":
    main()
