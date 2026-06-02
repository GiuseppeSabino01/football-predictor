from __future__ import annotations

from datetime import date, datetime
from typing import Any

import requests

from config.competitions import Competition
from config.settings import Settings
from data_sources.base import DataSourceError
from schemas import Match


class FootballDataOrgClient:
    base_url = "https://api.football-data.org/v4"

    def __init__(self, settings: Settings):
        self.settings = settings

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.settings.football_data_org_key:
            return {}
        response = requests.get(
            f"{self.base_url}{endpoint}",
            headers={"X-Auth-Token": self.settings.football_data_org_key},
            params=params or {},
            timeout=self.settings.request_timeout_seconds,
            verify=self.settings.verify_ssl,
        )
        if response.status_code >= 400:
            raise DataSourceError(f"football-data.org error {response.status_code}: {response.text[:240]}")
        return response.json()

    def matches_for_date(self, target_date: date, competitions: list[Competition] | None = None) -> list[Match]:
        payload = self._get(
            "/matches",
            {"dateFrom": target_date.isoformat(), "dateTo": target_date.isoformat()},
        )
        rows = payload.get("matches", [])
        if competitions:
            allowed_codes = {competition.football_data_org_code for competition in competitions if competition.football_data_org_code}
            allowed_names = {competition.name.lower() for competition in competitions}
            rows = [
                row
                for row in rows
                if _competition_matches(row, allowed_codes, allowed_names)
            ]
        return [self._parse_match(row) for row in rows]

    @staticmethod
    def _parse_match(row: dict[str, Any]) -> Match:
        competition = row.get("competition") or {}
        home = row.get("homeTeam") or {}
        away = row.get("awayTeam") or {}
        raw_date = row.get("utcDate")
        match_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")) if raw_date else datetime.utcnow()
        return Match(
            id=str(row.get("id")),
            source="football-data.org",
            competition=competition.get("name", "Competition"),
            season=None,
            match_date=match_date,
            home_team=home.get("name", "Home"),
            away_team=away.get("name", "Away"),
            status=row.get("status", "SCHEDULED"),
            stage=row.get("stage"),
            raw=row,
        )


def _competition_matches(row: dict[str, Any], allowed_codes: set[str], allowed_names: set[str]) -> bool:
    competition = row.get("competition") or {}
    code = competition.get("code")
    name = str(competition.get("name", "")).lower()
    return bool((code and code in allowed_codes) or (name and name in allowed_names))
