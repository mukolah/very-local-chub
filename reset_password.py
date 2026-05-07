#!/usr/bin/env python3
"""
Resets the auth credentials stored in the settings table.
Run this if you forgot your password or want to re-enable the setup prompt.

Only deletes: username, password_hash, first_login_done
Everything else (api_token, auth_skipped, tag merges, scores) is preserved.
"""
import sqlite3
import os

DB_PATH = 'cards.db'

if not os.path.exists(DB_PATH):
    print(f"Database not found: {DB_PATH}")
    print("Nothing to reset.")
    raise SystemExit(1)

keys_to_delete = ['username', 'password_hash', 'first_login_done']

with sqlite3.connect(DB_PATH) as conn:
    try:
        placeholders = ','.join('?' * len(keys_to_delete))
        conn.execute(f"DELETE FROM settings WHERE key IN ({placeholders})", keys_to_delete)
        conn.commit()
        print("Auth credentials cleared.")
        print("Restart the app — you will be prompted to create an account or skip.")
    except sqlite3.OperationalError as e:
        print(f"Error: {e}")
        print("The settings table may not exist yet. Start the app at least once first.")
        raise SystemExit(1)
