# main.py
# FastAPI application entry point for Backlogia

import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import DATABASE_PATH, ENABLE_AUTH, SECRET_KEY
from .database import ensure_extra_columns, ensure_collections_tables, ensure_edit_overrides
from .services.database_builder import create_database
from .services.igdb_sync import add_igdb_columns
from .services.jobs import cleanup_orphaned_jobs

# Import routers
from .routes.api_games import router as api_games_router
from .routes.api_metadata import router as api_metadata_router
from .routes.sync import router as sync_router
from .routes.auth import router as auth_router
from .routes.app_auth import router as app_auth_router
from .routes.collections import router as collections_router
from .routes.library import router as library_router
from .routes.discover import router as discover_router
from .routes.settings import router as settings_router
from .routes.jobs import router as jobs_router


def init_database():
    """Initialize the database and ensure all tables/columns exist."""
    create_database()
    ensure_extra_columns()
    ensure_collections_tables()
    ensure_edit_overrides()

    conn = sqlite3.connect(DATABASE_PATH)
    add_igdb_columns(conn)
    conn.close()

    # Clean up any jobs that were running when the server last stopped
    cleanup_orphaned_jobs()


# Create FastAPI app
app = FastAPI(
    title="Backlogia API",
    description="API for managing your game library across multiple stores",
    version="1.0.0",
)

# Add CORS middleware to allow bookmarklet requests from external sites
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://account.ubisoft.com",
        "https://www.ubisoft.com",
        "https://www.gog.com",
        "http://localhost:5050",
        "http://127.0.0.1:5050",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Conditionally add auth middleware (after CORS so CORS is the outer layer)
if ENABLE_AUTH:
    from .middleware import AuthMiddleware
    from .services.auth_service import get_or_create_secret_key, cleanup_expired_sessions

    actual_secret = SECRET_KEY or get_or_create_secret_key()
    app.add_middleware(AuthMiddleware, secret_key=actual_secret)
    cleanup_expired_sessions()

# Initialize database on startup
init_database()

# Serve the service worker from root scope for PWA support
sw_path = Path(__file__).parent / "static" / "sw.js"


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse(sw_path, media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/"})


# Mount static files
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=static_path), name="static")

# Configure templates (shared instance for all routers)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# Include routers
app.include_router(library_router)
app.include_router(api_games_router)
app.include_router(api_metadata_router)
app.include_router(discover_router)
app.include_router(settings_router)
app.include_router(sync_router)
app.include_router(auth_router)
app.include_router(app_auth_router)
app.include_router(collections_router)
app.include_router(jobs_router)
