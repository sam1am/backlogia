# humble.py
# Fetches owned games from Humble Bundle using session cookie authentication

import json
import sqlite3
import requests
from pathlib import Path
from datetime import datetime
from settings import get_humble_credentials

DATABASE_PATH = Path(__file__).parent.parent / "game_library.db"

# Humble Bundle API endpoints
API_BASE = "https://www.humblebundle.com"
ORDERS_ENDPOINT = f"{API_BASE}/api/v1/user/order"

# Required header for API requests
REQUIRED_HEADERS = {
    "X-Requested-By": "hb_android_app",
    "Accept": "application/json",
}


def get_session():
    """Get authenticated requests session using stored cookie."""
    creds = get_humble_credentials()
    session_cookie = creds.get("session_cookie")

    if not session_cookie:
        return None

    session = requests.Session()
    session.headers.update(REQUIRED_HEADERS)
    session.cookies.set("_simpleauth_sess", session_cookie, domain=".humblebundle.com")

    return session


def verify_session(session):
    """Verify the session is authenticated."""
    try:
        response = session.get(ORDERS_ENDPOINT)
        if response.status_code == 200:
            data = response.json()
            # If we get a list of orders, we're authenticated
            if isinstance(data, list):
                print(f"Authenticated - found {len(data)} orders")
                return True
        print(f"Authentication failed: {response.status_code}")
        return False
    except Exception as e:
        print(f"Error verifying session: {e}")
        return False


def get_order_details(session, gamekey):
    """Fetch details for a specific order."""
    try:
        response = session.get(f"{API_BASE}/api/v1/order/{gamekey}")
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"Error fetching order {gamekey}: {e}")
        return None


def get_humble_library():
    """Fetch all games from Humble Bundle library."""
    session = get_session()
    if not session:
        print("Error: Humble Bundle session cookie not configured")
        print("\nTo set up Humble Bundle:")
        print("1. Log in to humblebundle.com in your browser")
        print("2. Open Developer Tools (F12) -> Application -> Cookies")
        print("3. Find the '_simpleauth_sess' cookie value")
        print("4. Add it in the Settings page")
        return None

    if not verify_session(session):
        print("Error: Session cookie is invalid or expired")
        print("Please update your Humble Bundle session cookie in Settings")
        return None

    print("Fetching Humble Bundle orders...")

    # Get all orders
    try:
        response = session.get(ORDERS_ENDPOINT)
        if response.status_code != 200:
            print(f"Failed to fetch orders: {response.status_code}")
            return None

        orders = response.json()
        print(f"Found {len(orders)} orders")
    except Exception as e:
        print(f"Error fetching orders: {e}")
        return None

    games = []
    processed_keys = set()  # Track unique game keys to avoid duplicates

    # Process each order
    for i, order in enumerate(orders):
        gamekey = order.get("gamekey")
        if not gamekey:
            continue

        print(f"  Processing order {i + 1}/{len(orders)}: {gamekey[:8]}...")

        order_details = get_order_details(session, gamekey)
        if not order_details:
            continue

        # Extract products (games) from the order
        products = order_details.get("subproducts", [])
        for product in products:
            machine_name = product.get("machine_name")
            if not machine_name or machine_name in processed_keys:
                continue

            processed_keys.add(machine_name)

            # Extract platform information
            downloads = product.get("downloads", [])
            platforms = set()
            for download in downloads:
                platform = download.get("platform", "").lower()
                if platform == "windows":
                    platforms.add("Windows")
                elif platform == "mac":
                    platforms.add("Mac")
                elif platform == "linux":
                    platforms.add("Linux")
                elif platform == "android":
                    platforms.add("Android")

            # Get the best available icon/image
            icon = product.get("icon") or product.get("human_icon")

            # Extract URL if available
            url = product.get("url")

            games.append({
                "machine_name": machine_name,
                "human_name": product.get("human_name"),
                "icon": icon,
                "url": url,
                "platforms": list(platforms),
                "payee": order_details.get("payee", {}).get("human_name"),  # Publisher
                "created": order_details.get("created"),  # Order date
                "gamekey": gamekey,
            })

    return games


def import_to_database(games):
    """Import Humble Bundle games to the database."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    count = 0
    for game in games:
        try:
            cursor.execute(
                """INSERT OR REPLACE INTO games (
                    name, store, store_id, cover_image, icon,
                    supported_platforms, publishers, release_date,
                    extra_data, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    game.get("human_name"),
                    "humble",
                    game.get("machine_name"),
                    game.get("icon"),
                    game.get("icon"),
                    json.dumps(game.get("platforms", [])),
                    json.dumps([game.get("payee")]) if game.get("payee") else None,
                    game.get("created"),
                    json.dumps(game),
                    datetime.now().isoformat(),
                ),
            )
            count += 1
        except Exception as e:
            print(f"Error importing {game.get('human_name')}: {e}")

    conn.commit()
    conn.close()

    return count


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Import Humble Bundle library")
    parser.add_argument("--export", type=str, help="Export to JSON file instead of database")
    args = parser.parse_args()

    print("Humble Bundle Library Import")
    print("=" * 60)

    games = get_humble_library()
    if not games:
        print("Failed to fetch Humble Bundle library")
        return

    print(f"\nFound {len(games)} unique games")

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
