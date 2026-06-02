from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Competition:
    key: str
    name: str
    api_football_league_id: int | None
    api_football_season: int | None
    football_data_org_code: str | None
    is_national: bool = False


SUPPORTED_COMPETITIONS: dict[str, Competition] = {
    "worldcup": Competition("worldcup", "FIFA World Cup 2026", 1, 2026, "WC", True),
    "serie_a": Competition("serie_a", "Serie A", 135, 2025, "SA"),
    "premier": Competition("premier", "Premier League", 39, 2025, "PL"),
    "liga": Competition("liga", "La Liga", 140, 2025, "PD"),
    "bundesliga": Competition("bundesliga", "Bundesliga", 78, 2025, "BL1"),
    "ligue_1": Competition("ligue_1", "Ligue 1", 61, 2025, "FL1"),
    "champions": Competition("champions", "Champions League", 2, 2025, "CL"),
    "europa": Competition("europa", "Europa League", 3, 2025, "EL"),
    "conference": Competition("conference", "Conference League", 848, 2025, None),
}


DEFAULT_COMPETITIONS = [
    "worldcup",
    "serie_a",
    "premier",
    "liga",
    "bundesliga",
    "ligue_1",
    "champions",
    "europa",
    "conference",
]


WORLD_CUP_KEYS = ["worldcup"]

