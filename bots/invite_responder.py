"""Delayed bot responses to human invites.

When `POST /matchmaking/invite` targets a bot, the endpoint schedules a
bot response through `schedule_bot_response`. A `threading.Timer` fires
after a "thinking" delay (Uniform a few seconds) and decides the outcome:

- Accept (`BOT_INVITE_ACCEPT_P`): take the same path a human taking
  `POST /matchmaking/respond` with accept=true would — mark the invite
  accepted, create the match, and start the `BotMatchDriver` so the bot
  is attached before the human's real WebSocket arrives.
- Decline (complement): flip the invite to rejected. The inviter's
  existing invite-polling surfaces this the same way it would for a human
  decline.
- Timeout (`BOT_INVITE_TIMEOUT_P`): do nothing — leave the invite pending
  so it simply ages out, mimicking a human who just didn't notice the
  ping. Still counts as "the bot thought about it" because we already
  committed to waiting the think delay before doing nothing.

Notes
-----

* We do NOT import `matchmaking`, `match`, or `match_driver` at module
  load time. That keeps this module importable from inside
  `matchmaking.py`'s request handler without building an import cycle.
* We never accept on behalf of a bot that has since gone offline or been
  dragged into a different match — a bot accepting an invite it can no
  longer fulfill would orphan the inviter inside a half-built match.
* The inviter's online status is re-checked immediately before
  `create_match`. If they gave up mid-think we silently drop the accept
  rather than creating a match whose human side will never attach.
"""

from __future__ import annotations

import random
import threading

from session_tracker import tracker

from .live_config import (
    BOT_INVITE_ACCEPT_P,
    BOT_INVITE_THINK_MAX_S,
    BOT_INVITE_THINK_MIN_S,
    BOT_INVITE_TIMEOUT_P,
)
from .registry import bot_registry


# Module-level RNG so tests can swap in a seeded instance if they want
# reproducible scheduling. Guarded by a lock because timers may resolve
# concurrently across many threads.
_rng_lock = threading.Lock()
_rng = random.Random()


def _roll() -> float:
    with _rng_lock:
        return _rng.random()


def _uniform(a: float, b: float) -> float:
    with _rng_lock:
        return _rng.uniform(a, b)


def schedule_bot_response(invite_id: str, bot_username: str) -> None:
    """Fire-and-forget: schedule a bot decision on a pending invite.

    Must be safe to call from inside the matchmaking request handler —
    it returns immediately after spawning a daemon timer.
    """
    # Pre-decide the outcome before sleeping so a "timeout" branch still
    # looks like a real delay to the inviter (the alternative — choosing
    # after the timer fires — collapses timeouts to zero delay).
    r = _roll()
    if r < BOT_INVITE_TIMEOUT_P:
        return  # ghost the invite; it will expire on its own
    accept = r < (BOT_INVITE_TIMEOUT_P + BOT_INVITE_ACCEPT_P)

    delay = _uniform(BOT_INVITE_THINK_MIN_S, BOT_INVITE_THINK_MAX_S)
    timer = threading.Timer(
        delay,
        _respond,
        args=(invite_id, bot_username, accept),
    )
    timer.daemon = True
    timer.name = f"bot-invite-{bot_username}"
    timer.start()


def _respond(invite_id: str, bot_username: str, accept: bool) -> None:
    """Timer callback — runs on a background thread after the think delay."""
    try:
        # Local imports keep this module importable from matchmaking.py
        # without creating a circular dependency at request time.
        from match import match_manager
        from matchmaking import invite_store

        # If the bot is no longer reachable (went offline during its
        # think pause) or is already in a match from an earlier invite
        # that resolved first, silently drop — the invite will expire.
        status = tracker.get_status(bot_username)
        if status != "online":
            return

        bot = bot_registry.get(bot_username)
        if bot is None:
            return

        if not accept:
            invite_store.respond(invite_id, False)
            return

        result = invite_store.respond(invite_id, True)
        if not result or not result.get("match_id"):
            # Already rejected/cancelled/accepted by a concurrent path.
            return

        inviter = result["from"]
        match_id = result["match_id"]

        # Re-check the inviter's presence at the last possible moment.
        # If they dropped off during the think pause, do not spin up a
        # match whose human half will never attach.
        if not tracker.is_active(inviter):
            return

        match_manager.create_match(match_id, inviter, bot_username)
        match = match_manager.get_match(match_id)
        if match is None:
            return

        # Deferred import: match_driver pulls in brain/runner, which we
        # don't want to load on every matchmaking request.
        from .match_driver import BotMatchDriver

        driver = BotMatchDriver(match, bot)
        driver.start()
    except Exception:
        # A crash here must never take the matchmaking thread down.
        # The invite will age out naturally if we fail to respond.
        pass
