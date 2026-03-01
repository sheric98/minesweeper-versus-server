import uuid
import threading

from flask import Blueprint, jsonify, request, g

from auth import require_auth
from session_tracker import tracker

matchmaking_bp = Blueprint("matchmaking", __name__)


class InviteStore:
    def __init__(self):
        self._lock = threading.Lock()
        # invite_id -> {"from": str, "to": str, "status": "pending"|"accepted"|"rejected", "match_id": str|None}
        self._invites: dict[str, dict] = {}

    def create(self, from_user: str, to_user: str) -> str:
        invite_id = str(uuid.uuid4())
        with self._lock:
            self._invites[invite_id] = {
                "from": from_user,
                "to": to_user,
                "status": "pending",
                "match_id": None,
            }
        return invite_id

    def get(self, invite_id: str) -> dict | None:
        with self._lock:
            inv = self._invites.get(invite_id)
            return dict(inv) if inv else None

    def respond(self, invite_id: str, accept: bool) -> dict | None:
        """Returns invite dict with match_id if accepted, or None if not found/already responded."""
        with self._lock:
            inv = self._invites.get(invite_id)
            if not inv or inv["status"] != "pending":
                return None
            if accept:
                match_id = str(uuid.uuid4())
                inv["status"] = "accepted"
                inv["match_id"] = match_id
            else:
                inv["status"] = "rejected"
            return dict(inv)

    def cancel_pending_for_user(self, username: str):
        """Cancel all pending invites where the user is sender or receiver."""
        with self._lock:
            for inv in self._invites.values():
                if inv["status"] == "pending" and (inv["from"] == username or inv["to"] == username):
                    inv["status"] = "cancelled"

    def get_for_user(self, username: str) -> dict:
        """Returns {sent: [...], received: [...]} invites relevant to the user.

        Sent list includes pending and accepted invites (accepted includes matchId
        so the inviter can navigate to the game page).
        Received list includes only pending invites (accepted/rejected are no longer actionable).
        """
        with self._lock:
            sent = []
            received = []
            for inv_id, inv in self._invites.items():
                if inv["from"] == username:
                    if inv["status"] == "pending":
                        sent.append({"inviteId": inv_id, "to": inv["to"], "status": "pending"})
                    elif inv["status"] == "accepted":
                        sent.append({"inviteId": inv_id, "to": inv["to"], "status": "accepted", "matchId": inv["match_id"]})
                if inv["to"] == username and inv["status"] == "pending":
                    received.append({"inviteId": inv_id, "from": inv["from"], "status": "pending"})
            return {"sent": sent, "received": received}


invite_store = InviteStore()


@matchmaking_bp.route("/matchmaking/players", methods=["GET"])
@require_auth
def get_players():
    players = tracker.get_active_players(exclude=g.username)
    return jsonify({"players": players})


@matchmaking_bp.route("/matchmaking/invite", methods=["POST"])
@require_auth
def send_invite():
    body = request.get_json(silent=True) or {}
    target = body.get("targetUsername", "")
    if isinstance(target, str):
        target = target.strip()
    if not target:
        return jsonify({"error": "targetUsername is required"}), 400
    if target == g.username:
        return jsonify({"error": "Cannot invite yourself"}), 400
    if not tracker.is_active(target):
        return jsonify({"error": "Player not online"}), 404

    invite_id = invite_store.create(g.username, target)
    return jsonify({"inviteId": invite_id})


@matchmaking_bp.route("/matchmaking/invite", methods=["GET"])
@require_auth
def get_invites():
    result = invite_store.get_for_user(g.username)
    return jsonify(result)


@matchmaking_bp.route("/matchmaking/respond", methods=["POST"])
@require_auth
def respond_invite():
    body = request.get_json(silent=True) or {}
    invite_id = body.get("inviteId", "")
    if isinstance(invite_id, str):
        invite_id = invite_id.strip()
    accept = body.get("accept")

    if not invite_id:
        return jsonify({"error": "inviteId is required"}), 400
    if not isinstance(accept, bool):
        return jsonify({"error": "accept must be a boolean"}), 400

    inv = invite_store.get(invite_id)
    if not inv or inv["to"] != g.username:
        return jsonify({"error": "Invite not found"}), 404

    result = invite_store.respond(invite_id, accept)
    if not result:
        return jsonify({"error": "Invite already responded to"}), 409

    if accept:
        from match import match_manager
        match_manager.create_match(result["match_id"], result["from"], result["to"])
        return jsonify({"matchId": result["match_id"]})
    return jsonify({})
