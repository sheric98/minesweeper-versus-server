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

./.deploy.sh

echo "Deployed. Logs: docker logs -f minesweeper-backend"
