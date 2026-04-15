"""End-to-end smoke test for the bots-in-multiplayer pipeline.

Plays N bot-vs-bot matches through the real `Match` object — the same
object the live server uses for a human vs bot match. Both sides are
driven by `BotMatchDriver`, so every piece of the live path gets
exercised: duck-typed connection attach, `_run_match` countdown +
`game_start`, `WsTransport` → `handle_message` relay, `_handle_completion`
winner detection, and `_update_elo_ratings` + `_record_h2h_result`.

After the games, the test reads `elo_ratings` and `head_to_head_records`
straight out of Postgres to prove that bot ELO persistence and H2H
bookkeeping work exactly like they do for humans, and prints the top-10
leaderboard to confirm bots are not filtered out of it.

This is implementation-order step 6 from `bots/MULTIPLAYER_PLAN.md`.

Prerequisites
-------------
- `DATABASE_URL` is set and points at the same DB the live server uses.
- `python -m bots.seed_elo` has been run so `bots/user_ids.json` exists
  and `users` / `elo_ratings` rows are populated.

Usage
-----
    python -m bots.smoke_test                         # 3 games, auto-pick bots
    python -m bots.smoke_test --games 2
    python -m bots.smoke_test --bot-a <username> --bot-b <username>
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid

from config import DATABASE_URL


# --------------------------------------------------------------------- DB reads


def _snapshot_elo(cur, user_ids: list[str]) -> dict[str, dict]:
    cur.execute(
        "SELECT user_id::text, rating, wins, losses "
        "FROM elo_ratings WHERE user_id = ANY(%s)",
        (user_ids,),
    )
    return {
        row[0]: {"rating": row[1], "wins": row[2], "losses": row[3]}
        for row in cur.fetchall()
    }


def _snapshot_h2h(cur, a_id: str, b_id: str) -> dict:
    p1, p2 = (a_id, b_id) if a_id < b_id else (b_id, a_id)
    cur.execute(
        "SELECT player1_wins, player2_wins "
        "FROM head_to_head_records WHERE player1_id = %s AND player2_id = %s",
        (p1, p2),
    )
    row = cur.fetchone()
    return {
        "p1_id": p1,
        "p2_id": p2,
        "player1_wins": row[0] if row else 0,
        "player2_wins": row[1] if row else 0,
    }


def _top_leaderboard(cur, limit: int = 10) -> list[tuple[str, int]]:
    cur.execute(
        "SELECT u.display_name, e.rating "
        "FROM elo_ratings e JOIN users u ON u.id = e.user_id "
        "ORDER BY e.rating DESC LIMIT %s",
        (limit,),
    )
    return [(row[0], row[1]) for row in cur.fetchall()]


# ------------------------------------------------------------------ Match driver


def run_one_match(bot_a, bot_b, *, timeout_s: float) -> None:
    """Run exactly one game of bot_a vs bot_b through a fresh Match."""
    from match import match_manager
    from session_tracker import tracker
    from bots.match_driver import BotMatchDriver

    # Create sessions so Match's tracker.set_in_game / set_online are not
    # no-ops. (SessionTracker.set_in_game silently ignores unknown users.)
    tracker.touch(bot_a.username)
    tracker.touch(bot_b.username)

    match_id = str(uuid.uuid4())
    match_manager.create_match(match_id, bot_a.username, bot_b.username)
    match = match_manager.get_match(match_id)
    if match is None:
        raise RuntimeError(f"match_manager lost {match_id} immediately")

    driver_a = BotMatchDriver(match, bot_a)
    driver_b = BotMatchDriver(match, bot_b)

    # Attaching the second connection inside add_connection triggers
    # `_run_match` on its own thread, so both drivers must start before
    # the match thread expects the human-looking second peer.
    driver_a.start()
    driver_b.start()

    deadline = time.monotonic() + timeout_s
    while not match.finished and time.monotonic() < deadline:
        time.sleep(0.25)

    if not match.finished:
        match_manager.remove_match(match_id)
        raise RuntimeError(
            f"match {match_id} did not finish within {timeout_s:.0f}s"
        )

    # Let both drivers run their post-game (decline rematch → detach) path.
    for driver in (driver_a, driver_b):
        if driver._thread is not None:
            driver._thread.join(timeout=10)

    match_manager.remove_match(match_id)


# --------------------------------------------------------------------- Entrypoint


def _pick_bots(bot_registry, bot_a_arg: str | None, bot_b_arg: str | None):
    def by_name(name: str):
        entry = bot_registry.get(name)
        if entry is None:
            print(f"ERROR: no bot with username {name!r}.", file=sys.stderr)
            sys.exit(2)
        return entry

    all_bots = bot_registry.all_bots()
    if len(all_bots) < 2:
        print("ERROR: registry has fewer than 2 bots.", file=sys.stderr)
        sys.exit(2)

    bots_sorted = sorted(all_bots, key=lambda b: -b.rating)
    bot_a = by_name(bot_a_arg) if bot_a_arg else bots_sorted[0]
    # Pick the median-rated bot as opponent so the skill gap is wide
    # enough that ELO and H2H both clearly move in one direction on
    # most games, but not so wide that the weaker bot never wins.
    default_b = bots_sorted[len(bots_sorted) // 2]
    if default_b.username == bot_a.username and len(bots_sorted) >= 2:
        default_b = bots_sorted[1]
    bot_b = by_name(bot_b_arg) if bot_b_arg else default_b
    if bot_a.username == bot_b.username:
        print("ERROR: bot A and bot B must be different.", file=sys.stderr)
        sys.exit(2)
    return bot_a, bot_b


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=3)
    parser.add_argument("--bot-a", type=str, default=None)
    parser.add_argument("--bot-b", type=str, default=None)
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="per-match timeout in seconds (default: 180)",
    )
    args = parser.parse_args(argv)

    if not DATABASE_URL:
        print(
            "ERROR: DATABASE_URL must be set for the smoke test.",
            file=sys.stderr,
        )
        return 2

    from bots.registry import bot_registry

    bot_registry.load()

    # Force one-game-per-Match. BOT_REMATCH_P is star-imported into
    # match_driver at module load, so patching live_config alone is not
    # enough — we rebind the name on match_driver directly too.
    import bots.live_config as live_config
    import bots.match_driver as match_driver_mod

    live_config.BOT_REMATCH_P = 0.0
    match_driver_mod.BOT_REMATCH_P = 0.0

    bot_a, bot_b = _pick_bots(bot_registry, args.bot_a, args.bot_b)
    print(
        f"Bot A: {bot_a.username:<22} "
        f"rating={bot_a.rating:>4}  profile={bot_a.profile_name}"
    )
    print(
        f"Bot B: {bot_b.username:<22} "
        f"rating={bot_b.rating:>4}  profile={bot_b.profile_name}"
    )

    from db import get_conn

    ids = [bot_a.user_id, bot_b.user_id]

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            before_elo = _snapshot_elo(cur, ids)
            before_h2h = _snapshot_h2h(cur, bot_a.user_id, bot_b.user_id)
    finally:
        conn.close()

    def _fmt_elo(uid: str, snap: dict[str, dict]) -> str:
        row = snap.get(uid)
        if not row:
            return f"{uid[:8]}…  <no elo_ratings row>"
        return (
            f"{uid[:8]}…  rating={row['rating']:>4}  "
            f"W={row['wins']}  L={row['losses']}"
        )

    print("\nBefore:")
    print("  " + _fmt_elo(bot_a.user_id, before_elo))
    print("  " + _fmt_elo(bot_b.user_id, before_elo))
    print(
        f"  H2H: p1_wins={before_h2h['player1_wins']}  "
        f"p2_wins={before_h2h['player2_wins']}"
    )

    for i in range(args.games):
        print(f"\n--- game {i + 1}/{args.games} ---")
        t0 = time.monotonic()
        run_one_match(bot_a, bot_b, timeout_s=args.timeout)
        print(f"  finished in {time.monotonic() - t0:.1f}s")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            after_elo = _snapshot_elo(cur, ids)
            after_h2h = _snapshot_h2h(cur, bot_a.user_id, bot_b.user_id)
            top = _top_leaderboard(cur, limit=10)
    finally:
        conn.close()

    print("\nAfter:")
    print("  " + _fmt_elo(bot_a.user_id, after_elo))
    print("  " + _fmt_elo(bot_b.user_id, after_elo))
    print(
        f"  H2H: p1_wins={after_h2h['player1_wins']}  "
        f"p2_wins={after_h2h['player2_wins']}"
    )

    print("\nLeaderboard top 10:")
    for name, rating in top:
        marker = "[bot]" if bot_registry.is_bot(name) else "     "
        print(f"  {marker} {name:<24} {rating}")

    # ------------------------------------------------------------- Checks
    ok = True

    def check(label: str, cond: bool) -> None:
        nonlocal ok
        status = "OK  " if cond else "FAIL"
        print(f"  [{status}] {label}")
        if not cond:
            ok = False

    print("\nChecks:")

    # 1. Each game adds exactly one win + one loss across the two bots.
    def _wl(snap: dict[str, dict], uid: str) -> int:
        row = snap.get(uid) or {}
        return (row.get("wins") or 0) + (row.get("losses") or 0)

    delta_wl = (
        _wl(after_elo, bot_a.user_id)
        + _wl(after_elo, bot_b.user_id)
        - _wl(before_elo, bot_a.user_id)
        - _wl(before_elo, bot_b.user_id)
    )
    check(
        f"wins+losses across both bots advanced by {2 * args.games} "
        f"(actual: {delta_wl})",
        delta_wl == 2 * args.games,
    )

    # 2. At least one rating moved (Elo can net to zero only if each bot
    #    wins exactly half the games, and even then only on specific
    #    starting-rating symmetries — still worth asserting any movement).
    moved = any(
        (before_elo.get(uid, {}).get("rating")
         != after_elo.get(uid, {}).get("rating"))
        for uid in ids
    )
    check("at least one bot's elo_ratings.rating changed", moved)

    # 3. head_to_head_records advanced by exactly `games`.
    h2h_delta = (
        after_h2h["player1_wins"]
        + after_h2h["player2_wins"]
        - before_h2h["player1_wins"]
        - before_h2h["player2_wins"]
    )
    check(
        f"head_to_head_records total wins advanced by {args.games} "
        f"(actual: {h2h_delta})",
        h2h_delta == args.games,
    )

    # 4. Leaderboard query returned rows and bots are not filtered out.
    check("leaderboard top-10 query returned rows", len(top) > 0)
    check(
        "at least one bot appears in leaderboard top-10 "
        "(i.e. no is_bot filter)",
        any(bot_registry.is_bot(name) for name, _ in top),
    )

    print()
    if ok:
        print("SMOKE TEST PASSED")
        return 0
    print("SMOKE TEST FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
