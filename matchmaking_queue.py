import uuid
import threading
import time

from flask import Blueprint, jsonify, g

from auth import require_auth
from session_tracker import tracker
from elo import DEFAULT_RATING
from config import (
    DATABASE_URL,
    QUEUE_BASE_RANGE,
    QUEUE_EXPANSION_INTERVAL,
    QUEUE_RANGE_STEP,
    QUEUE_MAX_RANGE,
    QUEUE_MAX_WAIT,
    MATCH_LOOP_INTERVAL,
)

queue_bp = Blueprint("matchmaking_queue", __name__)


class MatchmakingQueue:
    def __init__(self):
        self._lock = threading.Lock()
        self._queue: dict[str, dict] = {}

    def join(self, username: str, user_id: str | None, rating: int, is_rated: bool) -> bool:
        with self._lock:
            if username in self._queue:
                return False
            self._queue[username] = {
                "username": username,
                "user_id": user_id,
                "rating": rating,
                "is_rated": is_rated,
                "enqueue_time": time.time(),
                "match_id": None,
                "matched_opponent": None,
                "status": "waiting",
            }
            return True

    def leave(self, username: str) -> bool:
        with self._lock:
            if username in self._queue:
                del self._queue[username]
                return True
            return False

    def is_queued(self, username: str) -> bool:
        with self._lock:
            entry = self._queue.get(username)
            return entry is not None and entry["status"] == "waiting"

    def get_status(self, username: str) -> dict | None:
        with self._lock:
            entry = self._queue.get(username)
            if not entry:
                return None
            return dict(entry)

    def consume_match(self, username: str) -> dict | None:
        with self._lock:
            entry = self._queue.get(username)
            if entry and entry["status"] == "matched":
                del self._queue[username]
                return dict(entry)
            return None

    def run_matching_cycle(self):
        self._cleanup_stale()
        pairs = self._find_matches()
        for a, b in pairs:
            self._create_match_for_pair(a, b)

    def _cleanup_stale(self):
        now = time.time()
        with self._lock:
            to_remove = []
            for username, entry in self._queue.items():
                if entry["status"] != "waiting":
                    continue
                if not tracker.is_active(username):
                    to_remove.append(username)
                elif (now - entry["enqueue_time"]) > QUEUE_MAX_WAIT:
                    to_remove.append(username)
            for username in to_remove:
                del self._queue[username]

    def _find_matches(self) -> list[tuple[dict, dict]]:
        now = time.time()
        with self._lock:
            waiting = [
                e for e in self._queue.values() if e["status"] == "waiting"
            ]

        if len(waiting) < 2:
            return []

        def allowed_range(entry):
            wait = now - entry["enqueue_time"]
            r = QUEUE_BASE_RANGE + (wait / QUEUE_EXPANSION_INTERVAL) * QUEUE_RANGE_STEP
            return min(r, QUEUE_MAX_RANGE)

        candidates = []
        for i in range(len(waiting)):
            for j in range(i + 1, len(waiting)):
                a, b = waiting[i], waiting[j]
                diff = abs(a["rating"] - b["rating"])
                if diff <= min(allowed_range(a), allowed_range(b)):
                    candidates.append((diff, a, b))

        candidates.sort(key=lambda x: x[0])

        matched_usernames = set()
        pairs = []
        for diff, a, b in candidates:
            if a["username"] in matched_usernames or b["username"] in matched_usernames:
                continue
            pairs.append((a, b))
            matched_usernames.add(a["username"])
            matched_usernames.add(b["username"])

        return pairs

    def _create_match_for_pair(self, a: dict, b: dict):
        from match import match_manager
        from matchmaking import invite_store

        match_id = str(uuid.uuid4())

        with self._lock:
            entry_a = self._queue.get(a["username"])
            entry_b = self._queue.get(b["username"])
            if not entry_a or entry_a["status"] != "waiting":
                return
            if not entry_b or entry_b["status"] != "waiting":
                return

            entry_a["status"] = "matched"
            entry_a["match_id"] = match_id
            entry_a["matched_opponent"] = b["username"]
            entry_b["status"] = "matched"
            entry_b["match_id"] = match_id
            entry_b["matched_opponent"] = a["username"]

        match_manager.create_match(match_id, a["username"], b["username"])
        tracker.set_in_game(a["username"], match_id)
        tracker.set_in_game(b["username"], match_id)
        invite_store.cancel_pending_for_user(a["username"])
        invite_store.cancel_pending_for_user(b["username"])


matchmaking_queue = MatchmakingQueue()


def _fetch_rating(user_id: str | None) -> int:
    if not DATABASE_URL or not user_id:
        return DEFAULT_RATING
    try:
        from db import get_conn
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT rating FROM elo_ratings WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
                return row[0] if row else DEFAULT_RATING
        finally:
            conn.close()
    except Exception:
        return DEFAULT_RATING


@queue_bp.route("/matchmaking/queue/join", methods=["POST"])
@require_auth
def join_queue():
    username = g.username
    user_id = getattr(g, "user_id", None)
    auth_level = getattr(g, "auth_level", "anonymous")

    players = tracker.get_active_players()
    for p in players:
        if p["username"] == username and p["status"] == "in_game":
            return jsonify({"error": "Already in a game"}), 409

    if matchmaking_queue.is_queued(username):
        return jsonify({"error": "Already in queue"}), 409

    is_rated = auth_level == "google" and user_id is not None
    rating = _fetch_rating(user_id) if is_rated else DEFAULT_RATING

    if not matchmaking_queue.join(username, user_id, rating, is_rated):
        return jsonify({"error": "Already in queue"}), 409

    tracker.set_queued(username)
    return jsonify({"status": "queued"})


@queue_bp.route("/matchmaking/queue/leave", methods=["POST"])
@require_auth
def leave_queue():
    if matchmaking_queue.leave(g.username):
        tracker.set_online(g.username)
        return jsonify({"status": "left"})
    return jsonify({"error": "Not in queue"}), 404


@queue_bp.route("/matchmaking/queue/status", methods=["GET"])
@require_auth
def queue_status():
    entry = matchmaking_queue.get_status(g.username)
    if not entry:
        consumed = matchmaking_queue.consume_match(g.username)
        if consumed:
            return jsonify({
                "status": "matched",
                "matchId": consumed["match_id"],
                "opponent": consumed["matched_opponent"],
            })
        return jsonify({"status": "none"})

    if entry["status"] == "matched":
        matchmaking_queue.consume_match(g.username)
        return jsonify({
            "status": "matched",
            "matchId": entry["match_id"],
            "opponent": entry["matched_opponent"],
        })

    return jsonify({
        "status": "waiting",
        "waitSeconds": round(time.time() - entry["enqueue_time"], 1),
    })


def _match_loop():
    print("[matchmaking-queue] started")
    while True:
        try:
            matchmaking_queue.run_matching_cycle()
        except Exception as e:
            print(f"[matchmaking-queue] error: {e}")
        time.sleep(MATCH_LOOP_INTERVAL)


def start_matchmaking_loop():
    t = threading.Thread(target=_match_loop, daemon=True)
    t.start()
    return t
