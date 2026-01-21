# app.py
# Web interface for the game library

import sys
from flask import Flask, render_template, request, jsonify, redirect, url_for
import sqlite3
import json
from pathlib import Path

# Add scripts directory to path for settings module
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from settings import (
    get_setting, set_setting, get_all_settings,
    STEAM_ID, STEAM_API_KEY, IGDB_CLIENT_ID, IGDB_CLIENT_SECRET, ITCH_API_KEY
)
from igdb_sync import IGDBClient, sync_games as igdb_sync_games, add_igdb_columns
from build_database import (
    create_database, import_steam_games, import_epic_games,
    import_gog_games, import_itch_games
)

app = Flask(__name__)

DATABASE_PATH = Path(__file__).parent.parent / "game_library.db"

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
    cursor.execute("PRAGMA table_info(games)")
    columns = {row[1] for row in cursor.fetchall()}
    if "hidden" not in columns:
        cursor.execute("ALTER TABLE games ADD COLUMN hidden BOOLEAN DEFAULT 0")
    if "nsfw" not in columns:
        cursor.execute("ALTER TABLE games ADD COLUMN nsfw BOOLEAN DEFAULT 0")
    conn.commit()
    conn.close()


# Ensure extra columns exist on startup
ensure_extra_columns()


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
    store_filter = request.args.get("store", "")
    search = request.args.get("search", "")
    sort_by = request.args.get("sort", "name")
    sort_order = request.args.get("order", "asc")

    # Build query (exclude Amazon Prime/Luna duplicates and hidden games)
    query = "SELECT * FROM games WHERE 1=1" + EXCLUDE_HIDDEN_FILTER
    params = []

    if store_filter:
        query += " AND store = ?"
        params.append(store_filter)

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
    def get_sort_key(g):
        primary = g["primary"]
        val = primary.get(sort_by)
        if val is None:
            return (1, "")  # Put nulls last
        if isinstance(val, str):
            return (0, val.lower())
        return (0, val)

    reverse = sort_order == "desc"
    grouped_games.sort(key=get_sort_key, reverse=reverse)

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

    conn.close()

    return render_template(
        "index.html",
        games=grouped_games,
        store_counts=store_counts,
        total_count=total_count,
        unique_count=unique_count,
        hidden_count=hidden_count,
        current_store=store_filter,
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
                nsfw = ?
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


if __name__ == "__main__":
    app.run(debug=True, port=5050)
