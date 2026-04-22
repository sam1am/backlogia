# gog.py
# Fetches games from GOG via direct API (OAuth) or local Galaxy database

import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..services.settings import get_gog_settings, get_gog_credentials

# GOG OAuth constants (public Galaxy client credentials — same as gogdl / Heroic)
_GOG_CLIENT_ID = "46899977096215655"
_GOG_CLIENT_SECRET = "9d85c43b1482497dbbce61f6e4aa173a433796eeae2ca8c5f6129f2dc4de46d9"
_GOG_REDIRECT_URI = "https://embed.gog.com/on_login_success?origin=client"
GOG_LOGIN_URL = (
    "https://login.gog.com/auth"
    "?client_id=46899977096215655"
    "&redirect_uri=https%3A%2F%2Fembed.gog.com%2Fon_login_success%3Forigin%3Dclient"
    "&response_type=code"
    "&layout=client2"
)


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

def exchange_code_for_token(code: str) -> dict | None:
    """Exchange a GOG authorization code for access/refresh tokens."""
    params = urllib.parse.urlencode({
        "client_id": _GOG_CLIENT_ID,
        "client_secret": _GOG_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": _GOG_REDIRECT_URI,
        "code": code.strip(),
    })
    try:
        req = urllib.request.Request(f"https://auth.gog.com/token?{params}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[GOG] Token exchange HTTP error {e.code}: {e.read().decode()}")
        return None
    except Exception as e:
        print(f"[GOG] Token exchange failed: {e}")
        return None


def _refresh_access_token(refresh_token: str) -> dict | None:
    """Refresh an expired GOG access token."""
    params = urllib.parse.urlencode({
        "client_id": _GOG_CLIENT_ID,
        "client_secret": _GOG_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    })
    try:
        req = urllib.request.Request(f"https://auth.gog.com/token?{params}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"[GOG] Token refresh failed: {e}")
        return None


def save_gog_token(token_data: dict) -> None:
    """Persist GOG token data to settings."""
    from ..services.settings import set_setting, GOG_ACCESS_TOKEN, GOG_REFRESH_TOKEN, GOG_TOKEN_EXPIRES_AT
    expires_at = str(time.time() + int(token_data.get("expires_in", 3600)))
    set_setting(GOG_ACCESS_TOKEN, token_data.get("access_token", ""))
    set_setting(GOG_REFRESH_TOKEN, token_data.get("refresh_token", ""))
    set_setting(GOG_TOKEN_EXPIRES_AT, expires_at)


def clear_gog_token() -> None:
    """Remove stored GOG token from settings."""
    from ..services.settings import set_setting, GOG_ACCESS_TOKEN, GOG_REFRESH_TOKEN, GOG_TOKEN_EXPIRES_AT
    set_setting(GOG_ACCESS_TOKEN, "")
    set_setting(GOG_REFRESH_TOKEN, "")
    set_setting(GOG_TOKEN_EXPIRES_AT, "")


def _get_heroic_token() -> dict | None:
    """Load GOG token from Heroic Games Launcher's auth.json (if present)."""
    heroic_auth = Path.home() / ".config" / "heroic" / "gog_store" / "auth.json"
    if not heroic_auth.exists():
        return None
    try:
        with open(heroic_auth) as f:
            data = json.load(f)
        if data.get("access_token"):
            return data
    except Exception:
        pass
    return None


def get_valid_token() -> str | None:
    """
    Return a valid GOG access token, or None.

    Priority:
    1. Stored settings token (auto-refreshed if expired).
    2. Heroic Games Launcher auth.json (read-only fallback).
    """
    creds = get_gog_credentials()
    access_token = creds.get("access_token")
    refresh_token = creds.get("refresh_token")
    expires_at_str = creds.get("expires_at")

    if access_token:
        try:
            expires_at = float(expires_at_str or 0)
        except (TypeError, ValueError):
            expires_at = 0

        if time.time() < expires_at - 60:
            return access_token

        # Token expired — try refreshing
        if refresh_token:
            new_data = _refresh_access_token(refresh_token)
            if new_data and new_data.get("access_token"):
                save_gog_token(new_data)
                return new_data["access_token"]

    # Fall back to Heroic's token (not persisted in our settings)
    heroic = _get_heroic_token()
    if heroic:
        return heroic.get("access_token")

    return None


def check_auth_status() -> dict:
    """Return GOG authentication status dict."""
    heroic_data = _get_heroic_token()
    heroic_available = heroic_data is not None

    creds = get_gog_credentials()
    has_stored = bool(creds.get("access_token"))

    token = get_valid_token()
    if not token:
        return {
            "authenticated": False,
            "heroic": heroic_available,
            "source": None,
        }

    source = "stored" if has_stored else "heroic"
    return {
        "authenticated": True,
        "source": source,
        "heroic": heroic_available,
    }


# ---------------------------------------------------------------------------
# Library fetch — GOG API
# ---------------------------------------------------------------------------

def get_gog_library_via_api() -> list:
    """Fetch the GOG library via the GOG embed API (no Galaxy required)."""
    token = get_valid_token()
    if not token:
        return []

    games = []
    page = 1
    total_pages = 1

    while page <= total_pages:
        url = (
            "https://embed.gog.com/account/getFilteredProducts"
            f"?mediaType=1&sortBy=title&page={page}"
        )
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            print(f"[GOG] API request failed (page {page}): {e}")
            break

        if page == 1:
            total_pages = data.get("totalPages", 1)
            print(f"[GOG] Fetching {total_pages} page(s) of GOG library via API...")

        for product in data.get("products", []):
            if not product.get("isGame", True):
                continue
            gog_id = str(product.get("id", ""))
            raw_image = product.get("image", "")
            if raw_image:
                if raw_image.startswith("//"):
                    cover = f"https:{raw_image}.jpg"
                elif not raw_image.startswith("http"):
                    cover = f"https://images.gog.com{raw_image}.jpg"
                else:
                    cover = raw_image
            else:
                cover = None
            games.append({
                "name": product.get("title"),
                "product_id": gog_id,
                "release_key": f"gog_{gog_id}" if gog_id else None,
                "slug": product.get("slug"),
                "cover_image": cover,
                "release_date": product.get("releaseDate"),
                "store": "gog",
            })

        page += 1

    print(f"[GOG] Found {len(games)} games via API")
    return games


def find_gog_database():
    """Find GOG Galaxy database"""
    print("[GOG DEBUG] Looking for GOG database...")

    # First check configured path from settings/environment
    gog_settings = get_gog_settings()
    configured_path = gog_settings.get("db_path")
    print(f"[GOG DEBUG] Configured GOG_DB_PATH: {configured_path}")

    if configured_path:
        path = Path(configured_path)
        print(f"[GOG DEBUG] Checking configured path: {path}")
        print(f"[GOG DEBUG] Path exists: {path.exists()}")
        if path.exists():
            print(f"[GOG DEBUG] Using configured path: {path}")
            return path
        else:
            print(f"[GOG DEBUG] Configured path does not exist!")

    # Fall back to auto-detection
    print("[GOG DEBUG] Falling back to auto-detection...")
    possible_paths = [
        # macOS (shared location)
        Path("/Users/Shared/GOG.com/Galaxy/Storage/galaxy-2.0.db"),
        # Windows
        Path(os.environ.get("ProgramData", "C:/ProgramData")) /
        "GOG.com" / "Galaxy" / "storage" / "galaxy-2.0.db",
        # macOS (alternative - user library, older versions)
        Path.home() / "Library" / "Application Support" /
        "GOG.com" / "Galaxy" / "storage" / "galaxy-2.0.db",
        # Linux (via Wine/Heroic)
        Path.home() / ".config" / "heroic" / "gog_store" / "library.json",
    ]

    for path in possible_paths:
        print(f"[GOG DEBUG] Checking: {path} - exists: {path.exists()}")
        if path.exists():
            print(f"[GOG DEBUG] Found database at: {path}")
            return path

    print("[GOG DEBUG] No GOG database found!")
    return None


def _parse_json_value(value):
    """Safely parse JSON value from GamePieces."""
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def get_gog_library():
    """Return GOG library games.

    Tries in order:
    1. Direct GOG API (stored OAuth token or Heroic auth.json).
    2. GOG Galaxy SQLite database (Windows/macOS).
    3. Heroic library.json (Linux fallback, minimal data).
    """
    # --- Primary: GOG API ---
    token = get_valid_token()
    if token:
        games = get_gog_library_via_api()
        if games:
            return games
        print("[GOG] API returned no games, falling back to Galaxy DB...")

    # --- Fallback: Galaxy DB / Heroic library.json ---
    db_path = find_gog_database()
    if not db_path:
        print("[GOG] No GOG database found and no valid API token.")
        return []

    print(f"[GOG DEBUG] Using database: {db_path}")
    games = []

    # SQLite database (Windows/macOS with GOG Galaxy)
    if db_path.suffix == ".db":
        print(f"[GOG DEBUG] Connecting to SQLite database...")
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            print(f"[GOG DEBUG] Connected successfully")
        except Exception as e:
            print(f"[GOG DEBUG] Connection failed: {e}")
            return []
        cursor = conn.cursor()

        # Get the GamePieceType IDs dynamically
        try:
            cursor.execute("SELECT id, type FROM GamePieceTypes WHERE type IN ('title', 'meta', 'originalImages', 'summary')")
            type_mapping = {row[1]: row[0] for row in cursor.fetchall()}

            title_id = type_mapping.get('title')
            meta_id = type_mapping.get('meta')
            images_id = type_mapping.get('originalImages')
            summary_id = type_mapping.get('summary')

            if not all([title_id, meta_id, images_id, summary_id]):
                raise ValueError(f"Some GamePieceTypes not found. Available types: {list(type_mapping.keys())}")
        except (sqlite3.OperationalError, ValueError) as e:
            print(f"[GOG DEBUG] Error fetching GamePieceTypes: {e}")
            conn.close()
            return []

        # Query for owned GOG games with all their metadata
        query = f"""
        SELECT
            lr.releaseKey,
            title.value as title_json,
            meta.value as meta_json,
            images.value as images_json,
            summary.value as summary_json
        FROM
            LibraryReleases lr
        LEFT JOIN
            GamePieces title ON lr.releaseKey = title.releaseKey AND title.gamePieceTypeId = {title_id}
        LEFT JOIN
            GamePieces meta ON lr.releaseKey = meta.releaseKey AND meta.gamePieceTypeId = {meta_id}
        LEFT JOIN
            GamePieces images ON lr.releaseKey = images.releaseKey AND images.gamePieceTypeId = {images_id}
        LEFT JOIN
            GamePieces summary ON lr.releaseKey = summary.releaseKey AND summary.gamePieceTypeId = {summary_id}
        WHERE
            lr.releaseKey LIKE 'gog_%'
        GROUP BY lr.releaseKey
        """

        try:
            print("[GOG DEBUG] Executing query...")
            cursor.execute(query)
            rows = cursor.fetchall()
            print(f"[GOG DEBUG] Query returned {len(rows)} rows")
            for row in rows:
                release_key = row[0]
                title_data = _parse_json_value(row[1])
                meta_data = _parse_json_value(row[2])
                images_data = _parse_json_value(row[3])
                summary_data = _parse_json_value(row[4])

                # Extract product ID from release key (e.g., "gog_1207658867" -> "1207658867")
                product_id = release_key.replace("gog_", "") if release_key else None

                games.append({
                    "name": title_data.get("title"),
                    "release_key": release_key,
                    "product_id": product_id,
                    "developers": meta_data.get("developers", []),
                    "publishers": meta_data.get("publishers", []),
                    "genres": meta_data.get("genres", []),
                    "themes": meta_data.get("themes", []),
                    "critics_score": meta_data.get("criticsScore"),
                    "release_date": meta_data.get("releaseDate"),
                    "summary": summary_data.get("summary"),
                    "cover_image": images_data.get("verticalCover"),
                    "background_image": images_data.get("background"),
                    "icon": images_data.get("squareIcon"),
                    "store": "gog"
                })
        except sqlite3.OperationalError as e:
            print(f"Database query error: {e}")
            # Schema might differ, show available tables
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table';")
            print("Available tables:", cursor.fetchall())

        conn.close()

    # JSON file (Heroic Games Launcher on Linux)
    elif db_path.suffix == ".json":
        with open(db_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for game in data.get("library", []):
            games.append({
                "name": game.get("title"),
                "app_name": game.get("app_name"),
                "platform": "gog"
            })

    print(f"[GOG DEBUG] Returning {len(games)} games")
    return games


if __name__ == "__main__":
    library = get_gog_library()
    with open("gog_library.json", "w") as f:
        json.dump(library, f, indent=2)
    print(f"Found {len(library)} GOG games")
