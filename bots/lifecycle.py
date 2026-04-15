"""Per-bot online/offline lifecycle loops.

Each bot runs an independent daemon thread alternating between:

    online  for X ~ Uniform(ONLINE_MIN_S, ONLINE_MAX_S)
    offline for Y ~ Uniform(OFFLINE_MIN_S, OFFLINE_MAX_S)

While online the loop calls `tracker.touch()` every HEARTBEAT_REFRESH_S
seconds so the session does not time out. On transition to offline it
calls `tracker.remove()` and cancels any pending invites involving this
bot. A bot whose online timer expires while it is `in_game` defers the
logoff until the match ends.

Initial state per bot is drawn from the steady-state distribution of
this alternating renewal process so the system does not cold-start at
zero online.

Started from `app.py` when `BOTS_ENABLED=1`. No central orchestrator —
average online count is a statistical property of the parameters in
`bots.live_config`.
"""

from __future__ import annotations

import logging
import random
import threading
import time

from session_tracker import tracker

from .live_config import (
    HEARTBEAT_REFRESH_S,
    LIFECYCLE_THREAD_STACK_BYTES,
    LOGOFF_DEFER_IF_IN_MATCH_S,
    OFFLINE_MAX_S,
    OFFLINE_MIN_S,
    ONLINE_MAX_S,
    ONLINE_MIN_S,
)
from .registry import BotEntry, bot_registry

logger = logging.getLogger(__name__)


_started = False
_start_lock = threading.Lock()


def _initial_state(rng: random.Random) -> tuple[str, float]:
    """Sample (state, remaining_seconds) from the steady-state distribution.

    Approximation: remaining lifetime of the current phase is uniform on
    [0, phase_max]. Not the exact equilibrium distribution of a uniform,
    but close enough — the system self-corrects within one cycle.
    """
    mean_on = (ONLINE_MIN_S + ONLINE_MAX_S) / 2.0
    mean_off = (OFFLINE_MIN_S + OFFLINE_MAX_S) / 2.0
    p_online = mean_on / (mean_on + mean_off)
    if rng.random() < p_online:
        return "online", rng.uniform(0.0, ONLINE_MAX_S)
    return "offline", rng.uniform(0.0, OFFLINE_MAX_S)


def _cancel_pending_invites(username: str) -> None:
    """Best-effort cancel — matchmaking module may not be importable in tests."""
    try:
        from matchmaking import invite_store
    except Exception:  # pragma: no cover
        return
    try:
        invite_store.cancel_pending_for_user(username)
    except Exception:  # pragma: no cover
        logger.exception("cancel_pending_for_user failed for %s", username)


def _run_bot(bot: BotEntry, rng: random.Random) -> None:
    state, remaining = _initial_state(rng)
    if state == "online":
        tracker.touch(bot.username)

    while True:
        try:
            slept = min(remaining, float(HEARTBEAT_REFRESH_S))
            if slept > 0:
                time.sleep(slept)
            remaining -= slept

            if state == "online" and remaining > 0:
                # Refresh the heartbeat so the session stays live.
                tracker.touch(bot.username)

            if remaining > 0:
                continue

            # Timer expired — transition.
            if state == "online":
                if tracker.get_status(bot.username) == "in_game":
                    # Defer logoff until the match ends.
                    remaining = float(LOGOFF_DEFER_IF_IN_MATCH_S)
                    continue
                tracker.remove(bot.username)
                _cancel_pending_invites(bot.username)
                state = "offline"
                remaining = rng.uniform(OFFLINE_MIN_S, OFFLINE_MAX_S)
            else:
                tracker.touch(bot.username)
                state = "online"
                remaining = rng.uniform(ONLINE_MIN_S, ONLINE_MAX_S)
        except Exception:  # pragma: no cover — never let a bot thread die silently
            logger.exception("lifecycle loop error for bot %s", bot.username)
            time.sleep(HEARTBEAT_REFRESH_S)


def start_lifecycle_loops(*, seed: int | None = None) -> int:
    """Spawn one daemon thread per registered bot.

    Idempotent — subsequent calls are no-ops. Returns the number of
    threads started on the first call, or 0 on subsequent calls.

    `seed` seeds a parent RNG that hands a child `random.Random` to each
    bot, for reproducible integration tests.
    """
    global _started
    with _start_lock:
        if _started:
            return 0
        _started = True

    bots = bot_registry.all_bots()
    if not bots:
        logger.warning("start_lifecycle_loops: bot registry is empty")
        return 0

    try:
        threading.stack_size(LIFECYCLE_THREAD_STACK_BYTES)
    except (ValueError, RuntimeError):  # pragma: no cover — platform-dependent
        logger.warning("Could not reduce thread stack size; using default")

    parent_rng = random.Random(seed)
    count = 0
    for bot in bots:
        bot_rng = random.Random(parent_rng.random())
        t = threading.Thread(
            target=_run_bot,
            args=(bot, bot_rng),
            name=f"bot-lifecycle-{bot.username}",
            daemon=True,
        )
        t.start()
        count += 1

    logger.info("Started %d bot lifecycle threads", count)
    return count
