# routes/api_games.py
# API endpoints for games data

import json
import sqlite3

from fastapi import APIRouter, Depends

from ..dependencies import get_db
from ..utils.filters import EXCLUDE_DUPLICATES_FILTER, EXCLUDE_HIDDEN_FILTER

router = APIRouter(tags=["Games"])


@router.get("/api/games")
def api_games(conn: sqlite3.Connection = Depends(get_db)):
    """Get all games in the library."""
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM games WHERE 1=1" + EXCLUDE_DUPLICATES_FILTER + " ORDER BY name")
    games = cursor.fetchall()

    return [dict(g) for g in games]


@router.get("/api/stats")
def api_stats(conn: sqlite3.Connection = Depends(get_db)):
    """Get library statistics."""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM games WHERE 1=1" + EXCLUDE_DUPLICATES_FILTER)
    total = cursor.fetchone()[0]

    cursor.execute("SELECT store, COUNT(*) FROM games WHERE 1=1" + EXCLUDE_DUPLICATES_FILTER + " GROUP BY store")
    by_store = dict(cursor.fetchall())

    cursor.execute("SELECT SUM(playtime_hours) FROM games WHERE playtime_hours IS NOT NULL" + EXCLUDE_DUPLICATES_FILTER)
    total_playtime = cursor.fetchone()[0] or 0

    return {
        "total_games": total,
        "by_store": by_store,
        "total_playtime_hours": round(total_playtime, 1)
    }


@router.get("/api/genres")
def api_genres(conn: sqlite3.Connection = Depends(get_db)):
    """Get all distinct genres present in the library.

    Merges genres from the store-provided ``genres`` column and from the
    user-defined ``genres_override`` column, returning a sorted, de-duplicated
    list of genre names.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT genres, genres_override FROM games WHERE 1=1" + EXCLUDE_HIDDEN_FILTER
    )
    rows = cursor.fetchall()

    genres_set: set[str] = set()
    for row in rows:
        for field in (row[0], row[1]):
            if not field:
                continue
            try:
                items = json.loads(field)
                if isinstance(items, list):
                    genres_set.update(str(g).strip() for g in items if g)
            except (json.JSONDecodeError, TypeError):
                pass

    return sorted(genres_set)
