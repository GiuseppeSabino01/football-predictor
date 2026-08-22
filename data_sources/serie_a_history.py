from __future__ import annotations

from datetime import date
from io import StringIO

import pandas as pd
import requests

from config.settings import Settings


class SerieAHistoryClient:
    """Carica risultati Serie A gratuiti da football-data.co.uk.

    Lo storico viene normalizzato nello stesso schema usato dal motore
    HistoricalStatsBuilder dei Mondiali: date, home_team, away_team,
    home_score, away_score.
    """

    base_url = "https://www.football-data.co.uk/mmz4281/{season}/I1.csv"

    def __init__(self, settings: Settings):
        self.settings = settings

    def load(self, target_date: date) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        # Per l'avvio della 2026/27 servono sia la stagione precedente sia
        # le partite gia giocate nella stagione corrente.
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

    def _load_season(self, season: str) -> pd.DataFrame:
        try:
            response = requests.get(
                self.base_url.format(season=season),
                timeout=self.settings.request_timeout_seconds,
                verify=self.settings.verify_ssl,
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
