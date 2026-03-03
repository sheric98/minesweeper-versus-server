#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Clean up legacy standalone container (from pre-compose deploys)
docker stop minesweeper-backend 2>/dev/null || true
docker rm minesweeper-backend 2>/dev/null || true

# Build and start services defined in docker-compose.yml
docker compose down
docker compose up --build -d
