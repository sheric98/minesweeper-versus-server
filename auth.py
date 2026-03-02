import re
import time
import uuid
from functools import wraps

import jwt
from flask import Blueprint, request, jsonify, g

from config import JWT_SECRET, JWT_ALGORITHM, DATABASE_URL
from session_tracker import tracker

auth_bp = Blueprint("auth", __name__)
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{1,20}$")


def create_jwt(username: str, user_id: str | None = None) -> str:
    payload = {"sub": username, "iat": int(time.time())}
    if user_id:
        payload["authLevel"] = "google"
        payload["userId"] = user_id
    else:
        payload["authLevel"] = "anonymous"
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.InvalidTokenError:
        return None


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Unauthorized"}), 401
        payload = decode_jwt(auth_header[7:])
        if not payload:
            return jsonify({"error": "Invalid token"}), 401
        g.username = payload["sub"]
        g.user_id = payload.get("userId")
        g.auth_level = payload.get("authLevel", "anonymous")
        tracker.touch(g.username)
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


@auth_bp.route("/auth/google", methods=["POST"])
def google_auth():
    body = request.get_json(silent=True) or {}
    google_id = body.get("google_id", "")
    email = body.get("email", "")
    display_name = body.get("display_name", "")

    if not google_id or not email:
        return jsonify({"error": "google_id and email are required"}), 400

    # Sanitize display_name
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "", display_name)[:20]
    if not sanitized:
        sanitized = "Player"

    # Mock mode — no database
    if not DATABASE_URL:
        token = create_jwt(sanitized, user_id=str(uuid.uuid4()))
        return jsonify({"token": token})

    # DB mode
    from db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Look up existing oauth credential
            cur.execute(
                "SELECT oc.user_id, u.display_name FROM oauth_credentials oc "
                "JOIN users u ON u.id = oc.user_id "
                "WHERE oc.provider = 'google' AND oc.provider_id = %s",
                (google_id,)
            )
            row = cur.fetchone()
            if row:
                user_id, existing_name = str(row[0]), row[1]
                token = create_jwt(existing_name, user_id=user_id)
                return jsonify({"token": token})

            # New user — handle name collisions
            final_name = sanitized
            suffix = 1
            while True:
                cur.execute("SELECT 1 FROM users WHERE display_name = %s", (final_name,))
                if not cur.fetchone():
                    break
                final_name = f"{sanitized[:18]}_{suffix}"
                suffix += 1

            # Insert user + credential
            cur.execute(
                "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
                (final_name,)
            )
            user_id = str(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO oauth_credentials (user_id, provider, provider_id, email) "
                "VALUES (%s, 'google', %s, %s)",
                (user_id, google_id, email)
            )
        conn.commit()
        token = create_jwt(final_name, user_id=user_id)
        return jsonify({"token": token})
    finally:
        conn.close()
