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
                    display_name VARCHAR(20) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );

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
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_leaderboard_time ON leaderboard_scores (time_seconds ASC);

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
            """)
        conn.commit()
    finally:
        conn.close()
