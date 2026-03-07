from flask import Blueprint, jsonify, request, g

from auth import require_auth
from config import DATABASE_URL

head_to_head_bp = Blueprint("head_to_head", __name__)


@head_to_head_bp.route("/head-to-head", methods=["GET"])
@require_auth
def get_head_to_head():
    if not DATABASE_URL:
        return jsonify({"error": "Database not configured"}), 503
    if g.auth_level != "google" or not g.user_id:
        return jsonify({"error": "Google authentication required"}), 403

    opponent_name = request.args.get("opponent")
    from db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if opponent_name:
                return _get_single_record(cur, g.user_id, opponent_name)
            else:
                return _get_all_records(cur, g.user_id)
    finally:
        conn.close()


def _get_single_record(cur, user_id, opponent_name):
    cur.execute("SELECT id FROM users WHERE display_name = %s", (opponent_name,))
    row = cur.fetchone()
    if not row:
        return jsonify({"error": "Opponent not found"}), 404
    opponent_id = str(row[0])

    if user_id < opponent_id:
        p1_id, p2_id = user_id, opponent_id
    else:
        p1_id, p2_id = opponent_id, user_id

    cur.execute(
        "SELECT player1_wins, player2_wins FROM head_to_head_records "
        "WHERE player1_id = %s AND player2_id = %s",
        (p1_id, p2_id)
    )
    row = cur.fetchone()
    if not row:
        return jsonify({"wins": 0, "losses": 0, "opponent": opponent_name})

    p1_wins, p2_wins = row
    if user_id < opponent_id:
        wins, losses = p1_wins, p2_wins
    else:
        wins, losses = p2_wins, p1_wins

    return jsonify({"wins": wins, "losses": losses, "opponent": opponent_name})


def _get_all_records(cur, user_id):
    cur.execute("""
        SELECT
            CASE WHEN h.player1_id = %s THEN u2.display_name ELSE u1.display_name END AS opponent,
            CASE WHEN h.player1_id = %s THEN h.player1_wins ELSE h.player2_wins END AS wins,
            CASE WHEN h.player1_id = %s THEN h.player2_wins ELSE h.player1_wins END AS losses
        FROM head_to_head_records h
        JOIN users u1 ON u1.id = h.player1_id
        JOIN users u2 ON u2.id = h.player2_id
        WHERE h.player1_id = %s OR h.player2_id = %s
        ORDER BY h.updated_at DESC
    """, (user_id, user_id, user_id, user_id, user_id))

    records = [
        {"opponent": row[0], "wins": row[1], "losses": row[2]}
        for row in cur.fetchall()
    ]
    return jsonify({"records": records})
