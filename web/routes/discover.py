# routes/discover.py
# Discover page routes

import hashlib
import random
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..dependencies import get_db
from ..utils.filters import EXCLUDE_HIDDEN_FILTER
from ..utils.helpers import parse_json_field

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

# Module-level IGDB cache
_igdb_cache = {
    "data": None,
    "expires_at": 0,
    "igdb_ids_hash": None
}
CACHE_TTL = 900  # 15 minutes


def _hash_igdb_ids(igdb_ids):
    """Create a stable hash of the igdb_ids set for cache key."""
    return hashlib.md5(
        ",".join(str(i) for i in sorted(set(igdb_ids))).encode()
    ).hexdigest()


def _get_library_games(conn):
    """Get all games with IGDB IDs from the library."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, name, store, igdb_id, igdb_cover_url, cover_image,
                  igdb_summary, description, igdb_screenshots, total_rating,
                  igdb_rating, aggregated_rating, genres, playtime_hours
           FROM games
           WHERE igdb_id IS NOT NULL AND igdb_id > 0""" + EXCLUDE_HIDDEN_FILTER + """
           ORDER BY total_rating DESC NULLS LAST"""
    )
    return cursor.fetchall()


def _build_igdb_mapping(library_games):
    """Build igdb_id -> game data mapping and deduplicated unique games list."""
    igdb_to_local = {}
    igdb_ids = []
    unique_games = []
    seen_igdb_ids = set()

    for game in library_games:
        igdb_id = game["igdb_id"]
        igdb_ids.append(igdb_id)
        igdb_to_local[igdb_id] = dict(game)
        if igdb_id not in seen_igdb_ids:
            seen_igdb_ids.add(igdb_id)
            unique_games.append(dict(game))

    return igdb_to_local, igdb_ids, unique_games


def _derive_db_categories(unique_games):
    """Derive category lists from the already-fetched unique games (no extra SQL)."""
    highly_rated = [g for g in unique_games if (g["total_rating"] or 0) >= 90][:10]

    hidden_gems = [g for g in unique_games
                   if (g["total_rating"] or 0) >= 75
                   and (g["total_rating"] or 0) < 90
                   and g["aggregated_rating"] is None]
    hidden_gems.sort(key=lambda g: g["igdb_rating"] or 0, reverse=True)
    hidden_gems = hidden_gems[:10]

    most_played = [g for g in unique_games if (g["playtime_hours"] or 0) > 0]
    most_played.sort(key=lambda g: g["playtime_hours"] or 0, reverse=True)
    most_played = most_played[:10]

    critic_favorites = [g for g in unique_games if (g["aggregated_rating"] or 0) >= 80]
    critic_favorites.sort(key=lambda g: g["aggregated_rating"] or 0, reverse=True)
    critic_favorites = critic_favorites[:10]

    random_picks = random.sample(unique_games, min(10, len(unique_games)))

    return highly_rated, hidden_gems, most_played, critic_favorites, random_picks


def _empty_igdb_result():
    return {
        "popularity_source": "rating",
        "featured_games": [],
        "igdb_visits": [],
        "want_to_play": [],
        "playing": [],
        "played": [],
        "steam_peak_24h": [],
        "steam_positive_reviews": [],
    }


def _fetch_igdb_sections(igdb_ids, igdb_to_local):
    """Fetch all IGDB popularity data in parallel, using cache if available."""
    from ..services.igdb_sync import (
        IGDBClient,
        POPULARITY_TYPE_IGDB_VISITS, POPULARITY_TYPE_IGDB_WANT_TO_PLAY,
        POPULARITY_TYPE_IGDB_PLAYING, POPULARITY_TYPE_IGDB_PLAYED,
        POPULARITY_TYPE_STEAM_PEAK_24H, POPULARITY_TYPE_STEAM_POSITIVE_REVIEWS
    )

    if not igdb_ids:
        return _empty_igdb_result()

    ids_hash = _hash_igdb_ids(igdb_ids)
    now = time.time()

    # Check cache
    if (_igdb_cache["data"] is not None
            and _igdb_cache["igdb_ids_hash"] == ids_hash
            and now < _igdb_cache["expires_at"]):
        return _igdb_cache["data"]

    # Fetch fresh data with parallelized API calls
    try:
        client = IGDBClient()

        pop_types = {
            "igdb_visits": POPULARITY_TYPE_IGDB_VISITS,
            "want_to_play": POPULARITY_TYPE_IGDB_WANT_TO_PLAY,
            "playing": POPULARITY_TYPE_IGDB_PLAYING,
            "played": POPULARITY_TYPE_IGDB_PLAYED,
            "steam_peak_24h": POPULARITY_TYPE_STEAM_PEAK_24H,
            "steam_positive_reviews": POPULARITY_TYPE_STEAM_POSITIVE_REVIEWS,
        }

        def _resolve_popularity(pop_data):
            """Map IGDB popularity response to local game data."""
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

        results = {}

        with ThreadPoolExecutor(max_workers=7) as executor:
            # Submit all 7 IGDB calls in parallel
            future_popular = executor.submit(
                client.get_popular_games, igdb_ids, None, 100
            )
            futures_by_key = {
                executor.submit(
                    client.get_popular_games, igdb_ids, pop_type, 10
                ): key
                for key, pop_type in pop_types.items()
            }

            # Collect general popularity result
            popularity_data = future_popular.result()
            popular_games = _resolve_popularity(popularity_data)
            popularity_source = "igdb_popularity" if popular_games else "rating"

            # Collect typed results
            for future, key in futures_by_key.items():
                results[key] = _resolve_popularity(future.result())

        featured_games = popular_games[:20] if popular_games else []

        result = {
            "popularity_source": popularity_source,
            "featured_games": featured_games,
            "igdb_visits": results.get("igdb_visits", []),
            "want_to_play": results.get("want_to_play", []),
            "playing": results.get("playing", []),
            "played": results.get("played", []),
            "steam_peak_24h": results.get("steam_peak_24h", []),
            "steam_positive_reviews": results.get("steam_positive_reviews", []),
        }

        # Update cache
        _igdb_cache["data"] = result
        _igdb_cache["expires_at"] = now + CACHE_TTL
        _igdb_cache["igdb_ids_hash"] = ids_hash

        return result

    except Exception as e:
        print(f"Could not fetch IGDB popularity data: {e}")
        return _empty_igdb_result()


def _game_to_json(game):
    """Convert a game dict to a JSON-safe dict with parsed JSON fields."""
    return {
        "id": game["id"],
        "name": game["name"],
        "store": game.get("store", ""),
        "igdb_cover_url": game.get("igdb_cover_url") or "",
        "cover_image": game.get("cover_image") or "",
        "igdb_summary": game.get("igdb_summary") or "",
        "description": game.get("description") or "",
        "igdb_screenshots": parse_json_field(game.get("igdb_screenshots")),
        "genres": parse_json_field(game.get("genres")),
        "total_rating": game.get("total_rating"),
        "igdb_rating": game.get("igdb_rating"),
        "aggregated_rating": game.get("aggregated_rating"),
        "playtime_hours": game.get("playtime_hours"),
    }


@router.get("/discover", response_class=HTMLResponse)
def discover(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Discover page - renders immediately with DB data, IGDB sections load via AJAX."""
    library_games = _get_library_games(conn)
    igdb_to_local, igdb_ids, unique_games = _build_igdb_mapping(library_games)

    highly_rated, hidden_gems, most_played, critic_favorites, random_picks = (
        _derive_db_categories(unique_games)
    )

    has_igdb_ids = bool(igdb_ids)

    return templates.TemplateResponse(
        request,
        "discover.html",
        {
            "highly_rated": highly_rated,
            "hidden_gems": hidden_gems,
            "most_played": most_played,
            "critic_favorites": critic_favorites,
            "random_picks": random_picks,
            "has_igdb_ids": has_igdb_ids,
            "parse_json": parse_json_field,
        }
    )


@router.get("/api/discover/igdb-sections")
def discover_igdb_sections(conn: sqlite3.Connection = Depends(get_db)):
    """API endpoint returning IGDB popularity sections as JSON."""
    library_games = _get_library_games(conn)
    igdb_to_local, igdb_ids, unique_games = _build_igdb_mapping(library_games)

    igdb_data = _fetch_igdb_sections(igdb_ids, igdb_to_local)

    # If no IGDB popularity data, use rating-based fallback
    if not igdb_data["featured_games"] and unique_games:
        igdb_data["popularity_source"] = "rating"
        igdb_data["featured_games"] = [
            g for g in unique_games if g["total_rating"]
        ][:20]

    return JSONResponse(content={
        "popularity_source": igdb_data["popularity_source"],
        "featured_games": [_game_to_json(g) for g in igdb_data["featured_games"]],
        "igdb_visits": [_game_to_json(g) for g in igdb_data["igdb_visits"]],
        "want_to_play": [_game_to_json(g) for g in igdb_data["want_to_play"]],
        "playing": [_game_to_json(g) for g in igdb_data["playing"]],
        "played": [_game_to_json(g) for g in igdb_data["played"]],
        "steam_peak_24h": [_game_to_json(g) for g in igdb_data["steam_peak_24h"]],
        "steam_positive_reviews": [_game_to_json(g) for g in igdb_data["steam_positive_reviews"]],
    })
