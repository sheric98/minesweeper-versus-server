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
            """)
        conn.commit()
    finally:
        conn.close()
