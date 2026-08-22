from models.empirical_score import (
    empirical_1x2,
    empirical_both_teams_to_score,
    empirical_over_under_25,
    empirical_scoreline,
)


def test_empirical_probabilities_are_normalized_and_reflect_strength_gap() -> None:
    probabilities = empirical_1x2(2.45, 0.75)

    assert abs(sum(probabilities.values()) - 1.0) < 0.000001
    assert probabilities["home"] > 0.70


def test_empirical_scoreline_expresses_dominant_home_win() -> None:
    probabilities = empirical_1x2(2.45, 0.75)

    assert empirical_scoreline(2.45, 0.75, "home", probabilities) == "3-0"


def test_empirical_scoreline_expresses_away_favorite() -> None:
    probabilities = empirical_1x2(0.90, 1.60)

    assert empirical_scoreline(0.90, 1.60, "away", probabilities) == "1-2"


def test_empirical_scoreline_keeps_tight_game_conservative() -> None:
    probabilities = empirical_1x2(1.05, 1.28)

    assert empirical_scoreline(1.05, 1.28, "away", probabilities) == "0-1"


def test_empirical_goal_markets_are_probabilities() -> None:
    for values in (
        empirical_over_under_25(1.4, 1.1),
        empirical_both_teams_to_score(1.4, 1.1),
    ):
        assert abs(sum(values.values()) - 1.0) < 0.000001
