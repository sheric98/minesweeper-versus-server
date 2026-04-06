from flask import Blueprint, request, jsonify

from auth import require_auth
from board_cache import get_cached_board
from board_encoder import encode_board
from board_generator import generate_solvable_board, DIFFICULTY_SOLVERS
from config import ROWS, COLS, DATABASE_URL

board_bp = Blueprint("board", __name__)


@board_bp.route("/board", methods=["GET"])
@require_auth
def get_board():
    difficulty = request.args.get("difficulty", "expert")
    if difficulty not in DIFFICULTY_SOLVERS:
        return jsonify({"error": f"Invalid difficulty: {difficulty}"}), 400

    try:
        start_row = int(request.args.get("start_row", ""))
        start_col = int(request.args.get("start_col", ""))
    except (ValueError, TypeError):
        return jsonify({"error": "start_row and start_col are required integers"}), 400

    if not (0 <= start_row < ROWS and 0 <= start_col < COLS):
        return jsonify({"error": f"start_row must be 0-{ROWS-1}, start_col must be 0-{COLS-1}"}), 400

    cached = False
    board = None

    if DATABASE_URL:
        board = get_cached_board(difficulty, start_row, start_col)
        if board:
            cached = True

    if not board:
        board, _ = generate_solvable_board(start_row, start_col, difficulty=difficulty)

    return jsonify({
        "board": encode_board(board, ""),
        "startRow": start_row,
        "startCol": start_col,
        "cached": cached,
    })
