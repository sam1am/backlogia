# routes/library.py
# Library, game detail, random game, and hidden games routes

import json
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..dependencies import get_db
from ..utils.filters import EXCLUDE_HIDDEN_FILTER, EXCLUDE_DUPLICATES_FILTER
from ..utils.helpers import parse_json_field, get_store_url, group_games_by_igdb

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/", response_class=RedirectResponse)
def home():
    """Home page - redirect to discover."""
    return RedirectResponse(url="/discover", status_code=302)


@router.get("/library", response_class=HTMLResponse)
def library(
    request: Request,
    stores: list[str] = Query(default=[]),
    genres: list[str] = Query(default=[]),
    search: str = "",
    sort: str = "name",
    order: str = "asc",
    conn: sqlite3.Connection = Depends(get_db)
):
    """Library page - list all games."""
    cursor = conn.cursor()

    # Build query (exclude Amazon Prime/Luna duplicates and hidden games)
    query = "SELECT * FROM games WHERE 1=1" + EXCLUDE_HIDDEN_FILTER
    params = []

    if stores:
        placeholders = ",".join("?" * len(stores))
        query += f" AND store IN ({placeholders})"
        params.extend(stores)

    if genres:
        # Filter by genres (JSON array stored in genres column)
        # Use LIKE with JSON pattern matching for each genre
        genre_conditions = []
        for genre in genres:
            # Match genre in JSON array (case-insensitive)
            genre_conditions.append("LOWER(genres) LIKE ?")
            params.append(f'%"{genre.lower()}"%')
        query += " AND (" + " OR ".join(genre_conditions) + ")"

    if search:
        query += " AND name LIKE ?"
        params.append(f"%{search}%")

    # Sorting
    valid_sorts = ["name", "store", "playtime_hours", "critics_score", "release_date", "total_rating", "igdb_rating", "aggregated_rating", "average_rating", "metacritic_score", "metacritic_user_score"]
    if sort in valid_sorts:
        order_dir = "DESC" if order == "desc" else "ASC"
        if sort in ["playtime_hours", "critics_score", "total_rating", "igdb_rating", "aggregated_rating", "average_rating", "metacritic_score", "metacritic_user_score"]:
            query += f" ORDER BY {sort} {order_dir} NULLS LAST"
        else:
            query += f" ORDER BY {sort} COLLATE NOCASE {order_dir}"

    cursor.execute(query, params)
    games = cursor.fetchall()

    # Group games by IGDB ID (combines multi-store ownership)
    grouped_games = group_games_by_igdb(games)

    # Sort grouped games by primary game's sort field
    # Separate games with null sort values so nulls are always last
    reverse = order == "desc"
    with_values = []
    without_values = []

    for g in grouped_games:
        val = g["primary"].get(sort)
        if val is None:
            without_values.append(g)
        else:
            with_values.append(g)

    def get_sort_key(g):
        val = g["primary"].get(sort)
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

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "games": grouped_games,
            "store_counts": store_counts,
            "genre_counts": genre_counts,
            "total_count": total_count,
            "unique_count": unique_count,
            "hidden_count": hidden_count,
            "current_stores": stores,
            "current_genres": genres,
            "current_search": search,
            "current_sort": sort,
            "current_order": order,
            "parse_json": parse_json_field
        }
    )


@router.get("/game/{game_id}", response_class=HTMLResponse)
def game_detail(request: Request, game_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """Game detail page - shows combined view for games owned on multiple stores."""
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
    game = cursor.fetchone()

    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

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

    return templates.TemplateResponse(
        "game_detail.html",
        {
            "request": request,
            "game": primary_game,
            "store_info": store_info,
            "related_games": related_games,
            "parse_json": parse_json_field,
            "get_store_url": get_store_url
        }
    )


@router.get("/random", response_class=RedirectResponse)
def random_game(conn: sqlite3.Connection = Depends(get_db)):
    """Redirect to a random game detail page."""
    cursor = conn.cursor()

    # Get a random game that isn't hidden
    cursor.execute(
        "SELECT id FROM games WHERE 1=1" + EXCLUDE_HIDDEN_FILTER + " ORDER BY RANDOM() LIMIT 1"
    )
    result = cursor.fetchone()

    if result:
        return RedirectResponse(url=f"/game/{result['id']}", status_code=302)
    else:
        return RedirectResponse(url="/library", status_code=302)


@router.get("/hidden", response_class=HTMLResponse)
def hidden_games(
    request: Request,
    search: str = "",
    conn: sqlite3.Connection = Depends(get_db)
):
    """Page showing all hidden games."""
    cursor = conn.cursor()

    query = "SELECT * FROM games WHERE hidden = 1" + EXCLUDE_DUPLICATES_FILTER
    params = []

    if search:
        query += " AND name LIKE ?"
        params.append(f"%{search}%")

    query += " ORDER BY name COLLATE NOCASE ASC"

    cursor.execute(query, params)
    games = cursor.fetchall()

    return templates.TemplateResponse(
        "hidden_games.html",
        {
            "request": request,
            "games": games,
            "current_search": search,
            "parse_json": parse_json_field
        }
    )
