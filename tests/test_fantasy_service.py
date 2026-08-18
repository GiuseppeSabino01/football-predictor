import pytest

from fantasy.catalog import make_player
from fantasy.service import (
    GAME_MODE_LIST,
    add_purchase,
    add_purchases_batch,
    create_league,
    new_workspace,
    remove_purchase,
    reset_preferred_xi,
    role_balance_recommendation,
    roster_summary,
    set_captain,
    set_preferred_xi,
    suggest_lineup,
    top_xi_summary,
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


def test_batch_purchase_is_atomic() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Batch",
        initial_budget=20,
        roster_slots={"P": 0, "D": 0, "C": 2, "A": 0},
    )
    players = [
        make_player(name="C1", team="Roma", role="C", quote=12),
        make_player(name="C2", team="Milan", role="C", quote=12),
    ]

    with pytest.raises(ValueError, match="Crediti insufficienti"):
        add_purchases_batch(league, players)

    assert league["purchases"] == []


def test_role_advice_starts_at_half_slots_and_recommends_goals() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Consigli",
        initial_budget=250,
        roster_slots={"P": 0, "D": 0, "C": 7, "A": 0},
    )
    owned = [
        make_player(
            name=f"Titolare {index}",
            team="Roma",
            role="C",
            quote=5,
            expected_goals=1,
            expected_assists=2,
            starter_probability=90,
        )
        for index in range(4)
    ]
    candidates = [
        make_player(
            name=f"Bomber {index}",
            team="Milan",
            role="C",
            quote=10,
            expected_goals=8 - index,
            expected_assists=3,
            starter_probability=80,
        )
        for index in range(6)
    ]
    add_purchases_batch(league, owned)

    advice = role_balance_recommendation(league, [*owned, *candidates], "C")

    assert advice is not None
    assert advice["focus"] == "goals"
    assert len(advice["candidates"]) == 5
    assert advice["candidates"][0]["name"] == "Bomber 0"


def test_top_xi_defaults_to_most_expensive_and_can_be_customized() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Top 11",
        initial_budget=500,
        roster_slots={"P": 0, "D": 0, "C": 12, "A": 0},
    )
    players = []
    for index in range(12):
        player = make_player(
            name=f"Player {index}",
            team="Roma",
            role="C",
            quote=index + 1,
            expected_goals=index,
            expected_assists=index / 2,
        )
        player["expected_fantasy_average"] = 6 + index / 10
        players.append(player)
        add_purchase(league, player, index + 1)

    automatic = top_xi_summary(league)
    assert automatic["count"] == 11
    assert "Player 0" not in {row["name"] for row in automatic["players"]}
    assert automatic["expected_fantasy_average"] == pytest.approx(6.6)

    custom_ids = [player["id"] for player in players[:11]]
    set_preferred_xi(league, custom_ids)
    assert top_xi_summary(league)["player_ids"] == custom_ids

    reset_preferred_xi(league)
    assert top_xi_summary(league)["player_ids"] == automatic["player_ids"]
