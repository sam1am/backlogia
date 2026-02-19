# Configuration

- [Store Credentials](#store-credentials)
- [Local Games](#local-games)

---

Configure all store connections through the **Settings** page in Backlogia. Each store section includes step-by-step instructions for obtaining the required credentials.

## Store Credentials

| Store | Credential Source |
|-------|-------------------|
| **Steam** | [Steam Web API](https://steamcommunity.com/dev/apikey) for API key |
| **IGDB** | [Twitch Developer Console](https://dev.twitch.tv/console/apps) (IGDB uses Twitch auth) |
| **Epic Games** | OAuth flow in Settings page |
| **GOG** | Reads from local GOG Galaxy database OR uses bookmarklet import (instructions in Settings) |
| **itch.io** | [itch.io API Keys](https://itch.io/user/settings/api-keys) |
| **Humble Bundle** | Session cookie from browser (instructions in Settings) |
| **Battle.net** | Session cookie from browser (instructions in Settings) |
| **Amazon** | OAuth flow in Settings page |
| **EA** | Bearer token via bookmarklet (instructions in Settings) |
| **Xbox / Game Pass** | XSTS token via bookmarklet or browser DevTools (instructions in Settings). Game Pass catalog syncs without authentication. |
| **Ubisoft** | Bookmarklet import from account.ubisoft.com (instructions in Settings) |
| **Local Folder** | Configure paths in `.env` file (see [Local Games](#local-games) below) |

---

## Local Games

Import games from local folders on your machine. Each subfolder is treated as a game and matched to IGDB for metadata.

### Setup

1. Add your game folder paths to `.env` (up to 5 by default):
   ```bash
   LOCAL_GAMES_DIR_1=/path/to/games
   LOCAL_GAMES_DIR_2=/mnt/storage/more-games
   # Add more in docker-compose.yml if you need more than 5
   ```

2. Restart the container (paths are mounted automatically):
   ```bash
   docker compose down && docker compose up -d
   ```

3. Click "Sync Local" in Settings to import games

### Folder Structure

```
/path/to/games/
├── The Witcher 3/          → Imported as "The Witcher 3"
├── DOOM 2016/              → Imported as "DOOM 2016"
└── Hollow Knight/          → Imported as "Hollow Knight"
```

### Override File (game.json)

For better IGDB matching or custom names, create a `game.json` file inside any game folder:

```json
{
  "name": "The Witcher 3: Wild Hunt",
  "igdb_id": 1942
}
```

All fields are optional:

| Field | Description |
|-------|-------------|
| `name` | Override the game name (used for display and IGDB matching) |
| `igdb_id` | Manually specify the IGDB game ID for exact matching |
| `description` | Custom description |
| `developers` | Array of developer names, e.g. `["CD Projekt Red"]` |
| `genres` | Array of genres, e.g. `["RPG", "Action"]` |
| `release_date` | Release date in ISO format, e.g. `"2015-05-19"` |
| `cover_image` | URL to a custom cover image |

**Example game.json:**
```json
{
  "name": "DOOM (2016)",
  "igdb_id": 7351,
  "developers": ["id Software"],
  "genres": ["FPS", "Action"]
}
```

After syncing local games, run "Sync Missing Metadata" to fetch cover images, ratings, and other data from IGDB.
