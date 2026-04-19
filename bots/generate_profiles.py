import json
import random
from itertools import product
from pathlib import Path

SOLVERS = ["basic", "subset", "probabilistic", "perfect"]
PROB_SOLVERS = {"probabilistic", "perfect"}

GUESS_OPTIONS = {
    "basic":         ["frontier", "near_frontier", "deep"],   # blind_guess_region
    "subset":        ["frontier", "near_frontier", "deep"],
    "probabilistic": ["any", "near_frontier", "deep"],        # off_frontier_pick
    "perfect":       ["any", "near_frontier", "deep"],
}

SPEEDS = {
    "lightning": (0.3, 0.5),
    "fast":      (0.38, 0.58),
    "medium":    (0.48, 0.68),
    "slow":      (0.62, 0.82),
}

MISTAKE_FIELDS = [
    ("w", "p_wrong_cell"),
    ("r", "p_random_cell"),
    ("s", "p_skip_deduction"),
]

# --- username word lists ---
ADJECTIVES = [
    "swift", "dark", "silent", "mighty", "cosmic", "lucky", "iron", "golden",
    "crimson", "shadow", "frost", "storm", "wild", "silver", "phantom", "royal",
    "rapid", "epic", "neon", "rogue", "brave", "wise", "savage", "mystic",
    "turbo", "electric", "lunar", "solar", "steel", "ruby", "jade", "midnight",
    "thunder", "venom", "blaze", "arctic", "feral", "stealth", "ember", "frozen",
    "toxic", "radiant", "grim", "vicious", "silent", "chrome", "obsidian", "zen",
]

NOUNS = [
    "wolf", "fox", "hawk", "tiger", "dragon", "falcon", "panda", "raven",
    "ninja", "ghost", "blade", "arrow", "phoenix", "viper", "panther", "eagle",
    "bear", "shark", "lion", "cobra", "knight", "mage", "sniper", "wizard",
    "ranger", "hunter", "monk", "samurai", "pirate", "warrior", "king", "queen",
    "pixel", "byte", "node", "glitch", "echo", "reaper", "comet", "nova",
    "fury", "titan", "oracle", "jester", "warden", "specter", "howl", "fang",
]

USERNAME_SEED = 1337


def mistake_suffix(bits: tuple[bool, bool, bool]) -> str:
    letters = "".join(code for (code, _), on in zip(MISTAKE_FIELDS, bits) if on)
    return letters or "clean"


def make_usernames(n: int, seed: int = USERNAME_SEED) -> list[str]:
    """Generate `n` unique realistic-looking usernames, deterministically."""
    rng = random.Random(seed)
    seen: set[str] = set()
    out: list[str] = []
    while len(out) < n:
        adj = rng.choice(ADJECTIVES)
        noun = rng.choice(NOUNS)
        style = rng.randrange(5)
        if style == 0:
            u = f"{adj.capitalize()}{noun.capitalize()}"
        elif style == 1:
            u = f"{adj.capitalize()}{noun.capitalize()}{rng.randint(10, 99)}"
        elif style == 2:
            u = f"{adj}_{noun}"
        elif style == 3:
            u = f"{adj}{noun}{rng.randint(1, 999)}"
        else:
            u = f"x{adj.capitalize()}{noun.capitalize()}x"
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def build_entry(solver, guess, speed_name, bits, username):
    min_d, max_d = SPEEDS[speed_name]
    entry = {
        "name": f"{solver}_{guess}_{speed_name}_{mistake_suffix(bits)}",
        "username": username,
        "solver_tier": solver,
        "min_move_delay": min_d,
        "max_move_delay": max_d,
    }
    if solver in PROB_SOLVERS:
        entry["off_frontier_pick"] = guess
    else:
        entry["blind_guess_region"] = guess
    for (_, field), on in zip(MISTAKE_FIELDS, bits):
        entry[field] = 0.05 if on else 0.0
    return entry


def generate():
    combos = []
    for solver in SOLVERS:
        for guess in GUESS_OPTIONS[solver]:
            for speed in SPEEDS:
                for bits in product([False, True], repeat=3):
                    combos.append((solver, guess, speed, bits))
    usernames = make_usernames(len(combos))
    return [
        build_entry(solver, guess, speed, bits, username)
        for (solver, guess, speed, bits), username in zip(combos, usernames)
    ]


if __name__ == "__main__":
    profiles = generate()
    assert len(profiles) == 384, f"expected 384, got {len(profiles)}"
    names = [p["name"] for p in profiles]
    usernames = [p["username"] for p in profiles]
    assert len(set(names)) == 384, "duplicate names"
    assert len(set(usernames)) == 384, "duplicate usernames"
    out = Path(__file__).parent / "profiles.json"
    out.write_text(json.dumps(profiles, indent=2) + "\n")
    print(f"Wrote {len(profiles)} profiles to {out}")
