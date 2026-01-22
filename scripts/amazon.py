# amazon.py
# Fetches owned games from Amazon Games using Nile CLI
# https://github.com/imLinguin/nile

import json
import subprocess
import shutil
import os
from pathlib import Path

DATABASE_PATH = Path(__file__).parent.parent / "game_library.db"

# Nile config path - same logic as Nile uses
NILE_CONFIG_PATH = Path(
    os.environ.get("NILE_CONFIG_PATH") or
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
) / "nile"


def _run_nile_command(args, timeout=60):
    """Run a Nile CLI command and return the result."""
    nile_path = shutil.which("nile")
    if not nile_path:
        return None, "Nile is not installed. Install it with: pip install nile"

    try:
        result = subprocess.run(
            [nile_path] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result, None
    except subprocess.TimeoutExpired:
        return None, "Command timed out"
    except Exception as e:
        return None, str(e)


def is_nile_installed():
    """Check if Nile is installed and available."""
    return shutil.which("nile") is not None


def start_auth():
    """Start Amazon authentication - returns login URL and credentials for registration."""
    result, error = _run_nile_command(["auth", "--login", "--non-interactive"])

    if error:
        return None, error

    # Nile outputs JSON with login URL and credentials
    try:
        data = json.loads(result.stdout)
        return {
            "login_url": data.get("login_url") or data.get("url"),
            "client_id": data.get("client_id"),
            "code_verifier": data.get("code_verifier"),
            "serial": data.get("serial"),
        }, None
    except json.JSONDecodeError:
        # Try to extract URL from text output
        output = result.stdout + result.stderr
        for line in output.split("\n"):
            if "amazon.com" in line:
                url_start = line.find("http")
                if url_start != -1:
                    return {"login_url": line[url_start:].strip()}, None

        return None, f"Failed to parse auth response: {result.stdout or result.stderr}"


def complete_auth(code, client_id=None, code_verifier=None, serial=None):
    """Complete Amazon authentication with the authorization code."""
    args = ["register", "--code", code]

    if client_id:
        args.extend(["--client-id", client_id])
    if code_verifier:
        args.extend(["--code-verifier", code_verifier])
    if serial:
        args.extend(["--serial", serial])

    result, error = _run_nile_command(args, timeout=30)

    if error:
        return False, error

    if result.returncode != 0:
        return False, result.stderr or result.stdout or "Registration failed"

    return True, "Authentication successful"


def check_auth_status():
    """Check if user is authenticated with Amazon via Nile."""
    result, error = _run_nile_command(["auth", "--status"])

    if error:
        return {"authenticated": False, "error": error}

    if result.returncode != 0:
        return {"authenticated": False, "error": result.stderr}

    # Nile outputs JSON: {"Username": "...", "LoggedIn": true/false}
    try:
        data = json.loads(result.stdout)
        return {
            "authenticated": data.get("LoggedIn", False),
            "username": data.get("Username"),
        }
    except json.JSONDecodeError:
        # Fallback to text parsing
        output = result.stdout.lower()
        if "true" in output or "logged in" in output:
            return {"authenticated": True}
        return {"authenticated": False, "message": result.stdout.strip()}


def sync_library():
    """Sync the Amazon Games library using Nile."""
    result, error = _run_nile_command(["library", "sync"], timeout=120)

    if error:
        return False, error

    if result.returncode != 0:
        return False, result.stderr or "Failed to sync library"

    return True, "Library synced successfully"


def _read_library_file():
    """Read the library directly from Nile's library.json file."""
    library_file = NILE_CONFIG_PATH / "library.json"

    if not library_file.exists():
        return None

    try:
        with open(library_file, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"  Error reading library file: {e}")
        return None


def get_amazon_library():
    """Fetch all games from Amazon Games library via Nile."""
    if not is_nile_installed():
        print("Error: Nile is not installed")
        print("Install it with: pip install nile")
        print("Then authenticate with: nile auth --login")
        return None

    # Check authentication status
    status = check_auth_status()
    if not status.get("authenticated"):
        print("Error: Not authenticated with Amazon Games")
        print("Authenticate with: nile auth --login")
        return None

    # Sync library first
    print("  Syncing Amazon Games library...")
    success, message = sync_library()
    if not success:
        print(f"  Warning: Could not sync library: {message}")
        # Continue anyway - might have cached data

    # Read library from Nile's library.json file (more reliable than CLI output)
    games_data = _read_library_file()

    if games_data is None:
        # Fall back to CLI command
        print("  Reading library via CLI...")
        result, error = _run_nile_command(["library", "list", "--json"])

        if error:
            print(f"  Error getting library: {error}")
            return None

        if result.returncode != 0:
            print(f"  Error getting library: {result.stderr}")
            return None

        try:
            games_data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"  Error parsing library JSON: {e}")
            return None

    # Convert Nile format to our format
    # Nile stores games with nested product info from the Amazon API
    games = []
    for game in games_data:
        # Handle nested product structure (from API response)
        product = game.get("product", game)
        product_detail = game.get("productDetail", {})
        details = product_detail.get("details", {})

        # Get the title - try multiple locations
        title = (
            product.get("title") or
            details.get("title") or
            game.get("title")
        )

        if not title:
            continue

        # Get product ID
        product_id = (
            product.get("id") or
            product.get("asin") or
            game.get("id")
        )

        # Get artwork URLs
        icon_url = None
        if product_detail.get("iconUrl"):
            icon_url = product_detail.get("iconUrl")
        elif details.get("logoUrl"):
            icon_url = details.get("logoUrl")

        # Get developer/publisher from details
        developer = details.get("developer")
        publisher = details.get("publisher")

        game_entry = {
            "product_id": product_id,
            "name": title,
            "developer": developer,
            "publisher": publisher,
            "icon_url": icon_url,
            "is_streaming": False,
            "raw_data": game,
        }

        games.append(game_entry)

    print(f"  Found {len(games)} Amazon games")
    return games if games else None


def logout():
    """Log out from Amazon Games via Nile."""
    result, error = _run_nile_command(["auth", "--logout"])

    if error:
        return False, error

    if result.returncode != 0:
        return False, result.stderr or "Failed to logout"

    return True, "Logged out successfully"


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Import Amazon Games library via Nile")
    parser.add_argument("--export", type=str, help="Export to JSON file instead of database")
    parser.add_argument("--auth", action="store_true", help="Start authentication flow")
    parser.add_argument("--status", action="store_true", help="Check authentication status")
    parser.add_argument("--logout", action="store_true", help="Log out from Amazon")
    args = parser.parse_args()

    if not is_nile_installed():
        print("Error: Nile is not installed")
        print("Install it with: pip install nile")
        print("For more info: https://github.com/imLinguin/nile")
        return

    if args.status:
        status = check_auth_status()
        if status.get("authenticated"):
            print("Authenticated with Amazon Games")
        else:
            print("Not authenticated")
            if status.get("error"):
                print(f"Error: {status['error']}")
        return

    if args.logout:
        success, message = logout()
        print(message)
        return

    if args.auth:
        print("Amazon Games Authentication via Nile")
        print("=" * 60)
        print("\nStarting Nile authentication...")
        print("This will open a browser window for Amazon login.\n")

        result, error = _run_nile_command(["auth", "--login"], timeout=300)
        if error:
            print(f"Error: {error}")
        elif result.returncode != 0:
            print(f"Authentication may have failed: {result.stderr}")
        else:
            print("Authentication complete!")
        return

    print("Amazon Games Library Import via Nile")
    print("=" * 60)

    games = get_amazon_library()
    if not games:
        print("Failed to fetch Amazon Games library")
        return

    print(f"\nFound {len(games)} games")

    if args.export:
        with open(args.export, "w") as f:
            json.dump(games, f, indent=2, default=str)
        print(f"Exported to {args.export}")
    else:
        # Import to database
        import sqlite3
        from datetime import datetime

        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        count = 0
        for game in games:
            try:
                developers = [game.get("developer")] if game.get("developer") else None
                publishers = [game.get("publisher")] if game.get("publisher") else None

                cursor.execute(
                    """INSERT OR REPLACE INTO games (
                        name, store, store_id, cover_image, icon,
                        developers, publishers, extra_data, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        game.get("name"),
                        "amazon",
                        game.get("product_id"),
                        game.get("icon_url"),
                        game.get("icon_url"),
                        json.dumps(developers) if developers else None,
                        json.dumps(publishers) if publishers else None,
                        json.dumps(game.get("raw_data", {})),
                        datetime.now().isoformat(),
                    ),
                )
                count += 1
            except Exception as e:
                print(f"  Error importing {game.get('name')}: {e}")

        conn.commit()
        conn.close()
        print(f"Imported {count} games to database")


if __name__ == "__main__":
    main()
