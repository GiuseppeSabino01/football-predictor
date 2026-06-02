from datetime import date

import pandas as pd

from features.historical_stats import HistoricalStatsBuilder
from features.team_strength import canonical_team_name, rating_based_1x2


def test_canonical_team_names():
    assert canonical_team_name("Italia") == "Italy"
    assert canonical_team_name("Paesi Bassi") == "Netherlands"
    assert canonical_team_name("Turchia") == "Turkey"
    assert canonical_team_name("Repubblica Ceca") == "Czech Republic"
    assert canonical_team_name("Bosnia ed Erzegovina") == "Bosnia and Herzegovina"
    assert canonical_team_name("Corea del Sud") == "South Korea"
    assert canonical_team_name("Kanada") == "Canada"


def test_rating_based_probabilities_vary_by_team_strength():
    probabilities = rating_based_1x2("Qatar", "Svizzera")
    assert probabilities is not None
    assert probabilities["away"] > probabilities["home"]


def test_historical_stats_builder():
    frame = pd.DataFrame(
        [
            {
                "date": date(2026, 1, 1),
                "home_team": "Germany",
                "away_team": "Italy",
                "home_score": 2,
                "away_score": 2,
            },
            {
                "date": date(2025, 1, 1),
                "home_team": "Italy",
                "away_team": "Germany",
                "home_score": 2,
                "away_score": 2,
            },
            {
                "date": date(2024, 1, 1),
                "home_team": "Italy",
                "away_team": "France",
                "home_score": 1,
                "away_score": 0,
            },
        ]
    )
    stats = HistoricalStatsBuilder(frame).build("Germany", "Italy")
    assert stats.h2h.matches == 2
    assert stats.h2h.most_common_score == ((2, 2), 1.0)
    assert stats.home_recent.scored_rate == 1.0
    assert stats.away_recent.scored_rate == 1.0
    assert "vinte" in stats.notes[0]
    assert "Gol fatti" in stats.notes[0]
    assert "H2H" in stats.notes[2]
