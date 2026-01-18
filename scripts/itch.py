# itch.py
# Fetches owned games from itch.io using API key or OAuth

import os
import json
import sqlite3
import webbrowser
import requests
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs
from datetime import datetime
from dotenv import load_dotenv
from settings import get_itch_credentials

# Load environment variables (for ITCH_CLIENT_ID fallback only)
load_dotenv(Path(__file__).parent.parent / ".env")

# OAuth client ID can still come from .env as it's not sensitive
ITCH_CLIENT_ID = os.getenv("ITCH_CLIENT_ID")

DATABASE_PATH = Path(__file__).parent.parent / "game_library.db"
TOKEN_FILE = Path(__file__).parent.parent / ".itch_token"

# OAuth settings (only used if no API key)
REDIRECT_PORT = 8976
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
OAUTH_URL = "https://itch.io/user/oauth"
API_BASE = "https://api.itch.io"


def get_api_key_token():
    """Use API key for authentication (preferred method)."""
    creds = get_itch_credentials()
    api_key = creds.get("api_key")

    if not api_key:
        return None

    # Verify the API key works
    try:
        response = requests.get(
            f"{API_BASE}/profile",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if response.status_code == 200:
            user = response.json().get("user", {})
            print(f"Authenticated via API key as: {user.get('username')}")
            return api_key
        else:
            print(f"API key invalid: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Error validating API key: {e}")
        return None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to capture OAuth callback."""

    def log_message(self, format, *args):
        pass  # Suppress HTTP logging

    def do_GET(self):
        """Handle the OAuth callback."""
        if self.path.startswith("/callback"):
            # Send HTML page that extracts token from hash
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()

            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>itch.io Authorization</title>
                <style>
                    body {
                        font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                        color: #e4e4e4;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        height: 100vh;
                        margin: 0;
                    }
                    .container {
                        text-align: center;
                        padding: 40px;
                        background: rgba(255,255,255,0.05);
                        border-radius: 12px;
                    }
                    h1 { color: #fa5c5c; }
                    .success { color: #4caf50; }
                    .error { color: #f44336; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>itch.io Authorization</h1>
                    <p id="status">Processing...</p>
                </div>
                <script>
                    const hash = window.location.hash.substring(1);
                    const params = new URLSearchParams(hash);
                    const token = params.get('access_token');

                    if (token) {
                        fetch('/token?access_token=' + token)
                            .then(() => {
                                document.getElementById('status').innerHTML =
                                    '<span class="success">✓ Authorization successful!</span><br><br>You can close this window.';
                            });
                    } else {
                        document.getElementById('status').innerHTML =
                            '<span class="error">✗ Authorization failed</span><br><br>' +
                            (params.get('error_description') || 'No token received');
                    }
                </script>
            </body>
            </html>
            """
            self.wfile.write(html.encode())

        elif self.path.startswith("/token"):
            # Receive the token from JavaScript
            query = parse_qs(urlparse(self.path).query)
            token = query.get("access_token", [None])[0]

            if token:
                self.server.access_token = token
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
            else:
                self.send_response(400)
                self.end_headers()

            # Signal to stop the server
            self.server.should_stop = True


def get_oauth_token():
    """Get OAuth token through browser authorization."""
    if not ITCH_CLIENT_ID:
        print("Error: ITCH_CLIENT_ID not set in .env file")
        print("\nTo set up itch.io OAuth:")
        print("1. Go to https://itch.io/user/settings/oauth-apps")
        print("2. Create a new OAuth application")
        print(f"3. Set the redirect URI to: {REDIRECT_URI}")
        print("4. Add ITCH_CLIENT_ID=your_client_id to your .env file")
        return None

    # Check for saved token
    if TOKEN_FILE.exists():
        try:
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
                token = data.get("access_token")
                if token:
                    # Verify token is still valid
                    response = requests.get(
                        f"{API_BASE}/profile",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    if response.status_code == 200:
                        print(f"Using saved token for: {response.json().get('user', {}).get('username')}")
                        return token
        except Exception:
            pass

    # Start local server for callback
    server = HTTPServer(("localhost", REDIRECT_PORT), OAuthCallbackHandler)
    server.access_token = None
    server.should_stop = False

    # Build authorization URL
    params = {
        "client_id": ITCH_CLIENT_ID,
        "scope": "profile:owned",
        "response_type": "token",
        "redirect_uri": REDIRECT_URI,
    }
    auth_url = f"{OAUTH_URL}?{urlencode(params)}"

    print("Opening browser for itch.io authorization...")
    print(f"If browser doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    print("Waiting for authorization...")

    # Handle requests until we get the token
    while not server.should_stop:
        server.handle_request()

    if server.access_token:
        # Save token for future use
        with open(TOKEN_FILE, "w") as f:
            json.dump({"access_token": server.access_token}, f)
        print("Authorization successful!")
        return server.access_token

    return None


def get_owned_games(token):
    """Fetch owned games from itch.io API."""
    print("Fetching owned games from itch.io...")

    games = []
    page = 1

    while True:
        response = requests.get(
            f"{API_BASE}/profile/owned-keys",
            headers={"Authorization": f"Bearer {token}"},
            params={"page": page},
        )

        if response.status_code != 200:
            print(f"API error: {response.status_code} - {response.text}")
            break

        data = response.json()
        owned_keys = data.get("owned_keys", [])

        if not owned_keys:
            break

        for key in owned_keys:
            game = key.get("game", {})
            if game:
                games.append({
                    "id": game.get("id"),
                    "title": game.get("title"),
                    "short_text": game.get("short_text"),
                    "cover_url": game.get("cover_url"),
                    "url": game.get("url"),
                    "created_at": game.get("created_at"),
                    "published_at": game.get("published_at"),
                    "platforms": {
                        "windows": game.get("p_windows", False),
                        "mac": game.get("p_osx", False),
                        "linux": game.get("p_linux", False),
                        "android": game.get("p_android", False),
                    },
                    "game_type": game.get("type"),  # "default", "flash", "html", etc.
                    "classification": game.get("classification"),  # "game", "tool", "assets", etc.
                    "download_key_id": key.get("id"),
                })

        print(f"  Page {page}: found {len(owned_keys)} games")
        page += 1

        # Check if there are more pages
        if len(owned_keys) < 50:  # Default page size
            break

    return games


def import_to_database(games):
    """Import itch.io games to the database."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    count = 0
    for game in games:
        try:
            # Build platforms list
            platforms = []
            if game["platforms"].get("windows"):
                platforms.append("Windows")
            if game["platforms"].get("mac"):
                platforms.append("Mac")
            if game["platforms"].get("linux"):
                platforms.append("Linux")
            if game["platforms"].get("android"):
                platforms.append("Android")

            cursor.execute(
                """INSERT OR REPLACE INTO games (
                    name, store, store_id, description, cover_image,
                    supported_platforms, release_date, extra_data, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    game.get("title"),
                    "itch",
                    str(game.get("id")),
                    game.get("short_text"),
                    game.get("cover_url"),
                    json.dumps(platforms) if platforms else None,
                    game.get("published_at"),
                    json.dumps(game),
                    datetime.now().isoformat(),
                ),
            )
            count += 1
        except Exception as e:
            print(f"Error importing {game.get('title')}: {e}")

    conn.commit()
    conn.close()

    return count


def get_auth_token():
    """Get authentication token - tries API key first, then OAuth."""
    # Try API key first (preferred)
    token = get_api_key_token()
    if token:
        return token

    # Fall back to OAuth
    print("No API key configured, falling back to OAuth...")
    return get_oauth_token()


def logout():
    """Remove saved token."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
        print("Logged out from itch.io")
    else:
        print("Not logged in")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Import itch.io library")
    parser.add_argument("--logout", action="store_true", help="Remove saved credentials")
    parser.add_argument("--export", type=str, help="Export to JSON file instead of database")
    args = parser.parse_args()

    if args.logout:
        logout()
        return

    print("itch.io Library Import")
    print("=" * 60)

    # Get authentication token (API key preferred, OAuth fallback)
    token = get_auth_token()
    if not token:
        print("Failed to get authorization token")
        print("\nTo authenticate with itch.io, either:")
        print("  1. Set your itch.io API key in the Settings page")
        print("     (Get your API key at: https://itch.io/user/settings/api-keys)")
        print("  2. Or set up OAuth with ITCH_CLIENT_ID in .env")
        print("     (Create OAuth app at: https://itch.io/user/settings/oauth-apps)")
        return

    # Fetch owned games
    games = get_owned_games(token)
    print(f"\nFound {len(games)} owned games")

    if not games:
        return

    if args.export:
        # Export to JSON
        with open(args.export, "w") as f:
            json.dump(games, f, indent=2)
        print(f"Exported to {args.export}")
    else:
        # Import to database
        count = import_to_database(games)
        print(f"Imported {count} games to database")


if __name__ == "__main__":
    main()
