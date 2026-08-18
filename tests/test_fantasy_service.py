import pytest

from fantasy.catalog import make_player
from fantasy.service import (
    GAME_MODE_LIST,
    add_purchase,
    create_league,
    new_workspace,
    remove_purchase,
    roster_summary,
    set_captain,
    suggest_lineup,
    update_league_settings,
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


def test_list_mode_has_no_participants_and_uses_official_quote() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Listone",
        initial_budget=100,
        participants=None,
        game_mode=GAME_MODE_LIST,
    )
    player = make_player(name="Attaccante", team="Inter", role="A", quote=17)

    purchase = add_purchase(league, player, 99)

    assert league["participants"] is None
    assert purchase["price"] == 17
    assert roster_summary(league)["remaining_budget"] == 83


def test_custom_slots_cannot_drop_below_current_roster() -> None:
    workspace = new_workspace()
    league = create_league(workspace, "Regole", roster_slots={"P": 1, "D": 2, "C": 2, "A": 1})
    player = make_player(name="Portiere", team="Roma", role="P", quote=5)
    add_purchase(league, player, 5)

    with pytest.raises(ValueError, match="meno di 1 slot"):
        update_league_settings(
            league,
            name="Regole",
            initial_budget=250,
            participants=10,
            game_mode="auction",
            modifier_enabled=True,
            captain_enabled=False,
            roster_slots={"P": 0, "D": 2, "C": 2, "A": 1},
        )


def test_captain_is_cleared_when_player_is_removed() -> None:
    workspace = new_workspace()
    league = create_league(workspace, "Capitano", captain_enabled=True)
    player = make_player(name="Leader", team="Inter", role="A", quote=20)
    add_purchase(league, player, 20)

    set_captain(league, player["id"])
    remove_purchase(league, player["id"])

    assert league["captain_player_id"] is None
