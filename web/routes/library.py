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
from ..utils.filters import EXCLUDE_HIDDEN_FILTER, EXCLUDE_DUPLICATES_FILTER, PLAYTIME_LABELS
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
    exclude_streaming: bool = False,
    collection: int = 0,
    protondb_tier: str = "",
    no_igdb: bool = False,
    playtime_label: list[str] = Query(default=[]),
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
        # Filter by genres, preferring genres_override if set
        genre_conditions = []
        for genre in genres:
            genre_conditions.append("LOWER(COALESCE(genres_override, genres)) LIKE ?")
            params.append(f'%"{genre.lower()}"%')
        query += " AND (" + " OR ".join(genre_conditions) + ")"

    if search:
        query += " AND name LIKE ?"
        params.append(f"%{search}%")

    # Collection filter
    if collection:
        query += " AND id IN (SELECT game_id FROM collection_games WHERE collection_id = ?)"
        params.append(collection)

    # ProtonDB tier filter (hierarchy: platinum > gold > silver > bronze)
    protondb_hierarchy = ["platinum", "gold", "silver", "bronze"]
    if protondb_tier and protondb_tier in protondb_hierarchy:
        tier_index = protondb_hierarchy.index(protondb_tier)
        allowed_tiers = protondb_hierarchy[:tier_index + 1]
        placeholders = ",".join("?" * len(allowed_tiers))
        query += f" AND protondb_tier IN ({placeholders})"
        params.extend(allowed_tiers)

    # No IGDB data filter
    if no_igdb:
        query += " AND (igdb_id IS NULL OR igdb_id = 0)"

    # Playtime label filter – supports multiple values; unplayed/tried/played
    # also match games with no explicit label using playtime_hours ranges.
    active_labels = [l for l in playtime_label if l in PLAYTIME_LABELS]
    if active_labels:
        label_conditions: list[str] = []
        for lbl in active_labels:
            if lbl == "unplayed":
                label_conditions.append(
                    "(playtime_label = 'unplayed' OR "
                    "(playtime_label IS NULL AND (playtime_hours IS NULL OR playtime_hours = 0)))"
                )
            elif lbl == "tried":
                label_conditions.append(
                    "(playtime_label = 'tried' OR "
                    "(playtime_label IS NULL AND playtime_hours > 0 AND playtime_hours <= 2))"
                )
            elif lbl == "played":
                label_conditions.append(
                    "(playtime_label = 'played' OR "
                    "(playtime_label IS NULL AND playtime_hours > 2 AND playtime_hours <= 20))"
                )
            elif lbl == "heavily_played":
                label_conditions.append(
                    "(playtime_label = 'heavily_played' OR "
                    "(playtime_label IS NULL AND playtime_hours > 20))"
                )
            else:  # abandoned – explicit label only
                label_conditions.append(f"playtime_label = '{lbl}'")
        query += " AND (" + " OR ".join(label_conditions) + ")"

    # Sorting - detect which columns actually exist in the DB
    cursor.execute("PRAGMA table_info(games)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    valid_sorts = ["name", "store", "playtime_hours", "critics_score", "release_date", "total_rating", "igdb_rating", "aggregated_rating", "average_rating", "metacritic_score", "metacritic_user_score"]
    available_sorts = [s for s in valid_sorts if s in existing_columns]
    if sort not in available_sorts:
        sort = "name"
    if sort in available_sorts:
        order_dir = "DESC" if order == "desc" else "ASC"
        if sort == "playtime_hours":
            # Respect manual playtime_label when playtime_hours is NULL:
            # COALESCE tries hours first, then falls back to a sentinel derived from the label.
            query += f""" ORDER BY COALESCE(
                playtime_hours,
                CASE playtime_label
                    WHEN 'heavily_played' THEN 1000
                    WHEN 'abandoned'      THEN 50
                    WHEN 'played'         THEN 11
                    WHEN 'tried'          THEN 1
                    WHEN 'unplayed'       THEN 0
                    ELSE NULL
                END
            ) {order_dir} NULLS LAST"""
        elif sort in ["critics_score", "total_rating", "igdb_rating", "aggregated_rating", "average_rating", "metacritic_score", "metacritic_user_score"]:
            query += f" ORDER BY {sort} {order_dir} NULLS LAST"
        else:
            query += f" ORDER BY {sort} COLLATE NOCASE {order_dir}"

    cursor.execute(query, params)
    games = cursor.fetchall()

    # Group games by IGDB ID (combines multi-store ownership)
    grouped_games = group_games_by_igdb(games)

    # Post-grouping filter: exclude streaming-only games
    if exclude_streaming:
        grouped_games = [g for g in grouped_games if not g.get("only_streaming", False)]

    # Sort grouped games by primary game's sort field
    # Separate games with null sort values so nulls are always last
    reverse = order == "desc"

    _PLAYTIME_LABEL_SENTINEL = {
        "heavily_played": 1000,
        "abandoned": 50,
        "played": 11,
        "tried": 1,
        "unplayed": 0,
    }

    def effective_sort_value(game: dict, field: str):
        """Return the value used for sorting, applying label-based fallback for playtime_hours."""
        val = game.get(field)
        if field == "playtime_hours" and val is None:
            label = game.get("playtime_label")
            val = _PLAYTIME_LABEL_SENTINEL.get(label)  # None if no label
        return val

    with_values = []
    without_values = []

    for g in grouped_games:
        val = effective_sort_value(g["primary"], sort)
        if val is None:
            without_values.append(g)
        else:
            with_values.append(g)

    def get_sort_key(g):
        val = effective_sort_value(g["primary"], sort)
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

    # Get removed count
    cursor.execute("SELECT COUNT(*) FROM games WHERE removed = 1")
    removed_count = cursor.fetchone()[0]

    # Get collections for the filter dropdown
    cursor.execute("""
        SELECT c.id, c.name, COUNT(cg.game_id) as game_count
        FROM collections c
        LEFT JOIN collection_games cg ON c.id = cg.collection_id
        GROUP BY c.id
        ORDER BY c.name
    """)
    collections = [{"id": row[0], "name": row[1], "game_count": row[2]} for row in cursor.fetchall()]

    # Get all unique genres with counts, preferring genres_override if set
    cursor.execute("SELECT COALESCE(genres_override, genres) FROM games WHERE COALESCE(genres_override, genres) IS NOT NULL AND COALESCE(genres_override, genres) != '[]'" + EXCLUDE_HIDDEN_FILTER)
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
            "removed_count": removed_count,
            "current_stores": stores,
            "current_genres": genres,
            "current_search": search,
            "current_sort": sort,
            "current_order": order,
            "current_exclude_streaming": exclude_streaming,
            "current_collection": collection,
            "current_protondb_tier": protondb_tier,
            "current_no_igdb": no_igdb,
            "current_playtime_labels": playtime_label,
            "collections": collections,
            "available_sorts": available_sorts,
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


@router.get("/removed", response_class=HTMLResponse)
def removed_games(
    request: Request,
    search: str = "",
    conn: sqlite3.Connection = Depends(get_db)
):
    """Page showing all removed games."""
    cursor = conn.cursor()

    query = "SELECT * FROM games WHERE removed = 1" + EXCLUDE_DUPLICATES_FILTER
    params = []

    if search:
        query += " AND name LIKE ?"
        params.append(f"%{search}%")

    query += " ORDER BY name COLLATE NOCASE ASC"

    cursor.execute(query, params)
    games = cursor.fetchall()

    return templates.TemplateResponse(
        "removed_games.html",
        {
            "request": request,
            "games": games,
            "current_search": search,
            "parse_json": parse_json_field
        }
    )
