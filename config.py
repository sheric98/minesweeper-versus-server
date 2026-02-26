import os
import secrets

JWT_SECRET = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")

ROWS = 16
COLS = 30
MINE_COUNT = 99

TICKET_EXPIRY_SECONDS = 30
HEARTBEAT_TIMEOUT_SECONDS = 60
COUNTDOWN_SECONDS = 5
