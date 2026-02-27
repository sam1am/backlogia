# database.py
# Database connection and migration functions

import sqlite3
from .config import DATABASE_PATH


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_extra_columns():
    """Add extra columns to database if they don't exist."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    # Check if games table exists first
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='games'")
    if not cursor.fetchone():
        conn.close()
        return  # Table doesn't exist yet, nothing to migrate
    cursor.execute("PRAGMA table_info(games)")
    columns = {row[1] for row in cursor.fetchall()}
    if "hidden" not in columns:
        cursor.execute("ALTER TABLE games ADD COLUMN hidden BOOLEAN DEFAULT 0")
    if "nsfw" not in columns:
        cursor.execute("ALTER TABLE games ADD COLUMN nsfw BOOLEAN DEFAULT 0")
    if "cover_url_override" not in columns:
        cursor.execute("ALTER TABLE games ADD COLUMN cover_url_override TEXT")
    if "removed" not in columns:
        cursor.execute("ALTER TABLE games ADD COLUMN removed BOOLEAN DEFAULT 0")
    conn.commit()
    conn.close()


def ensure_edit_overrides():
    """Add genres_override and playtime_label columns to the games table."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='games'")
    if not cursor.fetchone():
        conn.close()
        return
    cursor.execute("PRAGMA table_info(games)")
    columns = {row[1] for row in cursor.fetchall()}
    if "genres_override" not in columns:
        cursor.execute("ALTER TABLE games ADD COLUMN genres_override TEXT")
    if "playtime_label" not in columns:
        cursor.execute("ALTER TABLE games ADD COLUMN playtime_label TEXT")
    conn.commit()
    conn.close()


def ensure_collections_tables():
    """Create collections tables if they don't exist."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS collection_games (
            collection_id INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (collection_id, game_id),
            FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE,
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()
