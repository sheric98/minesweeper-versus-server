"""Unit tests for singleplayer.parse_game_submission."""

import uuid

from singleplayer import parse_game_submission


def _valid_uuid():
    return str(uuid.uuid4())


def test_valid_random_win():
    body = {
        "mode": "random",
        "difficulty": "standard",
        "result": "win",
        "time_seconds": 87,
        "client_game_id": _valid_uuid(),
    }
    parsed, err = parse_game_submission(body)
    assert err is None
    assert parsed["mode"] == "random"
    assert parsed["difficulty"] == "standard"
    assert parsed["result"] == "win"
    assert parsed["time_seconds"] == 87


def test_valid_no_guess_wins_each_difficulty():
    for d in ("beginner", "intermediate", "advanced", "expert"):
        body = {
            "mode": "no-guess",
            "difficulty": d,
            "result": "win",
            "time_seconds": 12,
            "client_game_id": _valid_uuid(),
        }
        parsed, err = parse_game_submission(body)
        assert err is None, f"{d}: {err}"
        assert parsed["difficulty"] == d


def test_valid_loss_has_null_time():
    body = {
        "mode": "random",
        "difficulty": "standard",
        "result": "loss",
        "time_seconds": None,
        "client_game_id": _valid_uuid(),
    }
    parsed, err = parse_game_submission(body)
    assert err is None
    assert parsed["time_seconds"] is None


def test_random_with_non_standard_difficulty_rejected():
    body = {
        "mode": "random",
        "difficulty": "beginner",
        "result": "loss",
        "time_seconds": None,
        "client_game_id": _valid_uuid(),
    }
    _, err = parse_game_submission(body)
    assert err is not None


def test_no_guess_with_standard_difficulty_rejected():
    body = {
        "mode": "no-guess",
        "difficulty": "standard",
        "result": "loss",
        "time_seconds": None,
        "client_game_id": _valid_uuid(),
    }
    _, err = parse_game_submission(body)
    assert err is not None


def test_win_requires_time_seconds():
    body = {
        "mode": "random",
        "difficulty": "standard",
        "result": "win",
        "time_seconds": None,
        "client_game_id": _valid_uuid(),
    }
    _, err = parse_game_submission(body)
    assert err is not None


def test_time_seconds_out_of_range_rejected():
    for t in (0, -1, 1000, 99999):
        body = {
            "mode": "random",
            "difficulty": "standard",
            "result": "win",
            "time_seconds": t,
            "client_game_id": _valid_uuid(),
        }
        _, err = parse_game_submission(body)
        assert err is not None, f"t={t} should fail"


def test_invalid_mode_rejected():
    body = {
        "mode": "bogus",
        "difficulty": "standard",
        "result": "loss",
        "time_seconds": None,
        "client_game_id": _valid_uuid(),
    }
    _, err = parse_game_submission(body)
    assert err is not None


def test_invalid_result_rejected():
    body = {
        "mode": "random",
        "difficulty": "standard",
        "result": "draw",
        "time_seconds": None,
        "client_game_id": _valid_uuid(),
    }
    _, err = parse_game_submission(body)
    assert err is not None


def test_bad_uuid_rejected():
    body = {
        "mode": "random",
        "difficulty": "standard",
        "result": "loss",
        "time_seconds": None,
        "client_game_id": "not-a-uuid",
    }
    _, err = parse_game_submission(body)
    assert err is not None


def test_missing_field_rejected():
    body = {"mode": "random", "difficulty": "standard"}
    _, err = parse_game_submission(body)
    assert err is not None


def test_loss_time_seconds_coerced_to_none():
    """If frontend sends a numeric time on a loss, ignore/null it (not an error)."""
    body = {
        "mode": "random",
        "difficulty": "standard",
        "result": "loss",
        "time_seconds": 42,
        "client_game_id": _valid_uuid(),
    }
    parsed, err = parse_game_submission(body)
    assert err is None
    assert parsed["time_seconds"] is None


def test_bool_time_seconds_rejected():
    """`True` happens to satisfy isinstance(int) and equals 1, so the validator
    must explicitly reject booleans to avoid accepting malformed JSON payloads."""
    body = {
        "mode": "random",
        "difficulty": "standard",
        "result": "win",
        "time_seconds": True,
        "client_game_id": _valid_uuid(),
    }
    _, err = parse_game_submission(body)
    assert err is not None
