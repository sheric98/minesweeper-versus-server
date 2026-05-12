"""Single-player stats endpoints + helpers.

POST /singleplayer/games  - record one completed game (win or loss)
GET  /singleplayer/stats/me - return the requester's per-category stats
"""

import uuid

from flask import Blueprint

singleplayer_bp = Blueprint("singleplayer", __name__)

VALID_MODES = ("random", "no-guess")
VALID_NO_GUESS_DIFFICULTIES = ("beginner", "intermediate", "advanced", "expert")
VALID_RESULTS = ("win", "loss")


def parse_game_submission(body):
    """Validate a POST /singleplayer/games request body.

    Returns (parsed_dict, None) on success or (None, error_message) on failure.
    `parsed_dict` keys: mode, difficulty, result, time_seconds, client_game_id.
    `time_seconds` is forced to None when result == "loss".
    """
    if not isinstance(body, dict):
        return None, "body must be a JSON object"

    mode = body.get("mode")
    if mode not in VALID_MODES:
        return None, f"mode must be one of {VALID_MODES}"

    difficulty = body.get("difficulty")
    if mode == "random":
        if difficulty != "standard":
            return None, "difficulty must be 'standard' when mode is 'random'"
    else:  # no-guess
        if difficulty not in VALID_NO_GUESS_DIFFICULTIES:
            return None, f"difficulty must be one of {VALID_NO_GUESS_DIFFICULTIES}"

    result = body.get("result")
    if result not in VALID_RESULTS:
        return None, f"result must be one of {VALID_RESULTS}"

    time_seconds = body.get("time_seconds")
    if result == "win":
        if isinstance(time_seconds, bool) or not isinstance(time_seconds, int) or time_seconds < 1 or time_seconds > 999:
            return None, "time_seconds must be an integer 1-999 for a win"
    else:
        # Loss — drop any time the client may have sent.
        time_seconds = None

    raw_client_game_id = body.get("client_game_id")
    if not isinstance(raw_client_game_id, str):
        return None, "client_game_id must be a string"
    try:
        client_game_id = str(uuid.UUID(raw_client_game_id))
    except (ValueError, AttributeError):
        return None, "client_game_id must be a UUID"

    return {
        "mode": mode,
        "difficulty": difficulty,
        "result": result,
        "time_seconds": time_seconds,
        "client_game_id": client_game_id,
    }, None
