# steam.py
# Fetches games from Steam library

import json
import requests

from ..services.settings import get_steam_credentials


def get_steam_library():
    """Fetch games from Steam library using credentials from database."""
    creds = get_steam_credentials()
    STEAM_API_KEY = creds.get("api_key")
    STEAM_ID = creds.get("steam_id")

    if not STEAM_API_KEY or not STEAM_ID:
        print("Steam credentials not configured. Please set them in Settings.")
        return []

    url = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
    params = {
        "key": STEAM_API_KEY,
        "steamid": STEAM_ID,
        "include_appinfo": True,
        "include_played_free_games": True,
    }

    response = requests.get(url, params=params)
    data = response.json()

    raw_games = data.get("response", {}).get("games", [])

    games = []
    for game in raw_games:
        games.append({
            "name": game.get("name"),
            "appid": game.get("appid"),
            "playtime_hours": round(game.get("playtime_forever", 0) / 60, 1),
            "icon_url": f"https://media.steampowered.com/steamcommunity/public/images/apps/{game['appid']}/{game.get('img_icon_url')}.jpg",
        })
    return games


if __name__ == "__main__":
    library = get_steam_library()
    with open("steam_library.json", "w") as f:
        json.dump(library, f, indent=2)

    print(f"\nExported {len(library)} Steam games")
