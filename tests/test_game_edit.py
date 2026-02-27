"""tests/test_game_edit.py

Unit / integration tests for the game metadata edit feature.

Covered endpoints:
  GET  /api/genres
  POST /api/games/bulk/edit
"""

import json


# --------------------------------------------------------------------------- #
# GET /api/genres                                                              #
# --------------------------------------------------------------------------- #


class TestApiGenres:
    def test_returns_list(self, client):
        """Endpoint returns a JSON array."""
        resp = client.get("/api/genres")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_returns_sorted_unique_genres(self, client):
        """Genres are sorted and de-duplicated."""
        body = client.get("/api/genres").json()
        assert body == sorted(set(body))

    def test_includes_store_genres(self, client, sample_games, db_conn):
        """Genres from the store-provided 'genres' column are included."""
        body = client.get("/api/genres").json()
        # Sample games contain: Action, Shooter, RPG, Adventure, Platformer, Indie
        for genre in ("Action", "Shooter", "RPG", "Adventure", "Platformer", "Indie"):
            assert genre in body

    def test_includes_override_genres(self, client, sample_games, db_conn):
        """Genres from 'genres_override' are also included."""
        game_id = sample_games[0]
        db_conn.execute(
            "UPDATE games SET genres_override = ? WHERE id = ?",
            (json.dumps(["Custom Genre"]), game_id),
        )
        db_conn.commit()

        body = client.get("/api/genres").json()
        assert "Custom Genre" in body

    def test_excludes_hidden_games(self, client, sample_games, db_conn):
        """Hidden games' genres should NOT appear (uses EXCLUDE_HIDDEN_FILTER)."""
        # Add a hidden game with a unique genre
        db_conn.execute(
            "INSERT INTO games (name, store, genres, hidden) VALUES (?, ?, ?, ?)",
            ("Hidden Game", "steam", json.dumps(["SecretGenre"]), 1),
        )
        db_conn.commit()

        body = client.get("/api/genres").json()
        assert "SecretGenre" not in body


# --------------------------------------------------------------------------- #
# POST /api/games/bulk/edit                                                    #
# --------------------------------------------------------------------------- #


class TestBulkEdit:
    def test_update_genres_override(self, client, sample_games, db_conn):
        """genres_override is written when update_genres_override=True."""
        game_id = sample_games[0]
        resp = client.post(
            "/api/games/bulk/edit",
            json={
                "game_ids": [game_id],
                "genres_override": ["Narrative", "Indie"],
                "update_genres_override": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        row = db_conn.execute(
            "SELECT genres_override FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        assert json.loads(row[0]) == ["Narrative", "Indie"]

    def test_update_playtime_label(self, client, sample_games, db_conn):
        """playtime_label is written when update_playtime_label=True."""
        game_id = sample_games[1]
        resp = client.post(
            "/api/games/bulk/edit",
            json={
                "game_ids": [game_id],
                "playtime_label": "played",
                "update_playtime_label": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        row = db_conn.execute(
            "SELECT playtime_label FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        assert row[0] == "played"

    def test_update_both_fields(self, client, sample_games, db_conn):
        """Both fields can be updated in a single request."""
        game_id = sample_games[0]
        resp = client.post(
            "/api/games/bulk/edit",
            json={
                "game_ids": [game_id],
                "genres_override": ["Strategy"],
                "update_genres_override": True,
                "playtime_label": "heavily_played",
                "update_playtime_label": True,
            },
        )
        assert resp.status_code == 200

        row = db_conn.execute(
            "SELECT genres_override, playtime_label FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        assert json.loads(row[0]) == ["Strategy"]
        assert row[1] == "heavily_played"

    def test_clear_genres_override(self, client, sample_games, db_conn):
        """Passing genres_override=None with the flag clears the stored value."""
        game_id = sample_games[0]
        db_conn.execute(
            "UPDATE games SET genres_override = ? WHERE id = ?",
            (json.dumps(["OldGenre"]), game_id),
        )
        db_conn.commit()

        resp = client.post(
            "/api/games/bulk/edit",
            json={
                "game_ids": [game_id],
                "genres_override": None,
                "update_genres_override": True,
            },
        )
        assert resp.status_code == 200

        row = db_conn.execute(
            "SELECT genres_override FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        assert row[0] is None

    def test_clear_playtime_label(self, client, sample_games, db_conn):
        """Passing playtime_label=None with the flag clears the stored label."""
        game_id = sample_games[2]  # Celeste already has playtime_label="heavily_played"

        resp = client.post(
            "/api/games/bulk/edit",
            json={
                "game_ids": [game_id],
                "playtime_label": None,
                "update_playtime_label": True,
            },
        )
        assert resp.status_code == 200

        row = db_conn.execute(
            "SELECT playtime_label FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        assert row[0] is None

    def test_bulk_update_multiple_games(self, client, sample_games, db_conn):
        """All listed game IDs are updated in a single call."""
        resp = client.post(
            "/api/games/bulk/edit",
            json={
                "game_ids": sample_games,
                "playtime_label": "tried",
                "update_playtime_label": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] == len(sample_games)

    def test_invalid_playtime_label_returns_422(self, client, sample_games):
        """An unrecognised playtime label produces a 422 error."""
        resp = client.post(
            "/api/games/bulk/edit",
            json={
                "game_ids": [sample_games[0]],
                "playtime_label": "immortal",
                "update_playtime_label": True,
            },
        )
        assert resp.status_code == 422

    def test_empty_game_ids_returns_400(self, client):
        """Passing an empty game_ids list produces a 400 error."""
        resp = client.post(
            "/api/games/bulk/edit",
            json={
                "game_ids": [],
                "playtime_label": "played",
                "update_playtime_label": True,
            },
        )
        assert resp.status_code == 400

    def test_no_update_flags_returns_400(self, client, sample_games):
        """If neither update flag is set, the server returns 400."""
        resp = client.post(
            "/api/games/bulk/edit",
            json={"game_ids": [sample_games[0]]},
        )
        assert resp.status_code == 400

    def test_untouched_fields_are_not_overwritten(self, client, sample_games, db_conn):
        """Updating genres_override does not affect playtime_label and vice-versa."""
        game_id = sample_games[2]  # Celeste has playtime_label="heavily_played"
        original_label = db_conn.execute(
            "SELECT playtime_label FROM games WHERE id = ?", (game_id,)
        ).fetchone()[0]

        client.post(
            "/api/games/bulk/edit",
            json={
                "game_ids": [game_id],
                "genres_override": ["Platformer"],
                "update_genres_override": True,
            },
        )

        row = db_conn.execute(
            "SELECT playtime_label FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        assert row[0] == original_label  # unchanged
