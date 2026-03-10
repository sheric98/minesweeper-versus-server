from flask import Blueprint, jsonify, request, g

from auth import require_auth
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

    from db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT u.display_name, ls.time_seconds, ls.created_at "
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


@leaderboard_bp.route("/leaderboard", methods=["POST"])
@require_auth
def post_score():
    if not DATABASE_URL:
        return jsonify({"error": "Database not configured"}), 503

    if g.auth_level != "google":
        return jsonify({"error": "Google authentication required"}), 403

    body = request.get_json(silent=True) or {}
    time_seconds = body.get("time_seconds")

    if not isinstance(time_seconds, int) or time_seconds < 1 or time_seconds > 999:
        return jsonify({"error": "time_seconds must be an integer between 1 and 999"}), 400

    mode = body.get("mode", "random")
    if mode not in ("random", "no-guess"):
        mode = "random"

    from db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO leaderboard_scores (user_id, time_seconds, mode) VALUES (%s, %s, %s)",
                (g.user_id, time_seconds, mode)
            )
        conn.commit()
        return jsonify({"success": True})
    finally:
        conn.close()
