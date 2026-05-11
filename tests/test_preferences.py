"""Unit tests for preferences.parse_controls.

Mirrors the JS-side tests in app/lib/__tests__/controls.test.ts. Keeps the
server-side validator in sync with the client-side schema.
"""

from preferences import DEFAULT_CONTROLS, parse_controls


def test_returns_defaults_for_non_dict_input():
    assert parse_controls(None) == DEFAULT_CONTROLS
    assert parse_controls("string") == DEFAULT_CONTROLS
    assert parse_controls(42) == DEFAULT_CONTROLS
    assert parse_controls([]) == DEFAULT_CONTROLS


def test_returns_defaults_for_empty_dict():
    assert parse_controls({}) == DEFAULT_CONTROLS


def test_passes_valid_values_through():
    valid = {
        "chordTrigger": "middle-click",
        "spacebarAction": "flag-only",
        "questionMarks": True,
    }
    assert parse_controls(valid) == valid


def test_falls_back_for_invalid_enum_values():
    result = parse_controls({
        "chordTrigger": "bogus",
        "spacebarAction": 17,
        "questionMarks": False,
    })
    assert result["chordTrigger"] == DEFAULT_CONTROLS["chordTrigger"]
    assert result["spacebarAction"] == DEFAULT_CONTROLS["spacebarAction"]
    assert result["questionMarks"] is False


def test_falls_back_for_non_boolean_question_marks():
    result = parse_controls({
        "chordTrigger": "double-click",
        "spacebarAction": "off",
        "questionMarks": "true",
    })
    assert result["questionMarks"] is DEFAULT_CONTROLS["questionMarks"]
    assert result["chordTrigger"] == "double-click"
    assert result["spacebarAction"] == "off"


def test_fills_in_missing_keys():
    result = parse_controls({"chordTrigger": "none"})
    assert result == {
        "chordTrigger": "none",
        "spacebarAction": DEFAULT_CONTROLS["spacebarAction"],
        "questionMarks": DEFAULT_CONTROLS["questionMarks"],
    }


def test_drops_unknown_keys():
    result = parse_controls({
        "chordTrigger": "middle-click",
        "spacebarAction": "flag-only",
        "questionMarks": True,
        "extraGarbage": "ignored",
        "anotherOne": 99,
    })
    assert set(result.keys()) == {"chordTrigger", "spacebarAction", "questionMarks"}


def test_accepts_every_documented_enum_value():
    for t in ("both-buttons", "middle-click", "double-click", "none"):
        assert parse_controls({"chordTrigger": t})["chordTrigger"] == t
    for a in ("flag-or-chord", "flag-only", "off"):
        assert parse_controls({"spacebarAction": a})["spacebarAction"] == a
