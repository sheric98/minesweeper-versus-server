import uuid
import time
import threading

from flask import Blueprint, jsonify, g

from auth import require_auth
from config import TICKET_EXPIRY_SECONDS

ws_ticket_bp = Blueprint("ws_ticket", __name__)


class TicketStore:
    def __init__(self):
        self._lock = threading.Lock()
        # ticket_str -> {"username": str, "created_at": float}
        self._tickets: dict[str, dict] = {}

    def create(self, username: str, user_id: str | None = None) -> str:
        ticket = str(uuid.uuid4())
        with self._lock:
            self._tickets[ticket] = {
                "username": username,
                "user_id": user_id,
                "created_at": time.time(),
            }
        return ticket

    def consume(self, ticket: str) -> dict | None:
        """Returns {"username": str, "user_id": str|None} if valid. Single-use: removes on consume."""
        with self._lock:
            t = self._tickets.pop(ticket, None)
            if not t:
                return None
            if (time.time() - t["created_at"]) > TICKET_EXPIRY_SECONDS:
                return None
            return {"username": t["username"], "user_id": t.get("user_id")}

    def cleanup_expired(self):
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._tickets.items()
                       if (now - v["created_at"]) > TICKET_EXPIRY_SECONDS]
            for k in expired:
                del self._tickets[k]


ticket_store = TicketStore()


@ws_ticket_bp.route("/ws/ticket", methods=["POST"])
@require_auth
def create_ticket():
    ticket = ticket_store.create(g.username, user_id=g.user_id)
    return jsonify({"ticket": ticket})
