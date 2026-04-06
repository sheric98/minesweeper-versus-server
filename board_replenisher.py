import threading
import time

from board_cache import get_cache_counts, store_board
from board_generator import generate_solvable_board, DIFFICULTY_SOLVERS
from config import ROWS, COLS

TARGET_PER_SLOT = 10
CYCLE_SLEEP_SECONDS = 60


def _replenish_cycle():
    """One pass: find depleted slots and generate one board for each."""
    counts = get_cache_counts()
    difficulties = list(DIFFICULTY_SOLVERS.keys())
    all_positions = [(r, c) for r in range(ROWS) for c in range(COLS)]

    slots_to_fill = []
    for difficulty in difficulties:
        for r, c in all_positions:
            current = counts.get((difficulty, r, c), 0)
            if current < TARGET_PER_SLOT:
                slots_to_fill.append((difficulty, r, c, TARGET_PER_SLOT - current))

    if not slots_to_fill:
        return 0

    # Prioritize most depleted slots, with randomness to spread work
    slots_to_fill.sort(key=lambda s: s[3], reverse=True)

    generated = 0
    for difficulty, r, c, deficit in slots_to_fill:
        try:
            board, _ = generate_solvable_board(r, c, difficulty=difficulty)
            store_board(difficulty, r, c, board)
            generated += 1
        except Exception as e:
            print(f"[board-replenisher] error generating {difficulty} ({r},{c}): {e}")
        # Yield CPU between boards
        time.sleep(0.1)

    return generated


def _replenish_loop():
    """Main loop: run cycles forever."""
    print("[board-replenisher] started")
    while True:
        try:
            generated = _replenish_cycle()
            if generated:
                print(f"[board-replenisher] generated {generated} boards this cycle")
        except Exception as e:
            print(f"[board-replenisher] cycle error: {e}")
        time.sleep(CYCLE_SLEEP_SECONDS)


def start_replenisher():
    """Launch the replenisher as a daemon thread."""
    t = threading.Thread(target=_replenish_loop, daemon=True)
    t.start()
    return t
