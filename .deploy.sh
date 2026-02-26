#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

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
