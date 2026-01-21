# app.py
# Web interface for the game library

import os
import sys
from flask import Flask, render_template, request, jsonify, redirect, url_for
import sqlite3
import json
from pathlib import Path

# Add scripts directory to path for settings module
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from settings import (
    get_setting, set_setting,
    STEAM_ID, STEAM_API_KEY, IGDB_CLIENT_ID, IGDB_CLIENT_SECRET, ITCH_API_KEY,
    HUMBLE_SESSION_COOKIE, GOG_DB_PATH
)
from igdb_sync import (
    IGDBClient, sync_games as igdb_sync_games, add_igdb_columns,
    extract_genres_and_themes, merge_and_dedupe_genres,
    POPULARITY_TYPE_IGDB_VISITS, POPULARITY_TYPE_IGDB_WANT_TO_PLAY,
    POPULARITY_TYPE_IGDB_PLAYING, POPULARITY_TYPE_IGDB_PLAYED,
    POPULARITY_TYPE_STEAM_PEAK_24H, POPULARITY_TYPE_STEAM_POSITIVE_REVIEWS
)
from build_database import (
    create_database, import_steam_games, import_epic_games,
    import_gog_games, import_itch_games, import_humble_games
)
from epic import is_legendary_installed, check_authentication
import subprocess

app = Flask(__name__)

DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", Path(__file__).parent.parent / "game_library.db"))

# Filter out duplicate GOG entries from Amazon Prime/Luna
EXCLUDE_DUPLICATES_FILTER = """
    AND name NOT LIKE '% - Amazon Prime'
    AND name NOT LIKE '% - Amazon Luna'
"""

# Filter to exclude hidden games (in addition to duplicates)
EXCLUDE_HIDDEN_FILTER = EXCLUDE_DUPLICATES_FILTER + """
    AND (hidden IS NULL OR hidden = 0)
"""


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
    conn.commit()
    conn.close()


# Ensure database and tables exist on startup
create_database()
ensure_extra_columns()
# Add IGDB columns
_init_conn = sqlite3.connect(DATABASE_PATH)
add_igdb_columns(_init_conn)
_init_conn.close()


def parse_json_field(value):
    """Safely parse a JSON field."""
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def get_store_url(store, store_id, extra_data=None):
    """Generate the store URL for a game."""
    if not store_id:
        return None

    if store == "steam":
        return f"https://store.steampowered.com/app/{store_id}"
    elif store == "epic":
        # Epic URLs use the app_name slug
        return f"https://store.epicgames.com/en-US/p/{store_id}"
    elif store == "gog":
        # GOG URLs use the product ID
        return f"https://www.gog.com/en/game/{store_id}"
    elif store == "itch":
        # Itch URLs are stored in extra_data
        if extra_data:
            try:
                data = json.loads(extra_data) if isinstance(extra_data, str) else extra_data
                return data.get("url")
            except (json.JSONDecodeError, TypeError):
                pass
        return None
    elif store == "humble":
        # Humble Bundle URLs - link to downloads page with gamekey
        if extra_data:
            try:
                data = json.loads(extra_data) if isinstance(extra_data, str) else extra_data
                gamekey = data.get("gamekey")
                if gamekey:
                    return f"https://www.humblebundle.com/downloads?key={gamekey}"
            except (json.JSONDecodeError, TypeError):
                pass
        return None
    return None


def group_games_by_igdb(games):
    """Group games by IGDB ID, keeping separate entries for games without IGDB match."""
    grouped = {}
    no_igdb_games = []

    for game in games:
        game_dict = dict(game)
        igdb_id = game_dict.get("igdb_id")

        if igdb_id:
            if igdb_id not in grouped:
                grouped[igdb_id] = {
                    "primary": game_dict,
                    "stores": [game_dict["store"]],
                    "game_ids": [game_dict["id"]],
                    "store_data": {game_dict["store"]: game_dict}
                }
            else:
                grouped[igdb_id]["stores"].append(game_dict["store"])
                grouped[igdb_id]["game_ids"].append(game_dict["id"])
                grouped[igdb_id]["store_data"][game_dict["store"]] = game_dict
                # Use the one with more data as primary (prefer one with playtime or better cover)
                current_primary = grouped[igdb_id]["primary"]
                if (game_dict.get("playtime_hours") and not current_primary.get("playtime_hours")) or \
                   (game_dict.get("igdb_cover_url") and not current_primary.get("igdb_cover_url")):
                    grouped[igdb_id]["primary"] = game_dict
        else:
            no_igdb_games.append({
                "primary": game_dict,
                "stores": [game_dict["store"]],
                "game_ids": [game_dict["id"]],
                "store_data": {game_dict["store"]: game_dict}
            })

    # Convert grouped dict to list and add non-IGDB games
    result = list(grouped.values()) + no_igdb_games
    return result


@app.route("/")
def home():
    """Home page - redirect to discover."""
    return redirect(url_for('discover'))


@app.route("/library")
def library():
    """Library page - list all games."""
    conn = get_db()
    cursor = conn.cursor()

    # Get filter parameters
    store_filters = request.args.getlist("stores")  # Multi-select stores
    genre_filters = request.args.getlist("genres")  # Multi-select genres
    search = request.args.get("search", "")
    sort_by = request.args.get("sort", "name")
    sort_order = request.args.get("order", "asc")

    # Build query (exclude Amazon Prime/Luna duplicates and hidden games)
    query = "SELECT * FROM games WHERE 1=1" + EXCLUDE_HIDDEN_FILTER
    params = []

    if store_filters:
        placeholders = ",".join("?" * len(store_filters))
        query += f" AND store IN ({placeholders})"
        params.extend(store_filters)

    if genre_filters:
        # Filter by genres (JSON array stored in genres column)
        # Use LIKE with JSON pattern matching for each genre
        genre_conditions = []
        for genre in genre_filters:
            # Match genre in JSON array (case-insensitive)
            genre_conditions.append("LOWER(genres) LIKE ?")
            params.append(f'%"{genre.lower()}"%')
        query += " AND (" + " OR ".join(genre_conditions) + ")"

    if search:
        query += " AND name LIKE ?"
        params.append(f"%{search}%")

    # Sorting
    valid_sorts = ["name", "store", "playtime_hours", "critics_score", "release_date", "total_rating", "igdb_rating", "aggregated_rating"]
    if sort_by in valid_sorts:
        order = "DESC" if sort_order == "desc" else "ASC"
        if sort_by in ["playtime_hours", "critics_score", "total_rating", "igdb_rating", "aggregated_rating"]:
            query += f" ORDER BY {sort_by} {order} NULLS LAST"
        else:
            query += f" ORDER BY {sort_by} COLLATE NOCASE {order}"

    cursor.execute(query, params)
    games = cursor.fetchall()

    # Group games by IGDB ID (combines multi-store ownership)
    grouped_games = group_games_by_igdb(games)

    # Sort grouped games by primary game's sort field
    # Separate games with null sort values so nulls are always last
    reverse = sort_order == "desc"
    with_values = []
    without_values = []

    for g in grouped_games:
        val = g["primary"].get(sort_by)
        if val is None:
            without_values.append(g)
        else:
            with_values.append(g)

    def get_sort_key(g):
        val = g["primary"].get(sort_by)
        if isinstance(val, str):
            return val.lower()
        return val

    with_values.sort(key=get_sort_key, reverse=reverse)
    grouped_games = with_values + without_values

    # Get store counts for filters (exclude duplicates and hidden)
    cursor.execute("SELECT store, COUNT(*) FROM games WHERE 1=1" + EXCLUDE_HIDDEN_FILTER + " GROUP BY store")
    store_counts = dict(cursor.fetchall())

    cursor.execute("SELECT COUNT(*) FROM games WHERE 1=1" + EXCLUDE_HIDDEN_FILTER)
    total_count = cursor.fetchone()[0]

    # Count unique games (grouped)
    unique_count = len(grouped_games)

    # Get hidden count
    cursor.execute("SELECT COUNT(*) FROM games WHERE hidden = 1")
    hidden_count = cursor.fetchone()[0]

    # Get all unique genres with counts
    cursor.execute("SELECT genres FROM games WHERE genres IS NOT NULL AND genres != '[]'" + EXCLUDE_HIDDEN_FILTER)
    genre_rows = cursor.fetchall()
    genre_counts = {}
    for row in genre_rows:
        try:
            genres_list = json.loads(row[0]) if row[0] else []
            for genre in genres_list:
                if genre:
                    genre_counts[genre] = genre_counts.get(genre, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass
    # Sort genres by count (descending) then alphabetically
    genre_counts = dict(sorted(genre_counts.items(), key=lambda x: (-x[1], x[0].lower())))

    conn.close()

    return render_template(
        "index.html",
        games=grouped_games,
        store_counts=store_counts,
        genre_counts=genre_counts,
        total_count=total_count,
        unique_count=unique_count,
        hidden_count=hidden_count,
        current_stores=store_filters,
        current_genres=genre_filters,
        current_search=search,
        current_sort=sort_by,
        current_order=sort_order,
        parse_json=parse_json_field
    )


@app.route("/game/<int:game_id>")
def game_detail(game_id):
    """Game detail page - shows combined view for games owned on multiple stores."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
    game = cursor.fetchone()

    if not game:
        conn.close()
        return "Game not found", 404

    game_dict = dict(game)

    # Find all copies of this game across stores (by IGDB ID)
    related_games = []
    if game_dict.get("igdb_id"):
        cursor.execute(
            "SELECT * FROM games WHERE igdb_id = ? ORDER BY store",
            (game_dict["igdb_id"],)
        )
        related_games = [dict(g) for g in cursor.fetchall()]
    else:
        related_games = [game_dict]

    conn.close()

    # Build store info with URLs for each copy
    store_info = []
    for g in related_games:
        store_url = get_store_url(g["store"], g["store_id"], g.get("extra_data"))
        store_info.append({
            "store": g["store"],
            "store_id": g["store_id"],
            "store_url": store_url,
            "game_id": g["id"],
            "playtime_hours": g.get("playtime_hours"),
        })

    # Use the best game data as primary (prefer one with IGDB data, then playtime)
    primary_game = game_dict
    for g in related_games:
        if g.get("igdb_cover_url") and not primary_game.get("igdb_cover_url"):
            primary_game = g
        elif g.get("playtime_hours") and not primary_game.get("playtime_hours"):
            primary_game = g

    return render_template(
        "game_detail.html",
        game=primary_game,
        store_info=store_info,
        related_games=related_games,
        parse_json=parse_json_field,
        get_store_url=get_store_url
    )


@app.route("/random")
def random_game():
    """Redirect to a random game detail page."""
    conn = get_db()
    cursor = conn.cursor()

    # Get a random game that isn't hidden
    cursor.execute(
        "SELECT id FROM games WHERE 1=1" + EXCLUDE_HIDDEN_FILTER + " ORDER BY RANDOM() LIMIT 1"
    )
    result = cursor.fetchone()
    conn.close()

    if result:
        return redirect(url_for('game_detail', game_id=result['id']))
    else:
        return redirect(url_for('index'))


@app.route("/api/games")
def api_games():
    """API endpoint for games."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM games WHERE 1=1" + EXCLUDE_DUPLICATES_FILTER + " ORDER BY name")
    games = cursor.fetchall()

    conn.close()

    return jsonify([dict(g) for g in games])


@app.route("/api/stats")
def api_stats():
    """API endpoint for library statistics."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM games WHERE 1=1" + EXCLUDE_DUPLICATES_FILTER)
    total = cursor.fetchone()[0]

    cursor.execute("SELECT store, COUNT(*) FROM games WHERE 1=1" + EXCLUDE_DUPLICATES_FILTER + " GROUP BY store")
    by_store = dict(cursor.fetchall())

    cursor.execute("SELECT SUM(playtime_hours) FROM games WHERE playtime_hours IS NOT NULL" + EXCLUDE_DUPLICATES_FILTER)
    total_playtime = cursor.fetchone()[0] or 0

    conn.close()

    return jsonify({
        "total_games": total,
        "by_store": by_store,
        "total_playtime_hours": round(total_playtime, 1)
    })


@app.route("/api/game/<int:game_id>/igdb", methods=["POST"])
def update_igdb(game_id):
    """Update IGDB ID for a game and resync its data."""
    data = request.get_json()
    if not data or "igdb_id" not in data:
        return jsonify({"error": "igdb_id is required"}), 400

    igdb_id = data.get("igdb_id")

    # Allow clearing the IGDB ID
    if igdb_id is None or igdb_id == "":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE games SET
                igdb_id = NULL,
                igdb_slug = NULL,
                igdb_rating = NULL,
                igdb_rating_count = NULL,
                aggregated_rating = NULL,
                aggregated_rating_count = NULL,
                total_rating = NULL,
                total_rating_count = NULL,
                igdb_summary = NULL,
                igdb_cover_url = NULL,
                igdb_screenshots = NULL,
                igdb_matched_at = NULL
            WHERE id = ?""",
            (game_id,),
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "IGDB data cleared"})

    # Validate igdb_id is a number
    try:
        igdb_id = int(igdb_id)
    except (ValueError, TypeError):
        return jsonify({"error": "igdb_id must be a number"}), 400

    # Fetch data from IGDB
    try:
        client = IGDBClient()
        igdb_game = client.get_game_by_id(igdb_id)

        if not igdb_game:
            return jsonify({"error": f"No game found with IGDB ID {igdb_id}"}), 404

        # Extract cover URL
        cover_url = None
        if igdb_game.get("cover"):
            cover_url = igdb_game["cover"].get("url", "")
            cover_url = cover_url.replace("t_thumb", "t_cover_big")
            if cover_url and not cover_url.startswith("http"):
                cover_url = "https:" + cover_url

        # Extract screenshots
        screenshots = []
        if igdb_game.get("screenshots"):
            for screenshot in igdb_game["screenshots"][:5]:
                url = screenshot.get("url", "")
                url = url.replace("t_thumb", "t_screenshot_big")
                if url and not url.startswith("http"):
                    url = "https:" + url
                screenshots.append(url)

        # Check if game is NSFW
        is_nsfw = IGDBClient.is_nsfw(igdb_game)

        # Update the database
        conn = get_db()
        cursor = conn.cursor()

        # Fetch existing genres to merge with IGDB data
        cursor.execute("SELECT genres FROM games WHERE id = ?", (game_id,))
        row = cursor.fetchone()
        existing_genres = row[0] if row else None

        # Extract genres and themes from IGDB and merge with existing
        igdb_tags = extract_genres_and_themes(igdb_game)
        merged_genres = merge_and_dedupe_genres(existing_genres, igdb_tags)

        cursor.execute(
            """UPDATE games SET
                igdb_id = ?,
                igdb_slug = ?,
                igdb_rating = ?,
                igdb_rating_count = ?,
                aggregated_rating = ?,
                aggregated_rating_count = ?,
                total_rating = ?,
                total_rating_count = ?,
                igdb_summary = ?,
                igdb_cover_url = ?,
                igdb_screenshots = ?,
                igdb_matched_at = CURRENT_TIMESTAMP,
                nsfw = ?,
                genres = ?
            WHERE id = ?""",
            (
                igdb_game.get("id"),
                igdb_game.get("slug"),
                igdb_game.get("rating"),
                igdb_game.get("rating_count"),
                igdb_game.get("aggregated_rating"),
                igdb_game.get("aggregated_rating_count"),
                igdb_game.get("total_rating"),
                igdb_game.get("total_rating_count"),
                igdb_game.get("summary"),
                cover_url,
                json.dumps(screenshots) if screenshots else None,
                1 if is_nsfw else 0,
                merged_genres,
                game_id,
            ),
        )
        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "message": f"Synced with IGDB: {igdb_game.get('name')}",
            "igdb_name": igdb_game.get("name"),
            "igdb_id": igdb_game.get("id")
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to fetch from IGDB: {str(e)}"}), 500


@app.route("/api/game/<int:game_id>/hidden", methods=["POST"])
def update_hidden(game_id):
    """Toggle hidden status for a game."""
    data = request.get_json()
    if data is None or "hidden" not in data:
        return jsonify({"error": "hidden is required"}), 400

    hidden = 1 if data.get("hidden") else 0

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE games SET hidden = ? WHERE id = ?", (hidden, game_id))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "hidden": bool(hidden)})


@app.route("/api/game/<int:game_id>/nsfw", methods=["POST"])
def update_nsfw(game_id):
    """Toggle NSFW status for a game."""
    data = request.get_json()
    if data is None or "nsfw" not in data:
        return jsonify({"error": "nsfw is required"}), 400

    nsfw = 1 if data.get("nsfw") else 0

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE games SET nsfw = ? WHERE id = ?", (nsfw, game_id))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "nsfw": bool(nsfw)})


@app.route("/api/game/<int:game_id>/cover-override", methods=["POST"])
def update_cover_override(game_id):
    """Update the cover art override URL for a game."""
    data = request.get_json()
    if data is None:
        return jsonify({"error": "Request body required"}), 400

    # Allow empty string or None to clear the override
    cover_url = data.get("cover_url_override", "").strip() or None

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE games SET cover_url_override = ? WHERE id = ?", (cover_url, game_id)
    )
    conn.commit()
    conn.close()

    return jsonify({"success": True, "cover_url_override": cover_url})


@app.route("/api/games/bulk/hide", methods=["POST"])
def bulk_hide_games():
    """Hide multiple games at once."""
    data = request.get_json()
    if data is None or "game_ids" not in data:
        return jsonify({"error": "game_ids is required"}), 400

    game_ids = data.get("game_ids", [])
    if not game_ids:
        return jsonify({"error": "No games selected"}), 400

    conn = get_db()
    cursor = conn.cursor()

    placeholders = ",".join("?" * len(game_ids))
    cursor.execute(f"UPDATE games SET hidden = 1 WHERE id IN ({placeholders})", game_ids)
    updated = cursor.rowcount

    conn.commit()
    conn.close()

    return jsonify({"success": True, "updated": updated})


@app.route("/api/games/bulk/nsfw", methods=["POST"])
def bulk_nsfw_games():
    """Mark multiple games as NSFW at once."""
    data = request.get_json()
    if data is None or "game_ids" not in data:
        return jsonify({"error": "game_ids is required"}), 400

    game_ids = data.get("game_ids", [])
    if not game_ids:
        return jsonify({"error": "No games selected"}), 400

    conn = get_db()
    cursor = conn.cursor()

    placeholders = ",".join("?" * len(game_ids))
    cursor.execute(f"UPDATE games SET nsfw = 1 WHERE id IN ({placeholders})", game_ids)
    updated = cursor.rowcount

    conn.commit()
    conn.close()

    return jsonify({"success": True, "updated": updated})


@app.route("/hidden")
def hidden_games():
    """Page showing all hidden games."""
    conn = get_db()
    cursor = conn.cursor()

    search = request.args.get("search", "")

    query = "SELECT * FROM games WHERE hidden = 1" + EXCLUDE_DUPLICATES_FILTER
    params = []

    if search:
        query += " AND name LIKE ?"
        params.append(f"%{search}%")

    query += " ORDER BY name COLLATE NOCASE ASC"

    cursor.execute(query, params)
    games = cursor.fetchall()

    conn.close()

    return render_template(
        "hidden_games.html",
        games=games,
        current_search=search,
        parse_json=parse_json_field
    )


@app.route("/discover")
def discover():
    """Discover page - showcase popular games from your library."""
    conn = get_db()
    cursor = conn.cursor()

    # Get all games with IGDB IDs from the library (excluding hidden/duplicates)
    cursor.execute(
        """SELECT id, name, store, igdb_id, igdb_cover_url, cover_image,
                  igdb_summary, description, igdb_screenshots, total_rating,
                  igdb_rating, aggregated_rating, genres, playtime_hours
           FROM games
           WHERE igdb_id IS NOT NULL""" + EXCLUDE_HIDDEN_FILTER + """
           ORDER BY total_rating DESC NULLS LAST"""
    )
    library_games = cursor.fetchall()

    # Create a mapping of igdb_id to local game data
    igdb_to_local = {}
    igdb_ids = []
    for game in library_games:
        igdb_id = game["igdb_id"]
        igdb_ids.append(igdb_id)
        igdb_to_local[igdb_id] = dict(game)

    # Try to get popularity data from IGDB
    popular_games = []
    popularity_source = "rating"  # Default fallback

    # Popularity-based sections (will be populated if IGDB API succeeds)
    igdb_visits = []
    want_to_play = []
    playing = []
    played = []
    steam_peak_24h = []
    steam_positive_reviews = []

    if igdb_ids:
        try:
            client = IGDBClient()

            # Try to fetch popularity primitives for our library games
            popularity_data = client.get_popular_games(igdb_ids, limit=100)

            if popularity_data:
                popularity_source = "igdb_popularity"
                # Sort by popularity value and get top games
                seen_ids = set()
                for pop in popularity_data:
                    game_id = pop.get("game_id")
                    if game_id in igdb_to_local and game_id not in seen_ids:
                        game_data = igdb_to_local[game_id].copy()
                        game_data["popularity_value"] = pop.get("value", 0)
                        popular_games.append(game_data)
                        seen_ids.add(game_id)

            # Helper function to fetch games by popularity type
            def fetch_by_popularity_type(pop_type, limit=10):
                pop_data = client.get_popular_games(igdb_ids, popularity_type=pop_type, limit=limit)
                result = []
                seen = set()
                for pop in pop_data:
                    gid = pop.get("game_id")
                    if gid in igdb_to_local and gid not in seen:
                        gdata = igdb_to_local[gid].copy()
                        gdata["popularity_value"] = pop.get("value", 0)
                        result.append(gdata)
                        seen.add(gid)
                return result

            # Fetch each popularity type
            igdb_visits = fetch_by_popularity_type(POPULARITY_TYPE_IGDB_VISITS)
            want_to_play = fetch_by_popularity_type(POPULARITY_TYPE_IGDB_WANT_TO_PLAY)
            playing = fetch_by_popularity_type(POPULARITY_TYPE_IGDB_PLAYING)
            played = fetch_by_popularity_type(POPULARITY_TYPE_IGDB_PLAYED)
            steam_peak_24h = fetch_by_popularity_type(POPULARITY_TYPE_STEAM_PEAK_24H)
            steam_positive_reviews = fetch_by_popularity_type(POPULARITY_TYPE_STEAM_POSITIVE_REVIEWS)

        except Exception as e:
            print(f"Could not fetch IGDB popularity data: {e}")

    # Fallback: use total_rating if no popularity data
    if not popular_games:
        popularity_source = "rating"
        popular_games = [dict(g) for g in library_games if g["total_rating"]]

    # Limit to top games for display
    featured_games = popular_games[:20] if popular_games else []

    # Get some category breakdowns
    # Highly rated games (90+)
    cursor.execute(
        """SELECT id, name, store, igdb_id, igdb_cover_url, cover_image,
                  igdb_summary, description, igdb_screenshots, total_rating,
                  igdb_rating, aggregated_rating, genres, playtime_hours
           FROM games
           WHERE igdb_id IS NOT NULL AND total_rating >= 90""" + EXCLUDE_HIDDEN_FILTER + """
           ORDER BY total_rating DESC
           LIMIT 10"""
    )
    highly_rated = [dict(g) for g in cursor.fetchall()]

    # Hidden gems (good ratings but less known - lower rating count approximated by using aggregated_rating)
    cursor.execute(
        """SELECT id, name, store, igdb_id, igdb_cover_url, cover_image,
                  igdb_summary, description, igdb_screenshots, total_rating,
                  igdb_rating, aggregated_rating, genres, playtime_hours
           FROM games
           WHERE igdb_id IS NOT NULL
             AND total_rating >= 75
             AND total_rating < 90
             AND aggregated_rating IS NULL""" + EXCLUDE_HIDDEN_FILTER + """
           ORDER BY igdb_rating DESC NULLS LAST
           LIMIT 10"""
    )
    hidden_gems = [dict(g) for g in cursor.fetchall()]

    # Most played (from Steam playtime)
    cursor.execute(
        """SELECT id, name, store, igdb_id, igdb_cover_url, cover_image,
                  igdb_summary, description, igdb_screenshots, total_rating,
                  igdb_rating, aggregated_rating, genres, playtime_hours
           FROM games
           WHERE igdb_id IS NOT NULL AND playtime_hours > 0""" + EXCLUDE_HIDDEN_FILTER + """
           ORDER BY playtime_hours DESC
           LIMIT 10"""
    )
    most_played = [dict(g) for g in cursor.fetchall()]

    # Critic favorites (high aggregated rating)
    cursor.execute(
        """SELECT id, name, store, igdb_id, igdb_cover_url, cover_image,
                  igdb_summary, description, igdb_screenshots, total_rating,
                  igdb_rating, aggregated_rating, genres, playtime_hours
           FROM games
           WHERE igdb_id IS NOT NULL AND aggregated_rating >= 80""" + EXCLUDE_HIDDEN_FILTER + """
           ORDER BY aggregated_rating DESC
           LIMIT 10"""
    )
    critic_favorites = [dict(g) for g in cursor.fetchall()]

    # Random picks (10 random games with IGDB data)
    cursor.execute(
        """SELECT id, name, store, igdb_id, igdb_cover_url, cover_image,
                  igdb_summary, description, igdb_screenshots, total_rating,
                  igdb_rating, aggregated_rating, genres, playtime_hours
           FROM games
           WHERE igdb_id IS NOT NULL""" + EXCLUDE_HIDDEN_FILTER + """
           ORDER BY RANDOM()
           LIMIT 10"""
    )
    random_picks = [dict(g) for g in cursor.fetchall()]

    conn.close()

    return render_template(
        "discover.html",
        featured_games=featured_games,
        highly_rated=highly_rated,
        hidden_gems=hidden_gems,
        most_played=most_played,
        critic_favorites=critic_favorites,
        random_picks=random_picks,
        popularity_source=popularity_source,
        igdb_visits=igdb_visits,
        want_to_play=want_to_play,
        playing=playing,
        played=played,
        steam_peak_24h=steam_peak_24h,
        steam_positive_reviews=steam_positive_reviews,
        parse_json=parse_json_field
    )


@app.route("/settings")
def settings_page():
    """Settings page for configuring API credentials."""
    settings = {
        "steam_id": get_setting(STEAM_ID, ""),
        "steam_api_key": get_setting(STEAM_API_KEY, ""),
        "igdb_client_id": get_setting(IGDB_CLIENT_ID, ""),
        "igdb_client_secret": get_setting(IGDB_CLIENT_SECRET, ""),
        "itch_api_key": get_setting(ITCH_API_KEY, ""),
        "humble_session_cookie": get_setting(HUMBLE_SESSION_COOKIE, ""),
        "gog_db_path": get_setting(GOG_DB_PATH, ""),
    }
    success = request.args.get("success") == "1"

    # Get hidden count
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM games WHERE hidden = 1")
    hidden_count = cursor.fetchone()[0]
    conn.close()

    return render_template("settings.html", settings=settings, success=success, hidden_count=hidden_count)


@app.route("/settings", methods=["POST"])
def save_settings():
    """Save settings from the form."""
    # Get form values and save them
    set_setting(STEAM_ID, request.form.get("steam_id", "").strip())
    set_setting(STEAM_API_KEY, request.form.get("steam_api_key", "").strip())
    set_setting(IGDB_CLIENT_ID, request.form.get("igdb_client_id", "").strip())
    set_setting(IGDB_CLIENT_SECRET, request.form.get("igdb_client_secret", "").strip())
    set_setting(ITCH_API_KEY, request.form.get("itch_api_key", "").strip())
    set_setting(HUMBLE_SESSION_COOKIE, request.form.get("humble_session_cookie", "").strip())
    set_setting(GOG_DB_PATH, request.form.get("gog_db_path", "").strip())

    return redirect(url_for("settings_page", success=1))


@app.route("/api/sync/store/<store>", methods=["POST"])
def sync_store(store):
    """Sync games from a specific store or all stores."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        # Ensure database tables exist
        create_database()
        conn = sqlite3.connect(DATABASE_PATH)

        results = {}

        if store == "steam" or store == "all":
            results["steam"] = import_steam_games(conn)

        if store == "epic" or store == "all":
            results["epic"] = import_epic_games(conn)

        if store == "gog" or store == "all":
            results["gog"] = import_gog_games(conn)

        if store == "itch" or store == "all":
            results["itch"] = import_itch_games(conn)

        if store == "humble" or store == "all":
            results["humble"] = import_humble_games(conn)

        conn.close()

        if store == "all":
            total = sum(results.values())
            message = f"Synced {total} games: " + ", ".join(
                f"{s.capitalize()}: {c}" for s, c in results.items()
            )
        else:
            count = results.get(store, 0)
            message = f"Synced {count} games from {store.capitalize()}"

        return jsonify({"success": True, "message": message, "results": results})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/epic/status", methods=["GET"])
def epic_auth_status():
    """Check Epic Games authentication status via Legendary."""
    try:
        if not is_legendary_installed():
            return jsonify({
                "success": True,
                "installed": False,
                "authenticated": False,
                "message": "Legendary CLI is not installed"
            })

        is_auth, username, error = check_authentication()

        if error == "corrective_action":
            return jsonify({
                "success": True,
                "installed": True,
                "authenticated": False,
                "needs_reauth": True,
                "message": "Epic requires you to accept updated terms. Please re-authenticate."
            })

        return jsonify({
            "success": True,
            "installed": True,
            "authenticated": is_auth,
            "username": username,
            "message": f"Logged in as {username}" if is_auth else "Not authenticated"
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/epic/auth", methods=["POST"])
def epic_authenticate():
    """Authenticate with Epic Games using an authorization code."""
    try:
        if not is_legendary_installed():
            return jsonify({
                "success": False,
                "error": "Legendary CLI is not installed. Please install it first."
            }), 400

        data = request.get_json() or {}
        auth_code = data.get("code", "").strip()

        if not auth_code:
            return jsonify({
                "success": False,
                "error": "Authorization code is required"
            }), 400

        # Run legendary auth with the provided code
        result = subprocess.run(
            ["legendary", "auth", "--code", auth_code],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            # Verify authentication succeeded
            is_auth, username, _ = check_authentication()
            if is_auth:
                return jsonify({
                    "success": True,
                    "message": f"Successfully authenticated as {username}",
                    "username": username
                })
            else:
                return jsonify({
                    "success": False,
                    "error": "Authentication appeared to succeed but verification failed"
                }), 500
        else:
            error_msg = result.stderr.strip() if result.stderr else "Authentication failed"
            return jsonify({
                "success": False,
                "error": error_msg
            }), 400

    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "error": "Authentication timed out"
        }), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sync/igdb/<mode>", methods=["POST"])
def sync_igdb(mode):
    """Sync IGDB metadata for games."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)

        # Ensure IGDB columns exist
        add_igdb_columns(conn)

        # Initialize client
        client = IGDBClient()

        # Sync games (force=True for 'all' mode)
        force = (mode == "all")
        matched, failed = igdb_sync_games(conn, client, force=force)

        conn.close()

        message = f"IGDB sync complete: {matched} matched, {failed} failed/no match"
        return jsonify({"success": True, "message": message, "matched": matched, "failed": failed})

    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Collections Feature
# ============================================================================

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


# Ensure collections tables exist on startup
ensure_collections_tables()


@app.route("/collections")
def collections_page():
    """Collections listing page."""
    conn = get_db()
    cursor = conn.cursor()

    # Get all collections with game count and cover thumbnails
    cursor.execute("""
        SELECT
            c.id,
            c.name,
            c.description,
            c.created_at,
            COUNT(cg.game_id) as game_count
        FROM collections c
        LEFT JOIN collection_games cg ON c.id = cg.collection_id
        GROUP BY c.id
        ORDER BY c.updated_at DESC
    """)
    collections = cursor.fetchall()

    # Get cover images for each collection (up to 4 games)
    collections_with_covers = []
    for collection in collections:
        collection_dict = dict(collection)
        cursor.execute("""
            SELECT g.igdb_cover_url, g.cover_image
            FROM collection_games cg
            JOIN games g ON cg.game_id = g.id
            WHERE cg.collection_id = ?
            ORDER BY cg.added_at DESC
            LIMIT 4
        """, (collection_dict["id"],))
        covers = []
        for row in cursor.fetchall():
            cover = row["igdb_cover_url"] or row["cover_image"]
            if cover:
                covers.append(cover)
        collection_dict["covers"] = covers
        collections_with_covers.append(collection_dict)

    conn.close()

    return render_template(
        "collections.html",
        collections=collections_with_covers
    )


@app.route("/collection/<int:collection_id>")
def collection_detail(collection_id):
    """View a single collection with its games."""
    conn = get_db()
    cursor = conn.cursor()

    # Get collection info
    cursor.execute("SELECT * FROM collections WHERE id = ?", (collection_id,))
    collection = cursor.fetchone()

    if not collection:
        conn.close()
        return "Collection not found", 404

    # Get games in collection
    cursor.execute("""
        SELECT g.*, cg.added_at as collection_added_at
        FROM collection_games cg
        JOIN games g ON cg.game_id = g.id
        WHERE cg.collection_id = ?
        ORDER BY cg.added_at DESC
    """, (collection_id,))
    games = cursor.fetchall()

    # Group games by IGDB ID (like the library page)
    grouped_games = group_games_by_igdb(games)

    conn.close()

    return render_template(
        "collection_detail.html",
        collection=dict(collection),
        games=grouped_games,
        parse_json=parse_json_field
    )


@app.route("/api/collections", methods=["GET"])
def api_get_collections():
    """Get all collections."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT c.id, c.name, c.description, COUNT(cg.game_id) as game_count
        FROM collections c
        LEFT JOIN collection_games cg ON c.id = cg.collection_id
        GROUP BY c.id
        ORDER BY c.name
    """)
    collections = [dict(c) for c in cursor.fetchall()]

    conn.close()
    return jsonify(collections)


@app.route("/api/collections", methods=["POST"])
def api_create_collection():
    """Create a new collection."""
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "name is required"}), 400

    name = data.get("name").strip()
    description = data.get("description", "").strip() or None

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO collections (name, description) VALUES (?, ?)",
        (name, description)
    )
    collection_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "id": collection_id,
        "name": name,
        "description": description
    })


@app.route("/api/collections/<int:collection_id>", methods=["DELETE"])
def api_delete_collection(collection_id):
    """Delete a collection."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
    if cursor.rowcount == 0:
        conn.close()
        return jsonify({"error": "Collection not found"}), 404

    conn.commit()
    conn.close()

    return jsonify({"success": True})


@app.route("/api/collections/<int:collection_id>", methods=["PUT"])
def api_update_collection(collection_id):
    """Update a collection's name and description."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    conn = get_db()
    cursor = conn.cursor()

    # Check if collection exists
    cursor.execute("SELECT id FROM collections WHERE id = ?", (collection_id,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "Collection not found"}), 404

    # Build update query
    updates = []
    params = []

    if "name" in data:
        updates.append("name = ?")
        params.append(data["name"].strip())

    if "description" in data:
        updates.append("description = ?")
        params.append(data["description"].strip() or None)

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(collection_id)
        cursor.execute(
            f"UPDATE collections SET {', '.join(updates)} WHERE id = ?",
            params
        )
        conn.commit()

    conn.close()
    return jsonify({"success": True})


@app.route("/api/collections/<int:collection_id>/games", methods=["POST"])
def api_add_game_to_collection(collection_id):
    """Add a game to a collection."""
    data = request.get_json()
    if not data or "game_id" not in data:
        return jsonify({"error": "game_id is required"}), 400

    game_id = data.get("game_id")

    conn = get_db()
    cursor = conn.cursor()

    # Check if collection exists
    cursor.execute("SELECT id FROM collections WHERE id = ?", (collection_id,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "Collection not found"}), 404

    # Check if game exists
    cursor.execute("SELECT id FROM games WHERE id = ?", (game_id,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "Game not found"}), 404

    # Try to add (ignore if already exists)
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO collection_games (collection_id, game_id) VALUES (?, ?)",
            (collection_id, game_id)
        )
        # Update collection's updated_at
        cursor.execute(
            "UPDATE collections SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (collection_id,)
        )
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500

    conn.close()
    return jsonify({"success": True})


@app.route("/api/collections/<int:collection_id>/games/<int:game_id>", methods=["DELETE"])
def api_remove_game_from_collection(collection_id, game_id):
    """Remove a game from a collection."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM collection_games WHERE collection_id = ? AND game_id = ?",
        (collection_id, game_id)
    )

    if cursor.rowcount == 0:
        conn.close()
        return jsonify({"error": "Game not in collection"}), 404

    # Update collection's updated_at
    cursor.execute(
        "UPDATE collections SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (collection_id,)
    )
    conn.commit()
    conn.close()

    return jsonify({"success": True})


@app.route("/api/game/<int:game_id>/collections", methods=["GET"])
def api_get_game_collections(game_id):
    """Get all collections a game belongs to."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT c.id, c.name
        FROM collections c
        JOIN collection_games cg ON c.id = cg.collection_id
        WHERE cg.game_id = ?
        ORDER BY c.name
    """, (game_id,))

    collections = [dict(c) for c in cursor.fetchall()]
    conn.close()

    return jsonify(collections)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("DEBUG", "true").lower() == "true"
    app.run(host="0.0.0.0", debug=debug, port=port)
