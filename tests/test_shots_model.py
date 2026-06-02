from models.shots_model import ShotsModel


def test_team_shots_and_corners_use_dynamic_lines():
    model = ShotsModel()
    picks = model.team_shots("Messico", "Sudafrica", home_xg=1.8, away_xg=0.8)

    assert len(picks) == 8
    markets = {pick.market for pick in picks}
    assert "Over tiri squadra casa" in markets
    assert "Under tiri squadra casa" in markets
    assert "Over tiri squadra ospiti" in markets
    assert "Under tiri squadra ospiti" in markets
    assert "Over angoli squadra casa" in markets
    assert "Under angoli squadra casa" in markets
    assert "Over angoli squadra ospiti" in markets
    assert "Under angoli squadra ospiti" in markets
    assert all(pick.selection.endswith(".5") for pick in picks)

    home_shots = [pick for pick in picks if pick.market.endswith("tiri squadra casa")]
    away_shots = [pick for pick in picks if pick.market.endswith("tiri squadra ospiti")]
    assert home_shots[0].selection != away_shots[0].selection


def test_over_under_pair_probabilities_are_complementary():
    model = ShotsModel()
    picks = model.team_shots("A", "B", home_xg=1.4, away_xg=1.2)
    grouped = {}
    for pick in picks:
        key = pick.market.replace("Over ", "").replace("Under ", ""), pick.selection
        grouped.setdefault(key, []).append(pick.probability)

    assert all(abs(sum(probabilities) - 1) <= 0.001 for probabilities in grouped.values())
