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
                # growing past 10 entries per category.
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
