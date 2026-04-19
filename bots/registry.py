"""Bot registry — loaded once at app startup.

Merges `bots/profiles.json`, `bots/ratings.json`, and `bots/user_ids.json`
into an immutable lookup keyed by the bot's human-facing `username`. This is
what the rest of the live server uses to know "is this name a bot?" and to
fetch the bot's config/UUID when plumbing matches.

Boot-fails loudly if `user_ids.json` is missing so we don't silently run
without persistent bot identities — `python -m bots.seed_elo` must be run
first.
"""

from __future__ import annotations

import json
import os
import random
import threading
from dataclasses import dataclass
from pathlib import Path

from .config import BotConfig, load_profiles


DEFAULT_PROFILES_PATH = Path(__file__).parent / "profiles.json"
DEFAULT_RATINGS_PATH = Path(__file__).parent / "ratings.json"
# `BOT_USER_IDS_PATH` allows pointing at a persistent volume in prod so the
# seeded UUID mapping survives container rebuilds. Falls back to the
# source-tree location used in dev and tests.
DEFAULT_USER_IDS_PATH = Path(
    os.getenv("BOT_USER_IDS_PATH") or (Path(__file__).parent / "user_ids.json")
)


@dataclass(frozen=True)
class BotEntry:
    username: str       # human-facing handle; matches session tracker keys
    display_name: str   # same as username — what the DB stores in users.display_name
    user_id: str        # UUID from bots/user_ids.json (persistent across restarts)
    profile_name: str   # systematic id, e.g. "perfect_deep_slow_wrs"
    cfg: BotConfig
    rating: int


class BotRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded = False
        self._by_username: dict[str, BotEntry] = {}

    def load(
        self,
        *,
        profiles_path: Path = DEFAULT_PROFILES_PATH,
        ratings_path: Path = DEFAULT_RATINGS_PATH,
        user_ids_path: Path = DEFAULT_USER_IDS_PATH,
    ) -> None:
        with self._lock:
            if self._loaded:
                return

            if not user_ids_path.exists():
                raise RuntimeError(
                    f"Bot registry cannot load: {user_ids_path} is missing. "
                    f"Run `python -m bots.seed_elo` before enabling BOTS_ENABLED."
                )

            profiles = load_profiles(profiles_path)
            raw = json.loads(ratings_path.read_text())
            # Support both old flat format {name: rating} and new nested
            # format {"ratings": {...}, "stats": {...}}.
            if "ratings" in raw and isinstance(raw.get("ratings"), dict):
                raw = raw["ratings"]
            ratings: dict[str, int] = {k: int(v) for k, v in raw.items()}
            user_ids: dict[str, str] = json.loads(user_ids_path.read_text())

            by_username: dict[str, BotEntry] = {}
            for profile_name, cfg in profiles.items():
                uid = user_ids.get(profile_name)
                if uid is None:
                    # Profile has no seeded user row — skip silently; seed_elo
                    # may not yet have been re-run after adding a new profile.
                    continue
                rating = ratings.get(profile_name)
                if rating is None:
                    continue
                if cfg.username in by_username:
                    raise RuntimeError(
                        f"Duplicate bot username {cfg.username!r} "
                        f"(profiles {by_username[cfg.username].profile_name} "
                        f"and {profile_name})"
                    )
                by_username[cfg.username] = BotEntry(
                    username=cfg.username,
                    display_name=cfg.username,
                    user_id=uid,
                    profile_name=profile_name,
                    cfg=cfg,
                    rating=rating,
                )

            self._by_username = by_username
            self._loaded = True

    def _require_loaded(self) -> None:
        if not self._loaded:
            raise RuntimeError("BotRegistry.load() has not been called")

    def is_bot(self, username: str) -> bool:
        if not self._loaded:
            return False
        return username in self._by_username

    def get(self, username: str) -> BotEntry | None:
        self._require_loaded()
        return self._by_username.get(username)

    def all_bots(self) -> list[BotEntry]:
        self._require_loaded()
        return list(self._by_username.values())

    def sample_by_rating(
        self,
        target_rating: int,
        tolerance: int,
        *,
        exclude: set[str] | None = None,
        rng: random.Random | None = None,
    ) -> BotEntry | None:
        """Uniformly pick one bot whose rating is within ±tolerance of target.

        Returns None if no bot matches. `exclude` filters by username.
        """
        self._require_loaded()
        rng = rng or random
        exclude = exclude or set()
        candidates = [
            b
            for b in self._by_username.values()
            if b.username not in exclude
            and abs(b.rating - target_rating) <= tolerance
        ]
        if not candidates:
            return None
        return rng.choice(candidates)

    def random_subset(
        self, n: int, *, rng: random.Random | None = None
    ) -> list[BotEntry]:
        self._require_loaded()
        rng = rng or random
        bots = list(self._by_username.values())
        if n >= len(bots):
            return bots
        return rng.sample(bots, n)


bot_registry = BotRegistry()
