"""Single-player stats endpoints + helpers.

POST /singleplayer/games  - record one completed game (win or loss)
GET  /singleplayer/stats/me - return the requester's per-category stats
"""

import uuid

from flask import Blueprint, g, jsonify, request

from auth import require_auth
from config import DATABASE_URL

singleplayer_bp = Blueprint("singleplayer", __name__)

VALID_MODES = ("random", "no-guess")
VALID_NO_GUESS_DIFFICULTIES = ("beginner", "intermediate", "advanced", "expert")
VALID_RESULTS = ("win", "loss")


def parse_game_submission(body):
    """Validate a POST /singleplayer/games request body.

    Returns (parsed_dict, None) on success or (None, error_message) on failure.
    `parsed_dict` keys: mode, difficulty, result, time_seconds, client_game_id.
    `time_seconds` is forced to None when result == "loss".
    """
    if not isinstance(body, dict):
        return None, "body must be a JSON object"

    mode = body.get("mode")
    if mode not in VALID_MODES:
        return None, f"mode must be one of {VALID_MODES}"

    difficulty = body.get("difficulty")
    if mode == "random":
        if difficulty != "standard":
            return None, "difficulty must be 'standard' when mode is 'random'"
    else:  # no-guess
        if difficulty not in VALID_NO_GUESS_DIFFICULTIES:
            return None, f"difficulty must be one of {VALID_NO_GUESS_DIFFICULTIES}"

    result = body.get("result")
    if result not in VALID_RESULTS:
        return None, f"result must be one of {VALID_RESULTS}"

    time_seconds = body.get("time_seconds")
    if result == "win":
        if isinstance(time_seconds, bool) or not isinstance(time_seconds, int) or time_seconds < 1 or time_seconds > 999:
            return None, "time_seconds must be an integer 1-999 for a win"
    else:
        # Loss — drop any time the client may have sent.
        time_seconds = None

    raw_client_game_id = body.get("client_game_id")
    if not isinstance(raw_client_game_id, str):
        return None, "client_game_id must be a string"
    try:
        client_game_id = str(uuid.UUID(raw_client_game_id))
    except (ValueError, AttributeError):
        return None, "client_game_id must be a UUID"

    return {
        "mode": mode,
        "difficulty": difficulty,
        "result": result,
        "time_seconds": time_seconds,
        "client_game_id": client_game_id,
    }, None


@singleplayer_bp.route("/singleplayer/games", methods=["POST"])
@require_auth
def post_game():
    if not DATABASE_URL:
        return jsonify({"error": "Database not configured"}), 503

    if g.auth_level != "google":
        return jsonify({"error": "Google authentication required"}), 403

    body = request.get_json(silent=True)
    parsed, err = parse_game_submission(body)
    if err:
        return jsonify({"error": err}), 400

    from db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Step 1: insert into rolling window (idempotent via UNIQUE constraint).
            cur.execute(
                """
                INSERT INTO recent_singleplayer_games
                    (user_id, mode, difficulty, result, time_seconds, client_game_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT ON CONSTRAINT recent_sp_games_unique_client DO NOTHING
                """,
                (
                    g.user_id,
                    parsed["mode"],
                    parsed["difficulty"],
                    parsed["result"],
                    parsed["time_seconds"],
                    parsed["client_game_id"],
                ),
            )
            if cur.rowcount == 0:
                # Idempotent retry — already recorded. No further side effects.
                conn.commit()
                return jsonify({"success": True})

            # Step 2: trim window to newest 100 for this user+category.
            cur.execute(
                """
                DELETE FROM recent_singleplayer_games
                WHERE user_id = %s AND mode = %s AND difficulty = %s
                  AND id NOT IN (
                    SELECT id FROM recent_singleplayer_games
                    WHERE user_id = %s AND mode = %s AND difficulty = %s
                    ORDER BY created_at DESC
                    LIMIT 100
                  )
                """,
                (
                    g.user_id, parsed["mode"], parsed["difficulty"],
                    g.user_id, parsed["mode"], parsed["difficulty"],
                ),
            )

            # Step 3: UPSERT lifetime stats. Wins bump total_wins and lower fastest.
            # Losses are no-ops here (rolling window already has them).
            if parsed["result"] == "win":
                cur.execute(
                    """
                    INSERT INTO user_singleplayer_stats
                        (user_id, mode, difficulty, total_wins, fastest_win_seconds)
                    VALUES (%s, %s, %s, 1, %s)
                    ON CONFLICT (user_id, mode, difficulty) DO UPDATE
                    SET total_wins = user_singleplayer_stats.total_wins + 1,
                        fastest_win_seconds = LEAST(
                            COALESCE(user_singleplayer_stats.fastest_win_seconds, EXCLUDED.fastest_win_seconds),
                            EXCLUDED.fastest_win_seconds
                        )
                    """,
                    (g.user_id, parsed["mode"], parsed["difficulty"], parsed["time_seconds"]),
                )

                # Step 4: maybe-insert into the bounded global leaderboard.
                # SELECT FOR UPDATE locks existing rows for this category to
                # serialize concurrent winners and prevent the table from
                # growing past 10 entries per category. Caveat: when the
                # table is empty for a category, FOR UPDATE locks nothing,
                # so the first ~10 concurrent winners may briefly produce
                # >10 rows. Self-corrects on the next winning submission.
                cur.execute(
                    """
                    SELECT id, time_seconds FROM leaderboard_scores
                    WHERE mode = %s AND difficulty = %s
                    ORDER BY time_seconds ASC
                    FOR UPDATE
                    """,
                    (parsed["mode"], parsed["difficulty"]),
                )
                rows = cur.fetchall()
                # Strict <: a tying time does NOT displace the current 10th-place holder.
                qualifies = len(rows) < 10 or parsed["time_seconds"] < rows[-1][1]
                if qualifies:
                    cur.execute(
                        """
                        INSERT INTO leaderboard_scores (user_id, mode, difficulty, time_seconds)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (g.user_id, parsed["mode"], parsed["difficulty"], parsed["time_seconds"]),
                    )
                    if len(rows) >= 10:
                        # New row pushed total to 11 — drop the slowest.
                        cur.execute(
                            "DELETE FROM leaderboard_scores WHERE id = %s",
                            (rows[-1][0],),
                        )

        conn.commit()
        return jsonify({"success": True})
    finally:
        conn.close()


ALL_CATEGORIES = (
    ("random", "standard"),
    ("no-guess", "beginner"),
    ("no-guess", "intermediate"),
    ("no-guess", "advanced"),
    ("no-guess", "expert"),
)


def _compute_stats_for_user(cur, user_id):
    """Return the list-of-categories dict for one user.

    Assumes `cur` is an open Postgres cursor inside an open connection.
    Caller is responsible for connection lifecycle.
    """
    cur.execute(
        """
        WITH all_categories(mode, difficulty) AS (
            VALUES ('random', 'standard'),
                   ('no-guess', 'beginner'),
                   ('no-guess', 'intermediate'),
                   ('no-guess', 'advanced'),
                   ('no-guess', 'expert')
        )
        SELECT c.mode, c.difficulty,
               COALESCE(s.total_wins, 0),
               s.fastest_win_seconds
        FROM all_categories c
        LEFT JOIN user_singleplayer_stats s
          ON s.user_id = %s AND s.mode = c.mode AND s.difficulty = c.difficulty
        """,
        (user_id,),
    )
    lifetime_rows = {(r[0], r[1]): (r[2], r[3]) for r in cur.fetchall()}

    cur.execute(
        """
        SELECT mode, difficulty,
               count(*) AS recent_count,
               count(*) FILTER (WHERE result = 'win') AS recent_wins,
               avg(time_seconds) FILTER (WHERE result = 'win') AS recent_avg
        FROM recent_singleplayer_games
        WHERE user_id = %s
        GROUP BY mode, difficulty
        """,
        (user_id,),
    )
    window_rows = {(r[0], r[1]): (r[2], r[3], r[4]) for r in cur.fetchall()}

    categories = []
    for (m, d) in ALL_CATEGORIES:
        total_wins, fastest = lifetime_rows.get((m, d), (0, None))
        recent_count, recent_wins, recent_avg = window_rows.get((m, d), (0, 0, None))
        categories.append({
            "mode": m,
            "difficulty": d,
            "total_wins": int(total_wins),
            "fastest_win_seconds": int(fastest) if fastest is not None else None,
            "recent_count": int(recent_count),
            "recent_wins": int(recent_wins),
            "recent_avg_win_seconds": round(float(recent_avg)) if recent_avg is not None else None,
        })
    return categories


@singleplayer_bp.route("/singleplayer/stats/me", methods=["GET"])
@require_auth
def get_my_stats():
    if not DATABASE_URL:
        # Mock mode — return empty stats for every category.
        categories = [
            {
                "mode": m,
                "difficulty": d,
                "total_wins": 0,
                "fastest_win_seconds": None,
                "recent_count": 0,
                "recent_wins": 0,
                "recent_avg_win_seconds": None,
            }
            for (m, d) in ALL_CATEGORIES
        ]
        return jsonify({"categories": categories})

    if g.auth_level != "google":
        return jsonify({"error": "Google authentication required"}), 403

    from db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            categories = _compute_stats_for_user(cur, g.user_id)
        return jsonify({"categories": categories})
    finally:
        conn.close()
