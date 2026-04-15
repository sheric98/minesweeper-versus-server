# Bot ELO Calibration

Offline simulation harness for establishing ELO ratings across all bot profiles
in `bots/profiles.json`. Matches run in-process via `bots.simulator.simulate_match`
— no network, no sleeps, no live matchmaking queue involved.

## Quick answer: how does pairing work?

Bots are paired **randomly** by default. Standard ELO math handles rating
disparity on its own (the expected-score term shrinks the point swing for
lopsided matches), so random pairing converges correctly given enough matches.

If you want faster convergence or tighter calibration between close-rated
bots, pass `--pairing elo-pool`. Each match samples `--pool-size` bots
(default 30), picks a random anchor from the pool, and pairs it with its
closest-rated opponent in the pool. This concentrates matches between
similarly-rated bots without maintaining any persistent queue state.

## Running the simulation

All commands run from the repo root using the project venv.

### One-shot calibration

Fixed number of matches, prints final leaderboard:

```bash
./venv/bin/python -m bots.tournament \
    --rounds 5000 \
    --output bots/ratings.json \
    --seed 42
```

### Continuous calibration (recommended)

Run until interrupted. SIGINT/SIGTERM flushes a final checkpoint before exit,
so progress is never lost:

```bash
./venv/bin/python -m bots.tournament \
    --rounds 0 \
    --output bots/ratings.json \
    --checkpoint-interval 1000 \
    --seed 42
```

Stop with Ctrl+C or `kill <pid>`.

### Resume a previous run

Picks up from the last checkpoint in `--output` instead of resetting to the
default rating:

```bash
./venv/bin/python -m bots.tournament \
    --rounds 0 \
    --resume \
    --output bots/ratings.json \
    --checkpoint-interval 1000
```

### Background execution

To detach from the terminal:

```bash
nohup ./venv/bin/python -m bots.tournament \
    --rounds 0 --output bots/ratings.json --checkpoint-interval 1000 --seed 42 \
    > bots/tournament.log 2>&1 &
echo $! > bots/tournament.pid
```

Tail progress: `tail -f bots/tournament.log`
Stop it: `kill $(cat bots/tournament.pid)`

## Flags

| Flag | Default | Purpose |
|---|---|---|
| `--rounds N` | `200` | Number of matches to play. `0` = infinite (stops on signal). |
| `--output PATH` | — | JSON file for ratings. Required for `--resume` and for `--rounds 0`. |
| `--pairing {random,round-robin,elo-pool}` | `random` | `random` samples two distinct bots per match; `round-robin` cycles all 384×383 ordered pairs deterministically; `elo-pool` samples a pool of `--pool-size` bots per match, picks a random anchor, and pairs it with its closest-rated opponent in the pool. |
| `--pool-size N` | `30` | Pool size for `--pairing elo-pool`. Ignored by other pairing modes. |
| `--checkpoint-interval N` | `1000` | Atomically writes `--output` every N matches. `0` to disable. |
| `--resume` | off | Load existing `--output` as starting ratings instead of seeding at `DEFAULT_RATING`. |
| `--difficulty {mixed,beginner,intermediate,advanced,expert}` | `mixed` | `mixed` samples a difficulty per match from the live multiplayer distribution in `config.DIFFICULTY_WEIGHTS` (currently beginner 10% / intermediate 40% / advanced 40% / expert 10%). Passing a specific difficulty forces it for every match. |
| `--seed N` | random | Seed the RNG for reproducibility. |
| `-v / --verbose` | off | Print every match result (noisy). |
| `--leaderboard-limit N` | all | Only print top N in the final leaderboard. |

## Seeding calibrated ratings into the live DB

After the simulation, push results to Postgres so bots appear in
`/elo/leaderboard` with realistic ratings:

```bash
# Preview without writing (DATABASE_URL not required)
./venv/bin/python -m bots.seed_elo --ratings bots/ratings.json --dry-run

# Actually write (requires DATABASE_URL)
./venv/bin/python -m bots.seed_elo --ratings bots/ratings.json
```

The seed script:

1. Creates a `users` row for each bot on first run, persisting the UUID
   mapping in `bots/user_ids.json`. Subsequent runs reuse those UUIDs so
   bot identities stay stable across re-calibrations.
2. Upserts `elo_ratings.rating` for each bot. `wins` / `losses` are left
   untouched — synthetic calibration matches should not inflate real
   win/loss counters.
3. Is idempotent. Safe to re-run after every calibration pass.

## Board cache

`board_generator.generate_solvable_board` is the main cost driver — expert
boards can take several seconds each to generate. `run_tournament` keeps a
per-run in-memory cache of generated boards keyed by difficulty. Each cached
entry tracks which bots have already played on it; a lookup returns the
first board where *neither* bot in the pending match has played before, so
no two bots ever face the same `(board, start_cell)` twice. On miss a fresh
board is generated and added to the cache. The cache is unbounded —
entries naturally retire once nearly every bot in the roster has played
them.
