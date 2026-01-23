# local.py
# Imports games from local folders

import os
import json
import hashlib
from pathlib import Path

from ..services.settings import get_local_games_settings


def discover_local_game_paths():
    """
    Discover local game paths from environment variable or by scanning
    for /local-games-* mount points (used in Docker).

    Returns a list of valid paths that exist and contain game folders.
    """
    settings = get_local_games_settings()
    paths_str = settings.get("paths", "")

    paths = []

    if paths_str:
        # Use configured paths from environment
        paths = [p.strip() for p in paths_str.split(",") if p.strip()]
    else:
        # Auto-discover /local-games-* mount points (Docker convention)
        for i in range(1, 10):
            mount_path = Path(f"/local-games-{i}")
            if mount_path.exists() and mount_path.is_dir():
                paths.append(str(mount_path))

    # Filter to only paths that exist and have game subfolders
    valid_paths = []
    for p in paths:
        path = Path(p).expanduser()

        # Skip placeholder paths
        if ".empty" in str(path) or path.name == ".empty":
            continue

        if not path.exists() or not path.is_dir():
            continue

        # Check if it has any non-hidden subdirectories (games)
        try:
            has_games = any(
                item.is_dir() and not item.name.startswith(".")
                for item in path.iterdir()
            )
            if has_games:
                valid_paths.append(str(path))
        except PermissionError:
            continue

    return valid_paths


def get_local_library():
    """
    Scan configured local game folders and return a list of games.

    Each subfolder (1 level deep) is treated as a game.
    Game name is taken from folder name, unless a game.json override exists.

    game.json format (optional, placed in game folder):
    {
        "name": "Actual Game Name",
        "igdb_id": 12345  // optional, for manual IGDB matching
    }
    """
    paths = discover_local_game_paths()

    if not paths:
        print("[LOCAL DEBUG] No local game paths found")
        return []

    print(f"[LOCAL DEBUG] Discovered paths: {paths}")

    games = []

    for base_path in paths:
        base = Path(base_path)
        print(f"[LOCAL DEBUG] Scanning: {base}")

        # Scan 1 level deep - each subfolder is a game
        for item in base.iterdir():
            if not item.is_dir():
                continue

            # Skip hidden folders
            if item.name.startswith("."):
                continue

            folder_name = item.name
            game_data = {
                "name": folder_name,
                "folder_path": str(item),
            }

            # Check for game.json override
            override_file = item / "game.json"
            if override_file.exists():
                try:
                    with open(override_file, "r", encoding="utf-8") as f:
                        override = json.load(f)
                    print(f"[LOCAL DEBUG] Found override for {folder_name}: {override}")

                    # Apply overrides
                    if override.get("name"):
                        game_data["name"] = override["name"]
                    if override.get("igdb_id"):
                        game_data["igdb_id"] = override["igdb_id"]
                    if override.get("description"):
                        game_data["description"] = override["description"]
                    if override.get("cover_image"):
                        game_data["cover_image"] = override["cover_image"]
                    if override.get("developers"):
                        game_data["developers"] = override["developers"]
                    if override.get("genres"):
                        game_data["genres"] = override["genres"]
                    if override.get("release_date"):
                        game_data["release_date"] = override["release_date"]

                except (json.JSONDecodeError, IOError) as e:
                    print(f"[LOCAL DEBUG] Error reading game.json for {folder_name}: {e}")

            # Generate a stable store_id from the folder path
            # Use a hash of the relative path within the base folder for stability
            relative_path = f"{base.name}/{folder_name}"
            store_id = hashlib.md5(relative_path.encode()).hexdigest()[:12]
            game_data["store_id"] = store_id

            games.append(game_data)
            print(f"[LOCAL DEBUG] Found game: {game_data['name']} (folder: {folder_name})")

    print(f"[LOCAL DEBUG] Total games found: {len(games)}")
    return games


if __name__ == "__main__":
    library = get_local_library()
    print(f"\nFound {len(library)} local games:")
    for game in library:
        print(f"  - {game['name']} ({game.get('folder_path', 'N/A')})")
