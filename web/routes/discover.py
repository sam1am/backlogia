# routes/discover.py
# Discover page routes

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..dependencies import get_db
from ..utils.filters import EXCLUDE_HIDDEN_FILTER
from ..utils.helpers import parse_json_field

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/discover", response_class=HTMLResponse)
def discover(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Discover page - showcase popular games from your library."""
    # Import here to avoid circular imports
    from ..services.igdb_sync import (
        IGDBClient,
        POPULARITY_TYPE_IGDB_VISITS, POPULARITY_TYPE_IGDB_WANT_TO_PLAY,
        POPULARITY_TYPE_IGDB_PLAYING, POPULARITY_TYPE_IGDB_PLAYED,
        POPULARITY_TYPE_STEAM_PEAK_24H, POPULARITY_TYPE_STEAM_POSITIVE_REVIEWS
    )

    cursor = conn.cursor()

    # Get all games with IGDB IDs from the library (excluding hidden/duplicates)
    cursor.execute(
        """SELECT id, name, store, igdb_id, igdb_cover_url, cover_image,
                  igdb_summary, description, igdb_screenshots, total_rating,
                  igdb_rating, aggregated_rating, genres, playtime_hours
           FROM games
           WHERE igdb_id IS NOT NULL AND igdb_id > 0""" + EXCLUDE_HIDDEN_FILTER + """
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
           WHERE igdb_id IS NOT NULL AND igdb_id > 0 AND total_rating >= 90""" + EXCLUDE_HIDDEN_FILTER + """
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
           WHERE igdb_id IS NOT NULL AND igdb_id > 0
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
           WHERE igdb_id IS NOT NULL AND igdb_id > 0 AND playtime_hours > 0""" + EXCLUDE_HIDDEN_FILTER + """
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
           WHERE igdb_id IS NOT NULL AND igdb_id > 0 AND aggregated_rating >= 80""" + EXCLUDE_HIDDEN_FILTER + """
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
           WHERE igdb_id IS NOT NULL AND igdb_id > 0""" + EXCLUDE_HIDDEN_FILTER + """
           ORDER BY RANDOM()
           LIMIT 10"""
    )
    random_picks = [dict(g) for g in cursor.fetchall()]

    return templates.TemplateResponse(
        "discover.html",
        {
            "request": request,
            "featured_games": featured_games,
            "highly_rated": highly_rated,
            "hidden_gems": hidden_gems,
            "most_played": most_played,
            "critic_favorites": critic_favorites,
            "random_picks": random_picks,
            "popularity_source": popularity_source,
            "igdb_visits": igdb_visits,
            "want_to_play": want_to_play,
            "playing": playing,
            "played": played,
            "steam_peak_24h": steam_peak_24h,
            "steam_positive_reviews": steam_positive_reviews,
            "parse_json": parse_json_field
        }
    )
