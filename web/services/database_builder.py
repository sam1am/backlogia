# database_builder.py
# Combines Steam, Epic, GOG, and itch.io libraries into a central SQLite database

import sqlite3
import json
from datetime import datetime

from ..config import DATABASE_PATH


def create_database():
    """Create the SQLite database with the games table."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            store TEXT NOT NULL,
            store_id TEXT,

            -- Metadata
            description TEXT,
            developers TEXT,  -- JSON array
            publishers TEXT,  -- JSON array
            genres TEXT,      -- JSON array

            -- Images
            cover_image TEXT,
            background_image TEXT,
            icon TEXT,

            -- Platform info
            supported_platforms TEXT,  -- JSON array

            -- Dates
            release_date TEXT,
            created_date TEXT,
            last_modified TEXT,

            -- Stats
            playtime_hours REAL,
            critics_score REAL,
            average_rating REAL,  -- Computed average across all available ratings

            -- Additional data
            can_run_offline BOOLEAN,
            dlcs TEXT,  -- JSON array
            extra_data TEXT,  -- JSON for store-specific data

            -- Tracking
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(store, store_id)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_games_store ON games(store)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_games_name ON games(name)
    """)

    # Settings table for storing user configuration
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Collections table for user-created game collections
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Junction table for games in collections
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
    return conn


def import_steam_games(conn):
    """Import games from Steam."""
    print("Importing Steam library...")
    cursor = conn.cursor()

    try:
        from ..sources.steam import get_steam_library

        games = get_steam_library(fetch_reviews=True, max_workers=5)
        if not games:
            print("  No Steam games found or not authenticated")
            return 0

        count = 0
        for game in games:
            try:
                # Build cover image URL from appid
                appid = game.get("appid")
                cover_image = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900_2x.jpg" if appid else None
                background_image = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_hero.jpg" if appid else None

                cursor.execute("""
                    INSERT INTO games (
                        name, store, store_id, cover_image, background_image, icon,
                        playtime_hours, critics_score, extra_data, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(store, store_id) DO UPDATE SET
                        name = excluded.name,
                        cover_image = excluded.cover_image,
                        background_image = excluded.background_image,
                        icon = excluded.icon,
                        playtime_hours = excluded.playtime_hours,
                        critics_score = excluded.critics_score,
                        extra_data = excluded.extra_data,
                        updated_at = excluded.updated_at
                """, (
                    game.get("name"),
                    "steam",
                    str(appid) if appid else None,
                    cover_image,
                    background_image,
                    game.get("icon_url"),
                    game.get("playtime_hours"),
                    game.get("review_score"),  # Steam user review percentage
                    json.dumps(game),
                    datetime.now().isoformat()
                ))
                count += 1
            except Exception as e:
                print(f"  Error importing {game.get('name')}: {e}")

        conn.commit()
        print(f"  Imported {count} Steam games")
        return count
    except Exception as e:
        print(f"  Steam import error: {e}")
        return 0


def import_epic_games(conn):
    """Import games from Epic Games Store."""
    print("Importing Epic library...")
    cursor = conn.cursor()

    try:
        from ..sources.epic import get_epic_library_legendary

        games = get_epic_library_legendary()
        if not games:
            print("  No Epic games found or not authenticated")
            return 0

        count = 0
        for game in games:
            try:
                cursor.execute("""
                    INSERT INTO games (
                        name, store, store_id, description, developers,
                        supported_platforms, cover_image, release_date,
                        created_date, last_modified, can_run_offline,
                        dlcs, extra_data, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(store, store_id) DO UPDATE SET
                        name = excluded.name,
                        description = excluded.description,
                        developers = excluded.developers,
                        supported_platforms = excluded.supported_platforms,
                        cover_image = excluded.cover_image,
                        release_date = excluded.release_date,
                        created_date = excluded.created_date,
                        last_modified = excluded.last_modified,
                        can_run_offline = excluded.can_run_offline,
                        dlcs = excluded.dlcs,
                        extra_data = excluded.extra_data,
                        updated_at = excluded.updated_at
                """, (
                    game.get("name"),
                    "epic",
                    game.get("app_name"),
                    game.get("description"),
                    json.dumps([game.get("developer")]) if game.get("developer") else None,
                    json.dumps(game.get("supported_platforms", [])),
                    game.get("cover_image"),
                    game.get("created_date"),
                    game.get("created_date"),
                    game.get("last_modified"),
                    game.get("can_run_offline"),
                    json.dumps(game.get("dlcs", [])),
                    json.dumps(game),
                    datetime.now().isoformat()
                ))
                count += 1
            except Exception as e:
                print(f"  Error importing {game.get('name')}: {e}")

        conn.commit()
        print(f"  Imported {count} Epic games")
        return count
    except Exception as e:
        print(f"  Epic import error: {e}")
        return 0


def import_gog_games(conn):
    """Import games from GOG Galaxy."""
    print("Importing GOG library...")
    cursor = conn.cursor()

    try:
        from ..sources.gog import get_gog_library

        games = get_gog_library()
        if not games:
            print("  No GOG games found or database not accessible")
            return 0

        count = 0
        for game in games:
            try:
                # Convert Unix timestamp to ISO date if present
                release_date = None
                if game.get("release_date"):
                    try:
                        release_date = datetime.fromtimestamp(
                            game["release_date"]
                        ).isoformat()
                    except (ValueError, TypeError):
                        pass

                # Combine genres and themes, de-duplicate (case-insensitive)
                genres = game.get("genres", [])
                themes = game.get("themes", [])
                seen = set()
                combined_tags = []
                for tag in genres + themes:
                    if tag and tag.lower() not in seen:
                        seen.add(tag.lower())
                        combined_tags.append(tag)

                cursor.execute("""
                    INSERT INTO games (
                        name, store, store_id, description, developers,
                        publishers, genres, cover_image, background_image,
                        icon, release_date, critics_score, extra_data, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(store, store_id) DO UPDATE SET
                        name = excluded.name,
                        description = excluded.description,
                        developers = excluded.developers,
                        publishers = excluded.publishers,
                        cover_image = excluded.cover_image,
                        background_image = excluded.background_image,
                        icon = excluded.icon,
                        release_date = excluded.release_date,
                        critics_score = excluded.critics_score,
                        extra_data = excluded.extra_data,
                        updated_at = excluded.updated_at
                """, (
                    game.get("name"),
                    "gog",
                    game.get("product_id"),
                    game.get("summary"),
                    json.dumps(game.get("developers", [])),
                    json.dumps(game.get("publishers", [])),
                    json.dumps(combined_tags),
                    game.get("cover_image"),
                    game.get("background_image"),
                    game.get("icon"),
                    release_date,
                    game.get("critics_score"),
                    json.dumps(game),
                    datetime.now().isoformat()
                ))
                count += 1
            except Exception as e:
                print(f"  Error importing {game.get('name')}: {e}")

        conn.commit()
        print(f"  Imported {count} GOG games")
        return count
    except Exception as e:
        print(f"  GOG import error: {e}")
        return 0


def import_itch_games(conn):
    """Import games from itch.io (requires prior OAuth setup)."""
    print("Importing itch.io library...")
    cursor = conn.cursor()

    try:
        from ..sources.itch import get_auth_token, get_owned_games

        token = get_auth_token()
        if not token:
            print("  itch.io not configured or not authenticated")
            print("  Set your itch.io API key in the Settings page")
            print("  (get key at: https://itch.io/user/settings/api-keys)")
            return 0

        games = get_owned_games(token)
        if not games:
            print("  No itch.io games found")
            return 0

        count = 0
        for game in games:
            try:
                # Build platforms list
                platforms = []
                if game.get("platforms", {}).get("windows"):
                    platforms.append("Windows")
                if game.get("platforms", {}).get("mac"):
                    platforms.append("Mac")
                if game.get("platforms", {}).get("linux"):
                    platforms.append("Linux")
                if game.get("platforms", {}).get("android"):
                    platforms.append("Android")

                cursor.execute("""
                    INSERT INTO games (
                        name, store, store_id, description, cover_image,
                        supported_platforms, release_date, extra_data, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(store, store_id) DO UPDATE SET
                        name = excluded.name,
                        description = excluded.description,
                        cover_image = excluded.cover_image,
                        supported_platforms = excluded.supported_platforms,
                        release_date = excluded.release_date,
                        extra_data = excluded.extra_data,
                        updated_at = excluded.updated_at
                """, (
                    game.get("title"),
                    "itch",
                    str(game.get("id")),
                    game.get("short_text"),
                    game.get("cover_url"),
                    json.dumps(platforms) if platforms else None,
                    game.get("published_at"),
                    json.dumps(game),
                    datetime.now().isoformat()
                ))
                count += 1
            except Exception as e:
                print(f"  Error importing {game.get('title')}: {e}")

        conn.commit()
        print(f"  Imported {count} itch.io games")
        return count
    except ImportError:
        print("  itch.io module not available")
        return 0
    except Exception as e:
        print(f"  itch.io import error: {e}")
        return 0


def import_humble_games(conn):
    """Import games from Humble Bundle (requires session cookie)."""
    print("Importing Humble Bundle library...")
    cursor = conn.cursor()

    try:
        from ..sources.humble import get_humble_library

        games = get_humble_library()
        if not games:
            print("  No Humble Bundle games found or not authenticated")
            print("  Set your Humble Bundle session cookie in Settings")
            return 0

        count = 0
        for game in games:
            try:
                cursor.execute("""
                    INSERT INTO games (
                        name, store, store_id, cover_image, icon,
                        supported_platforms, publishers, release_date,
                        extra_data, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(store, store_id) DO UPDATE SET
                        name = excluded.name,
                        cover_image = excluded.cover_image,
                        icon = excluded.icon,
                        supported_platforms = excluded.supported_platforms,
                        publishers = excluded.publishers,
                        release_date = excluded.release_date,
                        extra_data = excluded.extra_data,
                        updated_at = excluded.updated_at
                """, (
                    game.get("human_name"),
                    "humble",
                    game.get("machine_name"),
                    game.get("icon"),
                    game.get("icon"),
                    json.dumps(game.get("platforms", [])),
                    json.dumps([game.get("payee")]) if game.get("payee") else None,
                    game.get("created"),
                    json.dumps(game),
                    datetime.now().isoformat()
                ))
                count += 1
            except Exception as e:
                print(f"  Error importing {game.get('human_name')}: {e}")

        conn.commit()
        print(f"  Imported {count} Humble Bundle games")
        return count
    except ImportError:
        print("  Humble Bundle module not available")
        return 0
    except Exception as e:
        print(f"  Humble Bundle import error: {e}")
        return 0


def import_battlenet_games(conn):
    """Import games from Battle.net (requires session cookie)."""
    print("Importing Battle.net library...")
    cursor = conn.cursor()

    try:
        from ..sources.battlenet import get_battlenet_library

        games = get_battlenet_library()
        if not games:
            print("  No Battle.net games found or not authenticated")
            print("  Set your Battle.net session cookie in Settings")
            return 0

        count = 0
        for game in games:
            try:
                cursor.execute("""
                    INSERT INTO games (
                        name, store, store_id, cover_image,
                        extra_data, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(store, store_id) DO UPDATE SET
                        name = excluded.name,
                        cover_image = excluded.cover_image,
                        extra_data = excluded.extra_data,
                        updated_at = excluded.updated_at
                """, (
                    game.get("name"),
                    "battlenet",
                    game.get("title_id"),
                    game.get("cover_image"),
                    json.dumps(game.get("raw_data", {})),
                    datetime.now().isoformat()
                ))
                count += 1
            except Exception as e:
                print(f"  Error importing {game.get('name')}: {e}")

        conn.commit()
        print(f"  Imported {count} Battle.net games")
        return count
    except ImportError:
        print("  Battle.net module not available")
        return 0
    except Exception as e:
        print(f"  Battle.net import error: {e}")
        return 0


def import_ea_games(conn):
    """Import games from EA (requires session cookies)."""
    print("Importing EA library...")
    cursor = conn.cursor()

    try:
        from ..sources.ea import get_ea_library

        games = get_ea_library()
        if not games:
            print("  No EA games found or not authenticated")
            print("  Get a new EA bearer token using the script in Settings")
            return 0

        count = 0
        for game in games:
            try:
                # Build developers/publishers JSON arrays
                developers = [game.get("developer")] if game.get("developer") else None
                publishers = [game.get("publisher")] if game.get("publisher") else None

                cursor.execute("""
                    INSERT INTO games (
                        name, store, store_id, cover_image,
                        developers, publishers, release_date,
                        extra_data, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(store, store_id) DO UPDATE SET
                        name = excluded.name,
                        cover_image = excluded.cover_image,
                        developers = excluded.developers,
                        publishers = excluded.publishers,
                        release_date = excluded.release_date,
                        extra_data = excluded.extra_data,
                        updated_at = excluded.updated_at
                """, (
                    game.get("name"),
                    "ea",
                    game.get("offer_id"),
                    game.get("cover_image"),
                    json.dumps(developers) if developers else None,
                    json.dumps(publishers) if publishers else None,
                    game.get("release_date"),
                    json.dumps(game.get("raw_data", {})),
                    datetime.now().isoformat()
                ))
                count += 1
            except Exception as e:
                print(f"  Error importing {game.get('name')}: {e}")

        conn.commit()
        print(f"  Imported {count} EA games")
        return count
    except ImportError:
        print("  EA module not available")
        return 0
    except Exception as e:
        print(f"  EA import error: {e}")
        return 0


def import_amazon_games(conn):
    """Import games from Amazon Games (local database or API token)."""
    print("Importing Amazon Games library...")
    cursor = conn.cursor()

    try:
        from ..sources.amazon import get_amazon_library

        games = get_amazon_library()
        if not games:
            print("  No Amazon games found or not configured")
            print("  Set up Amazon Games in Settings (local database or API token)")
            return 0

        count = 0
        for game in games:
            try:
                # Build developers/publishers JSON arrays
                developers = [game.get("developer")] if game.get("developer") else None
                publishers = [game.get("publisher")] if game.get("publisher") else None

                cursor.execute("""
                    INSERT INTO games (
                        name, store, store_id, cover_image, icon,
                        developers, publishers, extra_data, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(store, store_id) DO UPDATE SET
                        name = excluded.name,
                        cover_image = excluded.cover_image,
                        icon = excluded.icon,
                        developers = excluded.developers,
                        publishers = excluded.publishers,
                        extra_data = excluded.extra_data,
                        updated_at = excluded.updated_at
                """, (
                    game.get("name"),
                    "amazon",
                    game.get("product_id"),
                    game.get("icon_url"),
                    game.get("icon_url"),
                    json.dumps(developers) if developers else None,
                    json.dumps(publishers) if publishers else None,
                    json.dumps(game.get("raw_data", {})),
                    datetime.now().isoformat()
                ))
                count += 1
            except Exception as e:
                print(f"  Error importing {game.get('name')}: {e}")

        conn.commit()
        print(f"  Imported {count} Amazon games")
        return count
    except ImportError:
        print("  Amazon Games module not available")
        return 0
    except Exception as e:
        print(f"  Amazon Games import error: {e}")
        return 0


def add_average_rating_column(conn):
    """Add average_rating column to the database if it doesn't exist."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(games)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    if "average_rating" not in existing_columns:
        cursor.execute("ALTER TABLE games ADD COLUMN average_rating REAL")
        print("Added column: average_rating")
        conn.commit()


def calculate_average_rating(
    critics_score=None,
    igdb_rating=None,
    aggregated_rating=None,
    total_rating=None,
    metacritic_score=None,
    metacritic_user_score=None,
):
    """
    Calculate the average rating across all available ratings.
    All ratings are normalized to 0-100 scale.
    Returns None if no ratings are available.
    """
    ratings = []

    # Steam critics_score is already 0-100
    if critics_score is not None:
        ratings.append(float(critics_score))

    # IGDB ratings are already 0-100
    if igdb_rating is not None:
        ratings.append(float(igdb_rating))
    if aggregated_rating is not None:
        ratings.append(float(aggregated_rating))
    if total_rating is not None:
        ratings.append(float(total_rating))

    # Metacritic critic score is 0-100
    if metacritic_score is not None:
        ratings.append(float(metacritic_score))

    # Metacritic user score is 0-10, normalize to 0-100
    if metacritic_user_score is not None:
        ratings.append(float(metacritic_user_score) * 10)

    if not ratings:
        return None

    return round(sum(ratings) / len(ratings), 1)


def update_average_rating(conn, game_id):
    """
    Fetch all ratings for a game and update its average_rating.
    Call this after updating any rating field for a game.
    """
    cursor = conn.cursor()

    # First ensure the column exists
    add_average_rating_column(conn)

    # Fetch all rating fields for this game
    cursor.execute(
        """SELECT critics_score, igdb_rating, aggregated_rating, total_rating,
                  metacritic_score, metacritic_user_score
           FROM games WHERE id = ?""",
        (game_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    avg = calculate_average_rating(
        critics_score=row[0],
        igdb_rating=row[1],
        aggregated_rating=row[2],
        total_rating=row[3],
        metacritic_score=row[4],
        metacritic_user_score=row[5],
    )

    cursor.execute(
        "UPDATE games SET average_rating = ? WHERE id = ?",
        (avg, game_id),
    )
    conn.commit()
    return avg


def get_stats(conn):
    """Get database statistics."""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM games")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT store, COUNT(*) FROM games GROUP BY store")
    by_store = dict(cursor.fetchall())

    return {"total": total, "by_store": by_store}
