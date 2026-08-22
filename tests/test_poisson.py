from models.poisson import (
    both_teams_to_score,
    exact_score,
    exact_score_for_outcome,
    over_under_25,
    representative_score_for_outcome,
    score_matrix,
)


def test_score_matrix_normalizes():
    matrix = score_matrix(1.4, 1.1)
    assert abs(sum(matrix.values()) - 1.0) < 0.000001


def test_exact_score_has_dash():
    assert "-" in exact_score(score_matrix(1.4, 1.1))


def test_exact_score_can_be_constrained_to_pick_outcome():
    matrix = score_matrix(0.95, 1.35)
    score = exact_score_for_outcome(matrix, "away")
    home_goals, away_goals = [int(value) for value in score.split("-")]
    assert away_goals > home_goals


def test_representative_score_expresses_a_dominant_home_win():
    matrix = score_matrix(2.45, 0.75)

    assert representative_score_for_outcome(matrix, "home") == "3-0"


def test_representative_score_uses_expected_goals_for_an_away_favorite():
    matrix = score_matrix(0.90, 1.60)

    assert representative_score_for_outcome(matrix, "away") == "1-2"


def test_representative_score_keeps_tight_games_conservative():
    matrix = score_matrix(1.05, 1.28)

    assert representative_score_for_outcome(matrix, "away") == "0-1"


def test_markets_are_probabilities():
    matrix = score_matrix(1.4, 1.1)
    for values in (over_under_25(matrix), both_teams_to_score(matrix)):
        assert abs(sum(values.values()) - 1.0) < 0.000001
