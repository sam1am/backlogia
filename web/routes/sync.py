# routes/sync.py
# Store sync and IGDB sync routes

import sqlite3
from enum import Enum

from fastapi import APIRouter, HTTPException

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
    all = "all"


@router.post("/api/sync/store/{store}")
def sync_store(store: StoreType):
    """Sync games from a store."""
    # Import here to avoid circular imports
    from ..services.database_builder import (
        create_database, import_steam_games, import_epic_games,
        import_gog_games, import_itch_games, import_humble_games,
        import_battlenet_games, import_amazon_games
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
