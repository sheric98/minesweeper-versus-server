# Minesweeper Multiplayer Game Server

Python Flask backend for the minesweeper game: multiplayer matches, ELO,
leaderboards, single-player stats, and bot opponents.

## Setup

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## Run

```bash
# Full stack (Postgres + app) — what production runs:
docker compose up --build

# App only, mock mode (no DB — DB-backed features disabled):
./venv/bin/python app.py
# Runs on http://0.0.0.0:5000
```

## Test

```bash
DATABASE_URL="" ./venv/bin/python -m pytest tests/ -q
# Note: tests/test_bot_simulator.py runs full game simulations and is slow —
# exclude it for a quick pass.
```

## Architecture

- **Flask + flask-sock** for HTTP REST + raw WebSocket (NOT Socket.IO)
- **Postgres** (via `psycopg2`, no ORM) for users, OAuth credentials,
  leaderboards, ELO ratings, head-to-head records, single-player stats,
  user preferences, and the pre-generated board cache. Schema is created
  idempotently by `db.py:init_db()` at startup.
- **Dual-mode:** when `DATABASE_URL` is unset the server runs in-memory
  ("mock mode") — auth and matchmaking work, DB-backed endpoints degrade
  or return empty. Guard new DB code with `if DATABASE_URL:`.
- **Bots:** optional (`BOTS_ENABLED=1`). Bot players join the matchmaking
  queue, accept invites, and play via the same WebSocket protocol as humans.
  See `bots/README.md` for the offline ELO-calibration harness.
- Frontend BFF (Next.js at `/home/sheric/minesweeper-web`) proxies to this
  server via `BACKEND_URL`. Google OAuth token verification happens in the
  BFF; this server receives already-verified claims on `/auth/google`.
- Deployed with Docker Compose (app + Postgres) behind nginx + Let's Encrypt
  on EC2 (`ec2-user-data.sh`, `redeploy.sh`). Gunicorn runs a **single
  gevent worker** (`entrypoint.sh`) — in-process state (session tracker,
  invites, tickets, rate-limit counters) relies on this.

## Key Files

| File | Purpose |
|---|---|
| `app.py` | Flask app factory + entry point; wires blueprints, limiter, background loops |
| `config.py` | Constants (JWT, board dims, timeouts, queue tuning, difficulty weights) |
| `db.py` | Postgres connection + idempotent schema creation |
| `auth.py` | `/auth/register`, `/auth/google`, `/auth/google/complete`, JWT helpers, `@require_auth` |
| `rate_limit.py` | flask-limiter setup; per-IP and per-user key functions |
| `session_tracker.py` | In-memory player presence tracking (60s heartbeat) |
| `ws_ticket.py` | `POST /ws/ticket` — single-use 30s WebSocket tickets |
| `matchmaking.py` | Direct invites: `GET/POST /matchmaking/{players,invite,respond}` |
| `matchmaking_queue.py` | Quick-match queue: `/matchmaking/queue/{join,leave,status}` + ELO-range pairing loop |
| `match.py` | Match lifecycle: countdown, message relay, game completion |
| `websocket_handler.py` | `GET /ws` — flask-sock WebSocket handler |
| `board_generator.py` | Solvable board generation with retry loop |
| `board_cache.py` / `board_replenisher.py` | DB cache of pre-generated boards + background top-up thread |
| `board_endpoint.py` | `GET /board` — serve a board (used by single-player no-guess mode) |
| `board_encoder.py` | Board → JSON encoding (shared with frontend mock format) |
| `solver/` | No-guess solver package: `basic_solver`, `subset_solver`, `probabilistic_solver`, `perfect_solver` |
| `elo.py` / `elo_endpoints.py` | ELO math + `/elo/{me,player,leaderboard}` |
| `leaderboard.py` | `GET /leaderboard` — multiplayer win-time leaderboard |
| `head_to_head.py` | `GET /head-to-head` — per-opponent W/L records |
| `singleplayer.py` | `POST /singleplayer/games{,/start}`, `/singleplayer/stats/{me,player}` — single-player stats + win-time plausibility gate |
| `preferences.py` | `GET/PUT /preferences/controls` — server-synced control settings |
| `bots/` | Bot opponents: profiles, brain, lifecycle, queue injector, ELO seeding/calibration |

## REST Endpoints

All authenticated endpoints expect `Authorization: Bearer <JWT>`.

- `POST /auth/register` — `{ "username" }` → `{ "token" }` (anonymous session)
- `POST /auth/google` — verified Google claims → `{ "token" }` or `needs_username` + pending token
- `POST /auth/google/complete` — `{ "pending_token", "username" }` → `{ "token" }`
- `POST /ws/ticket` — → `{ "ticket" }`
- `GET /board?difficulty=...` — pre-generated solvable board
- `GET /matchmaking/players` / `POST /matchmaking/invite` / `GET /matchmaking/invite` / `POST /matchmaking/respond`
- `POST /matchmaking/queue/join` / `POST /matchmaking/queue/leave` / `GET /matchmaking/queue/status`
- `GET /leaderboard`, `GET /elo/me`, `GET /elo/player`, `GET /elo/leaderboard`, `GET /head-to-head`
- `POST /singleplayer/games/start` — unauthenticated game-start ping `{ "client_game_id" }`; win times only reach the leaderboard when server-observed elapsed time covers them
- `POST /singleplayer/games`, `GET /singleplayer/stats/me`, `GET /singleplayer/stats/player`
- `GET /preferences/controls` / `PUT /preferences/controls`

## Rate Limiting

`rate_limit.py` (flask-limiter, in-memory storage — exact only with the single
gunicorn worker). Unauthenticated auth endpoints are keyed by end-user IP
(`X-Client-IP` header forwarded by the BFF); authenticated ones by JWT
username. Returns JSON 429s. Disable locally with `RATE_LIMIT_ENABLED=0`.

## WebSocket

`GET /ws?ticket=<ticket>&matchId=<matchId>` — raw WebSocket

## Environment Variables

- `JWT_SECRET` — signing key. **Startup fails if unset while `DATABASE_URL`
  is set** (a random per-process secret would invalidate all sessions on
  restart); mock mode generates an ephemeral one.
- `CORS_ORIGINS` — comma-separated allowed origins (default: `http://localhost:3000`)
- `DATABASE_URL` — Postgres DSN; unset = in-memory mock mode
- `POSTGRES_PASSWORD` — used by docker-compose for the `db` service
- `BOTS_ENABLED` — `1` to load bot profiles and start bot lifecycle loops
- `BOT_USER_IDS_PATH` — persisted bot-UUID mapping (set by docker-compose to a volume)
- `RATE_LIMIT_ENABLED` — `0` to disable rate limiting (default on)

Google OAuth client credentials live in the frontend BFF (Vercel), not here.

## Connecting Frontend

Set in the minesweeper-web `.env`:
```
BACKEND_URL=http://localhost:5000
NEXT_PUBLIC_WS_URL=ws://localhost:5000
```
