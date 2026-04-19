"""Seed calibrated bot ELO ratings into the live Postgres DB.

Reads a ratings JSON file produced by `bots.tournament`, ensures a `users`
row exists for each bot (creating one and persisting its UUID in
`bots/user_ids.json`), then writes each bot's calibrated rating into
`elo_ratings`. Idempotent: safe to re-run.

By default, only bots that don't already have an `elo_ratings` row get
one — existing rows are left untouched so live-game ELO drift is
preserved across server restarts (this script runs on every container
boot from entrypoint.sh when BOTS_ENABLED=1). Pass `--force` to overwrite
stored ratings with the calibrated values, e.g. after re-running the
tournament.

When the ratings file is in the nested `{"ratings": ..., "stats": ...}`
format produced by `bots.tournament`, per-bot `wins`/`losses` from the
stats block are also written:
  * insert-if-missing: W/L are seeded on the new row (default 0 if the
    stats block doesn't have this bot).
  * --force: W/L are overwritten alongside the rating, but only for
    bots present in the stats block. Bots missing from stats keep their
    existing W/L untouched.

Usage:
    python -m bots.seed_elo --dry-run
    python -m bots.seed_elo                    # insert-if-missing
    python -m bots.seed_elo --force            # recalibration: overwrite

Requires DATABASE_URL to be set (same env var as the Flask app).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import load_profiles


DEFAULT_RATINGS_PATH = "bots/ratings.json"
DEFAULT_PROFILES_PATH = "bots/profiles.json"
# Honors `BOT_USER_IDS_PATH` so containerized deploys can point this at a
# persistent volume (see docker-compose.yml).
DEFAULT_USER_IDS_PATH = os.getenv("BOT_USER_IDS_PATH") or "bots/user_ids.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_user_ids(path: Path, user_ids: dict[str, str]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(user_ids, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def seed(
    *,
    ratings_path: Path,
    profiles_path: Path,
    user_ids_path: Path,
    dry_run: bool,
    force: bool,
) -> None:
    raw = _load_json(ratings_path)
    # Support both old flat format {name: rating} and new nested
    # format {"ratings": {...}, "stats": {...}}.
    if "ratings" in raw and isinstance(raw.get("ratings"), dict):
        ratings = raw["ratings"]
        stats = raw.get("stats") or {}
    else:
        ratings = raw
        stats = {}
    if not ratings:
        print(f"No ratings found in {ratings_path}", file=sys.stderr)
        sys.exit(1)

    profiles = load_profiles(profiles_path)
    user_ids: dict[str, str] = _load_json(user_ids_path)

    missing = [name for name in ratings if name not in profiles]
    if missing:
        print(
            f"WARNING: {len(missing)} ratings reference bots not in profiles.json "
            f"(skipping): {missing[:5]}{'...' if len(missing) > 5 else ''}",
            file=sys.stderr,
        )

    def _wl(name: str) -> tuple[int, int] | None:
        s = stats.get(name)
        if not isinstance(s, dict) or "wins" not in s or "losses" not in s:
            return None
        return int(s["wins"]), int(s["losses"])

    to_process = [
        (name, int(r), _wl(name)) for name, r in ratings.items() if name in profiles
    ]
    to_process.sort(key=lambda x: -x[1])

    with_stats = sum(1 for _, _, wl in to_process if wl is not None)
    print(f"Planning to seed {len(to_process)} bot ratings.")
    print(f"  {sum(1 for n, _, _ in to_process if n not in user_ids)} need new users rows.")
    print(f"  {sum(1 for n, _, _ in to_process if n in user_ids)} already have user_ids.")
    print(f"  {with_stats} carry calibration wins/losses from stats block.")
    print(
        f"  mode: {'forced overwrite' if force else 'insert-if-missing'}"
        f" (live ELO preserved for existing rows unless --force)"
    )

    if dry_run:
        print("\n-- DRY RUN --")
        for name, rating, wl in to_process[:10]:
            uid = user_ids.get(name, "<new>")
            wl_str = f"{wl[0]}W/{wl[1]}L" if wl else "no-stats"
            print(f"  {name:<34} display={profiles[name].username:<20} "
                  f"rating={rating:>5} {wl_str:<12} user_id={uid}")
        if len(to_process) > 10:
            print(f"  ... and {len(to_process) - 10} more")
        return

    # Import DB lazily so --dry-run works without DATABASE_URL set.
    from db import get_conn
    from config import DATABASE_URL

    if not DATABASE_URL:
        print("DATABASE_URL is not set — cannot seed.", file=sys.stderr)
        sys.exit(2)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 1. Ensure users rows exist for all bots and capture UUIDs.
            new_count = 0
            for name, _rating, _wl in to_process:
                if name in user_ids:
                    # Verify the row still exists (DB may have been reset).
                    cur.execute(
                        "SELECT 1 FROM users WHERE id = %s",
                        (user_ids[name],),
                    )
                    if cur.fetchone() is not None:
                        continue
                    # Stale mapping — fall through and re-create.
                # Mapping file may have been wiped (fresh volume) while the DB
                # still holds the row from a previous seed. Recover the UUID
                # by display_name before falling through to INSERT, so we
                # never create duplicate users for the same bot.
                cur.execute(
                    "SELECT id FROM users WHERE display_name = %s",
                    (profiles[name].username,),
                )
                existing = cur.fetchone()
                if existing is not None:
                    user_ids[name] = str(existing[0])
                    continue
                cur.execute(
                    "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
                    (profiles[name].username,),
                )
                new_id = cur.fetchone()[0]
                user_ids[name] = str(new_id)
                new_count += 1

            # 2. Insert elo_ratings for bots that don't have a row yet.
            #    Without --force, existing rows are left alone so live-game
            #    ELO drift survives the on-boot seed run in entrypoint.sh.
            #    With --force, recalibrated ratings overwrite whatever is
            #    currently stored. If the ratings file carries a `stats`
            #    block, calibration W/L from it are written too (on insert
            #    always, on --force update only when stats exist for the
            #    bot — otherwise existing W/L are preserved).
            insert_missing_sql = """
                INSERT INTO elo_ratings (user_id, rating, wins, losses)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            """
            force_with_wl_sql = """
                INSERT INTO elo_ratings (user_id, rating, wins, losses)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE
                  SET rating = EXCLUDED.rating,
                      wins = EXCLUDED.wins,
                      losses = EXCLUDED.losses,
                      updated_at = now()
            """
            force_rating_only_sql = """
                INSERT INTO elo_ratings (user_id, rating, wins, losses)
                VALUES (%s, %s, 0, 0)
                ON CONFLICT (user_id) DO UPDATE
                  SET rating = EXCLUDED.rating,
                      updated_at = now()
            """
            rating_writes = 0
            for name, rating, wl in to_process:
                uid = user_ids[name]
                wins, losses = wl if wl is not None else (0, 0)
                if force:
                    if wl is not None:
                        cur.execute(force_with_wl_sql, (uid, rating, wins, losses))
                    else:
                        cur.execute(force_rating_only_sql, (uid, rating))
                else:
                    cur.execute(insert_missing_sql, (uid, rating, wins, losses))
                rating_writes += cur.rowcount
        conn.commit()
    finally:
        conn.close()

    _save_user_ids(user_ids_path, user_ids)
    mode = "forced overwrite" if force else "insert-if-missing"
    print(
        f"Seeded {len(to_process)} bots ({mode}): "
        f"{new_count} new users, {rating_writes} rating rows written, "
        f"{len(to_process) - rating_writes} left untouched."
    )
    print(f"User ID mapping written to {user_ids_path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Seed calibrated bot ELO ratings into the live DB"
    )
    parser.add_argument("--ratings", type=str, default=DEFAULT_RATINGS_PATH)
    parser.add_argument("--profiles", type=str, default=DEFAULT_PROFILES_PATH)
    parser.add_argument("--user-ids", type=str, default=DEFAULT_USER_IDS_PATH)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without writing to the database",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite existing elo_ratings rows with the calibrated rating "
            "from bots/ratings.json. Default behavior only inserts rows for "
            "bots that don't yet have one, preserving live-game ELO drift."
        ),
    )
    args = parser.parse_args(argv)

    seed(
        ratings_path=Path(args.ratings),
        profiles_path=Path(args.profiles),
        user_ids_path=Path(args.user_ids),
        dry_run=args.dry_run,
        force=args.force,
    )


if __name__ == "__main__":
    main()
