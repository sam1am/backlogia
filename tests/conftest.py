"""conftest.py – shared pytest fixtures for Backlogia tests."""

import json
import sqlite3
import pytest

from fastapi.testclient import TestClient


def _create_schema(conn: sqlite3.Connection) -> None:
    """Create the minimal games schema used in tests."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            store TEXT,
            store_id TEXT,
            genres TEXT,          -- JSON array
            genres_override TEXT, -- JSON array (user override)
            playtime_label TEXT,  -- unplayed/tried/played/heavily_played/abandoned
            playtime_hours REAL,
            hidden BOOLEAN DEFAULT 0,
            removed BOOLEAN DEFAULT 0,
            nsfw BOOLEAN DEFAULT 0,
            cover_image TEXT,
            cover_url_override TEXT,
            igdb_id INTEGER,
            igdb_slug TEXT,
            igdb_rating REAL,
            aggregated_rating REAL,
            total_rating REAL,
            igdb_cover_url TEXT,
            igdb_screenshots TEXT,
            igdb_summary TEXT,
            igdb_matched_at TIMESTAMP,
            metacritic_score INTEGER,
            metacritic_user_score REAL,
            metacritic_slug TEXT,
            metacritic_url TEXT,
            protondb_tier TEXT,
            protondb_total INTEGER,
            steam_app_id TEXT,
            average_rating REAL,
            description TEXT,
            release_date TEXT,
            developers TEXT,
            publishers TEXT,
            supported_platforms TEXT,
            extra_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS collection_games (
            collection_id INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (collection_id, game_id),
            FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE,
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS background_jobs (
            id TEXT PRIMARY KEY,
            type TEXT,
            status TEXT,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            result TEXT
        );
    """)


@pytest.fixture
def db_conn():
    """In-memory SQLite connection with the games schema pre-created."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_games(db_conn: sqlite3.Connection):
    """Insert a small set of sample games and return their IDs."""
    cursor = db_conn.cursor()
    cursor.executemany(
        """INSERT INTO games (name, store, store_id, genres, genres_override, playtime_label)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            ("Half-Life 2", "steam", "220", json.dumps(["Action", "Shooter"]), None, None),
            ("The Witcher 3", "gog", "1207664643", json.dumps(["RPG", "Adventure"]), None, None),
            ("Celeste", "epic", "celeste", json.dumps(["Platformer", "Indie"]), None, "heavily_played"),
        ],
    )
    db_conn.commit()
    cursor.execute("SELECT id FROM games ORDER BY id")
    ids = [row[0] for row in cursor.fetchall()]
    return ids


@pytest.fixture
def client(db_conn: sqlite3.Connection, sample_games):  # noqa: F811
    """TestClient with the get_db dependency overridden to use in-memory DB."""
    # Import here so DATABASE_PATH patching in main doesn't break other tests
    from web.main import app
    from web.dependencies import get_db

    def override_get_db():
        yield db_conn

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()
