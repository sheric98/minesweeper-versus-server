from flask import Blueprint, jsonify, request, g
from auth import require_auth
from config import DATABASE_URL
from elo import DEFAULT_RATING

elo_bp = Blueprint("elo", __name__)


@elo_bp.route("/elo/me", methods=["GET"])
@require_auth
def get_my_elo():
    if not DATABASE_URL:
        return jsonify({"error": "Database not configured"}), 503
    if g.auth_level != "google" or not g.user_id:
        return jsonify({"error": "Google authentication required"}), 403

    from db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rating, wins, losses FROM elo_ratings WHERE user_id = %s",
                (g.user_id,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"rating": DEFAULT_RATING, "wins": 0, "losses": 0})
            return jsonify({"rating": row[0], "wins": row[1], "losses": row[2]})
    finally:
        conn.close()


@elo_bp.route("/elo/leaderboard", methods=["GET"])
def get_elo_leaderboard():
    if not DATABASE_URL:
        return jsonify({"players": []})

    limit = max(1, min(request.args.get("limit", 20, type=int), 100))

    from db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.username, e.rating, e.wins, e.losses
                FROM elo_ratings e
                JOIN users u ON u.id = e.user_id
                ORDER BY e.rating DESC
                LIMIT %s
                """,
                (limit,),
            )
            players = [
                {"username": r[0], "rating": r[1], "wins": r[2], "losses": r[3]}
                for r in cur.fetchall()
            ]
        return jsonify({"players": players})
    finally:
        conn.close()
