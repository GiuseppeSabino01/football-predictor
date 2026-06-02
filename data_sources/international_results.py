from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from config.settings import Settings


class InternationalResultsClient:
    url = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache_path = Path(settings.sqlite_path).parent / "international_results.csv"

    def load(self, target_date: date) -> pd.DataFrame:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._cache_is_fresh():
            self._download()

        frame = pd.read_csv(self.cache_path)
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
        frame = frame.dropna(subset=["date", "home_team", "away_team", "home_score", "away_score"])
        frame = frame[frame["date"] < target_date]
        frame["home_score"] = frame["home_score"].astype(int)
        frame["away_score"] = frame["away_score"].astype(int)
        return frame

    def _cache_is_fresh(self) -> bool:
        if not self.cache_path.exists():
            return False
        modified_at = datetime.fromtimestamp(self.cache_path.stat().st_mtime)
        return datetime.now() - modified_at < timedelta(days=7)

    def _download(self) -> None:
        response = requests.get(
            self.url,
            timeout=self.settings.request_timeout_seconds,
            verify=self.settings.verify_ssl,
        )
        response.raise_for_status()
        self.cache_path.write_bytes(response.content)

