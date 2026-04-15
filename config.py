import os
import secrets

JWT_SECRET = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")

ROWS = 16
COLS = 30
MINE_COUNT = 99

# Distribution of board difficulties used for multiplayer matches.
# Kept here (rather than in match.py) so offline simulations can match the
# live distribution without importing Flask-coupled modules.
DIFFICULTY_WEIGHTS = [
    ("beginner", 0.10),
    ("intermediate", 0.40),
    ("advanced", 0.40),
    ("expert", 0.10),
]

# Escalating cooldown applied after every mine hit. Mirror of
# cooldownDuration() in minesweeper-web/app/lib/multiplayer-utils.ts.
# Cooldown after the N-th death (1-indexed) = BASE + (N-1) * STEP milliseconds:
#   1st death  -> 2000ms
#   2nd death  -> 4000ms
#   3rd death  -> 6000ms
DEATH_COOLDOWN_BASE_MS = 2000
DEATH_COOLDOWN_STEP_MS = 2000

TICKET_EXPIRY_SECONDS = 30
HEARTBEAT_TIMEOUT_SECONDS = 60
COUNTDOWN_SECONDS = 5

DATABASE_URL = os.environ.get("DATABASE_URL")

QUEUE_BASE_RANGE = 100
QUEUE_EXPANSION_INTERVAL = 5
QUEUE_RANGE_STEP = 50
QUEUE_MAX_RANGE = 800
QUEUE_MAX_WAIT = 300
MATCH_LOOP_INTERVAL = 2
