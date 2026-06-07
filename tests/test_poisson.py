from models.poisson import both_teams_to_score, exact_score, exact_score_for_outcome, over_under_25, score_matrix


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


def test_markets_are_probabilities():
    matrix = score_matrix(1.4, 1.1)
    for values in (over_under_25(matrix), both_teams_to_score(matrix)):
        assert abs(sum(values.values()) - 1.0) < 0.000001
