import re
import time
import uuid
from functools import wraps

import jwt
from flask import Blueprint, request, jsonify, g

from config import JWT_SECRET, JWT_ALGORITHM, DATABASE_URL
from rate_limit import limiter
from session_tracker import tracker

auth_bp = Blueprint("auth", __name__)
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{1,20}$")

# Pending-OAuth token TTL: how long the user has to pick a username
# after Google sign-in before the pending state expires.
PENDING_OAUTH_TTL_SECONDS = 600


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


def _create_pending_oauth_token(google_id: str, email: str, suggested: str) -> str:
    now = int(time.time())
    payload = {
        "kind": "pending_oauth",
        "google_id": google_id,
        "email": email,
        "suggested": suggested,
        "iat": now,
        "exp": now + PENDING_OAUTH_TTL_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


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
@limiter.limit("10 per minute; 60 per hour")
def register():
    body = request.get_json(silent=True) or {}
    username = body.get("username", "")
    if not isinstance(username, str) or not USERNAME_RE.match(username.strip()):
        return jsonify({"error": "username must be 1-20 alphanumeric/underscore characters"}), 400
    username = username.strip()

    if tracker.is_active(username):
        return jsonify({"error": "Username already taken"}), 409

    # Block guests from claiming a username already owned by a registered
    # (Google) user. Only relevant in DB mode.
    if DATABASE_URL:
        from db import get_conn
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
                if cur.fetchone():
                    return jsonify({"error": "Username already taken"}), 409
        finally:
            conn.close()

    token = create_jwt(username)
    tracker.touch(username)
    return jsonify({"token": token})


@auth_bp.route("/auth/google", methods=["POST"])
@limiter.limit("10 per minute; 60 per hour")
def google_auth():
    body = request.get_json(silent=True) or {}
    google_id = body.get("google_id", "")
    email = body.get("email", "")
    # `display_name` is the Google profile name we use as a seed for
    # the pending-token's `suggested` claim — not a separate persisted field.
    google_name = body.get("display_name", "")

    if not google_id or not email:
        return jsonify({"error": "google_id and email are required"}), 400

    sanitized = re.sub(r"[^a-zA-Z0-9_]", "", google_name)[:20]
    if not sanitized:
        sanitized = "Player"

    # Mock mode — no database. Defer to chooser flow same as DB mode.
    if not DATABASE_URL:
        pending = _create_pending_oauth_token(google_id, email, sanitized)
        return jsonify({
            "needs_username": True,
            "suggested": sanitized,
            "pending_token": pending,
        })

    # DB mode — look up existing oauth credential.
    from db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT oc.user_id, u.username FROM oauth_credentials oc "
                "JOIN users u ON u.id = oc.user_id "
                "WHERE oc.provider = 'google' AND oc.provider_id = %s",
                (google_id,)
            )
            row = cur.fetchone()
            if row:
                user_id, existing_name = str(row[0]), row[1]
                token = create_jwt(existing_name, user_id=user_id)
                return jsonify({"token": token})
    finally:
        conn.close()

    # New user — defer creation until they pick a username via /auth/google/complete.
    pending = _create_pending_oauth_token(google_id, email, sanitized)
    return jsonify({
        "needs_username": True,
        "suggested": sanitized,
        "pending_token": pending,
    })


@auth_bp.route("/auth/google/complete", methods=["POST"])
@limiter.limit("10 per minute; 60 per hour")
def google_auth_complete():
    body = request.get_json(silent=True) or {}
    pending_token = body.get("pending_token", "")
    raw_username = body.get("username", "")

    if not isinstance(raw_username, str) or not USERNAME_RE.match(raw_username.strip()):
        return jsonify({"error": "username must be 1-20 alphanumeric/underscore characters"}), 400
    username = raw_username.strip()

    payload = decode_jwt(pending_token)
    if not payload or payload.get("kind") != "pending_oauth":
        return jsonify({"error": "Invalid or expired sign-in"}), 401
    google_id = payload.get("google_id", "")
    email = payload.get("email", "")
    if not google_id or not email:
        return jsonify({"error": "Invalid or expired sign-in"}), 401

    # Mock mode — no DB. Best-effort uniqueness via the in-memory tracker.
    if not DATABASE_URL:
        if tracker.is_active(username):
            return jsonify({"error": "Username already taken"}), 409
        token = create_jwt(username, user_id=str(uuid.uuid4()))
        tracker.touch(username)
        return jsonify({"token": token})

    import psycopg2
    from db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Idempotency: if oauth row already exists (double-submit / second tab),
            # log in with the existing username, ignoring the just-chosen one.
            cur.execute(
                "SELECT oc.user_id, u.username FROM oauth_credentials oc "
                "JOIN users u ON u.id = oc.user_id "
                "WHERE oc.provider = 'google' AND oc.provider_id = %s",
                (google_id,)
            )
            row = cur.fetchone()
            if row:
                user_id, existing_name = str(row[0]), row[1]
                conn.commit()
                token = create_jwt(existing_name, user_id=user_id)
                return jsonify({"token": token})

            try:
                cur.execute(
                    "INSERT INTO users (username) VALUES (%s) RETURNING id",
                    (username,)
                )
                user_id = str(cur.fetchone()[0])
                cur.execute(
                    "INSERT INTO oauth_credentials (user_id, provider, provider_id, email) "
                    "VALUES (%s, 'google', %s, %s)",
                    (user_id, google_id, email)
                )
            except psycopg2.errors.UniqueViolation:
                # Could be users_username_unique (chosen name was taken)
                # OR oauth_credentials' (provider, provider_id) UNIQUE
                # (another tab finished registering this google_id between
                # our upfront SELECT and our INSERT). Re-query to disambiguate:
                # if a row now exists for the google_id, log in with that
                # existing user — same outcome as the upfront idempotency check.
                conn.rollback()
                cur.execute(
                    "SELECT oc.user_id, u.username FROM oauth_credentials oc "
                    "JOIN users u ON u.id = oc.user_id "
                    "WHERE oc.provider = 'google' AND oc.provider_id = %s",
                    (google_id,)
                )
                row = cur.fetchone()
                if row:
                    existing_user_id, existing_name = str(row[0]), row[1]
                    conn.commit()
                    token = create_jwt(existing_name, user_id=existing_user_id)
                    return jsonify({"token": token})
                conn.commit()
                return jsonify({"error": "Username already taken"}), 409

        conn.commit()
        token = create_jwt(username, user_id=user_id)
        return jsonify({"token": token})
    finally:
        conn.close()
