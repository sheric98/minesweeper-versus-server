import psycopg2
from config import DATABASE_URL


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    username VARCHAR(20) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT users_username_unique UNIQUE (username)
                );

                -- Migration: rename display_name -> username (idempotent).
                -- Pre-existing prod databases were created with a single
                -- `display_name` column; this block backfills the new
                -- `username` column from it and drops the old one.
                ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(20);

                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'display_name'
                    ) THEN
                        UPDATE users SET username = display_name WHERE username IS NULL;
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'users_username_unique'
                    ) THEN
                        ALTER TABLE users
                        ADD CONSTRAINT users_username_unique UNIQUE (username);
                    END IF;
                END $$;

                ALTER TABLE users ALTER COLUMN username SET NOT NULL;
                ALTER TABLE users DROP COLUMN IF EXISTS display_name;

                CREATE TABLE IF NOT EXISTS oauth_credentials (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL REFERENCES users(id),
                    provider VARCHAR(20) NOT NULL,
                    provider_id VARCHAR(255) NOT NULL,
                    email VARCHAR(255),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE(provider, provider_id)
                );

                CREATE TABLE IF NOT EXISTS leaderboard_scores (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL REFERENCES users(id),
                    time_seconds INTEGER NOT NULL,
                    mode VARCHAR(10) NOT NULL DEFAULT 'random',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_leaderboard_time ON leaderboard_scores (time_seconds ASC);
                -- TODO: Remove after production leaderboard_scores table has been altered
                ALTER TABLE leaderboard_scores
                ADD COLUMN IF NOT EXISTS mode VARCHAR(10) NOT NULL DEFAULT 'random';

                CREATE INDEX IF NOT EXISTS idx_leaderboard_mode_time ON leaderboard_scores (mode, time_seconds ASC);

                -- Add difficulty column for no-guess mode
                ALTER TABLE leaderboard_scores
                ADD COLUMN IF NOT EXISTS difficulty VARCHAR(15) DEFAULT NULL;

                -- Backfill existing no-guess rows as expert
                UPDATE leaderboard_scores SET difficulty = 'expert' WHERE mode = 'no-guess' AND difficulty IS NULL;

                CREATE INDEX IF NOT EXISTS idx_leaderboard_mode_difficulty_time ON leaderboard_scores (mode, difficulty, time_seconds ASC);

                CREATE TABLE IF NOT EXISTS head_to_head_records (
                    player1_id UUID NOT NULL REFERENCES users(id),
                    player2_id UUID NOT NULL REFERENCES users(id),
                    player1_wins INTEGER NOT NULL DEFAULT 0,
                    player2_wins INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (player1_id, player2_id),
                    CHECK (player1_id < player2_id)
                );
                CREATE INDEX IF NOT EXISTS idx_h2h_player1 ON head_to_head_records (player1_id);
                CREATE INDEX IF NOT EXISTS idx_h2h_player2 ON head_to_head_records (player2_id);

                CREATE TABLE IF NOT EXISTS elo_ratings (
                    user_id UUID PRIMARY KEY REFERENCES users(id),
                    rating INTEGER NOT NULL DEFAULT 1200,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_elo_ratings_rating ON elo_ratings (rating DESC);

                CREATE TABLE IF NOT EXISTS board_cache (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    difficulty VARCHAR(15) NOT NULL,
                    start_row SMALLINT NOT NULL,
                    start_col SMALLINT NOT NULL,
                    board_data BYTEA NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_board_cache_lookup
                    ON board_cache (difficulty, start_row, start_col);

                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id UUID PRIMARY KEY REFERENCES users(id),
                    controls JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
        conn.commit()
    finally:
        conn.close()
