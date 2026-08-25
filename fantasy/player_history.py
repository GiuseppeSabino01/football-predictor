from __future__ import annotations

import gzip
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

HISTORY_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "player_history_5y_2026_27.json.gz"
)


@lru_cache(maxsize=1)
def load_player_history() -> dict[str, dict[str, Any]]:
    """Load the verified, pre-built five-season player history snapshot."""
    if not HISTORY_PATH.exists():
        return {}
    try:
        with gzip.open(HISTORY_PATH, "rt", encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, ValueError, TypeError):
        return {}
    players = payload.get("players", {}) if isinstance(payload, dict) else {}
    return players if isinstance(players, dict) else {}


def attach_player_history(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach up to five completed seasons without changing existing analysis."""
    history = load_player_history()
    by_name: dict[str, list[dict[str, Any]]] = {}
    for entry in history.values():
        if isinstance(entry, dict):
            by_name.setdefault(_normalize_name(entry.get("name")), []).append(entry)

    for player in players:
        entry = history.get(str(player.get("id") or ""))
        if entry is None:
            matches = by_name.get(_normalize_name(player.get("name")), [])
            entry = matches[0] if len(matches) == 1 else None
        if not isinstance(entry, dict):
            continue
        seasons = [
            dict(item) for item in entry.get("seasons", []) if isinstance(item, dict)
        ][:5]
        if not seasons:
            continue
        player["history_5y"] = seasons
        player["history_seasons"] = len(seasons)
        player["history_source"] = str(entry.get("source") or "ESPN")
        player["history_source_url"] = str(entry.get("source_url") or "")
        if entry.get("age") is not None:
            player["age"] = entry["age"]
    return players


def _normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
