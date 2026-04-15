"""Pair long-waiting humans in the matchmaking queue with bots.

Humans who sit in `/matchmaking/queue` without finding a human opponent
are offered a rating-appropriate bot after `BOT_QUEUE_INJECT_AFTER_S`
seconds. The injector runs as a post-cycle hook on the matchmaking
thread (registered via `matchmaking_queue.register_post_cycle_hook`), so
it naturally runs *after* the human-vs-human `run_matching_cycle` and a
pair of queued humans who match each other will always pair up first.

Design notes
------------

* Bots are never enqueued. Keeping bots out of `_queue` preserves the
  existing `_find_matches` O(n²) search at n = number of humans instead
  of n = humans + 384 bots.
* Eligibility mirrors the human-vs-human matching widened-range logic:
  as the human waits longer, the acceptable rating gap grows the same
  way it does for human opponents, up to `QUEUE_MAX_RANGE`.
* The flip from `waiting` → `matched` happens under the queue's lock
  via `force_match_with_bot`. If that returns False the human was
  already picked up by `run_matching_cycle` on a sibling cycle — we
  silently skip the injection and the bot remains unattached.
* Within a single post-cycle tick we don't pick the same bot twice, and
  we exclude bots that are currently `in_game` (e.g. a bot that just
  accepted an invite earlier in the same tick). Without this guard two
  humans who queued at the same time could be matched to the same bot.
"""

from __future__ import annotations

import logging
import random
import threading
import time
import uuid

from config import (
    QUEUE_BASE_RANGE,
    QUEUE_EXPANSION_INTERVAL,
    QUEUE_MAX_RANGE,
    QUEUE_RANGE_STEP,
)
from session_tracker import tracker

from .live_config import BOT_QUEUE_INJECT_AFTER_S
from .registry import bot_registry


logger = logging.getLogger(__name__)


_started = False
_start_lock = threading.Lock()

# Module-level RNG so tests can seed deterministic bot selection.
_rng_lock = threading.Lock()
_rng = random.Random()


def _allowed_range(wait_seconds: float) -> float:
    """Mirror of `MatchmakingQueue._find_matches.allowed_range`."""
    r = QUEUE_BASE_RANGE + (wait_seconds / QUEUE_EXPANSION_INTERVAL) * QUEUE_RANGE_STEP
    return min(r, QUEUE_MAX_RANGE)


def _pick_bot(target_rating: int, tolerance: float, exclude: set[str]):
    """Pick a random online, idle bot within `tolerance` of `target_rating`.

    Walks `all_bots()` once — small (384) and we already need to filter
    on live presence so we can't use `sample_by_rating` alone.
    """
    candidates = []
    for bot in bot_registry.all_bots():
        if bot.username in exclude:
            continue
        if abs(bot.rating - target_rating) > tolerance:
            continue
        if tracker.get_status(bot.username) != "online":
            continue
        candidates.append(bot)
    if not candidates:
        return None
    with _rng_lock:
        return _rng.choice(candidates)


def _inject_once() -> None:
    """One pass over the waiting queue. Called from the matchmaking thread."""
    # Local imports keep this module importable without pulling Flask or
    # the match module in at bot-startup time.
    from match import match_manager
    from matchmaking import invite_store
    from matchmaking_queue import matchmaking_queue

    from .match_driver import BotMatchDriver

    now = time.time()
    snapshot = matchmaking_queue.get_waiting_snapshot()
    if not snapshot:
        return

    used_bots: set[str] = set()
    for entry in snapshot:
        wait = now - entry["enqueue_time"]
        if wait < BOT_QUEUE_INJECT_AFTER_S:
            continue

        tolerance = _allowed_range(wait)
        bot = _pick_bot(entry["rating"], tolerance, used_bots)
        if bot is None:
            continue

        username = entry["username"]
        match_id = str(uuid.uuid4())

        # Atomic flip inside the queue lock — rejects if the entry
        # was grabbed by `run_matching_cycle` on a concurrent cycle
        # or if the human has since dropped.
        if not matchmaking_queue.force_match_with_bot(
            username, bot.username, match_id
        ):
            continue

        # Reserve the bot before any more checks so a second human in
        # this same tick doesn't also pick it.
        used_bots.add(bot.username)

        try:
            match_manager.create_match(match_id, username, bot.username)
            match = match_manager.get_match(match_id)
            if match is None:
                logger.warning(
                    "queue-injector: create_match returned but match %s missing",
                    match_id,
                )
                continue

            tracker.set_in_game(username, match_id)
            tracker.set_in_game(bot.username, match_id)
            invite_store.cancel_pending_for_user(username)
            invite_store.cancel_pending_for_user(bot.username)

            driver = BotMatchDriver(match, bot)
            driver.start()
        except Exception:
            logger.exception(
                "queue-injector: failed to inject bot %s for human %s",
                bot.username,
                username,
            )
            # Leave the queue entry in the `matched` state it was
            # flipped to — the human's `queue_status` poll will
            # surface a match_id whose Match object may or may not
            # exist. This is the same degenerate state the
            # human-vs-human path would be in if create_match threw.


def start_queue_injector(*, seed: int | None = None) -> bool:
    """Register the injector as a post-cycle hook.

    Idempotent. Returns True the first time, False on subsequent calls.
    `seed` seeds the bot-selection RNG for reproducible integration tests.
    """
    global _started
    with _start_lock:
        if _started:
            return False
        _started = True

    if seed is not None:
        with _rng_lock:
            _rng.seed(seed)

    # Deferred import: matchmaking_queue is safe to import at start
    # time, but we do it lazily so test harnesses that import this
    # module without a Flask app can still construct mocks.
    from matchmaking_queue import register_post_cycle_hook

    register_post_cycle_hook(_inject_once)
    logger.info("Bot queue injector registered")
    return True
