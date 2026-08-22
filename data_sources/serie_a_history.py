from __future__ import annotations

from datetime import date, datetime
from io import StringIO

import pandas as pd
import requests

from config.settings import Settings
from schemas import Match


class SerieAHistoryClient:
    """Fonte gratuita Serie A basata sui CSV di football-data.co.uk.

    Espone sia lo storico risultati sia le fixture correnti. In questo modo
    la Serie A continua a funzionare anche quando API-Football free non rende
    disponibili le stagioni recenti.
    """

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
        cutoff = pd.Timestamp(target_date)
        result = result[result["date"] < cutoff].copy()
        result["home_score"] = result["home_score"].astype(int)
        result["away_score"] = result["away_score"].astype(int)
        result["date"] = result["date"].dt.strftime("%Y-%m-%d")
        return result.sort_values("date").reset_index(drop=True)

    def fixtures_for_date(self, target_date: date) -> list[Match]:
        """Restituisce le partite di Serie A del giorno dal feed fixture gratuito."""
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
        if frame.empty:
            return []

        matches: list[Match] = []
        for index, row in frame.reset_index(drop=True).iterrows():
            time_value = str(row.get("Time", "00:00")).strip()
            try:
                kickoff = datetime.strptime(
                    f"{target_date.isoformat()} {time_value}", "%Y-%m-%d %H:%M"
                )
            except ValueError:
                kickoff = datetime.combine(target_date, datetime.min.time())

            home = str(row.get("HomeTeam", "Home")).strip()
            away = str(row.get("AwayTeam", "Away")).strip()
            match_id = f"serie-a-{target_date.isoformat()}-{index}-{home}-{away}".lower().replace(" ", "-")
            matches.append(
                Match(
                    id=match_id,
                    source="football-data.co.uk",
                    competition="Serie A 2026/27",
                    season=2026,
                    match_date=kickoff,
                    home_team=home,
                    away_team=away,
                    status="SCHEDULED",
                    stage="Regular Season",
                    league_id=135,
                    raw=row.to_dict(),
                )
            )
        return matches

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
        return raw.rename(
            columns={
                "Date": "date",
                "HomeTeam": "home_team",
                "AwayTeam": "away_team",
                "FTHG": "home_score",
                "FTAG": "away_score",
            }
        )[["date", "home_team", "away_team", "home_score", "away_score"]]
