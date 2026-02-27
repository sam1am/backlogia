# filters.py
# SQL filter constants for game queries

# Filter out duplicate GOG entries from Amazon Prime/Luna
EXCLUDE_DUPLICATES_FILTER = """
    AND name NOT LIKE '% - Amazon Prime'
    AND name NOT LIKE '% - Amazon Luna'
"""

# Filter to exclude hidden games (in addition to duplicates)
EXCLUDE_HIDDEN_FILTER = EXCLUDE_DUPLICATES_FILTER + """
    AND (hidden IS NULL OR hidden = 0)
    AND (removed IS NULL OR removed = 0)
"""

# Valid playtime label values (used by the edit API and the library filter)
PLAYTIME_LABELS: frozenset[str] = frozenset({
    "unplayed",
    "tried",
    "played",
    "heavily_played",
    "abandoned",
})
