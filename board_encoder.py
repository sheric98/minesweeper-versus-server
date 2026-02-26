import json


def encode_board(board: list[list[dict]], match_id: str) -> str:
    """Encode board for transmission using the mock JSON format.

    Produces the same format the frontend's decodeMockBoard() expects:
    [[{"m": 0, "a": 2}, {"m": 1, "a": 0}, ...], ...]
    """
    data = [
        [{"m": 1 if cell["isMine"] else 0, "a": cell["adjacentMines"]} for cell in row]
        for row in board
    ]
    return json.dumps(data)
