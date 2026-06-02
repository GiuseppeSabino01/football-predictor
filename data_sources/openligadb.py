from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
import unicodedata

import requests

from config.settings import Settings
from data_sources.base import DataSourceError
from schemas import Match


TEAM_NAME_TRANSLATIONS = {
    "agypten": "Egitto",
    "algerien": "Algeria",
    "argentinien": "Argentina",
    "australien": "Australia",
    "belgien": "Belgio",
    "bosnien und herzegowina": "Bosnia ed Erzegovina",
    "brasilien": "Brasile",
    "chile": "Cile",
    "costa rica": "Costa Rica",
    "curacao": "Curaçao",
    "dr kongo": "RD Congo",
    "elfenbeinkuste": "Costa d'Avorio",
    "deutschland": "Germania",
    "ecuador": "Ecuador",
    "england": "Inghilterra",
    "frankreich": "Francia",
    "ghana": "Ghana",
    "haiti": "Haiti",
    "irak": "Iraq",
    "iran": "Iran",
    "italien": "Italia",
    "japan": "Giappone",
    "jordanien": "Giordania",
    "kanada": "Canada",
    "kap verde": "Capo Verde",
    "katar": "Qatar",
    "kolumbien": "Colombia",
    "kroatien": "Croazia",
    "marokko": "Marocco",
    "mexiko": "Messico",
    "neuseeland": "Nuova Zelanda",
    "niederlande": "Paesi Bassi",
    "nigeria": "Nigeria",
    "norwegen": "Norvegia",
    "osterreich": "Austria",
    "panama": "Panama",
    "paraguay": "Paraguay",
    "polen": "Polonia",
    "portugal": "Portogallo",
    "saudi arabien": "Arabia Saudita",
    "schottland": "Scozia",
    "schweden": "Svezia",
    "schweiz": "Svizzera",
    "senegal": "Senegal",
    "serbien": "Serbia",
    "spanien": "Spagna",
    "sudafrika": "Sudafrica",
    "sudkorea": "Corea del Sud",
    "tschechien": "Repubblica Ceca",
    "tunesien": "Tunisia",
    "turkei": "Turchia",
    "ukraine": "Ucraina",
    "ungarn": "Ungheria",
    "uruguay": "Uruguay",
    "usbekistan": "Uzbekistan",
    "vereinigte staaten": "USA",
    "usa": "USA",
    "wales": "Galles",
}


class OpenLigaDBClient:
    base_url = "https://api.openligadb.de"

    def __init__(self, settings: Settings):
        self.settings = settings

    def worldcup_matches_for_date(self, target_date: date) -> list[Match]:
        rows = self._get("/getmatchdata/wm26/2026")
        matches = [self._parse_match(row) for row in rows]
        return [
            match
            for match in matches
            if match.match_date.astimezone(self.settings.local_timezone).date() == target_date
        ]

    def _get(self, endpoint: str) -> list[dict[str, Any]]:
        response = requests.get(
            f"{self.base_url}{endpoint}",
            timeout=self.settings.request_timeout_seconds,
            verify=self.settings.verify_ssl,
        )
        if response.status_code >= 400:
            raise DataSourceError(f"OpenLigaDB error {response.status_code}: {response.text[:240]}")
        payload = response.json()
        return payload if isinstance(payload, list) else []

    @staticmethod
    def _parse_match(row: dict[str, Any]) -> Match:
        team1 = row.get("team1") or {}
        team2 = row.get("team2") or {}
        group = row.get("matchGroup") or {}
        raw_date = row.get("matchDateTimeUTC") or row.get("matchDateTime")
        return Match(
            id=f"openligadb-{row.get('matchID')}",
            source="openligadb",
            competition=row.get("leagueName") or "FIFA World Cup 2026",
            season=2026,
            match_date=_parse_date(raw_date),
            home_team=_team_name(team1.get("teamName", "Home")),
            away_team=_team_name(team2.get("teamName", "Away")),
            status="SCHEDULED",
            stage=group.get("groupName"),
            raw=row,
        )


def _parse_date(raw_date: str | None) -> datetime:
    if not raw_date:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _team_name(name: str) -> str:
    return TEAM_NAME_TRANSLATIONS.get(_normalize(name), name)


def _normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_value.lower().replace("-", " ").split())
