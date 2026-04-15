import threading
import time

from config import HEARTBEAT_TIMEOUT_SECONDS


class SessionTracker:
    def __init__(self):
        self._lock = threading.Lock()
        # username -> {"last_seen": float, "status": "online"|"in_game", "match_id": str|None}
        self._sessions: dict[str, dict] = {}

    def touch(self, username: str):
        """Update last_seen timestamp. Creates session if new."""
        with self._lock:
            if username in self._sessions:
                self._sessions[username]["last_seen"] = time.time()
            else:
                self._sessions[username] = {
                    "last_seen": time.time(),
                    "status": "online",
                    "match_id": None,
                }

    def is_active(self, username: str) -> bool:
        with self._lock:
            s = self._sessions.get(username)
            if not s:
                return False
            return (time.time() - s["last_seen"]) < HEARTBEAT_TIMEOUT_SECONDS

    def set_in_game(self, username: str, match_id: str):
        with self._lock:
            if username in self._sessions:
                self._sessions[username]["status"] = "in_game"
                self._sessions[username]["match_id"] = match_id

    def set_online(self, username: str):
        with self._lock:
            if username in self._sessions:
                self._sessions[username]["status"] = "online"
                self._sessions[username]["match_id"] = None

    def remove(self, username: str):
        """Evict a session entirely. Used for bot logoffs."""
        with self._lock:
            self._sessions.pop(username, None)

    def set_queued(self, username: str):
        with self._lock:
            if username in self._sessions:
                self._sessions[username]["status"] = "queued"
                self._sessions[username]["match_id"] = None

    def get_active_players(self, exclude: str | None = None) -> list[dict]:
        now = time.time()
        with self._lock:
            result = []
            for uname, s in self._sessions.items():
                if uname == exclude:
                    continue
                if (now - s["last_seen"]) < HEARTBEAT_TIMEOUT_SECONDS:
                    result.append({"username": uname, "status": s["status"]})
            return result


tracker = SessionTracker()
