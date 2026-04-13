import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SolverTier = Literal["basic", "subset", "probabilistic", "perfect"]
OffFrontierPick = Literal["any", "near_frontier", "deep"]
BlindGuessRegion = Literal["frontier", "near_frontier", "deep"]


@dataclass(frozen=True)
class BotConfig:
    name: str            # systematic id, e.g. "perfect_deep_slow_wrs"
    username: str        # human-facing handle, e.g. "SwiftFox42"
    solver_tier: SolverTier

    # move timing (seconds), sampled uniformly per move
    min_move_delay: float = 0.15
    max_move_delay: float = 0.35

    # --- Guessing ---
    # Probabilistic solvers (perfect, probabilistic) ALWAYS guess by minimum
    # mine probability. The only decision is: when the off-frontier global
    # density is lower than the best frontier cell's prob, which off-frontier
    # region do we actually click from? Ignored for basic/subset.
    off_frontier_pick: OffFrontierPick = "any"

    # Non-probabilistic solvers (basic, subset) cannot compare probabilities,
    # so their only lever is which region to blind-guess from. Ignored for
    # probabilistic/perfect.
    blind_guess_region: BlindGuessRegion = "frontier"

    # independent mistake probabilities — all three are evaluated per tick
    p_wrong_cell: float = 0.0      # pick a non-best frontier cell (weighted by badness)
    p_random_cell: float = 0.0     # click a uniformly random unknown
    p_skip_deduction: float = 0.0  # per newly-deduced safe cell: drop it this tick and guess instead


def load_profiles(path: str | Path) -> dict[str, BotConfig]:
    """Load a list of bot profiles from a JSON file keyed by profile name."""
    with open(path) as f:
        raw = json.load(f)
    return {entry["name"]: BotConfig(**entry) for entry in raw}
