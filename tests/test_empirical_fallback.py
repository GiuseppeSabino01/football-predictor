from datetime import UTC, datetime

from features.team_strength import SERIE_A_STRENGTH_RATINGS
from models.ensemble import EnsemblePredictor
from schemas import Match


def _serie_a_match(home: str, away: str) -> Match:
    return Match(
        id=f"{home}-{away}",
        source="test",
        competition="Serie A 2026/27",
        season=2026,
        match_date=datetime(2026, 8, 22, tzinfo=UTC),
        home_team=home,
        away_team=away,
        league_id=135,
    )


def test_local_strength_fallback_keeps_scorelines_team_specific() -> None:
    predictor = EnsemblePredictor()
    fixtures = [
        ("Inter", "Monza"),
        ("Udinese", "Como"),
        ("Frosinone", "Juventus"),
        ("Torino", "Milan"),
    ]

    scores = {
        fixture: predictor.predict(
            _serie_a_match(*fixture),
            team_ratings=SERIE_A_STRENGTH_RATINGS,
        ).exact_score
        for fixture in fixtures
    }

    assert scores[("Inter", "Monza")] == "3-0"
    assert scores[("Udinese", "Como")] == "1-2"
    assert scores[("Frosinone", "Juventus")] == "0-2"
    assert len(set(scores.values())) >= 3
