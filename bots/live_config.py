"""Tunables for live-server bot behavior.

Isolated from `bots/config.py` (per-bot profile config) so that changing
timings, injection thresholds, or invite-response probabilities does not
require touching anything the offline simulator depends on.
"""

from __future__ import annotations

# --- Lifecycle (per-bot online/offline cycle) -------------------------------

# With N = 384 bots and these parameters the steady-state online count is
# ~40, and stays inside the 30-50 band ~68% of the time:
#   p_online = E[X] / (E[X] + E[Y]) = 30 / (30 + 260) ≈ 0.104
#   online ~ Binomial(384, 0.104) ≈ N(40, 6)
ONLINE_MIN_S = 20 * 60
ONLINE_MAX_S = 40 * 60           # E[X] = 30 min

OFFLINE_MIN_S = 180 * 60
OFFLINE_MAX_S = 340 * 60         # E[Y] ≈ 260 min

# Must be strictly less than HEARTBEAT_TIMEOUT_SECONDS (60s in config.py).
HEARTBEAT_REFRESH_S = 20

# If a bot's online timer expires while it is in_game, defer the logoff
# transition and re-check after this many seconds.
LOGOFF_DEFER_IF_IN_MATCH_S = 30

# 64 KiB is plenty for the tiny lifecycle loop; default is ~8 MiB per
# thread, which on 384 threads burns ~3 GiB of virtual address space.
LIFECYCLE_THREAD_STACK_BYTES = 64 * 1024


# --- Invite responder -------------------------------------------------------

BOT_INVITE_THINK_MIN_S = 3
BOT_INVITE_THINK_MAX_S = 12
BOT_INVITE_ACCEPT_P = 0.85
BOT_INVITE_TIMEOUT_P = 0.05


# --- Queue injector --------------------------------------------------------

BOT_QUEUE_INJECT_AFTER_S = 5


# --- Match driver ----------------------------------------------------------

BOT_MATCH_START_TIMEOUT_S = 30
BOT_REMATCH_P = 0.3
