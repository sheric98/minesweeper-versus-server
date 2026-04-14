"""Seed calibrated bot ELO ratings into the live Postgres DB.

Reads a ratings JSON file produced by `bots.tournament`, ensures a `users`
row exists for each bot (creating one and persisting its UUID in
`bots/user_ids.json`), then upserts each bot's calibrated rating into
`elo_ratings`. Idempotent: safe to re-run after re-calibration.

Usage:
    python -m bots.seed_elo --ratings bots/ratings.json --dry-run
    python -m bots.seed_elo --ratings bots/ratings.json

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
DEFAULT_USER_IDS_PATH = "bots/user_ids.json"


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
) -> None:
    ratings = _load_json(ratings_path)
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

    to_process = [(name, int(r)) for name, r in ratings.items() if name in profiles]
    to_process.sort(key=lambda x: -x[1])

    print(f"Planning to seed {len(to_process)} bot ratings.")
    print(f"  {sum(1 for n, _ in to_process if n not in user_ids)} need new users rows.")
    print(f"  {sum(1 for n, _ in to_process if n in user_ids)} already have user_ids.")

    if dry_run:
        print("\n-- DRY RUN --")
        for name, rating in to_process[:10]:
            uid = user_ids.get(name, "<new>")
            print(f"  {name:<34} display={profiles[name].username:<20} "
                  f"rating={rating:>5} user_id={uid}")
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
            for name, _rating in to_process:
                if name in user_ids:
                    # Verify the row still exists (DB may have been reset).
                    cur.execute(
                        "SELECT 1 FROM users WHERE id = %s",
                        (user_ids[name],),
                    )
                    if cur.fetchone() is not None:
                        continue
                    # Stale mapping — fall through and re-create.
                cur.execute(
                    "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
                    (profiles[name].username,),
                )
                new_id = cur.fetchone()[0]
                user_ids[name] = str(new_id)
                new_count += 1

            # 2. Upsert elo_ratings (leave wins/losses alone).
            for name, rating in to_process:
                uid = user_ids[name]
                cur.execute(
                    """
                    INSERT INTO elo_ratings (user_id, rating)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE
                      SET rating = EXCLUDED.rating,
                          updated_at = now()
                    """,
                    (uid, rating),
                )
        conn.commit()
    finally:
        conn.close()

    _save_user_ids(user_ids_path, user_ids)
    print(
        f"Seeded {len(to_process)} ratings "
        f"({new_count} new users, {len(to_process) - new_count} updated)."
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
    args = parser.parse_args(argv)

    seed(
        ratings_path=Path(args.ratings),
        profiles_path=Path(args.profiles),
        user_ids_path=Path(args.user_ids),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
