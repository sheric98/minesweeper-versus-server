#!/bin/sh
# Container entrypoint.
#
# When BOTS_ENABLED=1, seeds calibrated bot ELO ratings into the DB before
# launching gunicorn. `bots/seed_elo` is idempotent and also ensures
# `$BOT_USER_IDS_PATH` (or the in-source default) exists, which the bot
# registry requires at app import time.
set -e

if [ "${BOTS_ENABLED:-0}" = "1" ]; then
    echo "[entrypoint] BOTS_ENABLED=1 — seeding bot ELO ratings"
    python -m bots.seed_elo
fi

exec gunicorn \
    --bind 0.0.0.0:5000 \
    --worker-class gevent \
    --workers 1 \
    --timeout 300 \
    "app:create_app()"
