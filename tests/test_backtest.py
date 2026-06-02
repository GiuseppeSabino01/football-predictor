from datetime import date, timedelta

import pandas as pd

from features.backtest import HistoricalBacktester


def test_historical_backtester_returns_reliability_metrics():
    teams = ["France", "Brazil", "Germany", "Italy"]
    start = date(2024, 1, 1)
    rows = []
    for index in range(18):
        home = teams[index % len(teams)]
        away = teams[(index + 1) % len(teams)]
        rows.append(
            {
                "date": start + timedelta(days=index * 10),
                "home_team": home,
                "away_team": away,
                "home_score": 2 if index % 3 else 1,
                "away_score": 1 if index % 4 else 1,
            }
        )

    report = HistoricalBacktester().run(pd.DataFrame(rows), max_matches=5, min_team_matches=1)

    assert report.samples > 0
    assert [market.market for market in report.markets] == ["1X2", "Over/Under 2.5", "Goal/No Goal"]
    assert all(0 <= market.hit_rate <= 1 for market in report.markets)
    assert all(0 <= market.brier_score <= 1 for market in report.markets)
    assert report.recent_rows
    assert "Reale" in report.recent_rows[0]
