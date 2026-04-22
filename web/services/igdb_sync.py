# igdb_sync.py
# Matches games in our database to IGDB entries and fetches ratings/metadata

import sqlite3
import requests
import time
import json
import re
from datetime import datetime, timezone

from .settings import get_igdb_credentials, get_setting, IGDB_MATCH_THRESHOLD

# IGDB API endpoints
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
IGDB_API_URL = "https://api.igdb.com/v4"

# IGDB Popularity Type IDs (from /popularity_types endpoint)
POPULARITY_TYPE_IGDB_VISITS = 1
POPULARITY_TYPE_IGDB_WANT_TO_PLAY = 2
POPULARITY_TYPE_IGDB_PLAYING = 3
POPULARITY_TYPE_IGDB_PLAYED = 4
POPULARITY_TYPE_STEAM_PEAK_24H = 5
POPULARITY_TYPE_STEAM_POSITIVE_REVIEWS = 6


class IGDBClient:
    def __init__(self):
        self.access_token = None
        self.token_expires_at = 0
        creds = get_igdb_credentials()
        self.client_id = creds.get("client_id")
        self.client_secret = creds.get("client_secret")
        self._get_access_token()

    def _get_access_token(self):
        """Get access token from Twitch OAuth."""
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "IGDB credentials not configured. Please set them in Settings."
            )

        response = requests.post(
            TWITCH_TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
        )

        if response.status_code != 200:
            raise Exception(f"Failed to get access token: {response.text}")

        data = response.json()
        self.access_token = data["access_token"]
        self.token_expires_at = time.time() + data["expires_in"] - 60

        print(f"Got IGDB access token (expires in {data['expires_in'] // 3600} hours)")

    def _ensure_token(self):
        """Ensure we have a valid access token."""
        if time.time() >= self.token_expires_at:
            self._get_access_token()

    def _request(self, endpoint, body):
        """Make a request to the IGDB API."""
        self._ensure_token()

        response = requests.post(
            f"{IGDB_API_URL}/{endpoint}",
            headers={
                "Client-ID": self.client_id,
                "Authorization": f"Bearer {self.access_token}",
            },
            data=body,
        )

        if response.status_code == 429:
            # Rate limited - wait and retry
            retry_after = int(response.headers.get("Retry-After", 1))
            print(f"Rate limited, waiting {retry_after}s...")
            time.sleep(retry_after)
            return self._request(endpoint, body)

        if response.status_code != 200:
            print(f"IGDB API error: {response.status_code} - {response.text}")
            return None

        return response.json()

    def search_game(self, name):
        """Search for a game by name."""
        # Clean up the name for better matching
        clean_name = self._clean_game_name(name)

        # Try exact name match first (avoids DLC variants crowding results)
        body = f'''
            where name = "{clean_name}";
            fields id, name, slug, category, rating, rating_count, aggregated_rating,
                   aggregated_rating_count, total_rating, total_rating_count,
                   summary, storyline, first_release_date,
                   genres.name, themes.id, themes.name, platforms.name,
                   involved_companies.company.name, involved_companies.developer,
                   involved_companies.publisher,
                   cover.url, screenshots.url,
                   external_games.uid, external_games.category;
            limit 5;
        '''
        results = self._request("games", body)
        if results:
            return results

        # Fall back to fuzzy search with higher limit
        body = f'''
            search "{clean_name}";
            fields id, name, slug, category, rating, rating_count, aggregated_rating,
                   aggregated_rating_count, total_rating, total_rating_count,
                   summary, storyline, first_release_date,
                   genres.name, themes.id, themes.name, platforms.name,
                   involved_companies.company.name, involved_companies.developer,
                   involved_companies.publisher,
                   cover.url, screenshots.url,
                   external_games.uid, external_games.category;
            limit 15;
        '''
        return self._request("games", body)

    def get_game_by_steam_id(self, steam_id):
        """Get a game by its Steam App ID.

        Tries external_games first (fast indexed lookup), then falls back to
        websites.url substring match for games not in external_games.
        """
        # Fast path: external_games has an indexed uid column
        body = f'''
            where uid = "{steam_id}" & category = 1;
            fields game;
            limit 1;
        '''
        results = self._request("external_games", body)
        if results:
            igdb_id = results[0].get("game")
            if igdb_id:
                return self.get_game_by_id(igdb_id)

        # Fallback: websites.url substring match — better coverage but slower
        body = f'''
            where websites.url ~ *"steampowered.com/app/{steam_id}"*;
            fields id, name, slug, rating, rating_count, aggregated_rating,
                   aggregated_rating_count, total_rating, total_rating_count,
                   summary, storyline, first_release_date,
                   genres.name, themes.id, themes.name, platforms.name,
                   involved_companies.company.name, involved_companies.developer,
                   involved_companies.publisher,
                   cover.url, screenshots.url,
                   external_games.uid, external_games.category;
            limit 1;
        '''
        results = self._request("games", body)
        if results:
            return results[0]

        return None
    def get_game_by_slug(self, slug):
        """Get a game by its store slug."""
        body = f'''
            where slug = "{slug}";
            fields id, name, slug, rating, rating_count, aggregated_rating,
                   aggregated_rating_count, total_rating, total_rating_count,
                   summary, storyline, first_release_date,
                   genres.name, themes.id, themes.name, platforms.name,
                   involved_companies.company.name, involved_companies.developer,
                   involved_companies.publisher,
                   cover.url, screenshots.url,
                   external_games.uid, external_games.category;
            limit 1;
        '''
        req = self._request("games", body)

        if req:
            return req

        slug = re.sub(r'-[0-9a-f]{6}$', '', slug)
        
        body = f'''
            where slug = "{slug}";
            fields id, name, slug, rating, rating_count, aggregated_rating,
                   aggregated_rating_count, total_rating, total_rating_count,
                   summary, storyline, first_release_date,
                   genres.name, themes.id, themes.name, platforms.name,
                   involved_companies.company.name, involved_companies.developer,
                   involved_companies.publisher,
                   cover.url, screenshots.url,
                   external_games.uid, external_games.category;
            limit 1;
        '''
        req = self._request("games", body)

        if req:
            return req

        return {}

    def get_game_by_id(self, igdb_id):
        """Get a game by its IGDB ID."""
        results = self.get_games_by_ids([igdb_id])
        return results[0] if results else None

    def get_popularity_types(self):
        """Get all available popularity types from IGDB."""
        body = '''
            fields id, name, created_at, updated_at;
            limit 50;
        '''
        return self._request("popularity_types", body) or []

    def get_popular_games(self, game_ids, popularity_type=None, limit=50):
        """
        Get popularity data for specific game IDs.

        Args:
            game_ids: List of IGDB game IDs to check
            popularity_type: Optional popularity type ID to filter by
            limit: Max results to return

        Returns:
            List of popularity primitives sorted by value (highest first)
        """
        if not game_ids:
            return []

        # Build the where clause
        ids_str = ",".join(str(id) for id in game_ids)
        where_clause = f"game_id = ({ids_str})"

        if popularity_type:
            where_clause += f" & popularity_type = {popularity_type}"

        body = f'''
            where {where_clause};
            fields game_id, value, popularity_type, calculated_at;
            sort value desc;
            limit {limit};
        '''

        return self._request("popularity_primitives", body) or []



    def get_games_by_ids(self, igdb_ids):
        """Get multiple games by their IGDB IDs."""
        if not igdb_ids:
            return []

        ids_str = ",".join(str(id) for id in igdb_ids)
        body = f'''
            where id = ({ids_str});
            fields id, name, slug, category, rating, rating_count, aggregated_rating,
                   aggregated_rating_count, total_rating, total_rating_count,
                   summary, storyline, first_release_date,
                   genres.name, themes.id, themes.name, platforms.name,
                   involved_companies.company.name, involved_companies.developer,
                   involved_companies.publisher,
                   cover.url, screenshots.url, artworks.url, videos.video_id,
                   external_games.uid, external_games.category;
            limit 500;
        '''

        return self._request("games", body) or []

    def batch_lookup_steam(self, appids):
        """Batch lookup games by Steam App IDs via website URL matching.

        10 appids per request using OR queries. Better coverage than external_games.
        Returns a dict mapping appid (str) -> game data dict.
        """
        if not appids:
            return {}

        BATCH = 10
        results = {}
        total_batches = (len(appids) + BATCH - 1) // BATCH

        for start in range(0, len(appids), BATCH):
            batch_num = start // BATCH + 1
            print(f"  Steam batch {batch_num}/{total_batches} ({len(results)} matched so far)...", flush=True)
            chunk = appids[start:start + BATCH]
            where_parts = " | ".join(
                f'websites.url ~ *"steampowered.com/app/{appid}"*' for appid in chunk
            )
            body = f'''
                where {where_parts};
                fields id, name, slug, category, rating, rating_count, aggregated_rating,
                       aggregated_rating_count, total_rating, total_rating_count,
                       summary, storyline, first_release_date,
                       genres.name, themes.id, themes.name, platforms.name,
                       involved_companies.company.name, involved_companies.developer,
                       involved_companies.publisher,
                       cover.url, screenshots.url,
                       external_games.uid, external_games.category,
                       websites.url;
                limit {BATCH};
            '''
            games = self._request("games", body) or []
            for game in games:
                for website in game.get("websites", []):
                    url = website.get("url", "")
                    for appid in chunk:
                        if re.search(rf"/app/{re.escape(str(appid))}(?:[/?#]|$)", url):
                            results[str(appid)] = game
                            break
            if start + BATCH < len(appids):
                time.sleep(0.3)

        print(f"  Steam batch done: {len(results)}/{len(appids)} matched")
        return results

    def batch_lookup_epic_slugs(self, slugs):
        """Batch lookup Epic games via website URL matching on /p/{slug}.

        Returns a dict mapping slug (str) -> game data dict.
        """
        if not slugs:
            return {}

        BATCH = 10
        results = {}

        for start in range(0, len(slugs), BATCH):
            chunk = slugs[start:start + BATCH]
            where_parts = " | ".join(
                f'websites.url ~ *"/p/{slug}"*' for slug in chunk
            )
            body = f'''
                where {where_parts};
                fields id, name, slug, category, rating, rating_count, aggregated_rating,
                       aggregated_rating_count, total_rating, total_rating_count,
                       summary, storyline, first_release_date,
                       genres.name, themes.id, themes.name, platforms.name,
                       involved_companies.company.name, involved_companies.developer,
                       involved_companies.publisher,
                       cover.url, screenshots.url,
                       external_games.uid, external_games.category,
                       websites.url;
                limit {BATCH};
            '''
            games = self._request("games", body) or []
            for game in games:
                for website in game.get("websites", []):
                    url = website.get("url", "")
                    for s in chunk:
                        if re.search(rf"/p/{re.escape(s)}(?:[/?#]|$)", url):
                            results[s] = game
                            break
            if start + BATCH < len(slugs):
                time.sleep(0.3)

        return results

    def batch_lookup_gog_slugs(self, slugs):
        """Batch lookup GOG games via website URL matching on /game/{slug}.

        Returns a dict mapping slug (str) -> game data dict.
        """
        if not slugs:
            return {}

        BATCH = 10
        results = {}

        for start in range(0, len(slugs), BATCH):
            chunk = slugs[start:start + BATCH]
            where_parts = " | ".join(
                f'websites.url ~ *"/game/{slug}"*' for slug in chunk
            )
            body = f'''
                where {where_parts};
                fields id, name, slug, category, rating, rating_count, aggregated_rating,
                       aggregated_rating_count, total_rating, total_rating_count,
                       summary, storyline, first_release_date,
                       genres.name, themes.id, themes.name, platforms.name,
                       involved_companies.company.name, involved_companies.developer,
                       involved_companies.publisher,
                       cover.url, screenshots.url,
                       external_games.uid, external_games.category,
                       websites.url;
                limit {BATCH};
            '''
            games = self._request("games", body) or []
            for game in games:
                for website in game.get("websites", []):
                    url = website.get("url", "")
                    for s in chunk:
                        if re.search(rf"/game/{re.escape(s)}(?:[/?#]|$)", url):
                            results[s] = game
                            break
            if start + BATCH < len(slugs):
                time.sleep(0.3)

        return results

    def batch_lookup_slugs(self, slugs):
        """Batch lookup games by derived IGDB slugs (where slug = (...)).

        Returns a dict mapping slug (str) -> game data dict.
        """
        if not slugs:
            return {}

        BATCH = 50
        slug_list = list(slugs)
        results = {}

        for start in range(0, len(slug_list), BATCH):
            chunk = slug_list[start:start + BATCH]
            slugs_str = ",".join(f'"{s}"' for s in chunk)
            body = f'''
                where slug = ({slugs_str});
                fields id, name, slug, category, rating, rating_count, aggregated_rating,
                       aggregated_rating_count, total_rating, total_rating_count,
                       summary, storyline, first_release_date,
                       genres.name, themes.id, themes.name, platforms.name,
                       involved_companies.company.name, involved_companies.developer,
                       involved_companies.publisher,
                       cover.url, screenshots.url,
                       external_games.uid, external_games.category;
                limit {BATCH};
            '''
            games = self._request("games", body) or []
            for game in games:
                results[game["slug"]] = game
            if start + BATCH < len(slug_list):
                time.sleep(0.3)

        return results

    @staticmethod
    def derive_igdb_slug(name):
        """Derive a candidate IGDB slug from a game name.

        IGDB slugs are lowercase with non-alphanumeric chars replaced by hyphens.
        """
        if not name:
            return None
        slug = name.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = slug.strip("-")
        return slug or None

    @staticmethod
    def is_nsfw(game_data):
        """Check if a game should be marked as NSFW based on IGDB data."""
        if not game_data:
            return False

        # Check for Erotic theme (ID 42)
        themes = game_data.get("themes", [])
        for theme in themes:
            if theme.get("id") == 42:  # Erotic
                return True

        return False

    @staticmethod
    def extract_steam_app_id(game_data):
        """Extract Steam App ID from IGDB external_games data.

        IGDB external_games category 1 = Steam
        Returns the Steam App ID as a string, or None if not found.
        """
        if not game_data:
            return None

        external_games = game_data.get("external_games", [])
        for ext_game in external_games:
            # Category 1 = Steam
            if ext_game.get("category") == 1:
                return str(ext_game.get("uid"))

        return None

    def _clean_game_name(self, name):
        """Clean game name for better search matching."""
        if not name:
            return ""

        # Remove common suffixes/prefixes that hurt matching
        patterns_to_remove = [
            r"\s*\(.*?\)",  # Remove parenthetical content
            r"\s*-\s*Demo$",
            r"\s*Demo$",
            r"\s*\[.*?\]",  # Remove bracketed content
            r"™",
            r"®",
            r"©",
        ]

        clean = name
        for pattern in patterns_to_remove:
            clean = re.sub(pattern, "", clean, flags=re.IGNORECASE)

        # Remove double quotes — they break the IGDB search "..." query syntax
        clean = clean.replace('"', '')

        return clean.strip()


def add_igdb_columns(conn):
    """Add IGDB-related columns to the database if they don't exist."""
    cursor = conn.cursor()

    # Check existing columns
    cursor.execute("PRAGMA table_info(games)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    new_columns = [
        ("igdb_id", "INTEGER"),
        ("igdb_slug", "TEXT"),
        ("igdb_rating", "REAL"),  # User/community rating (0-100)
        ("igdb_rating_count", "INTEGER"),
        ("aggregated_rating", "REAL"),  # Critic rating (0-100)
        ("aggregated_rating_count", "INTEGER"),
        ("total_rating", "REAL"),  # Combined rating (0-100)
        ("total_rating_count", "INTEGER"),
        ("summary", "TEXT"),
        ("cover_url", "TEXT"),
        ("screenshots", "TEXT"),  # JSON array of screenshot URLs
        ("igdb_matched_at", "TIMESTAMP"),
        ("nsfw", "BOOLEAN DEFAULT 0"),  # NSFW flag (from IGDB themes/age ratings or manual)
        ("steam_app_id", "TEXT"),  # Steam App ID from IGDB external_games (for ProtonDB)
        ("igdb_release_date", "INTEGER"),  # IGDB first_release_date as Unix timestamp
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            cursor.execute(f"ALTER TABLE games ADD COLUMN {col_name} {col_type}")
            print(f"Added column: {col_name}")

    conn.commit()


def extract_genres_and_themes(igdb_data):
    """Extract genres and themes from IGDB data as a combined list of tag names."""
    tags = []

    # Extract genres (e.g., "Action", "RPG", "Adventure")
    if igdb_data.get("genres"):
        for genre in igdb_data["genres"]:
            if genre.get("name"):
                tags.append(genre["name"])

    # Extract themes (e.g., "Fantasy", "Sci-fi", "Horror")
    if igdb_data.get("themes"):
        for theme in igdb_data["themes"]:
            # Skip the "Erotic" theme (ID 42) - handled separately via NSFW flag
            if theme.get("id") == 42:
                continue
            if theme.get("name"):
                tags.append(theme["name"])

    return tags


def merge_and_dedupe_genres(existing_genres_json, new_genres):
    """
    Merge existing genres with new genres and de-duplicate.

    Args:
        existing_genres_json: JSON string of existing genres (or None)
        new_genres: List of new genre/theme names to add

    Returns:
        JSON string of merged and de-duplicated genres
    """
    # Parse existing genres
    existing = []
    if existing_genres_json:
        try:
            existing = json.loads(existing_genres_json)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, TypeError):
            existing = []

    # Combine and de-duplicate (case-insensitive, preserving original case)
    seen = set()
    merged = []

    for genre in existing + new_genres:
        if not genre:
            continue
        genre_lower = genre.lower().strip()
        if genre_lower not in seen:
            seen.add(genre_lower)
            merged.append(genre.strip())

    return json.dumps(merged) if merged else None


def apply_igdb_data(conn, game_id, igdb_game, existing_genres=None):
    """Apply IGDB game data to the database for a given game_id.

    Args:
        conn: Database connection
        game_id: The local game ID
        igdb_game: IGDB game data dict
        existing_genres: Optional pre-fetched genres JSON string; fetched from DB if None
    """
    cursor = conn.cursor()

    # Extract cover URL
    cover_url = None
    if igdb_game.get("cover"):
        cover_url = igdb_game["cover"].get("url", "")
        cover_url = cover_url.replace("t_thumb", "t_cover_big")
        if cover_url and not cover_url.startswith("http"):
            cover_url = "https:" + cover_url

    # Extract up to 5 screenshot URLs
    screenshots = []
    if igdb_game.get("screenshots"):
        for screenshot in igdb_game["screenshots"][:5]:
            url = screenshot.get("url", "")
            url = url.replace("t_thumb", "t_screenshot_big")
            if url and not url.startswith("http"):
                url = "https:" + url
            screenshots.append(url)

    # Check if game is NSFW
    is_nsfw = IGDBClient.is_nsfw(igdb_game)

    # Extract Steam App ID from IGDB external_games
    steam_app_id = IGDBClient.extract_steam_app_id(igdb_game)

    # Fetch existing genres if not provided
    if existing_genres is None:
        cursor.execute("SELECT genres FROM games WHERE id = ?", (game_id,))
        row = cursor.fetchone()
        existing_genres = row[0] if row else None

    # Extract genres and themes from IGDB and merge with existing
    igdb_tags = extract_genres_and_themes(igdb_game)
    merged_genres = merge_and_dedupe_genres(existing_genres, igdb_tags)

    cursor.execute(
        """UPDATE games SET
            igdb_id = ?,
            igdb_slug = ?,
            igdb_rating = ?,
            igdb_rating_count = ?,
            aggregated_rating = ?,
            aggregated_rating_count = ?,
            total_rating = ?,
            total_rating_count = ?,
            summary = COALESCE(summary, ?),
            cover_url = COALESCE(cover_url, ?),
            screenshots = COALESCE(screenshots, ?),
            igdb_matched_at = CURRENT_TIMESTAMP,
            nsfw = ?,
            genres = ?,
            steam_app_id = COALESCE(steam_app_id, ?),
            igdb_release_date = ?
        WHERE id = ?""",
        (
            igdb_game.get("id"),
            igdb_game.get("slug"),
            igdb_game.get("rating"),
            igdb_game.get("rating_count"),
            igdb_game.get("aggregated_rating"),
            igdb_game.get("aggregated_rating_count"),
            igdb_game.get("total_rating"),
            igdb_game.get("total_rating_count"),
            igdb_game.get("summary"),
            cover_url,
            json.dumps(screenshots) if screenshots else None,
            1 if is_nsfw else 0,
            merged_genres,
            steam_app_id,
            igdb_game.get("first_release_date"),
            game_id,
        ),
    )


def calculate_match_score(game_name, igdb_result, game_release_year=None):
    """Calculate how well an IGDB result matches our game.

    Args:
        game_name: The game name from our database
        igdb_result: The IGDB search result dict
        game_release_year: Optional release year (int) from the store's release_date
    """
    if not igdb_result or not game_name:
        return 0

    igdb_name = igdb_result.get("name", "").lower()
    our_name = game_name.lower()

    # Exact match
    if our_name == igdb_name:
        score = 100
    # One contains the other
    elif our_name in igdb_name or igdb_name in our_name:
        score = 80
        # Penalize when IGDB name is much longer — likely a DLC/expansion with the
        # base game name as prefix (e.g. "100% OJ" vs "100% OJ: Krila & Kae")
        len_ratio = len(our_name) / len(igdb_name)
        if len_ratio < 0.85:
            score -= 20
    else:
        # Check word overlap
        our_words = set(re.findall(r"\w+", our_name))
        igdb_words = set(re.findall(r"\w+", igdb_name))

        if not our_words:
            return 0

        overlap = len(our_words & igdb_words)
        score = (overlap / len(our_words)) * 70

    # Penalize DLC/addon/expansion/mod categories (IGDB category field)
    # 0=main_game, 1=dlc_addon, 2=expansion, 5=mod, 6=episode, 7=season, 13=pack, 14=update
    DLC_CATEGORIES = {1, 2, 5, 6, 7, 13, 14}
    game_category = igdb_result.get("category")
    if game_category in DLC_CATEGORIES:
        score -= 30

    # Apply release year bonus/penalty if both sides have year data
    if game_release_year and igdb_result.get("first_release_date"):
        igdb_year = datetime.fromtimestamp(
            igdb_result["first_release_date"], tz=timezone.utc
        ).year
        year_diff = abs(game_release_year - igdb_year)

        if year_diff == 0:
            score += 10
        elif year_diff == 1:
            pass  # No change - accounts for regional release differences
        elif year_diff <= 3:
            score -= 15
        else:
            score -= 30

    return score


def sync_games(conn, client, limit=None, force=False, progress_callback=None):
    """Sync games with IGDB.

    Args:
        conn: Database connection
        client: IGDBClient instance
        limit: Maximum number of games to process
        force: If True, resync all games; if False, only sync unmatched games
        progress_callback: Optional callback function(current, total, message) for progress updates
    """
    cursor = conn.cursor()

    if force:
        cursor.execute(
            "SELECT id, name, store, genres, release_date, store_id, extra_data FROM games WHERE name IS NOT NULL ORDER BY name"
        )
    else:
        cursor.execute(
            """SELECT id, name, store, genres, release_date, store_id, extra_data FROM games
               WHERE name IS NOT NULL AND igdb_id IS NULL
               ORDER BY name"""
        )

    games = cursor.fetchall()
    if limit:
        games = games[:limit]

    total = len(games)
    print(f"Processing {total} games...")

    matched = 0
    failed = 0

    steam_games = [
        (gid, name, store, genres, rd, sid, extra)
        for gid, name, store, genres, rd, sid, extra in games
        if store == "steam" and sid
    ]
    if steam_games:
        print(f"Batch-resolving {len(steam_games)} Steam games...")
        if progress_callback:
            progress_callback(0, total, f"Batch-resolving {len(steam_games)} Steam games...")
        appids = [sid for _, _, _, _, _, sid, _ in steam_games]
        appid_to_game = client.batch_lookup_steam(appids)
        fallback_steam = []
        for gid, name, store, existing_genres, rd, sid, _ in steam_games:
            game_data = appid_to_game.get(str(sid))
            if game_data:
                apply_igdb_data(conn, gid, game_data, existing_genres=existing_genres)
                conn.commit()
                rating_str = f" (rating: {game_data['total_rating']:.1f})" if game_data.get("total_rating") else ""
                print(f"  [{sid}] matched: {game_data['name']}{rating_str}")
                matched += 1
            else:
                fallback_steam.append((gid, name, store, existing_genres, rd, sid, None))
        if fallback_steam:
            print(f"  {len(fallback_steam)} Steam games not found by URL, will try name search")
    else:
        fallback_steam = []

    epic_games = []
    for gid, name, store, genres, rd, sid, extra_raw in games:
        if store != "epic":
            continue
        product_slug = None
        if extra_raw:
            try:
                product_slug = json.loads(extra_raw).get("product_slug")
            except (json.JSONDecodeError, TypeError):
                pass
        epic_games.append((gid, name, store, genres, rd, sid, product_slug))

    epic_with_slug = [(gid, n, s, g, rd, sid, slug) for gid, n, s, g, rd, sid, slug in epic_games if slug]
    epic_no_slug   = [(gid, n, s, g, rd, sid, slug) for gid, n, s, g, rd, sid, slug in epic_games if not slug]

    if epic_with_slug:
        print(f"Batch-resolving {len(epic_with_slug)} Epic games by slug URL...")
        if progress_callback:
            progress_callback(0, total, f"Batch-resolving {len(epic_with_slug)} Epic games...")
        slugs = [slug for _, _, _, _, _, _, slug in epic_with_slug]
        slug_to_game = client.batch_lookup_epic_slugs(slugs)
        fallback_epic = list(epic_no_slug)
        for gid, name, store, existing_genres, rd, sid, slug in epic_with_slug:
            game_data = slug_to_game.get(slug)
            if game_data:
                apply_igdb_data(conn, gid, game_data, existing_genres=existing_genres)
                conn.commit()
                rating_str = f" (rating: {game_data['total_rating']:.1f})" if game_data.get("total_rating") else ""
                print(f"  [{slug}] matched: {game_data['name']}{rating_str}")
                matched += 1
            else:
                fallback_epic.append((gid, name, store, existing_genres, rd, sid, None))
        if fallback_epic:
            print(f"  {len(fallback_epic)} Epic games not found by slug, will try name search")
    else:
        fallback_epic = list(epic_no_slug)

    gog_games = []
    for gid, name, store, genres, rd, sid, extra_raw in games:
        if store != "gog":
            continue
        gog_slug = None
        if extra_raw:
            try:
                store_url = json.loads(extra_raw).get("store_url", "")
                m = re.search(r"/game/([^/?#]+)", store_url)
                if m:
                    gog_slug = m.group(1)
            except (json.JSONDecodeError, TypeError):
                pass
        gog_games.append((gid, name, store, genres, rd, sid, gog_slug))

    gog_with_slug = [(gid, n, s, g, rd, sid, slug) for gid, n, s, g, rd, sid, slug in gog_games if slug]
    gog_no_slug   = [(gid, n, s, g, rd, sid, slug) for gid, n, s, g, rd, sid, slug in gog_games if not slug]

    if gog_with_slug:
        print(f"Batch-resolving {len(gog_with_slug)} GOG games by slug URL...")
        if progress_callback:
            progress_callback(0, total, f"Batch-resolving {len(gog_with_slug)} GOG games...")
        slugs = [slug for _, _, _, _, _, _, slug in gog_with_slug]
        slug_to_game = client.batch_lookup_gog_slugs(slugs)
        fallback_gog = list(gog_no_slug)
        for gid, name, store, existing_genres, rd, sid, slug in gog_with_slug:
            game_data = slug_to_game.get(slug)
            if game_data:
                apply_igdb_data(conn, gid, game_data, existing_genres=existing_genres)
                conn.commit()
                rating_str = f" (rating: {game_data['total_rating']:.1f})" if game_data.get("total_rating") else ""
                print(f"  [{slug}] matched: {game_data['name']}{rating_str}")
                matched += 1
            else:
                fallback_gog.append((gid, name, store, existing_genres, rd, sid, None))
        if fallback_gog:
            print(f"  {len(fallback_gog)} GOG games not found by slug, will try name search")
    else:
        fallback_gog = list(gog_no_slug)

    amazon_games = []
    for gid, name, store, genres, rd, sid, extra_raw in games:
        if store != "amazon":
            continue
        steam_appid = None
        if extra_raw:
            try:
                data = json.loads(extra_raw)
                steam_url = (
                    data.get("product", {})
                        .get("productDetail", {})
                        .get("details", {})
                        .get("websites", {})
                        .get("STEAM")
                )
                if steam_url:
                    m = re.search(r"/app/(\d+)", steam_url)
                    if m:
                        steam_appid = m.group(1)
            except (json.JSONDecodeError, TypeError):
                pass
        amazon_games.append((gid, name, store, genres, rd, sid, steam_appid))

    amazon_with_appid = [(gid, n, s, g, rd, sid, appid) for gid, n, s, g, rd, sid, appid in amazon_games if appid]
    amazon_no_appid   = [(gid, n, s, g, rd, sid, appid) for gid, n, s, g, rd, sid, appid in amazon_games if not appid]

    if amazon_with_appid:
        print(f"Batch-resolving {len(amazon_with_appid)} Amazon games via Steam appid...")
        if progress_callback:
            progress_callback(0, total, f"Batch-resolving {len(amazon_with_appid)} Amazon games...")
        appids = [appid for _, _, _, _, _, _, appid in amazon_with_appid]
        appid_to_game = client.batch_lookup_steam(appids)
        fallback_amazon = list(amazon_no_appid)
        for gid, name, store, existing_genres, rd, sid, appid in amazon_with_appid:
            game_data = appid_to_game.get(str(appid))
            if game_data:
                apply_igdb_data(conn, gid, game_data, existing_genres=existing_genres)
                conn.commit()
                rating_str = f" (rating: {game_data['total_rating']:.1f})" if game_data.get("total_rating") else ""
                print(f"  [{appid}] matched: {game_data['name']}{rating_str}")
                matched += 1
            else:
                fallback_amazon.append((gid, name, store, existing_genres, rd, sid, None))
        if fallback_amazon:
            print(f"  {len(fallback_amazon)} Amazon games not found by Steam appid, will try name search")
    else:
        fallback_amazon = list(amazon_no_appid)

    batch_resolved_ids = (
        {g[0] for g in steam_games} |
        {g[0] for g in epic_games} |
        {g[0] for g in gog_games} |
        {g[0] for g in amazon_games}
    )
    other_games = [
        (gid, name, store, genres, rd, sid, extra)
        for gid, name, store, genres, rd, sid, extra in games
        if gid not in batch_resolved_ids
    ]
    slug_fallback_pool = fallback_steam + fallback_epic + fallback_gog + fallback_amazon + other_games

    slug_map = {}   # candidate_slug -> [(game_id, name, existing_genres, release_date)]
    no_slug_games = []
    for gid, name, store, existing_genres, rd, sid, _ in slug_fallback_pool:
        candidate = IGDBClient.derive_igdb_slug(client._clean_game_name(name))
        if candidate:
            slug_map.setdefault(candidate, []).append((gid, name, existing_genres, rd))
        else:
            no_slug_games.append((gid, name, store, existing_genres, rd, sid, None))

    slug_to_game = {}
    if slug_map:
        print(f"Batch slug lookup for {len(slug_map)} unique slugs...")
        if progress_callback:
            progress_callback(0, total, f"Batch slug lookup ({len(slug_map)} slugs)...")
        slug_to_game = client.batch_lookup_slugs(slug_map.keys())

    sequential_games = []
    for candidate_slug, game_list in slug_map.items():
        game_data = slug_to_game.get(candidate_slug)
        for gid, name, existing_genres, rd in game_list:
            if game_data:
                apply_igdb_data(conn, gid, game_data, existing_genres=existing_genres)
                conn.commit()
                rating_str = f" (rating: {game_data['total_rating']:.1f})" if game_data.get("total_rating") else ""
                print(f"  [{candidate_slug}] slug matched: {game_data['name']}{rating_str}")
                matched += 1
            else:
                sequential_games.append((gid, name, None, existing_genres, rd, None, None))

    sequential_games.extend(no_slug_games)

    min_match_score = int(get_setting(IGDB_MATCH_THRESHOLD, "50"))
    seq_total = len(sequential_games)
    if seq_total:
        print(f"Name search for {seq_total} remaining unmatched games...")

    for i, (gid, name, store, existing_genres, rd, sid, _) in enumerate(sequential_games):
        print(f"[{i+1}/{seq_total}] Searching for: {name}...", end=" ", flush=True)

        if progress_callback:
            done = total - seq_total + i
            progress_callback(done + 1, total, f"Processing: {name[:50]}...")

        game_release_year = None
        if rd:
            try:
                game_release_year = int(str(rd)[:4])
            except (ValueError, IndexError):
                pass

        try:
            results = client.search_game(name)

            if not results:
                print("No results")
                cursor.execute(
                    "UPDATE games SET igdb_id = 0, igdb_matched_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (gid,)
                )
                conn.commit()
                failed += 1
                time.sleep(0.3)
                continue

            best_match = None
            best_score = 0
            for result in results:
                score = calculate_match_score(name, result, game_release_year)
                if score > best_score:
                    best_score = score
                    best_match = result

            if best_match and best_score >= min_match_score:
                apply_igdb_data(conn, gid, best_match, existing_genres=existing_genres)
                conn.commit()
                rating_str = f" (rating: {best_match['total_rating']:.1f})" if best_match.get("total_rating") else ""
                print(f"matched: {best_match['name']} (score: {best_score:.0f}){rating_str}")
                matched += 1
            else:
                print(f"No good match (best score: {best_score:.0f})")
                cursor.execute(
                    "UPDATE games SET igdb_id = 0, igdb_matched_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (gid,)
                )
                conn.commit()
                failed += 1

            time.sleep(0.3)

        except Exception as e:
            print(f"Error: {e}")
            failed += 1

    return matched, failed


def get_stats(conn):
    """Get IGDB sync statistics."""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM games")
    total = cursor.fetchone()[0]

    # Count matched games (igdb_id > 0, not counting 0 which means "not found")
    cursor.execute("SELECT COUNT(*) FROM games WHERE igdb_id IS NOT NULL AND igdb_id > 0")
    matched = cursor.fetchone()[0]

    cursor.execute(
        "SELECT AVG(total_rating) FROM games WHERE total_rating IS NOT NULL"
    )
    avg_rating = cursor.fetchone()[0]

    cursor.execute(
        """SELECT name, total_rating FROM games
           WHERE total_rating IS NOT NULL
           ORDER BY total_rating DESC LIMIT 5"""
    )
    top_rated = cursor.fetchall()

    return {
        "total": total,
        "matched": matched,
        "match_rate": (matched / total * 100) if total > 0 else 0,
        "avg_rating": avg_rating,
        "top_rated": top_rated,
    }
