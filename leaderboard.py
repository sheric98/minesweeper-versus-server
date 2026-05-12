from flask import Blueprint, jsonify, request

from config import DATABASE_URL

leaderboard_bp = Blueprint("leaderboard", __name__)


@leaderboard_bp.route("/leaderboard", methods=["GET"])
def get_leaderboard():
    if not DATABASE_URL:
        return jsonify({"scores": []})

    limit = request.args.get("limit", 10, type=int)
    limit = max(1, min(limit, 50))
    mode = request.args.get("mode", "random")
    if mode not in ("random", "no-guess"):
        mode = "random"

    difficulty = request.args.get("difficulty")
    valid_difficulties = ("beginner", "intermediate", "advanced", "expert")

    from db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if mode == "no-guess":
                if difficulty not in valid_difficulties:
                    difficulty = "expert"
                cur.execute(
                    "SELECT u.username, ls.time_seconds, ls.created_at "
                    "FROM leaderboard_scores ls "
                    "JOIN users u ON u.id = ls.user_id "
                    "WHERE ls.mode = %s AND ls.difficulty = %s "
                    "ORDER BY ls.time_seconds ASC "
                    "LIMIT %s",
                    (mode, difficulty, limit)
                )
            else:
                cur.execute(
                    "SELECT u.username, ls.time_seconds, ls.created_at "
                    "FROM leaderboard_scores ls "
                    "JOIN users u ON u.id = ls.user_id "
                    "WHERE ls.mode = %s "
                    "ORDER BY ls.time_seconds ASC "
                    "LIMIT %s",
                    (mode, limit)
                )
            rows = cur.fetchall()
        scores = [
            {
                "username": row[0],
                "time_seconds": row[1],
                "created_at": row[2].isoformat(),
            }
            for row in rows
        ]
        return jsonify({"scores": scores})
    finally:
        conn.close()

