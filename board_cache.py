from config import ROWS, COLS
from db import get_conn


def board_to_bitmask(board: list[list[dict]]) -> bytes:
    """Encode a board as a 60-byte bitmask (480 cells, row-major, 1=mine)."""
    bits = []
    for r in range(ROWS):
        for c in range(COLS):
            bits.append(1 if board[r][c]["isMine"] else 0)
    # Pack bits into bytes
    data = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for j in range(8):
            if i + j < len(bits) and bits[i + j]:
                byte |= 1 << (7 - j)
        data.append(byte)
    return bytes(data)


def bitmask_to_board(data: bytes) -> list[list[dict]]:
    """Decode a bitmask back into a board with adjacency counts computed."""
    # Unpack bits
    mines = set()
    bit_idx = 0
    for r in range(ROWS):
        for c in range(COLS):
            byte_idx = bit_idx // 8
            bit_offset = 7 - (bit_idx % 8)
            if data[byte_idx] & (1 << bit_offset):
                mines.add((r, c))
            bit_idx += 1

    # Build board with adjacency
    board = []
    for r in range(ROWS):
        row = []
        for c in range(COLS):
            is_mine = (r, c) in mines
            adj = 0
            if not is_mine:
                for dr in range(-1, 2):
                    for dc in range(-1, 2):
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < ROWS and 0 <= nc < COLS and (nr, nc) in mines:
                            adj += 1
            row.append({"isMine": is_mine, "adjacentMines": adj})
        board.append(row)
    return board


def get_cached_board(difficulty: str, start_row: int, start_col: int):
    """Pop one cached board. Returns the board (list[list[dict]]) or None."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM board_cache
                WHERE id = (
                    SELECT id FROM board_cache
                    WHERE difficulty = %s AND start_row = %s AND start_col = %s
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING board_data
                """,
                (difficulty, start_row, start_col),
            )
            row = cur.fetchone()
        conn.commit()
        if row is None:
            return None
        return bitmask_to_board(bytes(row[0]))
    finally:
        conn.close()


def store_board(difficulty: str, start_row: int, start_col: int, board: list[list[dict]]):
    data = board_to_bitmask(board)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO board_cache (difficulty, start_row, start_col, board_data)
                VALUES (%s, %s, %s, %s)
                """,
                (difficulty, start_row, start_col, data),
            )
        conn.commit()
    finally:
        conn.close()


def get_cache_counts() -> dict[tuple[str, int, int], int]:
    """Return {(difficulty, start_row, start_col): count} for all cached slots."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT difficulty, start_row, start_col, count(*)
                FROM board_cache
                GROUP BY difficulty, start_row, start_col
                """
            )
            return {
                (row[0], row[1], row[2]): row[3] for row in cur.fetchall()
            }
    finally:
        conn.close()
