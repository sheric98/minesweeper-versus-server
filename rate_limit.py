"""Rate limiting for abuse-prone endpoints.

Key functions:
- client_ip: the end user's IP. Requests arrive via the Vercel BFF (and
  nginx), so remote_addr is a shared egress IP. The BFF forwards the real
  user IP as X-Client-IP; fall back to X-Forwarded-For, then remote_addr.
- user_or_ip: username from the Authorization JWT when present, else the
  client IP. The token is decoded here (not read from flask.g) because
  flask-limiter evaluates key functions in before_request, before
  @require_auth has run.

Storage is in-memory, which is exact for the single gunicorn worker in
entrypoint.sh. If the worker count ever grows, switch to a shared storage
backend (e.g. redis) — otherwise each worker gets its own counters.

Set RATE_LIMIT_ENABLED=0 to disable (local dev / load tests).
"""

import os

from flask import request
from flask_limiter import Limiter


def client_ip() -> str:
    ip = request.headers.get("X-Client-IP", "").strip()
    if not ip:
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return ip or request.remote_addr or "unknown"


def user_or_ip() -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        from auth import decode_jwt  # deferred: auth.py imports this module

        payload = decode_jwt(auth_header[7:])
        if payload and payload.get("sub"):
            return f"user:{payload['sub']}"
    return f"ip:{client_ip()}"


limiter = Limiter(
    key_func=client_ip,
    storage_uri="memory://",
    enabled=os.environ.get("RATE_LIMIT_ENABLED", "1") == "1",
)
