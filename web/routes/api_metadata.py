# routes/api_metadata.py
# API endpoints for game metadata operations (IGDB, hidden, NSFW, etc.)

import json
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..dependencies import get_db

router = APIRouter(tags=["Metadata"])


class UpdateIgdbRequest(BaseModel):
    igdb_id: Optional[int] = None


class UpdateHiddenRequest(BaseModel):
    hidden: bool


class UpdateNsfwRequest(BaseModel):
    nsfw: bool


class UpdateCoverOverrideRequest(BaseModel):
    cover_url_override: Optional[str] = None


class UpdateMetacriticRequest(BaseModel):
    metacritic_slug: Optional[str] = None


class BulkGameIdsRequest(BaseModel):
    game_ids: list[int]


@router.post("/api/game/{game_id}/igdb")
def update_igdb(game_id: int, body: UpdateIgdbRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Update IGDB ID for a game."""
    # Import here to avoid circular imports
    from ..services.igdb_sync import (
        IGDBClient, extract_genres_and_themes, merge_and_dedupe_genres
    )

    igdb_id = body.igdb_id

    # Allow clearing the IGDB ID
    if igdb_id is None:
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
        return {"success": True, "message": "IGDB data cleared"}

    # Fetch data from IGDB
    try:
        client = IGDBClient()
        igdb_game = client.get_game_by_id(igdb_id)

        if not igdb_game:
            raise HTTPException(status_code=404, detail=f"No game found with IGDB ID {igdb_id}")

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

        return {
            "success": True,
            "message": f"Synced with IGDB: {igdb_game.get('name')}",
            "igdb_name": igdb_game.get("name"),
            "igdb_id": igdb_game.get("id")
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch from IGDB: {str(e)}")


@router.post("/api/game/{game_id}/hidden")
def update_hidden(game_id: int, body: UpdateHiddenRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Toggle hidden status for a game."""
    hidden = 1 if body.hidden else 0

    cursor = conn.cursor()
    cursor.execute("UPDATE games SET hidden = ? WHERE id = ?", (hidden, game_id))
    conn.commit()

    return {"success": True, "hidden": bool(hidden)}


@router.post("/api/game/{game_id}/nsfw")
def update_nsfw(game_id: int, body: UpdateNsfwRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Toggle NSFW status for a game."""
    nsfw = 1 if body.nsfw else 0

    cursor = conn.cursor()
    cursor.execute("UPDATE games SET nsfw = ? WHERE id = ?", (nsfw, game_id))
    conn.commit()

    return {"success": True, "nsfw": bool(nsfw)}


@router.post("/api/game/{game_id}/cover-override")
def update_cover_override(game_id: int, body: UpdateCoverOverrideRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Update the cover art override URL for a game."""
    cover_url = body.cover_url_override.strip() if body.cover_url_override else None

    cursor = conn.cursor()
    cursor.execute(
        "UPDATE games SET cover_url_override = ? WHERE id = ?", (cover_url, game_id)
    )
    conn.commit()

    return {"success": True, "cover_url_override": cover_url}


@router.post("/api/game/{game_id}/metacritic")
def update_metacritic(game_id: int, body: UpdateMetacriticRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Set custom Metacritic slug and fetch data."""
    # Import here to avoid circular imports
    from ..services.metacritic_sync import MetacriticClient, add_metacritic_columns

    # Ensure columns exist
    add_metacritic_columns(conn)

    metacritic_slug = body.metacritic_slug

    # Allow clearing the Metacritic data
    if not metacritic_slug:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE games SET
                metacritic_score = NULL,
                metacritic_user_score = NULL,
                metacritic_url = NULL,
                metacritic_slug = NULL,
                metacritic_matched_at = NULL
            WHERE id = ?""",
            (game_id,),
        )
        conn.commit()
        return {"success": True, "message": "Metacritic data cleared"}

    # Fetch data from Metacritic
    try:
        client = MetacriticClient()
        mc_game = client.get_game_by_slug(metacritic_slug)

        if not mc_game:
            raise HTTPException(status_code=404, detail=f"No game found with Metacritic slug '{metacritic_slug}'")

        # Update the database
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE games SET
                metacritic_score = ?,
                metacritic_user_score = ?,
                metacritic_url = ?,
                metacritic_slug = ?,
                metacritic_matched_at = CURRENT_TIMESTAMP
            WHERE id = ?""",
            (
                mc_game.get("critic_score"),
                mc_game.get("user_score"),
                mc_game.get("url"),
                mc_game.get("slug"),
                game_id,
            ),
        )
        conn.commit()

        score_info = []
        if mc_game.get("critic_score"):
            score_info.append(f"Critic: {mc_game['critic_score']}")
        if mc_game.get("user_score"):
            score_info.append(f"User: {mc_game['user_score']}")

        message = f"Synced with Metacritic"
        if score_info:
            message += f" ({', '.join(score_info)})"

        return {
            "success": True,
            "message": message,
            "metacritic_name": mc_game.get("name"),
            "metacritic_slug": mc_game.get("slug"),
            "critic_score": mc_game.get("critic_score"),
            "user_score": mc_game.get("user_score"),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch from Metacritic: {str(e)}")


@router.post("/api/games/bulk/hide")
def bulk_hide_games(body: BulkGameIdsRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Hide multiple games at once."""
    game_ids = body.game_ids
    if not game_ids:
        raise HTTPException(status_code=400, detail="No games selected")

    cursor = conn.cursor()

    placeholders = ",".join("?" * len(game_ids))
    cursor.execute(f"UPDATE games SET hidden = 1 WHERE id IN ({placeholders})", game_ids)
    updated = cursor.rowcount

    conn.commit()

    return {"success": True, "updated": updated}


@router.post("/api/games/bulk/nsfw")
def bulk_nsfw_games(body: BulkGameIdsRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Mark multiple games as NSFW at once."""
    game_ids = body.game_ids
    if not game_ids:
        raise HTTPException(status_code=400, detail="No games selected")

    cursor = conn.cursor()

    placeholders = ",".join("?" * len(game_ids))
    cursor.execute(f"UPDATE games SET nsfw = 1 WHERE id IN ({placeholders})", game_ids)
    updated = cursor.rowcount

    conn.commit()

    return {"success": True, "updated": updated}
