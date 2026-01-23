# routes/sync.py
# Store sync and IGDB sync routes

import json
import re
import sqlite3
from datetime import datetime
from enum import Enum
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import DATABASE_PATH

router = APIRouter(tags=["Sync"])


class StoreType(str, Enum):
    steam = "steam"
    epic = "epic"
    gog = "gog"
    itch = "itch"
    humble = "humble"
    battlenet = "battlenet"
    amazon = "amazon"
    ea = "ea"
    ubisoft = "ubisoft"
    local = "local"
    all = "all"


@router.post("/api/sync/store/{store}")
def sync_store(store: StoreType):
    """Sync games from a store."""
    # Import here to avoid circular imports
    from ..services.database_builder import (
        create_database, import_steam_games, import_epic_games,
        import_gog_games, import_itch_games, import_humble_games,
        import_battlenet_games, import_amazon_games, import_ea_games,
        import_local_games
    )

    try:
        conn = sqlite3.connect(DATABASE_PATH)
        # Ensure database tables exist
        create_database()
        conn = sqlite3.connect(DATABASE_PATH)

        results = {}

        if store == StoreType.steam or store == StoreType.all:
            results["steam"] = import_steam_games(conn)

        if store == StoreType.epic or store == StoreType.all:
            results["epic"] = import_epic_games(conn)

        if store == StoreType.gog or store == StoreType.all:
            results["gog"] = import_gog_games(conn)

        if store == StoreType.itch or store == StoreType.all:
            results["itch"] = import_itch_games(conn)

        if store == StoreType.humble or store == StoreType.all:
            results["humble"] = import_humble_games(conn)

        if store == StoreType.battlenet or store == StoreType.all:
            results["battlenet"] = import_battlenet_games(conn)

        if store == StoreType.amazon or store == StoreType.all:
            results["amazon"] = import_amazon_games(conn)

        if store == StoreType.ea or store == StoreType.all:
            results["ea"] = import_ea_games(conn)

        if store == StoreType.local or store == StoreType.all:
            results["local"] = import_local_games(conn)

        conn.close()

        if store == StoreType.all:
            total = sum(results.values())
            message = f"Synced {total} games: " + ", ".join(
                f"{s.capitalize()}: {c}" for s, c in results.items()
            )
        else:
            count = results.get(store.value, 0)
            message = f"Synced {count} games from {store.value.capitalize()}"

        return {"success": True, "message": message, "results": results}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/sync/igdb/{mode}")
def sync_igdb(mode: str):
    """Sync IGDB metadata. Mode can be 'new'/'missing' (unmatched only) or 'all' (resync everything)."""
    # Import here to avoid circular imports
    from ..services.igdb_sync import IGDBClient, sync_games as igdb_sync_games, add_igdb_columns

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
        return {"success": True, "message": message, "matched": matched, "failed": failed}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/sync/metacritic/{mode}")
def sync_metacritic(mode: str):
    """Sync Metacritic scores. Mode can be 'missing' (unmatched only) or 'all' (resync everything)."""
    # Import here to avoid circular imports
    from ..services.metacritic_sync import (
        MetacriticClient, sync_games as metacritic_sync_games, add_metacritic_columns
    )

    try:
        conn = sqlite3.connect(DATABASE_PATH)

        # Ensure Metacritic columns exist
        add_metacritic_columns(conn)

        # Initialize client
        client = MetacriticClient()

        # Sync games (force=True for 'all' mode)
        force = (mode == "all")
        matched, failed = metacritic_sync_games(conn, client, force=force)

        conn.close()

        message = f"Metacritic sync complete: {matched} matched, {failed} failed/no match"
        return {"success": True, "message": message, "matched": matched, "failed": failed}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class UbisoftGame(BaseModel):
    title: str
    playtime: Optional[str] = None
    lastPlayed: Optional[str] = None
    platform: Optional[str] = None


class UbisoftImportRequest(BaseModel):
    games: List[UbisoftGame]


class GOGGame(BaseModel):
    id: str
    title: str
    profileUrl: Optional[str] = None
    storeUrl: Optional[str] = None


class GOGImportRequest(BaseModel):
    games: List[GOGGame]


@router.post("/api/import/ubisoft")
def import_ubisoft_games(request: UbisoftImportRequest):
    """Import games scraped from Ubisoft account page."""
    from ..services.database_builder import create_database

    try:
        # Ensure database exists
        create_database()
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        count = 0
        for game in request.games:
            try:
                # Parse playtime string (e.g. "10 hours", "2 hours 30 minutes")
                playtime_hours = None
                if game.playtime:
                    hours_match = re.search(r'(\d+)\s*hour', game.playtime)
                    mins_match = re.search(r'(\d+)\s*min', game.playtime)
                    hours = int(hours_match.group(1)) if hours_match else 0
                    mins = int(mins_match.group(1)) if mins_match else 0
                    playtime_hours = hours + (mins / 60) if (hours or mins) else None

                # Create a stable store_id from title
                store_id = game.title.lower().replace(' ', '-').replace(':', '').replace("'", "")

                # Store extra data
                extra_data = {
                    "playtime_raw": game.playtime,
                    "last_played": game.lastPlayed,
                    "platform": game.platform
                }

                cursor.execute("""
                    INSERT INTO games (
                        name, store, store_id, playtime_hours, extra_data, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(store, store_id) DO UPDATE SET
                        name = excluded.name,
                        playtime_hours = excluded.playtime_hours,
                        extra_data = excluded.extra_data,
                        updated_at = excluded.updated_at
                """, (
                    game.title,
                    "ubisoft",
                    store_id,
                    playtime_hours,
                    json.dumps(extra_data),
                    datetime.now().isoformat()
                ))
                count += 1
            except Exception as e:
                print(f"  Error importing {game.title}: {e}")

        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": f"Imported {count} Ubisoft games",
            "count": count
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/import/gog")
def import_gog_games(request: GOGImportRequest):
    """Import games scraped from GOG library page."""
    from ..services.database_builder import create_database

    try:
        # Ensure database exists
        create_database()
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        count = 0
        for game in request.games:
            try:
                # Store extra data
                extra_data = {
                    "profile_url": game.profileUrl,
                    "store_url": game.storeUrl
                }

                cursor.execute("""
                    INSERT INTO games (
                        name, store, store_id, extra_data, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(store, store_id) DO UPDATE SET
                        name = excluded.name,
                        extra_data = excluded.extra_data,
                        updated_at = excluded.updated_at
                """, (
                    game.title,
                    "gog",
                    game.id,
                    json.dumps(extra_data),
                    datetime.now().isoformat()
                ))
                count += 1
            except Exception as e:
                print(f"  Error importing {game.title}: {e}")

        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": f"Imported {count} GOG games",
            "count": count
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
