"""tests/test_search.py

Tests for the search functionality, focusing on correct escaping of SQL LIKE
special characters (%, _, \\) in search queries.
"""

import pytest

from web.utils.helpers import escape_like


# --------------------------------------------------------------------------- #
# escape_like helper                                                            #
# --------------------------------------------------------------------------- #


class TestEscapeLike:
    def test_plain_string_unchanged(self):
        """Strings with no special characters are left as-is."""
        assert escape_like("hello world") == "hello world"

    def test_percent_escaped(self):
        """% is escaped to \\%."""
        assert escape_like("%") == "\\%"
        assert escape_like("100%") == "100\\%"
        assert escape_like("%complete%") == "\\%complete\\%"

    def test_underscore_escaped(self):
        """_ is escaped to \\_."""
        assert escape_like("_") == "\\_"
        assert escape_like("game_1") == "game\\_1"

    def test_backslash_escaped(self):
        r"""\ is escaped to \\."""
        assert escape_like("a\\b") == "a\\\\b"

    def test_combined_special_chars(self):
        """Multiple special characters are all escaped."""
        assert escape_like("50% off_sale") == "50\\% off\\_sale"


# --------------------------------------------------------------------------- #
# Library search – special characters                                           #
# --------------------------------------------------------------------------- #


@pytest.fixture
def client_with_special_games(db_conn, client):
    """Insert games with special characters in their names."""
    db_conn.execute(
        "INSERT INTO games (name, store, store_id) VALUES (?, ?, ?)",
        ("100% Orange Juice", "steam", "282870"),
    )
    db_conn.execute(
        "INSERT INTO games (name, store, store_id) VALUES (?, ?, ?)",
        ("Pro_game", "steam", "99999"),
    )
    db_conn.execute(
        "INSERT INTO games (name, store, store_id) VALUES (?, ?, ?)",
        ("Normal Game", "steam", "11111"),
    )
    db_conn.commit()
    # client fixture already sets up the DB override; just return it
    return client


class TestLibrarySearchSpecialChars:
    def test_percent_search_returns_only_matching_game(self, client_with_special_games):
        """Searching for % should match games that contain % in their name, not all games."""
        resp = client_with_special_games.get("/library?search=%25")  # URL-encoded %
        assert resp.status_code == 200
        text = resp.text
        # The game with % in its name should appear
        assert "100% Orange Juice" in text
        # Normal games should NOT appear
        assert "Normal Game" not in text

    def test_underscore_search_returns_only_matching_game(self, client_with_special_games):
        """Searching for _ should not act as a wildcard; only exact matches are returned."""
        resp = client_with_special_games.get("/library?search=Pro_game")
        assert resp.status_code == 200
        text = resp.text
        assert "Pro_game" in text
        # Normal Game has no underscore – should not match
        assert "Normal Game" not in text

    def test_plain_search_still_works(self, client_with_special_games):
        """Regular search without special chars continues to work."""
        resp = client_with_special_games.get("/library?search=Normal")
        assert resp.status_code == 200
        assert "Normal Game" in resp.text
        assert "100% Orange Juice" not in resp.text

    def test_search_too_long_returns_422(self, client_with_special_games):
        """Search strings longer than 200 chars are rejected with HTTP 422."""
        long_search = "a" * 201
        resp = client_with_special_games.get(f"/library?search={long_search}")
        assert resp.status_code == 422

    def test_search_exactly_200_chars_is_accepted(self, client_with_special_games):
        """Search strings of exactly 200 chars are accepted."""
        search = "a" * 200
        resp = client_with_special_games.get(f"/library?search={search}")
        assert resp.status_code == 200
