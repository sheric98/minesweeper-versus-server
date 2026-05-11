import json

from flask import Blueprint, jsonify, request, g

from auth import require_auth
from config import DATABASE_URL

preferences_bp = Blueprint("preferences", __name__)

CHORD_TRIGGERS = {"both-buttons", "middle-click", "double-click", "none"}
SPACEBAR_ACTIONS = {"flag-or-chord", "flag-only", "off"}

DEFAULT_CONTROLS = {
    "chordTrigger": "both-buttons",
    "spacebarAction": "flag-or-chord",
    "questionMarks": False,
}


def parse_controls(raw):
    """Validate untrusted input. Returns a full ControlsPrefs dict, filling in
    defaults for any field that is missing or has an invalid value. Unknown
    keys are dropped. Mirrors parseControls in app/lib/controls.ts."""
    if not isinstance(raw, dict):
        return dict(DEFAULT_CONTROLS)
    out = dict(DEFAULT_CONTROLS)
    if raw.get("chordTrigger") in CHORD_TRIGGERS:
        out["chordTrigger"] = raw["chordTrigger"]
    if raw.get("spacebarAction") in SPACEBAR_ACTIONS:
        out["spacebarAction"] = raw["spacebarAction"]
    if isinstance(raw.get("questionMarks"), bool):
        out["questionMarks"] = raw["questionMarks"]
    return out


@preferences_bp.route("/preferences/controls", methods=["GET"])
@require_auth
def get_controls():
    if g.auth_level != "google":
        return jsonify({"error": "Google authentication required"}), 401
    if not DATABASE_URL:
        return jsonify({"error": "Database not configured"}), 503

    from db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT controls FROM user_preferences WHERE user_id = %s",
                (g.user_id,),
            )
            row = cur.fetchone()
            if row is None:
                return jsonify({"error": "Not found"}), 404
            # psycopg2 returns JSONB as a parsed Python value already.
            return jsonify({"controls": parse_controls(row[0])})
    finally:
        conn.close()


@preferences_bp.route("/preferences/controls", methods=["PUT"])
@require_auth
def put_controls():
    if g.auth_level != "google":
        return jsonify({"error": "Google authentication required"}), 401
    if not DATABASE_URL:
        return jsonify({"error": "Database not configured"}), 503

    body = request.get_json(silent=True) or {}
    controls = parse_controls(body.get("controls"))

    from db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_preferences (user_id, controls, updated_at)
                VALUES (%s, %s::jsonb, now())
                ON CONFLICT (user_id) DO UPDATE
                  SET controls = EXCLUDED.controls,
                      updated_at = now()
                """,
                (g.user_id, json.dumps(controls)),
            )
        conn.commit()
        return jsonify({"controls": controls})
    finally:
        conn.close()
