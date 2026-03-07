import json

from flask import request
from flask_sock import Sock

from ws_ticket import ticket_store
from match import match_manager

sock = Sock()


@sock.route("/ws")
def ws_handler(ws):
    """Handle raw WebSocket connections with ticket-based auth."""
    ticket = request.args.get("ticket")
    match_id = request.args.get("matchId")

    if not ticket or not match_id:
        ws.close(4000, "Missing ticket or matchId")
        return

    # Validate ticket (single-use, not expired)
    ticket_data = ticket_store.consume(ticket)
    if not ticket_data:
        ws.close(4001, "Invalid or expired ticket")
        return
    username = ticket_data["username"]
    user_id = ticket_data["user_id"]

    # Find match
    match = match_manager.get_match(match_id)
    if not match:
        ws.close(4002, "Match not found")
        return

    # Verify this user belongs to this match
    if username not in (match.player1, match.player2):
        ws.close(4003, "Not a participant in this match")
        return

    # Register connection (triggers match start when both connected)
    match.add_connection(username, ws, user_id=user_id)

    try:
        while True:
            data = ws.receive()
            if data is None:
                break
            try:
                msg = json.loads(data)
                match.handle_message(username, msg)
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    finally:
        match.handle_disconnect(username)
