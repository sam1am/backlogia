# settings.py
# Database-backed settings management for API credentials

import sqlite3
from pathlib import Path
from datetime import datetime

DATABASE_PATH = Path(__file__).parent.parent / "game_library.db"

# Setting keys
STEAM_ID = "steam_id"
STEAM_API_KEY = "steam_api_key"
IGDB_CLIENT_ID = "igdb_client_id"
IGDB_CLIENT_SECRET = "igdb_client_secret"
ITCH_API_KEY = "itch_api_key"
HUMBLE_SESSION_COOKIE = "humble_session_cookie"


def _ensure_settings_table(conn):
    """Ensure the settings table exists."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def get_setting(key, default=None):
    """Get a setting value from the database."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        _ensure_settings_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default


def set_setting(key, value):
    """Set a setting value in the database."""
    conn = sqlite3.connect(DATABASE_PATH)
    _ensure_settings_table(conn)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO settings (key, value, updated_at)
        VALUES (?, ?, ?)
    """, (key, value, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_all_settings():
    """Get all settings as a dictionary."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        _ensure_settings_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        rows = cursor.fetchall()
        conn.close()
        return {key: value for key, value in rows}
    except Exception:
        return {}


def delete_setting(key):
    """Delete a setting from the database."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
    conn.commit()
    conn.close()


# Convenience functions for specific settings
def get_steam_credentials():
    """Get Steam API credentials."""
    return {
        "steam_id": get_setting(STEAM_ID),
        "api_key": get_setting(STEAM_API_KEY),
    }


def get_igdb_credentials():
    """Get IGDB API credentials."""
    return {
        "client_id": get_setting(IGDB_CLIENT_ID),
        "client_secret": get_setting(IGDB_CLIENT_SECRET),
    }


def get_itch_credentials():
    """Get itch.io API credentials."""
    return {
        "api_key": get_setting(ITCH_API_KEY),
    }


def get_humble_credentials():
    """Get Humble Bundle credentials."""
    return {
        "session_cookie": get_setting(HUMBLE_SESSION_COOKIE),
    }
