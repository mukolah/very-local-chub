"""
Migration and merge utilities for Very Local Chub database

Usage:
    python migrate.py                           # Migrate all JSONs to database
    python migrate.py --merge database_to_merge.db  # Merge another database
"""

import os
import json
import sqlite3
import argparse
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = 'cards.db'


@contextmanager
def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def _init_database():
    with _get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                fullPath TEXT,
                description TEXT,
                tagline TEXT,
                starCount INTEGER DEFAULT 0,
                lastActivityAt TEXT,
                createdAt TEXT,
                nTokens INTEGER,
                rating REAL,
                ratingCount INTEGER DEFAULT 0,
                forksCount INTEGER DEFAULT 0,
                nChats INTEGER DEFAULT 0,
                nMessages INTEGER DEFAULT 0,
                hasGallery INTEGER DEFAULT 0,
                avatar_file_name TEXT,
                node_id TEXT,
                node_type TEXT,
                related_lorebooks TEXT,
                raw_json TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS card_tags (
                card_id INTEGER,
                tag TEXT,
                FOREIGN KEY (card_id) REFERENCES cards(id) ON DELETE CASCADE,
                PRIMARY KEY (card_id, tag)
            );
            CREATE TABLE IF NOT EXISTS card_scores (
                card_id    INTEGER PRIMARY KEY,
                quality    REAL DEFAULT NULL,
                lewdity    REAL DEFAULT NULL,
                story      REAL DEFAULT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS tag_metadata (
                tag          TEXT PRIMARY KEY,
                is_favourite INTEGER NOT NULL DEFAULT 0,
                is_banned    INTEGER NOT NULL DEFAULT 0,
                merged_into  TEXT DEFAULT NULL,
                updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS settings (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_createdAt ON cards(createdAt DESC);
            CREATE INDEX IF NOT EXISTS idx_lastActivityAt ON cards(lastActivityAt DESC);
            CREATE INDEX IF NOT EXISTS idx_nTokens ON cards(nTokens);
            CREATE INDEX IF NOT EXISTS idx_starCount ON cards(starCount DESC);
            CREATE INDEX IF NOT EXISTS idx_rating ON cards(rating DESC);
            CREATE INDEX IF NOT EXISTS idx_tags ON card_tags(tag);
            CREATE INDEX IF NOT EXISTS idx_fullPath ON cards(fullPath);
            CREATE INDEX IF NOT EXISTS idx_tm_merged_into ON tag_metadata(merged_into);
        """)
        conn.commit()


def _upsert_card(metadata):
    try:
        with _get_db() as conn:
            topics = [tag for tag in metadata.get('topics', []) if tag != 'ROOT']
            raw_json = json.dumps(metadata)
            conn.execute('''
                INSERT OR REPLACE INTO cards (
                    id, name, fullPath, description, tagline, starCount,
                    lastActivityAt, createdAt, nTokens, rating, ratingCount,
                    forksCount, nChats, nMessages, hasGallery, avatar_file_name,
                    node_id, node_type, related_lorebooks, raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                metadata.get('id'),
                metadata.get('name'),
                metadata.get('fullPath'),
                metadata.get('description'),
                metadata.get('tagline'),
                metadata.get('starCount', 0),
                metadata.get('lastActivityAt'),
                metadata.get('createdAt'),
                metadata.get('nTokens'),
                metadata.get('rating'),
                metadata.get('ratingCount', 0),
                metadata.get('forksCount', 0),
                metadata.get('nChats', 0),
                metadata.get('nMessages', 0),
                1 if metadata.get('hasGallery') else 0,
                metadata.get('avatar_file_name'),
                metadata.get('node', {}).get('id') if isinstance(metadata.get('node'), dict) else None,
                metadata.get('node', {}).get('nodeType') if isinstance(metadata.get('node'), dict) else None,
                json.dumps(metadata.get('related_lorebooks', [])),
                raw_json,
                datetime.now(timezone.utc).isoformat()
            ))
            card_id = metadata.get('id')
            conn.execute('DELETE FROM card_tags WHERE card_id = ?', (card_id,))
            for tag in topics:
                conn.execute('INSERT INTO card_tags (card_id, tag) VALUES (?, ?)', (card_id, tag))
            conn.commit()
            return True
    except Exception as e:
        print(f"Error upserting card {metadata.get('id')}: {e}")
        return False


def _get_card_by_id(card_id):
    try:
        with _get_db() as conn:
            row = conn.execute('SELECT * FROM cards WHERE id = ?', (card_id,)).fetchone()
            if not row:
                return None
            card = dict(row)
            card['topics'] = [r['tag'] for r in conn.execute(
                'SELECT tag FROM card_tags WHERE card_id = ?', (card_id,)
            ).fetchall()]
            return card
    except Exception as e:
        print(f"Error getting card {card_id}: {e}")
        return None


def _get_card_count():
    try:
        with _get_db() as conn:
            return conn.execute('SELECT COUNT(*) FROM cards').fetchone()[0]
    except Exception:
        return 0


def _table_exists(conn, table_name):
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone() is not None


def migrate_from_json(static_folder='static', verbose=True):
    """
    Migrate all JSON files from static folder to database

    Args:
        static_folder: Path to folder containing JSON files
        verbose: Print progress information

    Returns:
        Tuple of (successful_count, failed_count)
    """
    if verbose:
        print("Starting migration from JSON files...")
        print(f"Initializing database at: {DB_PATH}")

    _init_database()

    if not os.path.exists(static_folder):
        print(f"Error: Static folder '{static_folder}' does not exist")
        return 0, 0

    json_files = [f for f in os.listdir(static_folder) if f.endswith('.json')]

    if not json_files:
        print(f"No JSON files found in '{static_folder}'")
        return 0, 0

    if verbose:
        print(f"Found {len(json_files)} JSON files to migrate")

    success_count = 0
    failed_count = 0

    for i, json_file in enumerate(json_files, 1):
        try:
            file_path = os.path.join(static_folder, json_file)
            with open(file_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            if _upsert_card(metadata):
                success_count += 1
                if verbose and success_count % 10 == 0:
                    print(f"Progress: {success_count}/{len(json_files)} cards migrated ({success_count*100//len(json_files)}%)")
            else:
                failed_count += 1
                if verbose:
                    print(f"Failed to migrate: {json_file}")

        except Exception as e:
            failed_count += 1
            if verbose:
                print(f"Error processing {json_file}: {e}")

    if verbose:
        print(f"\nMigration complete!")
        print(f"Successfully migrated: {success_count}")
        print(f"Failed: {failed_count}")
        print(f"Total cards in database: {_get_card_count()}")

    return success_count, failed_count


def merge_databases(source_db_path, output_db_path='database_merged.db', verbose=True):
    """
    Merge another database into a new merged database.
    Merges cards, card_tags, card_scores, and tag_metadata.
    Settings are intentionally excluded (they are instance-specific).

    Args:
        source_db_path: Path to database to merge (e.g., 'database_to_merge.db')
        output_db_path: Path for merged output database
        verbose: Print progress information

    Returns:
        Tuple of (updated_count, inserted_count, skipped_count)
    """
    if not os.path.exists(source_db_path):
        print(f"Error: Source database '{source_db_path}' does not exist")
        return 0, 0, 0

    if not os.path.exists(DB_PATH):
        print(f"Error: Main database '{DB_PATH}' does not exist. Run migration first.")
        return 0, 0, 0

    if verbose:
        print(f"Merging databases...")
        print(f"Source: {source_db_path}")
        print(f"Main: {DB_PATH}")
        print(f"Output: {output_db_path}")

    shutil.copy2(DB_PATH, output_db_path)

    if verbose:
        print("Created output database from main database")

    source_conn = sqlite3.connect(source_db_path)
    source_conn.row_factory = sqlite3.Row
    output_conn = sqlite3.connect(output_db_path)
    output_conn.row_factory = sqlite3.Row

    updated_count = 0
    inserted_count = 0
    skipped_count = 0

    try:
        src = source_conn.cursor()
        out = output_conn.cursor()

        # ── Cards ──────────────────────────────────────────────────────────────
        src.execute('SELECT * FROM cards')
        source_cards = src.fetchall()

        if verbose:
            print(f"Found {len(source_cards)} cards in source database")

        for i, source_card in enumerate(source_cards, 1):
            card_id = source_card['id']

            out.execute('SELECT * FROM cards WHERE id = ?', (card_id,))
            existing_card = out.fetchone()

            if existing_card:
                source_activity = source_card['lastActivityAt']
                existing_activity = existing_card['lastActivityAt']

                if source_activity and existing_activity:
                    if source_activity > existing_activity:
                        _update_card_in_db(output_conn, source_card, card_id)
                        updated_count += 1
                        if verbose and updated_count % 10 == 0:
                            print(f"Updated: {updated_count} cards")
                    else:
                        skipped_count += 1
                else:
                    _update_card_in_db(output_conn, source_card, card_id)
                    updated_count += 1
            else:
                _insert_card_in_db(output_conn, source_card)
                inserted_count += 1
                if verbose and inserted_count % 10 == 0:
                    print(f"Inserted: {inserted_count} new cards")

            if verbose and i % 100 == 0:
                print(f"Progress: {i}/{len(source_cards)} cards processed")

        # ── Card scores ────────────────────────────────────────────────────────
        if _table_exists(source_conn, 'card_scores'):
            # Ensure output has the table (may be an older DB copy)
            output_conn.execute("""
                CREATE TABLE IF NOT EXISTS card_scores (
                    card_id    INTEGER PRIMARY KEY,
                    quality    REAL DEFAULT NULL,
                    lewdity    REAL DEFAULT NULL,
                    story      REAL DEFAULT NULL,
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)

            src.execute('SELECT * FROM card_scores')
            scores_merged = 0
            for row in src.fetchall():
                # Only insert if destination has no score for this card yet
                out.execute('SELECT card_id FROM card_scores WHERE card_id = ?', (row['card_id'],))
                if not out.fetchone():
                    output_conn.execute(
                        'INSERT INTO card_scores (card_id, quality, lewdity, story, updated_at) VALUES (?, ?, ?, ?, ?)',
                        (row['card_id'], row['quality'], row['lewdity'], row['story'], row['updated_at'])
                    )
                    scores_merged += 1

            if verbose:
                print(f"Card scores merged: {scores_merged}")

        # ── Tag metadata ───────────────────────────────────────────────────────
        if _table_exists(source_conn, 'tag_metadata'):
            output_conn.execute("""
                CREATE TABLE IF NOT EXISTS tag_metadata (
                    tag          TEXT PRIMARY KEY,
                    is_favourite INTEGER NOT NULL DEFAULT 0,
                    is_banned    INTEGER NOT NULL DEFAULT 0,
                    merged_into  TEXT DEFAULT NULL,
                    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

            src.execute('SELECT * FROM tag_metadata')
            tags_merged = 0
            for row in src.fetchall():
                out.execute('SELECT tag FROM tag_metadata WHERE tag = ?', (row['tag'],))
                if not out.fetchone():
                    output_conn.execute(
                        'INSERT INTO tag_metadata (tag, is_favourite, is_banned, merged_into, updated_at) VALUES (?, ?, ?, ?, ?)',
                        (row['tag'], row['is_favourite'], row['is_banned'], row['merged_into'], row['updated_at'])
                    )
                    tags_merged += 1

            if verbose:
                print(f"Tag metadata merged: {tags_merged}")

        output_conn.commit()

        if verbose:
            print(f"\nMerge complete!")
            print(f"Updated (newer): {updated_count}")
            print(f"Inserted (new): {inserted_count}")
            print(f"Skipped (older): {skipped_count}")
            out.execute('SELECT COUNT(*) as count FROM cards')
            print(f"Total cards in merged database: {out.fetchone()['count']}")
            print("Note: settings were not merged (they are instance-specific)")

    except Exception as e:
        print(f"Error during merge: {e}")
        import traceback
        traceback.print_exc()

    finally:
        source_conn.close()
        output_conn.close()

    return updated_count, inserted_count, skipped_count


def _update_card_in_db(conn, card_row, card_id):
    """Update a card in the database, pulling tags from raw_json."""
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE cards SET
            name = ?, fullPath = ?, description = ?, tagline = ?, starCount = ?,
            lastActivityAt = ?, createdAt = ?, nTokens = ?, rating = ?, ratingCount = ?,
            forksCount = ?, nChats = ?, nMessages = ?, hasGallery = ?, avatar_file_name = ?,
            node_id = ?, node_type = ?, related_lorebooks = ?, raw_json = ?, updated_at = ?
        WHERE id = ?
    ''', (
        card_row['name'],
        card_row['fullPath'],
        card_row['description'],
        card_row['tagline'],
        card_row['starCount'],
        card_row['lastActivityAt'],
        card_row['createdAt'],
        card_row['nTokens'],
        card_row['rating'],
        card_row['ratingCount'],
        card_row['forksCount'],
        card_row['nChats'],
        card_row['nMessages'],
        card_row['hasGallery'],
        card_row['avatar_file_name'],
        card_row['node_id'],
        card_row['node_type'],
        card_row['related_lorebooks'],
        card_row['raw_json'],
        datetime.now(timezone.utc).isoformat(),
        card_id
    ))

    cursor.execute('DELETE FROM card_tags WHERE card_id = ?', (card_id,))

    if card_row['raw_json']:
        try:
            tags = json.loads(card_row['raw_json']).get('topics', [])
            for tag in tags:
                if tag and tag != 'ROOT':
                    cursor.execute(
                        'INSERT OR IGNORE INTO card_tags (card_id, tag) VALUES (?, ?)',
                        (card_id, tag)
                    )
        except Exception:
            pass


def _insert_card_in_db(conn, card_row):
    """Insert a card into the database, pulling tags from raw_json."""
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO cards (
            id, name, fullPath, description, tagline, starCount,
            lastActivityAt, createdAt, nTokens, rating, ratingCount,
            forksCount, nChats, nMessages, hasGallery, avatar_file_name,
            node_id, node_type, related_lorebooks, raw_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        card_row['id'],
        card_row['name'],
        card_row['fullPath'],
        card_row['description'],
        card_row['tagline'],
        card_row['starCount'],
        card_row['lastActivityAt'],
        card_row['createdAt'],
        card_row['nTokens'],
        card_row['rating'],
        card_row['ratingCount'],
        card_row['forksCount'],
        card_row['nChats'],
        card_row['nMessages'],
        card_row['hasGallery'],
        card_row['avatar_file_name'],
        card_row['node_id'],
        card_row['node_type'],
        card_row['related_lorebooks'],
        card_row['raw_json'],
        datetime.utcnow().isoformat()
    ))

    if card_row['raw_json']:
        try:
            tags = json.loads(card_row['raw_json']).get('topics', [])
            for tag in tags:
                if tag and tag != 'ROOT':
                    cursor.execute(
                        'INSERT OR IGNORE INTO card_tags (card_id, tag) VALUES (?, ?)',
                        (card_row['id'], tag)
                    )
        except Exception:
            pass


def sync_from_json(static_folder='static', verbose=True):
    """
    Sync database with JSON files - update existing and add new cards

    Args:
        static_folder: Path to folder containing JSON files
        verbose: Print progress information

    Returns:
        Tuple of (updated_count, added_count)
    """
    if not os.path.exists(DB_PATH):
        if verbose:
            print("Database doesn't exist. Running full migration...")
        return migrate_from_json(static_folder, verbose)

    if verbose:
        print("Syncing database with JSON files...")

    json_files = [f for f in os.listdir(static_folder) if f.endswith('.json')]

    if not json_files:
        if verbose:
            print("No JSON files found")
        return 0, 0

    updated_count = 0
    added_count = 0

    for json_file in json_files:
        try:
            file_path = os.path.join(static_folder, json_file)
            card_id = int(json_file.replace('.json', ''))

            file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
            existing_card = _get_card_by_id(card_id)

            with open(file_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            if existing_card:
                db_updated = datetime.fromisoformat(existing_card['updated_at'])
                if file_mtime > db_updated:
                    if _upsert_card(metadata):
                        updated_count += 1
            else:
                if _upsert_card(metadata):
                    added_count += 1

        except Exception as e:
            if verbose:
                print(f"Error processing {json_file}: {e}")

    if verbose:
        print(f"Sync complete! Updated: {updated_count}, Added: {added_count}")

    return updated_count, added_count


def main():
    parser = argparse.ArgumentParser(
        description='Migration and merge utilities for Very Local Chub'
    )
    parser.add_argument(
        '--merge',
        type=str,
        help='Merge another database (e.g., --merge database_to_merge.db)'
    )
    parser.add_argument(
        '--sync',
        action='store_true',
        help='Sync database with JSON files (update existing, add new)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='database_merged.db',
        help='Output path for merged database (default: database_merged.db)'
    )
    parser.add_argument(
        '--static',
        type=str,
        default='static',
        help='Path to static folder containing JSON files (default: static)'
    )

    args = parser.parse_args()

    if args.merge:
        merge_databases(args.merge, args.output)
    elif args.sync:
        sync_from_json(args.static)
    else:
        migrate_from_json(args.static)


if __name__ == '__main__':
    main()
