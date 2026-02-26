import re
import time
from functools import wraps

import jwt
from flask import Blueprint, request, jsonify, g

from config import JWT_SECRET, JWT_ALGORITHM
from session_tracker import tracker

auth_bp = Blueprint("auth", __name__)
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{1,20}$")


def create_jwt(username: str) -> str:
    return jwt.encode(
        {"sub": username, "iat": int(time.time())},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def decode_jwt(token: str) -> str | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except jwt.InvalidTokenError:
        return None


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Unauthorized"}), 401
        username = decode_jwt(auth_header[7:])
        if not username:
            return jsonify({"error": "Invalid token"}), 401
        g.username = username
        tracker.touch(username)
        return f(*args, **kwargs)
    return decorated


@auth_bp.route("/auth/register", methods=["POST"])
def register():
    body = request.get_json(silent=True) or {}
    username = body.get("username", "")
    if not isinstance(username, str) or not USERNAME_RE.match(username.strip()):
        return jsonify({"error": "username must be 1-20 alphanumeric/underscore characters"}), 400
    username = username.strip()

    if tracker.is_active(username):
        return jsonify({"error": "Username already in use"}), 409

    token = create_jwt(username)
    tracker.touch(username)
    return jsonify({"token": token})
