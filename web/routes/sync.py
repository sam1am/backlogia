# routes/sync.py
# Store sync and IGDB sync routes

import json
import re
import sqlite3
from datetime import datetime
from enum import Enum
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..config import DATABASE_PATH, ENABLE_AUTH, SECRET_KEY
from ..services.jobs import (
    JobType, create_job, update_job_progress, complete_job, fail_job, run_job_async
)
from ..services.settings import record_sync_timestamp, get_sync_timestamps


def _validate_import_token(data: dict):
    """Validate import token if auth is enabled. Raises HTTPException if invalid."""
    if not ENABLE_AUTH:
        return
    from ..services.auth_service import get_or_create_secret_key, validate_import_token
    secret = SECRET_KEY or get_or_create_secret_key()
    token = data.get("token")
    if not token or not validate_import_token(secret, token):
        raise HTTPException(status_code=401, detail="Invalid or missing import token")

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
    xbox = "xbox"
    ubisoft = "ubisoft"
    local = "local"
    all = "all"


@router.get("/api/sync/timestamps")
def get_sync_timestamps_api():
    """Get last sync timestamps for all providers."""
    return {"success": True, "timestamps": get_sync_timestamps()}


@router.post("/api/sync/store/{store}")
def sync_store(store: StoreType):
    """Sync games from a store."""
    # Import here to avoid circular imports
    from ..services.database_builder import (
        create_database, import_steam_games, import_epic_games,
        import_gog_games, import_itch_games, import_humble_games,
        import_battlenet_games, import_amazon_games, import_ea_games,
        import_xbox_games, import_local_games
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

        if store == StoreType.xbox or store == StoreType.all:
            results["xbox"] = import_xbox_games(conn)

        if store == StoreType.local or store == StoreType.all:
            results["local"] = import_local_games(conn)

        conn.close()

        if store == StoreType.all:
            total = sum(results.values())
            message = f"Synced {total} games: " + ", ".join(
                f"{s.capitalize()}: {c}" for s, c in results.items()
            )
            for s in results:
                record_sync_timestamp(s)
        else:
            count = results.get(store.value, 0)
            message = f"Synced {count} games from {store.value.capitalize()}"
            record_sync_timestamp(store.value)

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
        record_sync_timestamp("igdb")
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
        record_sync_timestamp("metacritic")
        return {"success": True, "message": message, "matched": matched, "failed": failed}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Async Job-based Sync Endpoints
# =============================================================================

@router.post("/api/sync/store/{store}/async")
def sync_store_async(store: StoreType):
    """Start a background job to sync games from a store. Returns job ID for tracking."""
    from ..services.database_builder import (
        create_database, import_steam_games, import_epic_games,
        import_gog_games, import_itch_games, import_humble_games,
        import_battlenet_games, import_amazon_games, import_ea_games,
        import_xbox_games, import_local_games
    )

    store_name = "all stores" if store == StoreType.all else store.value.capitalize()
    job_id = create_job(JobType.STORE_SYNC, f"Starting {store_name} sync...")

    def run_sync(job_id: str):
        try:
            # Ensure database tables exist
            create_database()
            conn = sqlite3.connect(DATABASE_PATH)

            stores_to_sync = []
            if store == StoreType.all:
                stores_to_sync = [
                    ("steam", import_steam_games),
                    ("epic", import_epic_games),
                    ("gog", import_gog_games),
                    ("itch", import_itch_games),
                    ("humble", import_humble_games),
                    ("battlenet", import_battlenet_games),
                    ("amazon", import_amazon_games),
                    ("ea", import_ea_games),
                    ("xbox", import_xbox_games),
                    ("local", import_local_games),
                ]
            else:
                store_map = {
                    StoreType.steam: ("steam", import_steam_games),
                    StoreType.epic: ("epic", import_epic_games),
                    StoreType.gog: ("gog", import_gog_games),
                    StoreType.itch: ("itch", import_itch_games),
                    StoreType.humble: ("humble", import_humble_games),
                    StoreType.battlenet: ("battlenet", import_battlenet_games),
                    StoreType.amazon: ("amazon", import_amazon_games),
                    StoreType.ea: ("ea", import_ea_games),
                    StoreType.xbox: ("xbox", import_xbox_games),
                    StoreType.local: ("local", import_local_games),
                }
                if store in store_map:
                    stores_to_sync = [store_map[store]]

            total = len(stores_to_sync)
            results = {}

            for i, (store_name, import_func) in enumerate(stores_to_sync, 1):
                update_job_progress(job_id, i, total, f"Syncing {store_name.capitalize()}...")
                try:
                    count = import_func(conn)
                    results[store_name] = count
                except Exception as e:
                    results[store_name] = f"Error: {str(e)}"

            conn.close()

            # Build result message
            if store == StoreType.all:
                total_games = sum(v for v in results.values() if isinstance(v, int))
                message = f"Synced {total_games} games: " + ", ".join(
                    f"{s.capitalize()}: {c}" for s, c in results.items()
                )
            else:
                count = results.get(store.value, 0)
                message = f"Synced {count} games from {store.value.capitalize()}"

            # Record sync timestamps for completed stores
            for s in results:
                if isinstance(results[s], int):
                    record_sync_timestamp(s)

            complete_job(job_id, json.dumps(results), message)

        except Exception as e:
            fail_job(job_id, str(e))

    run_job_async(job_id, run_sync)

    return {"success": True, "job_id": job_id, "message": f"Started {store_name} sync job"}


@router.post("/api/sync/igdb/{mode}/async")
def sync_igdb_async(mode: str):
    """Start a background job to sync IGDB metadata. Returns job ID for tracking."""
    from ..services.igdb_sync import IGDBClient, sync_games as igdb_sync_games, add_igdb_columns

    mode_text = "all games" if mode == "all" else "missing metadata"
    job_id = create_job(JobType.IGDB_SYNC, f"Starting IGDB sync ({mode_text})...")

    def run_sync(job_id: str):
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            conn.row_factory = sqlite3.Row

            # Ensure IGDB columns exist
            add_igdb_columns(conn)

            update_job_progress(job_id, 0, 1, f"Initializing IGDB sync...")

            # Progress callback to update job status
            def on_progress(current, total, message):
                update_job_progress(job_id, current, total, message)

            # Initialize client and sync
            client = IGDBClient()
            force = (mode == "all")
            matched, failed = igdb_sync_games(conn, client, force=force, progress_callback=on_progress)

            conn.close()

            message = f"IGDB sync complete: {matched} matched, {failed} failed/no match"
            record_sync_timestamp("igdb")
            complete_job(job_id, json.dumps({"matched": matched, "failed": failed}), message)

        except Exception as e:
            fail_job(job_id, str(e))

    run_job_async(job_id, run_sync)

    return {"success": True, "job_id": job_id, "message": f"Started IGDB sync job ({mode_text})"}


@router.post("/api/sync/metacritic/{mode}/async")
def sync_metacritic_async(mode: str):
    """Start a background job to sync Metacritic scores. Returns job ID for tracking."""
    from ..services.metacritic_sync import (
        MetacriticClient, sync_games as metacritic_sync_games, add_metacritic_columns
    )

    mode_text = "all games" if mode == "all" else "missing scores"
    job_id = create_job(JobType.METACRITIC_SYNC, f"Starting Metacritic sync ({mode_text})...")

    def run_sync(job_id: str):
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            conn.row_factory = sqlite3.Row

            # Ensure Metacritic columns exist
            add_metacritic_columns(conn)

            update_job_progress(job_id, 0, 1, f"Initializing Metacritic sync...")

            # Progress callback to update job status
            def on_progress(current, total, message):
                update_job_progress(job_id, current, total, message)

            # Initialize client and sync
            client = MetacriticClient()
            force = (mode == "all")
            matched, failed = metacritic_sync_games(conn, client, force=force, progress_callback=on_progress)

            conn.close()

            message = f"Metacritic sync complete: {matched} matched, {failed} failed/no match"
            record_sync_timestamp("metacritic")
            complete_job(job_id, json.dumps({"matched": matched, "failed": failed}), message)

        except Exception as e:
            fail_job(job_id, str(e))

    run_job_async(job_id, run_sync)

    return {"success": True, "job_id": job_id, "message": f"Started Metacritic sync job ({mode_text})"}


@router.post("/api/sync/protondb/{mode}")
def sync_protondb(mode: str):
    """Sync ProtonDB data. Mode can be 'missing' (unmatched only) or 'all' (resync everything)."""
    from ..services.protondb_sync import (
        ProtonDBClient, sync_games as protondb_sync_games, add_protondb_columns
    )

    try:
        conn = sqlite3.connect(DATABASE_PATH)

        # Ensure ProtonDB columns exist
        add_protondb_columns(conn)

        # Initialize client
        client = ProtonDBClient()

        # Sync games (force=True for 'all' mode)
        force = (mode == "all")
        matched, failed = protondb_sync_games(conn, client, force=force)

        conn.close()

        message = f"ProtonDB sync complete: {matched} matched, {failed} failed/no data"
        record_sync_timestamp("protondb")
        return {"success": True, "message": message, "matched": matched, "failed": failed}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/sync/protondb/{mode}/async")
def sync_protondb_async(mode: str):
    """Start a background job to sync ProtonDB data. Returns job ID for tracking."""
    from ..services.protondb_sync import (
        ProtonDBClient, sync_games as protondb_sync_games, add_protondb_columns
    )

    mode_text = "all Steam games" if mode == "all" else "missing data"
    job_id = create_job(JobType.PROTONDB_SYNC, f"Starting ProtonDB sync ({mode_text})...")

    def run_sync(job_id: str):
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            conn.row_factory = sqlite3.Row

            # Ensure ProtonDB columns exist
            add_protondb_columns(conn)

            update_job_progress(job_id, 0, 1, f"Initializing ProtonDB sync...")

            # Progress callback to update job status
            def on_progress(current, total, message):
                update_job_progress(job_id, current, total, message)

            # Initialize client and sync
            client = ProtonDBClient()
            force = (mode == "all")
            matched, failed = protondb_sync_games(conn, client, force=force, progress_callback=on_progress)

            conn.close()

            message = f"ProtonDB sync complete: {matched} matched, {failed} failed/no data"
            record_sync_timestamp("protondb")
            complete_job(job_id, json.dumps({"matched": matched, "failed": failed}), message)

        except Exception as e:
            fail_job(job_id, str(e))

    run_job_async(job_id, run_sync)

    return {"success": True, "job_id": job_id, "message": f"Started ProtonDB sync job ({mode_text})"}


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
async def import_ubisoft_games(request: Request):
    """Import games scraped from Ubisoft account page."""
    from ..services.database_builder import create_database

    try:
        body = await request.body()
        raw = json.loads(body)
        _validate_import_token(raw)
        parsed = UbisoftImportRequest(**raw)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    try:
        # Ensure database exists
        create_database()
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        count = 0
        for game in parsed.games:
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

        record_sync_timestamp("ubisoft")
        return {
            "success": True,
            "message": f"Imported {count} Ubisoft games",
            "count": count
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/import/gog")
async def import_gog_games(request: Request):
    """Import games scraped from GOG library page."""
    from ..services.database_builder import create_database

    try:
        body = await request.body()
        raw = json.loads(body)
        _validate_import_token(raw)
        parsed = GOGImportRequest(**raw)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    try:
        # Ensure database exists
        create_database()
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        count = 0
        for game in parsed.games:
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

        record_sync_timestamp("gog")
        return {
            "success": True,
            "message": f"Imported {count} GOG games",
            "count": count
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
