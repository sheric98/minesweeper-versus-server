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
from dataclasses import dataclass, field
from pathlib import Path

from board_generator import generate_solvable_board
from config import COLS, DIFFICULTY_WEIGHTS, ROWS
from elo import DEFAULT_RATING, compute_rating_changes

from .config import BotConfig, load_profiles
from .simulator import simulate_match


@dataclass
class BotStats:
    wins: int = 0
    losses: int = 0
    total_win_time_ms: int = 0
    min_win_time_ms: int | None = None

    @property
    def avg_win_time_ms(self) -> float:
        return self.total_win_time_ms / self.wins if self.wins else 0.0

    def record_win(self, time_ms: int) -> None:
        self.wins += 1
        self.total_win_time_ms += time_ms
        if self.min_win_time_ms is None or time_ms < self.min_win_time_ms:
            self.min_win_time_ms = time_ms

    def to_dict(self) -> dict:
        d: dict = {
            "wins": self.wins,
            "losses": self.losses,
            "total_win_time_ms": self.total_win_time_ms,
        }
        if self.min_win_time_ms is not None:
            d["min_win_time_ms"] = self.min_win_time_ms
        return d

    @classmethod
    def from_dict(cls, d: dict) -> BotStats:
        return cls(
            wins=d.get("wins", 0),
            losses=d.get("losses", 0),
            total_win_time_ms=d.get("total_win_time_ms", 0),
            min_win_time_ms=d.get("min_win_time_ms"),
        )


@dataclass
class _CachedBoard:
    board: list[list[dict]]
    start_cell: tuple[int, int]
    played: set[str] = field(default_factory=set)


class _BoardCache:
    """Per-tournament cache of generated boards keyed by difficulty.

    Each cached board tracks the set of bots that have already played on it.
    A lookup returns the first board (for the requested difficulty) where
    *neither* bot in the current match has played before — guaranteeing no
    two bots ever face the same (board, start_cell) twice. On miss, a fresh
    board is generated and appended to the cache.
    """

    def __init__(self, rng: random.Random) -> None:
        self._by_difficulty: dict[str, list[_CachedBoard]] = {}
        self._rng = rng

    def get_or_generate(
        self, difficulty: str, bot_a: str, bot_b: str
    ) -> tuple[list[list[dict]], tuple[int, int]]:
        entries = self._by_difficulty.setdefault(difficulty, [])
        for entry in entries:
            if bot_a not in entry.played and bot_b not in entry.played:
                entry.played.add(bot_a)
                entry.played.add(bot_b)
                return entry.board, entry.start_cell

        # Miss: generate a fresh board and add it to the cache.
        start_row = self._rng.randrange(ROWS)
        start_col = self._rng.randrange(COLS)
        board, (start_row, start_col) = generate_solvable_board(
            start_row, start_col, difficulty=difficulty
        )
        entry = _CachedBoard(
            board=board,
            start_cell=(start_row, start_col),
            played={bot_a, bot_b},
        )
        entries.append(entry)
        return board, (start_row, start_col)

# "mixed" means sample difficulty per match from the live multiplayer
# distribution (config.DIFFICULTY_WEIGHTS). Any other value forces that
# specific difficulty for every match.
MIXED_DIFFICULTY = "mixed"


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def load_ratings_file(path: Path) -> tuple[dict[str, int], dict[str, dict]]:
    """Load a ratings JSON file, handling both old flat and new nested formats.

    Returns (ratings_dict, stats_dict) where stats_dict values are raw dicts.
    """
    if not path.exists():
        return {}, {}
    loaded = json.loads(path.read_text())
    if "ratings" in loaded and isinstance(loaded.get("ratings"), dict):
        ratings = {k: int(v) for k, v in loaded["ratings"].items()}
        stats = loaded.get("stats", {})
    else:
        # Old flat format: {name: rating_int}
        ratings = {k: int(v) for k, v in loaded.items()}
        stats = {}
    return ratings, stats


def _load_ratings(
    path: Path, names: list[str]
) -> tuple[dict[str, int], dict[str, BotStats]]:
    ratings: dict[str, int] = {n: DEFAULT_RATING for n in names}
    stats: dict[str, BotStats] = {n: BotStats() for n in names}
    if path.exists():
        loaded_ratings, loaded_stats = load_ratings_file(path)
        for k, v in loaded_ratings.items():
            if k in ratings:
                ratings[k] = v
        for k, v in loaded_stats.items():
            if k in stats:
                stats[k] = BotStats.from_dict(v)
    return ratings, stats


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


def _pick_elo_pool_pair(
    names: list[str],
    ratings: dict[str, int],
    pool_size: int,
    rng: random.Random,
) -> tuple[str, str]:
    """Sample a pool of *pool_size* bots, pick a random anchor from the pool,
    then return the anchor paired with its closest-rated opponent in the pool.

    Equidistant opponents are broken uniformly at random.
    """
    effective_pool_size = min(pool_size, len(names))
    pool = rng.sample(names, effective_pool_size)
    anchor = rng.choice(pool)
    anchor_rating = ratings[anchor]
    candidates = [n for n in pool if n != anchor]
    min_dist = min(abs(ratings[n] - anchor_rating) for n in candidates)
    closest = [n for n in candidates if abs(ratings[n] - anchor_rating) == min_dist]
    opponent = rng.choice(closest)
    return anchor, opponent


def run_tournament(
    profiles: dict[str, BotConfig],
    rounds: int,
    difficulty: str,
    *,
    seed: int | None = None,
    pairing: str = "random",
    pool_size: int = 30,
    output: Path | None = None,
    checkpoint_interval: int = 1000,
    resume: bool = False,
    verbose: bool = False,
) -> tuple[dict[str, int], dict[str, BotStats]]:
    """Run *rounds* matches among *profiles* and return final ratings and stats.

    If *rounds* is 0, runs until interrupted by SIGINT/SIGTERM.
    """
    rng = random.Random(seed)
    board_cache = _BoardCache(rng)
    names = sorted(profiles)

    if len(names) < 2:
        print("Need at least 2 profiles to run a tournament.", file=sys.stderr)
        sys.exit(1)

    if pairing == "elo-pool" and pool_size < 2:
        print("--pool-size must be at least 2 for elo-pool pairing.", file=sys.stderr)
        sys.exit(1)

    if resume and output is not None:
        ratings, stats = _load_ratings(output, names)
    else:
        ratings = {n: DEFAULT_RATING for n in names}
        stats = {n: BotStats() for n in names}

    # Precompute round-robin pair list only if needed.
    rr_pairs: list[tuple[str, str]] | None = None
    if pairing == "round-robin":
        rr_pairs = [(a, b) for a in names for b in names if a != b]

    # Precompute difficulty sampler. When the user passes --difficulty mixed,
    # each match independently samples a difficulty from the live multiplayer
    # distribution so calibration ratings reflect actual match conditions.
    mixed = difficulty == MIXED_DIFFICULTY
    if mixed:
        diff_names, diff_weights = zip(*DIFFICULTY_WEIGHTS)
    else:
        diff_names = diff_weights = None  # unused

    # SIGINT/SIGTERM handler: flush a final checkpoint and stop the loop.
    stop = {"flag": False}

    def _handle_stop(signum, frame):  # noqa: ARG001
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    def _checkpoint() -> None:
        if output is not None:
            _atomic_write_json(output, {
                "ratings": ratings,
                "stats": {n: s.to_dict() for n, s in stats.items()},
            })

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
            elif pairing == "elo-pool":
                name_a, name_b = _pick_elo_pool_pair(names, ratings, pool_size, rng)
            else:  # random
                name_a, name_b = rng.sample(names, 2)

            match_seed = rng.randint(0, 2**64)
            match_difficulty = (
                rng.choices(diff_names, weights=diff_weights, k=1)[0]
                if mixed
                else difficulty
            )
            board, start_cell = board_cache.get_or_generate(
                match_difficulty, name_a, name_b
            )
            result = simulate_match(
                profiles[name_a],
                profiles[name_b],
                difficulty=match_difficulty,
                seed=match_seed,
                board=board,
                start_cell=start_cell,
            )

            winner_new, loser_new = compute_rating_changes(
                ratings[result.winner], ratings[result.loser]
            )
            ratings[result.winner] = winner_new
            ratings[result.loser] = loser_new

            stats[result.winner].record_win(result.time_winner_ms)
            stats[result.loser].losses += 1

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

    return ratings, stats


def print_leaderboard(
    ratings: dict[str, int],
    stats: dict[str, BotStats] | None = None,
    limit: int | None = None,
) -> None:
    ranked = sorted(ratings.items(), key=lambda x: x[1], reverse=True)
    if limit is not None:
        ranked = ranked[:limit]
    has_stats = stats is not None and any(
        s.wins + s.losses > 0 for s in stats.values()
    )
    if has_stats:
        width = 90
        print()
        print("=" * width)
        print(
            f"{'Rank':<6}{'Bot':<28}{'ELO':>6}  "
            f"{'W':>5} {'L':>5} {'Win%':>6} {'AvgWin':>8} {'MinWin':>8}"
        )
        print("-" * width)
        for i, (name, elo) in enumerate(ranked, 1):
            s = stats.get(name, BotStats())
            total = s.wins + s.losses
            win_pct = (s.wins / total * 100) if total else 0.0
            avg_win = f"{s.avg_win_time_ms:.0f}ms" if s.wins else "-"
            min_win = f"{s.min_win_time_ms}ms" if s.min_win_time_ms is not None else "-"
            print(
                f"{i:<6}{name:<28}{elo:>6}  "
                f"{s.wins:>5} {s.losses:>5} {win_pct:>5.1f}% {avg_win:>8} {min_win:>8}"
            )
        print("=" * width)
    else:
        width = 46
        print()
        print("=" * width)
        print(f"{'Rank':<6}{'Bot':<34}{'ELO':>6}")
        print("-" * width)
        for i, (name, elo) in enumerate(ranked, 1):
            print(f"{i:<6}{name:<34}{elo:>6}")
        print("=" * width)


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
        default=MIXED_DIFFICULTY,
        choices=(MIXED_DIFFICULTY, "beginner", "intermediate", "advanced", "expert"),
        help="Board difficulty. 'mixed' (default) samples per match from the "
             "live multiplayer distribution (config.DIFFICULTY_WEIGHTS). "
             "Pass a specific difficulty to force it for every match.",
    )
    parser.add_argument(
        "--pairing",
        type=str,
        choices=("random", "round-robin", "elo-pool"),
        default="random",
        help="Pairing strategy (default: random). 'elo-pool' samples a pool "
             "of --pool-size bots per match, picks a random anchor, and pairs "
             "it with its closest-rated opponent in the pool.",
    )
    parser.add_argument(
        "--pool-size",
        type=int,
        default=30,
        help="Pool size for --pairing elo-pool (default: 30). Ignored by "
             "other pairing modes.",
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
    if args.difficulty == MIXED_DIFFICULTY:
        dist = ", ".join(f"{d}={int(w*100)}%" for d, w in DIFFICULTY_WEIGHTS)
        difficulty_desc = f"mixed ({dist})"
    else:
        difficulty_desc = f"{args.difficulty}-only"
    if args.rounds == 0:
        print(f"Running indefinitely, {difficulty_desc} boards, pairing={args.pairing}. "
              f"Send SIGINT/SIGTERM to stop.")
    else:
        print(f"Running {args.rounds} matches, {difficulty_desc} boards, "
              f"pairing={args.pairing}...")

    ratings, stats = run_tournament(
        profiles,
        rounds=args.rounds,
        difficulty=args.difficulty,
        seed=args.seed,
        pairing=args.pairing,
        pool_size=args.pool_size,
        output=output_path,
        checkpoint_interval=args.checkpoint_interval,
        resume=args.resume,
        verbose=args.verbose,
    )

    print_leaderboard(ratings, stats=stats, limit=args.leaderboard_limit)

    if output_path is not None:
        print(f"\nRatings written to {output_path}")


if __name__ == "__main__":
    main()
