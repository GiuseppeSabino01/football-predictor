from features.market_features import fair_odd, recommendation, value_score


def test_fair_odd():
    assert fair_odd(0.5) == 2.0


def test_value_score():
    assert value_score(0.55, 2.0) == 0.1


def test_recommendation_value():
    assert recommendation(0.55, 2.0) == "Value"

