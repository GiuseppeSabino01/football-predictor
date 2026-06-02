from __future__ import annotations

from datetime import date, datetime
from typing import Any

import requests

from config.competitions import Competition
from config.settings import Settings
from data_sources.base import DataSourceError
from schemas import Match


class APIFootballClient:
    base_url = "https://v3.football.api-sports.io"

    def __init__(self, settings: Settings):
        self.settings = settings

    def _get(self, endpoint: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.settings.api_football_key:
            return []

        response = requests.get(
            f"{self.base_url}{endpoint}",
            headers={"x-apisports-key": self.settings.api_football_key},
            params=params,
            timeout=self.settings.request_timeout_seconds,
            verify=self.settings.verify_ssl,
        )
        if response.status_code >= 400:
            raise DataSourceError(f"API-Football error {response.status_code}: {response.text[:240]}")

        payload = response.json()
        errors = payload.get("errors")
        if errors:
            raise DataSourceError(f"API-Football errors: {errors}")
        return payload.get("response", [])

    def fixtures_for_date(self, target_date: date, competitions: list[Competition]) -> list[Match]:
        matches: list[Match] = []
        for competition in competitions:
            if not competition.api_football_league_id or not competition.api_football_season:
                continue
            if self.settings.api_football_free_mode and competition.api_football_season > 2024:
                continue
            rows = self._get(
                "/fixtures",
                {
                    "date": target_date.isoformat(),
                    "league": competition.api_football_league_id,
                    "season": competition.api_football_season,
                },
            )
            matches.extend(self._parse_fixture(row, competition) for row in rows)
        return matches

    def odds_for_fixture(self, fixture_id: str) -> list[dict[str, Any]]:
        return self._get("/odds", {"fixture": fixture_id})

    def injuries_for_fixture(self, fixture_id: str) -> list[dict[str, Any]]:
        return self._get("/injuries", {"fixture": fixture_id})

    def lineups_for_fixture(self, fixture_id: str) -> list[dict[str, Any]]:
        return self._get("/fixtures/lineups", {"fixture": fixture_id})

    def statistics_for_fixture(self, fixture_id: str) -> list[dict[str, Any]]:
        return self._get("/fixtures/statistics", {"fixture": fixture_id})

    @staticmethod
    def _parse_fixture(row: dict[str, Any], competition: Competition) -> Match:
        fixture = row.get("fixture", {})
        teams = row.get("teams", {})
        venue = fixture.get("venue") or {}
        league = row.get("league") or {}
        raw_date = fixture.get("date")
        match_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")) if raw_date else datetime.utcnow()

        return Match(
            id=str(fixture.get("id")),
            source="api-football",
            competition=league.get("name") or competition.name,
            season=competition.api_football_season,
            match_date=match_date,
            home_team=(teams.get("home") or {}).get("name", "Home"),
            away_team=(teams.get("away") or {}).get("name", "Away"),
            status=(fixture.get("status") or {}).get("short", "SCHEDULED"),
            venue=venue.get("name"),
            stage=league.get("round"),
            league_id=competition.api_football_league_id,
            raw=row,
        )
