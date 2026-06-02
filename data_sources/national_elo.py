from __future__ import annotations

import html
import re
from datetime import date

import requests

from config.settings import Settings
from features.team_strength import canonical_team_name


class NationalEloClient:
    base_url = "https://www.international-football.net/elo-ratings-table"

    def __init__(self, settings: Settings):
        self.settings = settings

    def ratings_for_date(self, target_date: date) -> dict[str, int]:
        response = requests.get(
            self.base_url,
            params={
                "confed": "",
                "day": f"{target_date.day:02d}",
                "month": f"{target_date.month:02d}",
                "old-team": "",
                "year": target_date.year,
            },
            timeout=self.settings.request_timeout_seconds,
            verify=self.settings.verify_ssl,
        )
        response.raise_for_status()
        return self._parse(response.text)

    @staticmethod
    def _parse(raw_html: str) -> dict[str, int]:
        decoded = html.unescape(raw_html)
        rows = re.findall(
            r"<tr[^>]*class=\"survol\"[^>]*>.*?<td[^>]*>.*?</td><td>(?P<team>[^<]+)</td>"
            r"<td[^>]*>\s*(?P<rating>\d{3,4})\s*</td>",
            decoded,
            flags=re.DOTALL,
        )
        ratings: dict[str, int] = {}
        for team, rating in rows:
            ratings[canonical_team_name(team.strip())] = int(rating)
        return ratings

