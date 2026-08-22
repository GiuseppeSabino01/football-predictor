from __future__ import annotations

from datetime import date, datetime
from io import StringIO

import pandas as pd
import requests

from config.settings import Settings
from schemas import Match


# Calendario ufficiale noto della Serie A 2026/27. Il seed rende GiGi
# indipendente dai limiti di API-Football e dai feed CSV non aggiornati.
# Le giornate successive possono continuare ad arrivare dalle API configurate.
SERIE_A_2026_FIXTURES: dict[str, list[tuple[str, str, str]]] = {
    "2026-08-22": [
        ("18:30", "Inter", "Monza"),
        ("18:30", "Udinese", "Como"),
        ("20:45", "Genoa", "Napoli"),
        ("20:45", "Parma", "Cagliari"),
    ],
    "2026-08-23": [
        ("18:30", "Frosinone", "Juventus"),
        ("18:30", "Venezia", "Lecce"),
        ("20:45", "Atalanta", "Sassuolo"),
        ("20:45", "Torino", "Milan"),
    ],
    "2026-08-24": [
        ("18:30", "Bologna", "Lazio"),
        ("20:45", "Roma", "Fiorentina"),
    ],
    "2026-08-28": [("20:45", "Milan", "Venezia")],
    "2026-08-29": [
        ("18:30", "Fiorentina", "Frosinone"),
        ("18:30", "Monza", "Udinese"),
        ("18:30", "Sassuolo", "Torino"),
        ("20:45", "Juventus", "Parma"),
    ],
    "2026-08-30": [
        ("18:30", "Napoli", "Como"),
        ("20:45", "Cagliari", "Inter"),
        ("20:45", "Lazio", "Genoa"),
    ],
    "2026-08-31": [
        ("18:30", "Lecce", "Roma"),
        ("20:45", "Atalanta", "Bologna"),
    ],
    "2026-09-04": [("20:45", "Genoa", "Como")],
    "2026-09-05": [
        ("15:00", "Fiorentina", "Torino"),
        ("18:00", "Inter", "Napoli"),
        ("20:45", "Roma", "Atalanta"),
    ],
    "2026-09-06": [
        ("15:00", "Frosinone", "Venezia"),
        ("15:00", "Parma", "Monza"),
        ("18:00", "Bologna", "Sassuolo"),
        ("20:45", "Juventus", "Milan"),
    ],
    "2026-09-07": [
        ("18:30", "Cagliari", "Lecce"),
        ("20:45", "Udinese", "Lazio"),
    ],
}


class SerieAHistoryClient:
    """Fixture e storico Serie A con fallback locale affidabile."""

    base_url = "https://www.football-data.co.uk/mmz4281/{season}/I1.csv"
    fixtures_url = "https://www.football-data.co.uk/matches/resources/fixtures.csv"

    def __init__(self, settings: Settings):
        self.settings = settings

    def load(self, target_date: date) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for season in ("2526", "2627"):
            frame = self._load_season(season)
            if not frame.empty:
                frames.append(frame)
        if not frames:
            return pd.DataFrame()
        result = pd.concat(frames, ignore_index=True)
        result["date"] = pd.to_datetime(result["date"], errors="coerce", dayfirst=True)
        result = result.dropna(subset=["date", "home_team", "away_team", "home_score", "away_score"])
        result = result[result["date"] < pd.Timestamp(target_date)].copy()
        result["home_score"] = result["home_score"].astype(int)
        result["away_score"] = result["away_score"].astype(int)
        result["date"] = result["date"].dt.strftime("%Y-%m-%d")
        return result.sort_values("date").reset_index(drop=True)

    def fixtures_for_date(self, target_date: date) -> list[Match]:
        # Prima usa il calendario verificato: il feed football-data.co.uk puo
        # essere vecchio (ad agosto 2026 espone ancora fixture del 2025/26).
        seeded = self._seeded_fixtures(target_date)
        if seeded:
            return seeded

        try:
            response = requests.get(
                self.fixtures_url,
                timeout=self.settings.request_timeout_seconds,
                verify=self.settings.verify_ssl,
                headers={"User-Agent": "football-predictor/1.0"},
            )
            if response.status_code >= 400:
                return []
            raw = pd.read_csv(StringIO(response.text))
        except Exception:
            return []
        if raw.empty or not {"Date", "HomeTeam", "AwayTeam"}.issubset(raw.columns):
            return []
        frame = raw.copy()
        if "Div" in frame.columns:
            frame = frame[frame["Div"].astype(str).str.upper().eq("I1")]
        parsed_dates = pd.to_datetime(frame["Date"], errors="coerce", dayfirst=True)
        frame = frame[parsed_dates.dt.date == target_date].copy()
        return self._matches_from_frame(target_date, frame)

    def _seeded_fixtures(self, target_date: date) -> list[Match]:
        rows = SERIE_A_2026_FIXTURES.get(target_date.isoformat(), [])
        matches: list[Match] = []
        for index, (kickoff_time, home, away) in enumerate(rows):
            kickoff = datetime.strptime(
                f"{target_date.isoformat()} {kickoff_time}", "%Y-%m-%d %H:%M"
            )
            matches.append(self._make_match(target_date, index, kickoff, home, away, "lega-serie-a"))
        return matches

    def _matches_from_frame(self, target_date: date, frame: pd.DataFrame) -> list[Match]:
        matches: list[Match] = []
        for index, row in frame.reset_index(drop=True).iterrows():
            time_value = str(row.get("Time", "00:00")).strip()
            try:
                kickoff = datetime.strptime(f"{target_date.isoformat()} {time_value}", "%Y-%m-%d %H:%M")
            except ValueError:
                kickoff = datetime.combine(target_date, datetime.min.time())
            matches.append(self._make_match(
                target_date, index, kickoff,
                str(row.get("HomeTeam", "Home")).strip(),
                str(row.get("AwayTeam", "Away")).strip(),
                "football-data.co.uk",
                row.to_dict(),
            ))
        return matches

    @staticmethod
    def _make_match(target_date: date, index: int, kickoff: datetime, home: str, away: str, source: str, raw=None) -> Match:
        match_id = f"serie-a-{target_date.isoformat()}-{index}-{home}-{away}".lower().replace(" ", "-")
        return Match(
            id=match_id,
            source=source,
            competition="Serie A 2026/27",
            season=2026,
            match_date=kickoff,
            home_team=home,
            away_team=away,
            status="SCHEDULED",
            stage="Regular Season",
            league_id=135,
            raw=raw or {},
        )

    def _load_season(self, season: str) -> pd.DataFrame:
        try:
            response = requests.get(
                self.base_url.format(season=season),
                timeout=self.settings.request_timeout_seconds,
                verify=self.settings.verify_ssl,
                headers={"User-Agent": "football-predictor/1.0"},
            )
            if response.status_code >= 400:
                return pd.DataFrame()
            raw = pd.read_csv(StringIO(response.text))
        except Exception:
            return pd.DataFrame()
        required = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}
        if not required.issubset(raw.columns):
            return pd.DataFrame()
        return raw.rename(columns={
            "Date": "date", "HomeTeam": "home_team", "AwayTeam": "away_team",
            "FTHG": "home_score", "FTAG": "away_score",
        })[["date", "home_team", "away_team", "home_score", "away_score"]]
