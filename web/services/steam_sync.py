# steam_sync.py
# Fetches Steam review scores and updates games in the database

import json
import sqlite3
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import requests

from .database_builder import add_steam_synced_at_column

# Rate limiting for Steam Store API
_rate_limit_lock = Lock()
_last_request_time = 0
_MIN_REQUEST_INTERVAL = 0.2  # 200ms between requests (5 req/sec max)


def _rate_limited_request(url, params=None, interval=_MIN_REQUEST_INTERVAL):
    """Make a rate-limited request to Steam Store API."""
    global _last_request_time

    with _rate_limit_lock:
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < interval:
            time.sleep(interval - elapsed)
        _last_request_time = time.time()

    try:
        response = requests.get(url, params=params, timeout=10)
        return response
    except requests.RequestException:
        return None

def get_steam_store_info(appid):
    """Fetch store info for a Steam game.

    Returns a dict with:
    - screenshots: Steam store screenshots (max 5)
    - summary: text description 
    - developers: developers list
    - publishers: publishers list
    - release_date: release date
    """
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}"

    response = _rate_limited_request(url,interval=1.5)
    if not response:
        return None, "request_failed"
    if response.status_code != 200:
        return None, f"http_{response.status_code}"

    try:
        app_data = response.json().get(f"{appid}")
        if not app_data or not app_data.get("success"):
            return None, "not_found"
        data = app_data.get("data")
        if not data:
            return None, "no_data"
        summary = data.get("detailed_description")
        developers = data.get("developers")
        publishers = data.get("publishers")
        screenshots = [
            s["path_full"] for s in data.get("screenshots") or [] if s.get("path_full")
        ][:5]
        json_data = data.get("release_date") or {}
        comming_soon = json_data.get("coming_soon")
        release_date_raw = json_data.get("date")
        release_date = None
        if release_date_raw and not comming_soon:
            for fmt in ("%d %b, %Y", "%b %d, %Y", "%B %d, %Y", "%d %B, %Y", "%Y"):
                try:
                    release_date = datetime.strptime(release_date_raw, fmt).date().isoformat()
                    break
                except ValueError:
                    continue

        return {
            "summary": summary,
            "developers": developers,
            "publishers": publishers,
            "release_date": release_date,
            "screenshots": screenshots,
        }, None
    except Exception as e:
        return None, f"parse_error: {e}"


def get_steam_review_score(appid):
    """Fetch review score for a Steam game.

    Returns a dict with:
    - review_score: percentage of positive reviews (0-100)
    - review_desc: text description (e.g., "Very Positive")
    - total_reviews: total number of reviews
    """
    url = f"https://store.steampowered.com/appreviews/{appid}"
    params = {
        "json": 1,
        "language": "all",
        "purchase_type": "all"
    }

    response = _rate_limited_request(url, params)
    if not response:
        return None, "request_failed"
    if response.status_code != 200:
        return None, f"http_{response.status_code}"

    try:
        data = response.json()
        summary = data.get("query_summary", {})

        total_positive = summary.get("total_positive", 0)
        total_negative = summary.get("total_negative", 0)
        total_reviews = total_positive + total_negative

        if total_reviews == 0:
            return None, "no_reviews"

        review_score = round((total_positive / total_reviews) * 100, 1)
        review_desc = summary.get("review_score_desc", "")

        return {
            "review_score": review_score,
            "review_desc": review_desc,
            "total_reviews": total_reviews,
        }, None
    except Exception as e:
        return None, f"parse_error: {e}"

def sync_steam_store_info(conn, force=False, max_workers=5, progress_callback=None):
    """Fetch Steam review scores for all Steam games in the database and update critics_score.

    Args:
        conn: Database connection
        force: If True, re-fetch reviews for all Steam games; if False, only games missing critics_score
        max_workers: Number of threads for parallel fetching
        progress_callback: Optional callback(current, total, message)

    Returns:
        (updated, failed) counts
    """
    cursor = conn.cursor()

    add_steam_synced_at_column(conn)

    # Backfill steam_app_id from store_id for Steam games that predate this column
    cursor.execute(
        "UPDATE games SET steam_app_id = store_id WHERE store = 'steam' AND steam_app_id IS NULL AND store_id IS NOT NULL"
    )
    conn.commit()

    if force:
        cursor.execute(
            "SELECT id, steam_app_id, name FROM games WHERE steam_app_id IS NOT NULL"
        )
    else:
        cursor.execute(
            """SELECT id, steam_app_id, name FROM games
               WHERE steam_app_id IS NOT NULL AND steam_synced_at IS NULL"""
        )

    games = cursor.fetchall()
    total = len(games)

    if total == 0:
        return 0, 0

    print(f"Fetching Steam store info for {total} games ({max_workers} threads)...")

    updated = 0
    failed = 0
    completed = 0
    results_lock = Lock()

    db_path = conn.execute("PRAGMA database_list").fetchone()[2]

    def fetch_and_update(row):
        game_id, store_id, name = row
        store_info, reason = get_steam_store_info(store_id)
        return game_id, store_id, name, store_info, reason

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_and_update, row): row for row in games}

        for future in as_completed(futures):
            game_id, store_id, name, store_info, reason = future.result()

            with results_lock:
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, f"Processing: {name[:50]}...")

            if store_info:
                # Each thread needs its own connection
                thread_conn = sqlite3.connect(db_path)
                try:
                    thread_conn.execute(
                        """UPDATE games SET
                            summary = ?,
                            developers = ?,
                            publishers = ?,
                            release_date = ?,
                            screenshots = ?,
                            steam_synced_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?""",
                        (store_info["summary"],
                         json.dumps(store_info["developers"]) if store_info["developers"] else None,
                         json.dumps(store_info["publishers"]) if store_info["publishers"] else None,
                         store_info["release_date"],
                         json.dumps(store_info["screenshots"]) if store_info["screenshots"] else None,
                         game_id),
                    )
                    thread_conn.commit()
                finally:
                    thread_conn.close()

                with results_lock:
                    updated += 1
            else:
                if reason not in ("not_found", "no_data"):
                    print(f"  [store info] {name} (appid={store_id}): {reason}")
                thread_conn = sqlite3.connect(db_path)
                try:
                    thread_conn.execute(
                        """UPDATE games SET
                            steam_synced_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?""",
                        (game_id,),
                    )
                    thread_conn.commit()
                finally:
                    thread_conn.close()

                with results_lock:
                    failed += 1

    return updated, failed


def sync_steam_reviews(conn, force=False, max_workers=5, progress_callback=None):
    """Fetch Steam review scores for all Steam games in the database and update critics_score.

    Args:
        conn: Database connection
        force: If True, re-fetch reviews for all Steam games; if False, only games missing critics_score
        max_workers: Number of threads for parallel fetching
        progress_callback: Optional callback(current, total, message)

    Returns:
        (updated, failed) counts
    """
    cursor = conn.cursor()

    if force:
        cursor.execute(
            "SELECT id, store_id, name FROM games WHERE store = 'steam' AND store_id IS NOT NULL"
        )
    else:
        cursor.execute(
            """SELECT id, store_id, name FROM games
               WHERE store = 'steam' AND store_id IS NOT NULL AND critics_score IS NULL"""
        )

    games = cursor.fetchall()
    total = len(games)

    if total == 0:
        return 0, 0

    print(f"Fetching Steam reviews for {total} games ({max_workers} threads)...")

    updated = 0
    failed = 0
    completed = 0
    results_lock = Lock()

    db_path = conn.execute("PRAGMA database_list").fetchone()[2]

    def fetch_and_update(row):
        game_id, store_id, name = row
        reviews, reason = get_steam_review_score(store_id)
        return game_id, store_id, name, reviews, reason

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_and_update, row): row for row in games}

        for future in as_completed(futures):
            game_id, store_id, name, reviews, reason = future.result()

            with results_lock:
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, f"Processing: {name[:50]}...")

            if reviews:
                # Each thread needs its own connection
                thread_conn = sqlite3.connect(db_path)
                try:
                    thread_conn.execute(
                        """UPDATE games SET
                            critics_score = ?,
                            extra_data = json_set(COALESCE(extra_data, '{}'), '$.review_desc', ?, '$.total_reviews', ?),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?""",
                        (reviews["review_score"], reviews["review_desc"], reviews["total_reviews"], game_id),
                    )
                    thread_conn.commit()
                finally:
                    thread_conn.close()

                with results_lock:
                    updated += 1
            else:
                with results_lock:
                    failed += 1

    return updated, failed

def sync_steam(conn, force=False, max_workers=5, progress_callback=None):
    """Fetch Steam review scores for all Steam games in the database and update critics_score.

    Args:
        conn: Database connection
        force: If True, re-fetch reviews for all Steam games; if False, only games missing critics_score
        max_workers: Number of threads for parallel fetching
        progress_callback: Optional callback(current, total, message)

    Returns:
        (updated, failed) counts
    """

    def make_phase_progress(prefix):
        if not progress_callback:
            return None
        def _cb(current, total, message):
            progress_callback(current, total, f"[{prefix}] {message}")
        return _cb

    reviews_updated, reviews_failed = sync_steam_reviews(conn, force, max_workers, make_phase_progress("Reviews"))
    store_updated, store_failed = sync_steam_store_info(conn, force, 1, make_phase_progress("Store info"))

    return reviews_updated + store_updated, reviews_failed, store_failed
