import pytest

from fantasy.catalog import make_player
from fantasy.service import (
    add_purchase,
    create_league,
    new_workspace,
    roster_summary,
    suggest_lineup,
)


def test_multiple_leagues_keep_independent_rosters() -> None:
    workspace = new_workspace()
    first = create_league(workspace, "Fanta amici", initial_budget=250)
    second = create_league(workspace, "Fanta lavoro", initial_budget=500)
    player = make_player(name="Attaccante", team="Inter", role="A", quote=30)

    add_purchase(first, player, 40)

    assert len(workspace["leagues"]) == 2
    assert roster_summary(first)["remaining_budget"] == 210
    assert roster_summary(second)["remaining_budget"] == 500
    assert second["purchases"] == []


def test_purchase_respects_budget_and_role_limits() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Mini fanta",
        initial_budget=10,
        roster_slots={"P": 1, "D": 0, "C": 0, "A": 0},
    )
    first = make_player(name="Portiere uno", team="Roma", role="P", quote=1)
    second = make_player(name="Portiere due", team="Milan", role="P", quote=1)

    add_purchase(league, first, 10)

    with pytest.raises(ValueError, match="Crediti insufficienti|completato"):
        add_purchase(league, second, 1)


def test_modifier_prefers_four_defenders() -> None:
    workspace = new_workspace()
    league = create_league(workspace, "Modificatore", initial_budget=250, modifier_enabled=True)
    players = [
        make_player(name="P1", team="Roma", role="P", quote=10),
        *[make_player(name=f"D{i}", team="Roma", role="D", quote=10 + i) for i in range(1, 5)],
        *[make_player(name=f"C{i}", team="Roma", role="C", quote=10 + i) for i in range(1, 4)],
        *[make_player(name=f"A{i}", team="Roma", role="A", quote=10 + i) for i in range(1, 4)],
    ]
    for player in players:
        add_purchase(league, player, 1)

    lineup = suggest_lineup(league)

    assert lineup is not None
    assert lineup["formation"] == "4-3-3"
    assert len(lineup["players"]["D"]) == 4
