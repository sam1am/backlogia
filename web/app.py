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
from igdb_sync import IGDBClient

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


@app.route("/")
def index():
    """Main page - list all games."""
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

    # Get store counts for filters (exclude duplicates and hidden)
    cursor.execute("SELECT store, COUNT(*) FROM games WHERE 1=1" + EXCLUDE_HIDDEN_FILTER + " GROUP BY store")
    store_counts = dict(cursor.fetchall())

    cursor.execute("SELECT COUNT(*) FROM games WHERE 1=1" + EXCLUDE_HIDDEN_FILTER)
    total_count = cursor.fetchone()[0]

    # Get hidden count
    cursor.execute("SELECT COUNT(*) FROM games WHERE hidden = 1")
    hidden_count = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "index.html",
        games=games,
        store_counts=store_counts,
        total_count=total_count,
        hidden_count=hidden_count,
        current_store=store_filter,
        current_search=search,
        current_sort=sort_by,
        current_order=sort_order,
        parse_json=parse_json_field
    )


@app.route("/game/<int:game_id>")
def game_detail(game_id):
    """Game detail page."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
    game = cursor.fetchone()

    conn.close()

    if not game:
        return "Game not found", 404

    return render_template(
        "game_detail.html",
        game=game,
        parse_json=parse_json_field
    )


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
    return render_template("settings.html", settings=settings, success=success)


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


if __name__ == "__main__":
    app.run(debug=True, port=5050)
