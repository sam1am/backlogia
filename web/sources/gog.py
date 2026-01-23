# gog.py
# Fetches games from GOG Galaxy database

import os
import sqlite3
import json
from pathlib import Path

from ..services.settings import get_gog_settings


def find_gog_database():
    """Find GOG Galaxy database"""
    print("[GOG DEBUG] Looking for GOG database...")

    # First check configured path from settings/environment
    gog_settings = get_gog_settings()
    configured_path = gog_settings.get("db_path")
    print(f"[GOG DEBUG] Configured GOG_DB_PATH: {configured_path}")

    if configured_path:
        path = Path(configured_path)
        print(f"[GOG DEBUG] Checking configured path: {path}")
        print(f"[GOG DEBUG] Path exists: {path.exists()}")
        if path.exists():
            print(f"[GOG DEBUG] Using configured path: {path}")
            return path
        else:
            print(f"[GOG DEBUG] Configured path does not exist!")

    # Fall back to auto-detection
    print("[GOG DEBUG] Falling back to auto-detection...")
    possible_paths = [
        # macOS (shared location)
        Path("/Users/Shared/GOG.com/Galaxy/Storage/galaxy-2.0.db"),
        # Windows
        Path(os.environ.get("ProgramData", "C:/ProgramData")) /
        "GOG.com" / "Galaxy" / "storage" / "galaxy-2.0.db",
        # macOS (alternative - user library, older versions)
        Path.home() / "Library" / "Application Support" /
        "GOG.com" / "Galaxy" / "storage" / "galaxy-2.0.db",
        # Linux (via Wine/Heroic)
        Path.home() / ".config" / "heroic" / "gog_store" / "library.json",
    ]

    for path in possible_paths:
        print(f"[GOG DEBUG] Checking: {path} - exists: {path.exists()}")
        if path.exists():
            print(f"[GOG DEBUG] Found database at: {path}")
            return path

    print("[GOG DEBUG] No GOG database found!")
    return None


def _parse_json_value(value):
    """Safely parse JSON value from GamePieces."""
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def get_gog_library():
    db_path = find_gog_database()
    if not db_path:
        print("[GOG DEBUG] GOG Galaxy database not found!")
        return []

    print(f"[GOG DEBUG] Using database: {db_path}")
    games = []

    # SQLite database (Windows/macOS with GOG Galaxy)
    if db_path.suffix == ".db":
        print(f"[GOG DEBUG] Connecting to SQLite database...")
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            print(f"[GOG DEBUG] Connected successfully")
        except Exception as e:
            print(f"[GOG DEBUG] Connection failed: {e}")
            return []
        cursor = conn.cursor()

        # Get the GamePieceType IDs dynamically
        try:
            cursor.execute("SELECT id, type FROM GamePieceTypes WHERE type IN ('title', 'meta', 'originalImages', 'summary')")
            type_mapping = {row[1]: row[0] for row in cursor.fetchall()}

            title_id = type_mapping.get('title')
            meta_id = type_mapping.get('meta')
            images_id = type_mapping.get('originalImages')
            summary_id = type_mapping.get('summary')

            if not all([title_id, meta_id, images_id, summary_id]):
                raise ValueError(f"Some GamePieceTypes not found. Available types: {list(type_mapping.keys())}")
        except (sqlite3.OperationalError, ValueError) as e:
            print(f"[GOG DEBUG] Error fetching GamePieceTypes: {e}")
            conn.close()
            return []

        # Query for owned GOG games with all their metadata
        query = f"""
        SELECT
            lr.releaseKey,
            title.value as title_json,
            meta.value as meta_json,
            images.value as images_json,
            summary.value as summary_json
        FROM
            LibraryReleases lr
        LEFT JOIN
            GamePieces title ON lr.releaseKey = title.releaseKey AND title.gamePieceTypeId = {title_id}
        LEFT JOIN
            GamePieces meta ON lr.releaseKey = meta.releaseKey AND meta.gamePieceTypeId = {meta_id}
        LEFT JOIN
            GamePieces images ON lr.releaseKey = images.releaseKey AND images.gamePieceTypeId = {images_id}
        LEFT JOIN
            GamePieces summary ON lr.releaseKey = summary.releaseKey AND summary.gamePieceTypeId = {summary_id}
        WHERE
            lr.releaseKey LIKE 'gog_%'
        GROUP BY lr.releaseKey
        """

        try:
            print("[GOG DEBUG] Executing query...")
            cursor.execute(query)
            rows = cursor.fetchall()
            print(f"[GOG DEBUG] Query returned {len(rows)} rows")
            for row in rows:
                release_key = row[0]
                title_data = _parse_json_value(row[1])
                meta_data = _parse_json_value(row[2])
                images_data = _parse_json_value(row[3])
                summary_data = _parse_json_value(row[4])

                # Extract product ID from release key (e.g., "gog_1207658867" -> "1207658867")
                product_id = release_key.replace("gog_", "") if release_key else None

                games.append({
                    "name": title_data.get("title"),
                    "release_key": release_key,
                    "product_id": product_id,
                    "developers": meta_data.get("developers", []),
                    "publishers": meta_data.get("publishers", []),
                    "genres": meta_data.get("genres", []),
                    "themes": meta_data.get("themes", []),
                    "critics_score": meta_data.get("criticsScore"),
                    "release_date": meta_data.get("releaseDate"),
                    "summary": summary_data.get("summary"),
                    "cover_image": images_data.get("verticalCover"),
                    "background_image": images_data.get("background"),
                    "icon": images_data.get("squareIcon"),
                    "store": "gog"
                })
        except sqlite3.OperationalError as e:
            print(f"Database query error: {e}")
            # Schema might differ, show available tables
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table';")
            print("Available tables:", cursor.fetchall())

        conn.close()

    # JSON file (Heroic Games Launcher on Linux)
    elif db_path.suffix == ".json":
        with open(db_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for game in data.get("library", []):
            games.append({
                "name": game.get("title"),
                "app_name": game.get("app_name"),
                "platform": "gog"
            })

    print(f"[GOG DEBUG] Returning {len(games)} games")
    return games


if __name__ == "__main__":
    library = get_gog_library()
    with open("gog_library.json", "w") as f:
        json.dump(library, f, indent=2)
    print(f"Found {len(library)} GOG games")
