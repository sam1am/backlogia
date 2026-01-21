# Backlogia

**Your entire game library, finally in one place.**

Stop jumping between Steam, Epic, GOG, and a dozen other launchers just to see what you own. Backlogia aggregates all your games into a single, beautifully organized library with rich metadata, ratings, and discovery features—all running locally on your machine.

![Library View](docs/images/library.png)

---

## Supported Stores

<p align="center">
  <img src="web/static/images/steam-100.png" alt="Steam" width="48" height="48" style="margin: 0 10px;">
  <img src="web/static/images/epic-100.png" alt="Epic Games" width="48" height="48" style="margin: 0 10px;">
  <img src="web/static/images/gog-48.png" alt="GOG" width="48" height="48" style="margin: 0 10px;">
  <img src="web/static/images/itch-90.png" alt="itch.io" width="48" height="48" style="margin: 0 10px;">
  <img src="web/static/images/humble-96.png" alt="Humble Bundle" width="48" height="48" style="margin: 0 10px;">
</p>

<p align="center">
  <strong>Steam</strong> &nbsp;•&nbsp; <strong>Epic Games</strong> &nbsp;•&nbsp; <strong>GOG</strong> &nbsp;•&nbsp; <strong>itch.io</strong> &nbsp;•&nbsp; <strong>Humble Bundle</strong>
</p>

---

## Features

### Unified Library

All your games from every store, displayed in one place. Smart deduplication ensures games you own on multiple platforms appear as a single entry with all your purchase information intact.

![Library](docs/images/library.png)

- **Multi-store filtering** — Filter by store, genre, or search by name
- **Flexible sorting** — Sort by name, rating, playtime, or release date
- **Store indicators** — See at a glance which platforms you own each game on

### Rich Game Details

Every game is enriched with metadata from IGDB (Internet Game Database), giving you consistent information across all stores.

![Game Details](docs/images/game_preview.png)

- **Ratings** — Community ratings, critic scores, and aggregated scores
- **Screenshots** — High-quality screenshots from IGDB
- **Direct store links** — Jump straight to any store page
- **Playtime tracking** — See your Steam playtime stats

### Discover Your Library

Find your next game to play with curated discovery sections based on your actual library.

![Discover](docs/images/discover.png)

![Discover Sections](docs/images/discover_sections.png)

- **Popular games** — Based on IGDB popularity metrics
- **Highly rated** — Games scoring 90+ ratings
- **Hidden gems** — Quality games that deserve more attention
- **Most played** — Your games ranked by playtime
- **Random pick** — Can't decide? Let Backlogia choose for you

### Custom Collections

Organize games your way with custom collections that work across all stores.

![Collections](docs/images/collections.png)

- Create themed collections like "Weekend Playlist" or "Couch Co-op"
- Add games from any store to any collection
- Visual collection covers with game thumbnails

### Settings & Sync

Connect your accounts and sync your library with a single click.

![Settings](docs/images/settings.png)

- One-click sync per store or sync everything at once
- Secure credential storage
- IGDB integration for metadata enrichment

---

## Setup

### Prerequisites

- **Python 3.11+** (for local installation)
- **Docker & Docker Compose** (for containerized installation)
- API keys for the stores you want to sync (see [Configuration](#configuration))

### Option 1: Docker (Recommended)

1. **Clone the repository**
   ```bash
   git clone https://github.com/sam1am/backlogia.git
   cd backlogia
   ```

2. **Create your environment file**
   ```bash
   cp .env.example .env
   ```

3. **Edit `.env` with your API credentials** (see [Configuration](#configuration))

4. **Start the container**
   ```bash
   docker compose up -d
   ```

5. **Access Backlogia** at [http://localhost:5050](http://localhost:5050)

#### Docker Volumes

| Volume | Purpose |
|--------|---------|
| `./data:/data` | Database and persistent storage |
| `./data/legendary:/root/.config/legendary` | Epic Games authentication cache |
| `${GOG_DB_DIR}:/gog:ro` | GOG Galaxy database (read-only) |

### Option 2: Local Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/backlogia.git
   cd backlogia
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Create your environment file**
   ```bash
   cp .env.example .env
   ```

5. **Edit `.env` with your API credentials** (see [Configuration](#configuration))

6. **Initialize the database**
   ```bash
   python scripts/build_database.py
   ```

7. **Run the application**
   ```bash
   python web/app.py
   ```

8. **Access Backlogia** at [http://localhost:5050](http://localhost:5050)

---

## Configuration

Configure your store connections by editing the `.env` file or through the Settings page in the app.

### Steam

| Variable | Description |
|----------|-------------|
| `STEAM_ID` | Your 17-digit Steam ID |
| `STEAM_API_KEY` | Get one at [Steam Web API](https://steamcommunity.com/dev/apikey) |

### IGDB (Metadata)

| Variable | Description |
|----------|-------------|
| `IGDB_CLIENT_ID` | Twitch Developer Client ID |
| `IGDB_CLIENT_SECRET` | Twitch Developer Client Secret |

Get your credentials at [Twitch Developer Console](https://dev.twitch.tv/console/apps) (IGDB uses Twitch authentication).

### Epic Games

Epic Games uses the [Legendary](https://github.com/derrod/legendary) CLI. Authenticate through the Settings page in Backlogia or run:
```bash
legendary auth
```

### GOG Galaxy

| Variable | Description |
|----------|-------------|
| `GOG_DB_DIR` | Directory containing `galaxy-2.0.db` |

Default locations:
- **macOS**: `/Users/Shared/GOG.com/Galaxy/Storage`
- **Windows**: `C:/ProgramData/GOG.com/Galaxy/storage`

### itch.io

| Variable | Description |
|----------|-------------|
| `ITCH_API_KEY` | Your itch.io API key from [itch.io settings](https://itch.io/user/settings/api-keys) |

### Humble Bundle

| Variable | Description |
|----------|-------------|
| `HUMBLE_SESSION_COOKIE` | Your `_simpleauth_sess` cookie from humblebundle.com |

To get your session cookie:
1. Log in to [humblebundle.com](https://humblebundle.com)
2. Open browser DevTools (F12) → Application → Cookies
3. Copy the value of `_simpleauth_sess`

---

## Tech Stack

- **Backend**: Flask (Python)
- **Database**: SQLite
- **Frontend**: Jinja2 templates, vanilla JavaScript
- **Metadata**: IGDB API integration
- **Deployment**: Docker + Docker Compose

---

## License

MIT License - See [LICENSE](LICENSE) for details.
