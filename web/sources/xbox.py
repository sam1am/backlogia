# xbox.py
# Fetches owned games and Game Pass catalog from Xbox using XSTS token authentication
# User obtains XSTS token via browser DevTools network tab

import json
import requests

from ..services.settings import get_xbox_credentials

# Xbox API endpoints
TITLEHUB_ENDPOINT = "https://titlehub.xboxlive.com"
COLLECTIONS_ENDPOINT = "https://collections.mp.microsoft.com/v9.0/collections/publisherQuery"
GAMEPASS_CATALOG_ENDPOINT = "https://catalog.gamepass.com/sigls/v2"
DISPLAY_CATALOG_ENDPOINT = "https://displaycatalog.mp.microsoft.com/v7.0/products"

# Game Pass catalog IDs
# fdd9e2a7-0fee-49f6-ad69-4354098401ff = PC Game Pass
# f6f1f99f-9b49-4ccd-b3bf-4d9767a77f5e = Console Game Pass
# 29a81209-df6f-41fd-a528-2ae6b91f719c = EA Play
GAMEPASS_PC_CATALOG_ID = "fdd9e2a7-0fee-49f6-ad69-4354098401ff"

# Required headers for API requests
REQUIRED_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US",
    "x-xbl-contract-version": "2",
}


def get_xsts_token():
    """Get stored XSTS token from settings."""
    creds = get_xbox_credentials()
    token = creds.get("xsts_token")

    if token:
        token = token.strip()

    return token if token else None


def parse_xsts_token(token):
    """Parse XSTS token to extract XUID and format authorization header.

    Handles multiple token formats:
    1. Full auth header: "XBL3.0 x=<userhash>;<token>"
    2. Just the token part from cookies (JWT format starting with eyJ)
    3. Partial format: "XBL3.0 x=<token>" (missing userhash)
    """
    if not token:
        return None, None

    token = token.strip()

    # Format 1: Full XBL3.0 authorization header
    if token.upper().startswith("XBL3.0 X="):
        auth_header = token
        # Try to extract userhash
        try:
            # Format: XBL3.0 x=<userhash>;<token>
            after_prefix = token[9:]  # After "XBL3.0 x="
            if ";" in after_prefix:
                userhash = after_prefix.split(";")[0]
            else:
                userhash = None
        except Exception:
            userhash = None
        return auth_header, userhash

    # Format 2: Raw JWT token (starts with eyJ - base64 encoded JSON)
    # This comes from XBXXtk cookies - need to wrap it
    elif token.startswith("eyJ"):
        # For JWT tokens, we need a userhash. Try to decode and extract.
        # If we can't, just use a placeholder - the API might still work
        try:
            import base64
            # JWT is header.payload.signature - decode the payload
            parts = token.split(".")
            if len(parts) >= 2:
                # Add padding if needed
                payload = parts[1]
                padding = 4 - len(payload) % 4
                if padding != 4:
                    payload += "=" * padding
                decoded = base64.urlsafe_b64decode(payload)
                import json
                claims = json.loads(decoded)
                # Look for userhash in claims
                userhash = claims.get("xui", [{}])[0].get("uhs") if claims.get("xui") else None
        except Exception:
            userhash = None

        # Construct auth header
        if userhash:
            auth_header = f"XBL3.0 x={userhash};{token}"
        else:
            # Try without userhash - format varies
            auth_header = f"XBL3.0 x={token}"
        return auth_header, userhash

    # Format 3: Some other format - try wrapping it
    else:
        return f"XBL3.0 x={token}", None


def get_xuid_from_token(token):
    """Get XUID by making an authenticated request to Xbox profile API."""
    try:
        auth_header, _ = parse_xsts_token(token)
        if not auth_header:
            return None

        headers = {
            **REQUIRED_HEADERS,
            "Authorization": auth_header,
        }

        # Get current user's profile to extract XUID
        response = requests.get(
            "https://profile.xboxlive.com/users/me/profile/settings",
            headers=headers,
            params={"settings": "Gamertag"}
        )

        if response.status_code == 200:
            data = response.json()
            # XUID is in the response
            if "profileUsers" in data and len(data["profileUsers"]) > 0:
                return data["profileUsers"][0].get("id")
        else:
            print(f"  Failed to get XUID: {response.status_code}")
            # Try to extract from authorization header
            if ";" in auth_header:
                # Format: XBL3.0 x=userhash;token - userhash might be XUID
                pass

        return None
    except Exception as e:
        print(f"  Error getting XUID: {e}")
        return None


def get_owned_games(token, xuid=None):
    """Fetch owned games from Xbox TitleHub API."""
    try:
        auth_header, userhash = parse_xsts_token(token)
        if not auth_header:
            print("  Invalid XSTS token format")
            return []

        # Try to get XUID if not provided
        if not xuid:
            xuid = get_xuid_from_token(token)

        if not xuid:
            print("  Could not determine XUID - trying alternative API")
            # Fall back to Collections API which doesn't need XUID
            return get_owned_games_from_collections(token)

        headers = {
            **REQUIRED_HEADERS,
            "Authorization": auth_header,
        }

        all_games = []

        # Fetch title history
        url = f"{TITLEHUB_ENDPOINT}/users/xuid({xuid})/titles/titlehistory/decoration/detail,image,scid"
        params = {
            "maxItems": 1000,
        }

        print(f"  Fetching owned games for XUID: {xuid}")
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 401:
            print("  Token expired or invalid - please get a new XSTS token")
            return []

        if response.status_code != 200:
            print(f"  TitleHub error: {response.status_code} - {response.text[:200]}")
            # Try Collections API as fallback
            return get_owned_games_from_collections(token)

        try:
            data = response.json()
        except json.JSONDecodeError:
            print(f"  Response not JSON: {response.text[:200]}")
            return []

        titles = data.get("titles", [])
        print(f"  Found {len(titles)} titles in history")

        for title in titles:
            # Filter to games only (not apps)
            # titleType: "Game", "App", "DLC"
            if title.get("type") not in ["Game", None]:
                continue

            name = title.get("name")
            if not name:
                continue

            # Get product ID
            product_id = title.get("pfn") or title.get("titleId")

            # Get cover image - prefer portrait box art
            cover_image = None
            images = title.get("images", [])
            for img in images:
                img_type = img.get("type", "").lower()
                if img_type in ["boxart", "poster", "tile"]:
                    cover_image = img.get("url")
                    break
            if not cover_image and images:
                cover_image = images[0].get("url")

            # Get acquisition info
            acquisition = title.get("acquisition", {})

            all_games.append({
                "name": name,
                "store_id": str(product_id) if product_id else None,
                "cover_image": cover_image,
                "is_streaming": False,
                "acquisition_type": acquisition.get("type", "Single"),
                "title_id": title.get("titleId"),
                "pfn": title.get("pfn"),
                "raw_data": title,
            })

        return all_games

    except Exception as e:
        print(f"  Error fetching owned games: {e}")
        import traceback
        traceback.print_exc()
        return []


def get_owned_games_from_collections(token):
    """Fetch owned games using Collections API (alternative method)."""
    try:
        auth_header, _ = parse_xsts_token(token)
        if not auth_header:
            return []

        headers = {
            **REQUIRED_HEADERS,
            "Authorization": auth_header,
            "Content-Type": "application/json",
        }

        # Query for owned products
        payload = {
            "productIds": [],
            "productSkuIds": [],
            "idType": "ProductId",
            "beneficiaries": [],
            "market": "US",
            "languages": ["en-US"],
            "maxPageSize": 1000,
        }

        response = requests.post(
            COLLECTIONS_ENDPOINT,
            headers=headers,
            json=payload
        )

        if response.status_code != 200:
            print(f"  Collections API error: {response.status_code}")
            return []

        data = response.json()
        items = data.get("items", [])

        all_games = []
        for item in items:
            product = item.get("productInfo", {})
            name = product.get("localizedProperties", [{}])[0].get("productTitle")
            product_id = product.get("productId")

            if not name:
                continue

            # Get cover image
            cover_image = None
            images = product.get("localizedProperties", [{}])[0].get("images", [])
            for img in images:
                if img.get("imagePurpose") in ["BoxArt", "Poster", "Tile"]:
                    cover_image = img.get("uri")
                    break

            all_games.append({
                "name": name,
                "store_id": product_id,
                "cover_image": cover_image,
                "is_streaming": False,
                "acquisition_type": item.get("acquisitionType", "Single"),
                "raw_data": item,
            })

        return all_games

    except Exception as e:
        print(f"  Error fetching from Collections API: {e}")
        return []


def get_gamepass_catalog():
    """Fetch Game Pass PC catalog (public API, no auth required)."""
    try:
        all_games = []

        # Fetch Game Pass catalog
        url = f"{GAMEPASS_CATALOG_ENDPOINT}?id={GAMEPASS_PC_CATALOG_ID}&language=en-US&market=US"

        print("  Fetching Game Pass catalog...")
        response = requests.get(url, headers=REQUIRED_HEADERS)

        if response.status_code != 200:
            print(f"  Game Pass catalog error: {response.status_code}")
            return []

        data = response.json()

        # The response contains product IDs, we need to fetch details
        product_ids = []
        for item in data:
            if isinstance(item, dict) and "id" in item:
                product_ids.append(item["id"])
            elif isinstance(item, str):
                product_ids.append(item)

        print(f"  Found {len(product_ids)} Game Pass titles, fetching details...")

        # Fetch product details in batches
        batch_size = 20
        for i in range(0, len(product_ids), batch_size):
            batch = product_ids[i:i + batch_size]
            details = get_product_details(batch)
            all_games.extend(details)

        return all_games

    except Exception as e:
        print(f"  Error fetching Game Pass catalog: {e}")
        import traceback
        traceback.print_exc()
        return []


def get_product_details(product_ids):
    """Fetch product details from Display Catalog API."""
    if not product_ids:
        return []

    try:
        # Build the products query
        ids_param = ",".join(product_ids)
        url = f"{DISPLAY_CATALOG_ENDPOINT}?bigIds={ids_param}&market=US&languages=en-US"

        response = requests.get(url, headers=REQUIRED_HEADERS)

        if response.status_code != 200:
            print(f"  Display catalog error: {response.status_code}")
            return []

        data = response.json()
        products = data.get("Products", [])

        games = []
        for product in products:
            # Filter to games only
            product_type = product.get("ProductType", "")
            if product_type not in ["Game", "Application"]:
                continue

            localized = product.get("LocalizedProperties", [{}])[0]
            name = localized.get("ProductTitle")
            product_id = product.get("ProductId")

            if not name:
                continue

            # Get cover image
            cover_image = None
            images = localized.get("Images", [])
            for img in images:
                purpose = img.get("ImagePurpose", "")
                if purpose in ["BoxArt", "Poster", "Tile"]:
                    cover_image = img.get("Uri")
                    if cover_image and not cover_image.startswith("http"):
                        cover_image = f"https:{cover_image}"
                    break
            if not cover_image and images:
                cover_image = images[0].get("Uri")
                if cover_image and not cover_image.startswith("http"):
                    cover_image = f"https:{cover_image}"

            # Get publisher/developer
            properties = product.get("Properties", {})
            developer = localized.get("DeveloperName")
            publisher = localized.get("PublisherName")

            # Get release date
            market_props = product.get("MarketProperties", [{}])[0]
            release_date = market_props.get("OriginalReleaseDate")

            games.append({
                "name": name,
                "store_id": product_id,
                "cover_image": cover_image,
                "is_streaming": True,  # Game Pass games are streaming
                "acquisition_type": "Recurring",  # Subscription
                "developer": developer,
                "publisher": publisher,
                "release_date": release_date,
                "raw_data": product,
            })

        return games

    except Exception as e:
        print(f"  Error fetching product details: {e}")
        return []


def get_xbox_library():
    """Fetch all games from Xbox - owned games + Game Pass catalog."""
    token = get_xsts_token()

    print("Fetching Xbox library...")

    all_games = []
    owned_ids = set()

    # First, try to get owned games if token is available
    if token:
        owned_games = get_owned_games(token)
        print(f"  Found {len(owned_games)} owned Xbox games")

        for game in owned_games:
            store_id = game.get("store_id")
            if store_id:
                owned_ids.add(store_id)
            all_games.append(game)
    else:
        print("  No XSTS token configured - skipping owned games")
        print("  To import owned games, add your XSTS token in Settings")

    # Then fetch Game Pass catalog (public API)
    gamepass_games = get_gamepass_catalog()
    print(f"  Found {len(gamepass_games)} Game Pass games")

    # Add Game Pass games that aren't already owned
    for game in gamepass_games:
        store_id = game.get("store_id")
        if store_id and store_id not in owned_ids:
            all_games.append(game)
        elif store_id in owned_ids:
            # Update existing owned game to mark it has Game Pass too
            for owned in all_games:
                if owned.get("store_id") == store_id:
                    # Keep is_streaming False since they own it
                    break

    # Deduplicate by store_id
    seen_ids = set()
    unique_games = []
    for game in all_games:
        store_id = game.get("store_id")
        if store_id and store_id in seen_ids:
            continue
        if store_id:
            seen_ids.add(store_id)
        unique_games.append(game)

    print(f"  Total unique Xbox games: {len(unique_games)}")
    return unique_games


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Import Xbox library")
    parser.add_argument("--token", type=str, help="XSTS token (for testing)")
    parser.add_argument("--gamepass-only", action="store_true", help="Only fetch Game Pass catalog")
    parser.add_argument("--export", type=str, help="Export to JSON file instead of database")
    args = parser.parse_args()

    print("Xbox Library Import")
    print("=" * 60)

    if args.gamepass_only:
        print("Fetching Game Pass catalog only...")
        games = get_gamepass_catalog()
    elif args.token:
        # Use provided token for testing
        print("Using provided token...")
        games = get_owned_games(args.token)
    else:
        games = get_xbox_library()

    if not games:
        print("No games found")
        return

    print(f"\nFound {len(games)} games")

    if args.export:
        with open(args.export, "w") as f:
            json.dump(games, f, indent=2)
        print(f"Exported to {args.export}")
    else:
        streaming_count = sum(1 for g in games if g.get("is_streaming"))
        owned_count = len(games) - streaming_count
        print(f"  Owned: {owned_count}")
        print(f"  Game Pass: {streaming_count}")
        print("\nSample games:")
        for game in games[:10]:
            streaming = " [Streaming]" if game.get("is_streaming") else ""
            print(f"  - {game['name']}{streaming}")
        if len(games) > 10:
            print(f"  ... and {len(games) - 10} more")


if __name__ == "__main__":
    main()
