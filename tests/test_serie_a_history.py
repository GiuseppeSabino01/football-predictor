from datetime import date

import pandas as pd

from config.settings import load_settings
from data_sources.serie_a_history import SerieAHistoryClient


def test_history_loads_enough_seasons_for_promoted_teams(monkeypatch) -> None:
    client = SerieAHistoryClient(load_settings())
    requested_seasons: list[str] = []

    def fake_load_season(season: str) -> pd.DataFrame:
        requested_seasons.append(season)
        return pd.DataFrame(
            [
                {
                    "date": "20/05/2024",
                    "home_team": "Monza",
                    "away_team": "Inter",
                    "home_score": 0,
                    "away_score": 2,
                }
            ]
        )

    monkeypatch.setattr(client, "_load_season", fake_load_season)

    frame = client.load(date(2026, 8, 22))

    assert requested_seasons == ["2324", "2425", "2526", "2627"]
    assert len(frame) == 4
