# services/auth_service.py
# Authentication service for optional single-user login

import secrets
import sqlite3
from datetime import datetime, timedelta

import bcrypt

from ..config import DATABASE_PATH, SESSION_EXPIRY_DAYS


def _ensure_auth_tables():
    """Create auth tables if they don't exist."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()


def user_exists():
    """Check if any user account exists."""
    _ensure_auth_tables()
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0


def create_user(username, password):
    """Create the single owner account. Refuses if a user already exists."""
    _ensure_auth_tables()
    if user_exists():
        raise ValueError("An account already exists")

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, password_hash),
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return user_id


def verify_user(username, password):
    """Verify credentials. Returns user dict or None."""
    _ensure_auth_tables()
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    if bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8")):
        return {"id": row["id"], "username": row["username"]}

    return None


def create_session(user_id):
    """Create a new session and return the session ID."""
    _ensure_auth_tables()
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(days=SESSION_EXPIRY_DAYS)

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
        (session_id, user_id, expires_at.isoformat()),
    )
    conn.commit()
    conn.close()
    return session_id


def validate_session(session_id):
    """Validate a session ID. Returns user dict or None."""
    _ensure_auth_tables()
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """SELECT s.*, u.username FROM sessions s
           JOIN users u ON s.user_id = u.id
           WHERE s.id = ? AND s.expires_at > ?""",
        (session_id, datetime.now().isoformat()),
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    return {"id": row["user_id"], "username": row["username"]}


def delete_session(session_id):
    """Delete a session (logout)."""
    _ensure_auth_tables()
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


def cleanup_expired_sessions():
    """Purge expired session rows."""
    _ensure_auth_tables()
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE expires_at <= ?", (datetime.now().isoformat(),))
    conn.commit()
    conn.close()


def generate_import_token(secret_key):
    """Generate a stable import token for bookmarklet auth.

    This is a signed token derived from the secret key, used to authenticate
    bookmarklet import requests without cookies (which don't work cross-origin).
    """
    from itsdangerous import URLSafeSerializer
    signer = URLSafeSerializer(secret_key, salt="backlogia-import")
    return signer.dumps("import-authorized")


def validate_import_token(secret_key, token):
    """Validate an import token. Returns True if valid."""
    from itsdangerous import URLSafeSerializer, BadSignature
    signer = URLSafeSerializer(secret_key, salt="backlogia-import")
    try:
        return signer.loads(token) == "import-authorized"
    except BadSignature:
        return False


def get_or_create_secret_key():
    """Get or generate a persistent secret key stored in the settings table."""
    from .settings import get_setting, set_setting, _ensure_settings_table

    key = get_setting("_secret_key")
    if key:
        return key

    key = secrets.token_urlsafe(64)
    set_setting("_secret_key", key)
    return key
