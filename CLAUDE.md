# Minesweeper Multiplayer Game Server

Python Flask backend for the multiplayer minesweeper game.

## Setup

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## Run

```bash
./venv/bin/python app.py
# Runs on http://0.0.0.0:5000
```

## Architecture

- **Flask + flask-sock** for HTTP REST + raw WebSocket (NOT Socket.IO)
- **All state in-memory** — no database
- Frontend BFF (Next.js at `/home/sheric/minesweeper-web`) proxies to this server via `BACKEND_URL`

## Key Files

| File | Purpose |
|---|---|
| `app.py` | Flask app factory + entry point |
| `config.py` | Constants (JWT secret, board dims, timeouts) |
| `auth.py` | `POST /auth/register`, JWT helpers, `@require_auth` decorator |
| `session_tracker.py` | In-memory player presence tracking |
| `ws_ticket.py` | `POST /ws/ticket` — single-use 30s WebSocket tickets |
| `matchmaking.py` | `GET/POST /matchmaking/{players,invite,respond}` |
| `match.py` | Match lifecycle: countdown, message relay, game completion |
| `websocket_handler.py` | `GET /ws` — flask-sock WebSocket handler |
| `board_generator.py` | Solvable board generation with retry loop |
| `solver.py` | Constraint propagation no-guess solver |
| `board_encoder.py` | Board → JSON encoding (mock format) |

## REST Endpoints

All authenticated endpoints expect `Authorization: Bearer <JWT>`.

- `POST /auth/register` — `{ "username" }` → `{ "token" }`
- `POST /ws/ticket` — → `{ "ticket" }`
- `GET /matchmaking/players` — → `{ "players": [...] }`
- `POST /matchmaking/invite` — `{ "targetUsername" }` → `{ "inviteId" }`
- `GET /matchmaking/invite` — → `{ "sent": [...], "received": [...] }`
- `POST /matchmaking/respond` — `{ "inviteId", "accept" }` → `{ "matchId" }` or `{}`

## WebSocket

`GET /ws?ticket=<ticket>&matchId=<matchId>` — raw WebSocket

## Environment Variables

- `JWT_SECRET` — signing key (random per-process if unset)
- `CORS_ORIGINS` — comma-separated allowed origins (default: `http://localhost:3000`)

## Connecting Frontend

Set in the minesweeper-web `.env`:
```
BACKEND_URL=http://localhost:5000
NEXT_PUBLIC_WS_URL=ws://localhost:5000
```
