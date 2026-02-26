import random
from collections import deque

from config import ROWS, COLS, MINE_COUNT
from solver import is_solvable


def _compute_adjacency(board: list[list[dict]]):
    for r in range(ROWS):
        for c in range(COLS):
            if board[r][c]["isMine"]:
                continue
            count = 0
            for dr in range(-1, 2):
                for dc in range(-1, 2):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < ROWS and 0 <= nc < COLS and board[nr][nc]["isMine"]:
                        count += 1
            board[r][c]["adjacentMines"] = count


def _find_zero_cells(board: list[list[dict]]) -> list[tuple[int, int]]:
    """Find all cells with adjacentMines == 0 and not a mine (valid starting squares)."""
    return [
        (r, c)
        for r in range(ROWS)
        for c in range(COLS)
        if not board[r][c]["isMine"] and board[r][c]["adjacentMines"] == 0
    ]


def _unique_starting_regions(board: list[list[dict]], zero_cells: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Return one representative zero cell per connected flood-fill region.

    Zero cells in the same region reveal the same initial area, so
    we only need to test solvability once per region.
    """
    visited = set()
    representatives = []

    for r, c in zero_cells:
        if (r, c) in visited:
            continue
        # TODO: randomize representative chosen from this region instead of always picking the first one found
        representatives.append((r, c))
        # BFS to mark all connected zero cells in this region
        q = deque([(r, c)])
        while q:
            cr, cc = q.popleft()
            if (cr, cc) in visited:
                continue
            visited.add((cr, cc))
            for dr in range(-1, 2):
                for dc in range(-1, 2):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = cr + dr, cc + dc
                    if (
                        0 <= nr < ROWS
                        and 0 <= nc < COLS
                        and (nr, nc) not in visited
                        and not board[nr][nc]["isMine"]
                        and board[nr][nc]["adjacentMines"] == 0
                    ):
                        q.append((nr, nc))

    return representatives


def _generate_board() -> list[list[dict]]:
    """Place mines randomly on a 30x16 grid and compute adjacency."""
    all_positions = [(r, c) for r in range(ROWS) for c in range(COLS)]
    mines = set(random.sample(all_positions, MINE_COUNT))

    board = [
        [{"isMine": (r, c) in mines, "adjacentMines": 0} for c in range(COLS)]
        for r in range(ROWS)
    ]
    _compute_adjacency(board)
    return board


def generate_solvable_board(max_attempts: int = 1000) -> tuple[list[list[dict]], tuple[int, int]]:
    """Generate a solvable board and return (board, starting_square).

    Tries random mine placements until one is solvable from at least one zero cell.
    Groups zero cells by connected region to avoid redundant solver calls.
    """
    for _ in range(max_attempts):
        board = _generate_board()
        zero_cells = _find_zero_cells(board)
        if not zero_cells:
            continue

        # Only test one cell per connected zero-region
        representatives = _unique_starting_regions(board, zero_cells)
        random.shuffle(representatives)

        for start in representatives:
            if is_solvable(board, start[0], start[1]):
                # Pick a random zero cell from this region as the actual starting square
                return board, start

    # Fallback (should not happen with 1000 attempts)
    board = _generate_board()
    zero_cells = _find_zero_cells(board)
    if zero_cells:
        return board, random.choice(zero_cells)
    return board, (0, 0)
