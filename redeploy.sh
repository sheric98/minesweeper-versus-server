#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="/home/ubuntu/.env.minesweeper"
if [ ! -f "$ENV_FILE" ]; then
  echo "Error: $ENV_FILE not found. Create it with JWT_SECRET, CORS_ORIGINS, POSTGRES_PASSWORD, and DATABASE_URL."
  exit 1
fi

cd "$(dirname "$0")"
git pull

# Copy production env vars into .env for docker compose
cp "$ENV_FILE" .env

./.deploy.sh

echo "Deployed. Logs: docker compose logs -f"
