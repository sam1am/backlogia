# metacritic_sync.py
# Fetches Metacritic scores for games in our database

import sqlite3
import requests
import time
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed


# Metacritic's internal backend API key (public, embedded in their frontend bundle).
# If requests start failing with 401/403 the key has rotated; _discover_api_key() will
# re-scrape it from the homepage automatically.
_MC_API_KEY = "1MOZgmNFxvmljaQR1X9KAij9Mo4xAY3u"
_MC_BACKEND = "https://backend.metacritic.com"
_api_key_lock = threading.Lock()


def _discover_api_key():
    """Re-fetch the API key from Metacritic's homepage and update the module-level cache."""
    global _MC_API_KEY
    try:
        r = requests.get(
            "https://www.metacritic.com",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15,
        )
        m = re.search(r"apiKey=([A-Za-z0-9]{20,})", r.text)
        if m:
            with _api_key_lock:
                _MC_API_KEY = m.group(1)
            print(f"[metacritic] refreshed API key: {_MC_API_KEY[:8]}...")
    except Exception as e:
        print(f"[metacritic] could not refresh API key: {e}")


class MetacriticClient:
    """Client for fetching game data from Metacritic's backend JSON API."""

    BASE_URL = "https://www.metacritic.com"

    def __init__(self, min_request_interval=0.5):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.metacritic.com",
        })
        self.last_request_time = 0
        self.min_request_interval = min_request_interval
        self._lock = threading.Lock()

    def _rate_limit(self):
        """Ensure we don't make requests too quickly (thread-safe)."""
        with self._lock:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.min_request_interval:
                time.sleep(self.min_request_interval - elapsed)
            self.last_request_time = time.time()

    def _get(self, url):
        """Make a rate-limited GET request, returning parsed JSON or None.

        On 401/403 (key rotated), auto-discovers the new key and retries once.
        """
        self._rate_limit()
        try:
            response = self.session.get(url, timeout=15)
            if response.status_code in (401, 403):
                print("[metacritic] API key rejected, attempting to refresh...")
                _discover_api_key()
                # Rebuild URL with new key (replace the old key value)
                url = re.sub(r"apiKey=[A-Za-z0-9]+", f"apiKey={_MC_API_KEY}", url)
                self._rate_limit()
                response = self.session.get(url, timeout=15)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Request error: {e}")
            return None

    def search_game(self, name):
        """
        Search Metacritic for a game by name using the backend JSON API.

        Returns a list of results with: name, slug, url, score
        """
        clean_name = self._clean_game_name(name)
        url = (
            f"{_MC_BACKEND}/finder/metacritic/search/{requests.utils.quote(clean_name)}/web"
            f"?apiKey={_MC_API_KEY}&mcoTypeId=13&limit=10&page=1"
        )

        data = self._get(url)
        if not data:
            return []

        items = data.get("data", {}).get("items", [])
        results = []
        for item in items:
            if item.get("type") != "game-title":
                continue
            slug = item.get("slug")
            title = item.get("title")
            if not slug or not title:
                continue
            critic_score = None
            score_summary = item.get("criticScoreSummary") or {}
            raw_score = score_summary.get("score")
            if isinstance(raw_score, (int, float)) and raw_score > 0:
                critic_score = int(raw_score)
            results.append({
                "name": title,
                "slug": slug,
                "url": f"{self.BASE_URL}/game/{slug}/",
                "score": critic_score,
            })

        return results

    def get_game_by_slug(self, slug):
        """
        Get game details by Metacritic slug using the backend JSON API.

        Returns dict with: name, slug, url, critic_score, user_score
        """
        slug = slug.strip().lower()
        slug = re.sub(r"[^a-z0-9-]", "", slug)

        # Search returns critic score inline; fetch user score from the stats endpoint
        search_url = (
            f"{_MC_BACKEND}/finder/metacritic/search/{requests.utils.quote(slug)}/web"
            f"?apiKey={_MC_API_KEY}&mcoTypeId=13&limit=5&page=1"
        )
        search_data = self._get(search_url)

        critic_score = None
        name = None
        if search_data:
            for item in search_data.get("data", {}).get("items", []):
                if item.get("slug") == slug and item.get("type") == "game-title":
                    name = item.get("title")
                    ss = item.get("criticScoreSummary") or {}
                    raw = ss.get("score")
                    if isinstance(raw, (int, float)) and raw > 0:
                        critic_score = int(raw)
                    break

        # Fetch user score from the dedicated stats endpoint
        user_score = None
        stats_url = (
            f"{_MC_BACKEND}/reviews/metacritic/user/games/{slug}/stats/web"
            f"?apiKey={_MC_API_KEY}&componentName=user-score-summary"
            f"&componentDisplayName=User+Score+Summary&componentType=MetaScoreSummary"
        )
        stats_data = self._get(stats_url)
        if stats_data:
            item = stats_data.get("data", {}).get("item") or {}
            raw = item.get("score")
            if isinstance(raw, (int, float)) and 0 < raw <= 10:
                user_score = float(raw)

        return {
            "name": name,
            "slug": slug,
            "url": f"{self.BASE_URL}/game/{slug}/",
            "critic_score": critic_score,
            "user_score": user_score,
        }

    @staticmethod
    def _clean_game_name(name):
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
            r"\s*:\s*[^:]+Edition$",  # Remove edition suffixes
            r"\s*Deluxe\s*Edition$",
            r"\s*Gold\s*Edition$",
            r"\s*GOTY\s*Edition$",
        ]

        clean = name
        for pattern in patterns_to_remove:
            clean = re.sub(pattern, "", clean, flags=re.IGNORECASE)

        return clean.strip()


def add_metacritic_columns(conn):
    """Add Metacritic-related columns to the database if they don't exist."""
    cursor = conn.cursor()

    # Check existing columns
    cursor.execute("PRAGMA table_info(games)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    new_columns = [
        ("metacritic_score", "INTEGER"),  # Critic score 0-100
        ("metacritic_user_score", "REAL"),  # User score 0-10
        ("metacritic_url", "TEXT"),  # URL to the game page
        ("metacritic_slug", "TEXT"),  # Custom override for game matching
        ("metacritic_matched_at", "TIMESTAMP"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            cursor.execute(f"ALTER TABLE games ADD COLUMN {col_name} {col_type}")
            print(f"Added column: {col_name}")

    conn.commit()


def calculate_match_score(game_name, metacritic_result):
    """Calculate how well a Metacritic result matches our game."""
    if not metacritic_result or not game_name:
        return 0

    mc_name = metacritic_result.get("name", "").lower() if metacritic_result.get("name") else ""
    our_name = game_name.lower()

    if not mc_name:
        # Fall back to slug
        mc_name = metacritic_result.get("slug", "").replace("-", " ")

    # Exact match
    if our_name == mc_name:
        return 100

    # One contains the other
    if our_name in mc_name or mc_name in our_name:
        return 80

    # Check word overlap
    our_words = set(re.findall(r"\w+", our_name))
    mc_words = set(re.findall(r"\w+", mc_name))

    if not our_words:
        return 0

    overlap = len(our_words & mc_words)
    score = (overlap / len(our_words)) * 70

    return score


def _process_single_game(client, game_id, name):
    """
    Process a single game for Metacritic data.
    Returns a tuple of (game_id, success, result_dict or error_message).
    """
    try:
        results = client.search_game(name)

        if not results:
            return (game_id, False, "No results")

        # Find best match
        best_match = None
        best_score = 0

        for result in results:
            score = calculate_match_score(name, result)
            if score > best_score:
                best_score = score
                best_match = result

        if best_match and best_score >= 50:
            # Fetch full details for the matched game
            details = client.get_game_by_slug(best_match["slug"])

            if details:
                return (game_id, True, {
                    "critic_score": details.get("critic_score"),
                    "user_score": details.get("user_score"),
                    "url": details.get("url"),
                    "slug": details.get("slug"),
                    "match_name": best_match.get("name", best_match["slug"]),
                    "match_score": best_score,
                })
            else:
                return (game_id, False, f"Could not fetch details for: {best_match['slug']}")
        else:
            return (game_id, False, f"No good match (best score: {best_score:.0f})")

    except Exception as e:
        return (game_id, False, f"Error: {e}")


def sync_games(conn, client, limit=None, force=False, max_workers=5, progress_callback=None):
    """Sync games with Metacritic using multithreading.

    Args:
        conn: Database connection
        client: MetacriticClient instance
        limit: Maximum number of games to process
        force: If True, resync all games; if False, only sync unmatched games
        max_workers: Number of parallel workers
        progress_callback: Optional callback function(current, total, message) for progress updates
    """
    cursor = conn.cursor()

    # Get games that haven't been matched yet (or all if force)
    # Skip hidden games and deduplicate by name (for games owned on multiple stores)
    if force:
        cursor.execute(
            """SELECT MIN(id) as id, name FROM games
               WHERE name IS NOT NULL AND (hidden IS NULL OR hidden = 0)
               GROUP BY LOWER(name)
               ORDER BY name"""
        )
    else:
        cursor.execute(
            """SELECT MIN(id) as id, name FROM games
               WHERE name IS NOT NULL
               AND metacritic_score IS NULL
               AND metacritic_slug IS NULL
               AND (hidden IS NULL OR hidden = 0)
               GROUP BY LOWER(name)
               ORDER BY name"""
        )

    games = cursor.fetchall()

    if limit:
        games = games[:limit]

    total = len(games)
    print(f"Processing {total} games for Metacritic scores with {max_workers} workers...")

    matched = 0
    failed = 0
    completed = 0
    results_lock = threading.Lock()

    def update_database(game_id, name, result):
        """Update the database with the result for all games with this name (handles multi-store ownership)."""
        # Update all games with the same name (case-insensitive) to sync across stores
        cursor.execute(
            """UPDATE games SET
                metacritic_score = ?,
                metacritic_user_score = ?,
                metacritic_url = ?,
                metacritic_slug = ?,
                metacritic_matched_at = CURRENT_TIMESTAMP
            WHERE LOWER(name) = LOWER(?)""",
            (
                result["critic_score"],
                result["user_score"],
                result["url"],
                result["slug"],
                name,
            ),
        )

    def mark_not_found(name):
        """Mark all games with this name as searched but not found (metacritic_score = -1)."""
        cursor.execute(
            """UPDATE games SET
                metacritic_score = -1,
                metacritic_matched_at = CURRENT_TIMESTAMP
            WHERE LOWER(name) = LOWER(?)""",
            (name,),
        )

    # Process games in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_game = {
            executor.submit(_process_single_game, client, game_id, name): (game_id, name)
            for game_id, name in games
        }

        # Process results as they complete
        for future in as_completed(future_to_game):
            game_id, name = future_to_game[future]
            completed += 1

            # Report progress
            if progress_callback:
                progress_callback(completed, total, f"Processing: {name[:50]}...")

            try:
                result_game_id, success, result = future.result()

                if success:
                    # Update database (SQLite operations need to be serialized)
                    with results_lock:
                        update_database(result_game_id, name, result)
                        conn.commit()
                        matched += 1

                    score_str = ""
                    if result.get("critic_score"):
                        score_str = f" (Critic: {result['critic_score']}"
                        if result.get("user_score"):
                            score_str += f", User: {result['user_score']}"
                        score_str += ")"

                    print(f"[{completed}/{total}] {name} → Matched: {result['match_name']} (match: {result['match_score']:.0f}){score_str}")
                else:
                    # Mark as searched but not found
                    with results_lock:
                        mark_not_found(name)
                        conn.commit()
                        failed += 1
                    print(f"[{completed}/{total}] {name} → {result}")

            except Exception as e:
                # Mark as searched but not found on exception
                with results_lock:
                    mark_not_found(name)
                    conn.commit()
                    failed += 1
                print(f"[{completed}/{total}] {name} → Exception: {e}")

    return matched, failed


def get_stats(conn):
    """Get Metacritic sync statistics."""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM games")
    total = cursor.fetchone()[0]

    # Count matched games (metacritic_score >= 0, not counting -1 which means "not found")
    cursor.execute("SELECT COUNT(*) FROM games WHERE metacritic_score IS NOT NULL AND metacritic_score >= 0")
    matched = cursor.fetchone()[0]

    cursor.execute(
        "SELECT AVG(metacritic_score) FROM games WHERE metacritic_score IS NOT NULL AND metacritic_score >= 0"
    )
    avg_critic_score = cursor.fetchone()[0]

    cursor.execute(
        "SELECT AVG(metacritic_user_score) FROM games WHERE metacritic_user_score IS NOT NULL"
    )
    avg_user_score = cursor.fetchone()[0]

    cursor.execute(
        """SELECT name, metacritic_score FROM games
           WHERE metacritic_score IS NOT NULL AND metacritic_score >= 0
           ORDER BY metacritic_score DESC LIMIT 5"""
    )
    top_rated = cursor.fetchall()

    return {
        "total": total,
        "matched": matched,
        "match_rate": (matched / total * 100) if total > 0 else 0,
        "avg_critic_score": avg_critic_score,
        "avg_user_score": avg_user_score,
        "top_rated": top_rated,
    }
