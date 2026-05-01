#!/usr/bin/env python3
"""
Set or update a user's username (users.username).

Usage:
    python scripts/set_username.py --email alice@example.com --username alice_cool
    python scripts/set_username.py --current-username OldName --username NewName

Requires DATABASE_URL env var (same as the app).

After renaming, the affected user must log out and log back in — their existing
JWT still carries the old username in `sub`.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DATABASE_URL
from db import get_conn

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{1,20}$")


def find_user_id(cur, email: str | None, current_username: str | None) -> str | None:
    if email:
        cur.execute(
            "SELECT user_id FROM oauth_credentials WHERE email = %s",
            (email,),
        )
        row = cur.fetchone()
        return str(row[0]) if row else None
    if current_username:
        cur.execute(
            "SELECT id FROM users WHERE username = %s",
            (current_username,),
        )
        row = cur.fetchone()
        return str(row[0]) if row else None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Set a user's username.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--email", help="OAuth email of the user to rename")
    group.add_argument("--current-username", help="Current username of the user")
    parser.add_argument(
        "--username",
        required=True,
        help="New username (1-20 alphanumeric/underscore)",
    )
    args = parser.parse_args()

    if not DATABASE_URL:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        return 1

    new_username = args.username.strip()
    if not USERNAME_RE.match(new_username):
        print(
            "error: new username must match ^[a-zA-Z0-9_]{1,20}$",
            file=sys.stderr,
        )
        return 1

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            user_id = find_user_id(cur, args.email, args.current_username)
            if not user_id:
                print("error: user not found", file=sys.stderr)
                return 1

            cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
            current = cur.fetchone()[0]
            if current == new_username:
                print(f"no change: user {user_id} already has username '{new_username}'")
                return 0

            cur.execute(
                "SELECT 1 FROM users WHERE username = %s AND id <> %s",
                (new_username, user_id),
            )
            if cur.fetchone():
                print(
                    f"error: username '{new_username}' is already taken",
                    file=sys.stderr,
                )
                return 1

            cur.execute(
                "UPDATE users SET username = %s, updated_at = now() WHERE id = %s",
                (new_username, user_id),
            )
        conn.commit()
        print(f"updated user {user_id}: '{current}' -> '{new_username}'")
        print(
            "note: the user must log out and log back in — their current JWT "
            "still carries the old username."
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
