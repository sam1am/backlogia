# metacritic_sync.py
# Fetches Metacritic scores for games in our database

import sqlite3
import requests
import time
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from urllib.parse import quote


class MetacriticClient:
    """Client for fetching game data from Metacritic."""

    BASE_URL = "https://www.metacritic.com"
    SEARCH_URL = "https://www.metacritic.com/search"

    def __init__(self, min_request_interval=0.5):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
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

    def _make_request(self, url):
        """Make a rate-limited request."""
        self._rate_limit()
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            print(f"Request error: {e}")
            return None

    def search_game(self, name):
        """
        Search Metacritic for a game by name.

        Returns a list of results with: name, slug, platform, url
        """
        # Clean the search query
        clean_name = self._clean_game_name(name)
        search_url = f"{self.SEARCH_URL}/{quote(clean_name)}/?page=1&category=13"  # category 13 = games

        response = self._make_request(search_url)
        if not response:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        results = []

        # Find search result items
        # Metacritic uses different selectors over time, try multiple patterns
        result_cards = soup.select('a[class*="c-pageSiteSearch-results-item"]')

        if not result_cards:
            # Try alternative selector
            result_cards = soup.select('div.c-pageSiteSearch-results a[href*="/game/"]')

        for card in result_cards[:5]:  # Limit to top 5 results
            try:
                href = card.get("href", "")
                if "/game/" not in href:
                    continue

                # Extract slug from URL (e.g., /game/game-name/ -> game-name)
                slug_match = re.search(r"/game/([^/]+)", href)
                if not slug_match:
                    continue

                slug = slug_match.group(1)

                # Get game name from the card
                title_el = card.select_one('p[class*="title"], h3, span[class*="title"]')
                game_name = title_el.get_text(strip=True) if title_el else slug.replace("-", " ").title()

                # Get score if available
                score_el = card.select_one('span[class*="metascore"], div[class*="metascore"]')
                score = None
                if score_el:
                    score_text = score_el.get_text(strip=True)
                    if score_text.isdigit():
                        score = int(score_text)

                results.append({
                    "name": game_name,
                    "slug": slug,
                    "url": f"{self.BASE_URL}/game/{slug}/",
                    "score": score,
                })
            except Exception as e:
                print(f"Error parsing search result: {e}")
                continue

        return results

    def get_game_by_slug(self, slug):
        """
        Get game details by Metacritic slug.

        Returns dict with: name, slug, url, critic_score, user_score
        """
        # Clean the slug
        slug = slug.strip().lower()
        slug = re.sub(r"[^a-z0-9-]", "", slug)

        url = f"{self.BASE_URL}/game/{slug}/"
        response = self._make_request(url)

        if not response:
            return None

        if response.status_code == 404:
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        result = {
            "name": None,
            "slug": slug,
            "url": url,
            "critic_score": None,
            "user_score": None,
        }

        # Get game title
        title_el = soup.select_one('div[class*="c-productHero_title"] h1, h1[class*="product_title"]')
        if title_el:
            result["name"] = title_el.get_text(strip=True)

        # Get critic score (Metascore)
        metascore_el = soup.select_one(
            'div[class*="c-siteReviewScore"] span, '
            'span[class*="metascore_w"], '
            'div[class*="metascore"] span'
        )
        if metascore_el:
            score_text = metascore_el.get_text(strip=True)
            if score_text.isdigit():
                result["critic_score"] = int(score_text)

        # Try alternative metascore selector
        if result["critic_score"] is None:
            for el in soup.select('[data-testid="critic-score-value"], [class*="metascore"]'):
                score_text = el.get_text(strip=True)
                if score_text.isdigit():
                    result["critic_score"] = int(score_text)
                    break

        # Get user score
        userscore_el = soup.select_one(
            'div[class*="c-siteReviewScore_user"] span, '
            'span[class*="user"], '
            'div[class*="userscore"] span'
        )
        if userscore_el:
            score_text = userscore_el.get_text(strip=True)
            try:
                # User scores are typically 0-10
                user_score = float(score_text)
                if 0 <= user_score <= 10:
                    result["user_score"] = user_score
            except ValueError:
                pass

        # Try alternative user score selector
        if result["user_score"] is None:
            for el in soup.select('[data-testid="user-score-value"], [class*="userscore"]'):
                score_text = el.get_text(strip=True)
                try:
                    user_score = float(score_text)
                    if 0 <= user_score <= 10:
                        result["user_score"] = user_score
                        break
                except ValueError:
                    continue

        return result

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


def sync_games(conn, client, limit=None, force=False, max_workers=5):
    """Sync games with Metacritic using multithreading."""
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
                    with results_lock:
                        failed += 1
                    print(f"[{completed}/{total}] {name} → {result}")

            except Exception as e:
                with results_lock:
                    failed += 1
                print(f"[{completed}/{total}] {name} → Exception: {e}")

    return matched, failed


def get_stats(conn):
    """Get Metacritic sync statistics."""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM games")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM games WHERE metacritic_score IS NOT NULL")
    matched = cursor.fetchone()[0]

    cursor.execute(
        "SELECT AVG(metacritic_score) FROM games WHERE metacritic_score IS NOT NULL"
    )
    avg_critic_score = cursor.fetchone()[0]

    cursor.execute(
        "SELECT AVG(metacritic_user_score) FROM games WHERE metacritic_user_score IS NOT NULL"
    )
    avg_user_score = cursor.fetchone()[0]

    cursor.execute(
        """SELECT name, metacritic_score FROM games
           WHERE metacritic_score IS NOT NULL
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
