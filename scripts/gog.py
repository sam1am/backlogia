# gog_library.py
import os
import sqlite3
import json
from pathlib import Path


def find_gog_database():
    """Find GOG Galaxy database"""
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
        if path.exists():
            return path
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
        print("GOG Galaxy database not found!")
        return []

    games = []

    # SQLite database (Windows/macOS with GOG Galaxy)
    if db_path.suffix == ".db":
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()

        # Query for owned GOG games with all their metadata
        # GamePieceTypes: 112=title, 104=meta, 24=originalImages, 111=summary
        query = """
        SELECT
            lr.releaseKey,
            title.value as title_json,
            meta.value as meta_json,
            images.value as images_json,
            summary.value as summary_json
        FROM
            LibraryReleases lr
        LEFT JOIN
            GamePieces title ON lr.releaseKey = title.releaseKey AND title.gamePieceTypeId = 112
        LEFT JOIN
            GamePieces meta ON lr.releaseKey = meta.releaseKey AND meta.gamePieceTypeId = 104
        LEFT JOIN
            GamePieces images ON lr.releaseKey = images.releaseKey AND images.gamePieceTypeId = 24
        LEFT JOIN
            GamePieces summary ON lr.releaseKey = summary.releaseKey AND summary.gamePieceTypeId = 111
        WHERE
            lr.releaseKey LIKE 'gog_%'
        GROUP BY lr.releaseKey
        """

        try:
            cursor.execute(query)
            for row in cursor.fetchall():
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

    return games


if __name__ == "__main__":
    library = get_gog_library()
    with open("gog_library.json", "w") as f:
        json.dump(library, f, indent=2)
    print(f"Found {len(library)} GOG games")
