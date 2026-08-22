from datetime import UTC, datetime

from config.settings import load_settings
from features.team_strength import SERIE_A_STRENGTH_RATINGS
from models.ensemble import EnsemblePredictor
from schemas import Match
from services.predictor import PredictionService


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


def test_prediction_service_does_not_return_generic_serie_a_baseline() -> None:
    service = PredictionService(load_settings())
    match = _serie_a_match("Inter", "Monza")
    errors: list[str] = []

    ratings = service._load_team_ratings(match.match_date.date(), [match], errors)
    prediction = service.predictor.predict(match, team_ratings=ratings)
    probabilities = {
        pick.selection: pick.probability
        for pick in prediction.picks
        if pick.market == "1X2"
    }

    assert ratings["Inter"] == SERIE_A_STRENGTH_RATINGS["Inter"]
    assert ratings["Monza"] == SERIE_A_STRENGTH_RATINGS["Monza"]
    assert prediction.exact_score == "3-0"
    assert probabilities != {"Inter": 0.43, "Pareggio": 0.27, "Monza": 0.3}
    assert probabilities["Inter"] >= 0.75
