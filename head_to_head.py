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
                page = max(1, request.args.get("page", 1, type=int))
                page_size = max(1, min(request.args.get("page_size", 10, type=int), 50))
                search = request.args.get("search", "", type=str).strip()
                return _get_all_records(cur, g.user_id, page, page_size, search)
    finally:
        conn.close()


def _get_single_record(cur, user_id, opponent_name):
    cur.execute("SELECT id FROM users WHERE username = %s", (opponent_name,))
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


def _get_all_records(cur, user_id, page, page_size, search):
    base_query = """
        FROM head_to_head_records h
        JOIN users u1 ON u1.id = h.player1_id
        JOIN users u2 ON u2.id = h.player2_id
        WHERE (h.player1_id = %s OR h.player2_id = %s)
    """
    params = [user_id, user_id]

    if search:
        base_query += " AND CASE WHEN h.player1_id = %s THEN u2.username ELSE u1.username END ILIKE %s"
        params.extend([user_id, f"%{search}%"])

    cur.execute("SELECT COUNT(*) " + base_query, params)
    total_records = cur.fetchone()[0]

    offset = (page - 1) * page_size
    cur.execute("""
        SELECT
            CASE WHEN h.player1_id = %s THEN u2.username ELSE u1.username END AS opponent,
            CASE WHEN h.player1_id = %s THEN h.player1_wins ELSE h.player2_wins END AS wins,
            CASE WHEN h.player1_id = %s THEN h.player2_wins ELSE h.player1_wins END AS losses,
            (h.player1_wins + h.player2_wins) AS total_games
    """ + base_query + """
        ORDER BY total_games DESC
        LIMIT %s OFFSET %s
    """, [user_id, user_id, user_id] + params + [page_size, offset])

    records = [
        {"opponent": row[0], "wins": row[1], "losses": row[2], "total_games": row[3]}
        for row in cur.fetchall()
    ]
    return jsonify({
        "records": records,
        "page": page,
        "page_size": page_size,
        "total_records": total_records,
    })
