# routes/collections.py
# Collections page and API routes

import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ..dependencies import get_db
from ..utils.helpers import parse_json_field, group_games_by_igdb

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


class CreateCollectionRequest(BaseModel):
    name: str
    description: Optional[str] = None


class UpdateCollectionRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class AddGameRequest(BaseModel):
    game_id: int


@router.get("/collections", response_class=HTMLResponse)
def collections_page(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Collections listing page."""
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

    return templates.TemplateResponse(
        request,
        "collections.html",
        {
            "request": request,
            "collections": collections_with_covers
        }
    )


@router.get("/collection/{collection_id}", response_class=HTMLResponse)
def collection_detail(request: Request, collection_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """View a single collection with its games."""
    cursor = conn.cursor()

    # Get collection info
    cursor.execute("SELECT * FROM collections WHERE id = ?", (collection_id,))
    collection = cursor.fetchone()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

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

    return templates.TemplateResponse(
        request,
        "collection_detail.html",
        {
            "request": request,
            "collection": dict(collection),
            "games": grouped_games,
            "parse_json": parse_json_field
        }
    )


@router.get("/api/collections", tags=["Collections"])
def api_get_collections(conn: sqlite3.Connection = Depends(get_db)):
    """Get all collections."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT c.id, c.name, c.description, COUNT(cg.game_id) as game_count
        FROM collections c
        LEFT JOIN collection_games cg ON c.id = cg.collection_id
        GROUP BY c.id
        ORDER BY c.name
    """)
    collections = [dict(c) for c in cursor.fetchall()]

    return collections


@router.post("/api/collections", tags=["Collections"])
def api_create_collection(body: CreateCollectionRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Create a new collection."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    description = body.description.strip() if body.description else None

    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO collections (name, description) VALUES (?, ?)",
        (name, description)
    )
    collection_id = cursor.lastrowid
    conn.commit()

    return {
        "success": True,
        "id": collection_id,
        "name": name,
        "description": description
    }


@router.delete("/api/collections/{collection_id}", tags=["Collections"])
def api_delete_collection(collection_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """Delete a collection."""
    cursor = conn.cursor()

    cursor.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Collection not found")

    conn.commit()

    return {"success": True}


@router.put("/api/collections/{collection_id}", tags=["Collections"])
def api_update_collection(collection_id: int, body: UpdateCollectionRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Update a collection's name and description."""
    cursor = conn.cursor()

    # Check if collection exists
    cursor.execute("SELECT id FROM collections WHERE id = ?", (collection_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Collection not found")

    # Build update query
    updates = []
    params = []

    if body.name is not None:
        updates.append("name = ?")
        params.append(body.name.strip())

    if body.description is not None:
        updates.append("description = ?")
        params.append(body.description.strip() or None)

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(collection_id)
        cursor.execute(
            f"UPDATE collections SET {', '.join(updates)} WHERE id = ?",
            params
        )
        conn.commit()

    return {"success": True}


@router.post("/api/collections/{collection_id}/games", tags=["Collections"])
def api_add_game_to_collection(collection_id: int, body: AddGameRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Add a game to a collection."""
    game_id = body.game_id

    cursor = conn.cursor()

    # Check if collection exists
    cursor.execute("SELECT id FROM collections WHERE id = ?", (collection_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Collection not found")

    # Check if game exists
    cursor.execute("SELECT id FROM games WHERE id = ?", (game_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Game not found")

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
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True}


@router.delete("/api/collections/{collection_id}/games/{game_id}", tags=["Collections"])
def api_remove_game_from_collection(collection_id: int, game_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """Remove a game from a collection."""
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM collection_games WHERE collection_id = ? AND game_id = ?",
        (collection_id, game_id)
    )

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Game not in collection")

    # Update collection's updated_at
    cursor.execute(
        "UPDATE collections SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (collection_id,)
    )
    conn.commit()

    return {"success": True}


@router.get("/api/game/{game_id}/collections", tags=["Collections"])
def api_get_game_collections(game_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """Get all collections a game belongs to."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT c.id, c.name
        FROM collections c
        JOIN collection_games cg ON c.id = cg.collection_id
        WHERE cg.game_id = ?
        ORDER BY c.name
    """, (game_id,))

    collections = [dict(c) for c in cursor.fetchall()]

    return collections
