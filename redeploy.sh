#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="$HOME/.env.minesweeper"
if [ ! -f "$ENV_FILE" ]; then
  echo "Error: $ENV_FILE not found. Create it with JWT_SECRET and CORS_ORIGINS."
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

cd "$(dirname "$0")"
git pull

docker build -t minesweeper-backend .
docker stop minesweeper-backend 2>/dev/null || true
docker rm minesweeper-backend 2>/dev/null || true
docker run -d \
  --name minesweeper-backend \
  --restart unless-stopped \
  -p 5000:5000 \
  -e JWT_SECRET="$JWT_SECRET" \
  -e CORS_ORIGINS="$CORS_ORIGINS" \
  minesweeper-backend

echo "Deployed. Logs: docker logs -f minesweeper-backend"
