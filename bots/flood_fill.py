from collections import deque


def flood_fill_reveal(
    board: list[list[dict]],
    state: list[list],
    start: tuple[int, int],
) -> dict[tuple[int, int], int]:
    """Reveal from `start`, cascading through zero-adjacency cells.

    Mutates `state` so every newly uncovered cell holds its adjacency count.
    Returns the dict of {(r, c): adjacentMines} for cells revealed by this call.
    Cells already revealed in `state` are skipped.
    """
    rows = len(state)
    cols = len(state[0]) if rows else 0
    queue = deque([start])
    revealed: dict[tuple[int, int], int] = {}
    while queue:
        r, c = queue.popleft()
        if state[r][c] != "unknown":
            continue
        adj = board[r][c]["adjacentMines"]
        state[r][c] = adj
        revealed[(r, c)] = adj
        if adj == 0:
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols and state[nr][nc] == "unknown":
                        queue.append((nr, nc))
    return revealed
