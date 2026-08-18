import pytest

from fantasy.catalog import make_player
from fantasy.service import (
    GAME_MODE_AUCTION,
    GAME_MODE_LIST,
    add_purchase,
    add_purchases_batch,
    auction_manager_summary,
    auction_managers,
    auction_player_assignment,
    auction_player_tier,
    auction_price_board,
    create_auction_tier,
    create_league,
    delete_auction_tier,
    delete_league,
    list_trade_analysis,
    new_workspace,
    normalize_workspace,
    record_auction_purchase,
    remove_purchase,
    reset_preferred_xi,
    role_balance_recommendation,
    roster_summary,
    set_captain,
    set_preferred_xi,
    suggest_lineup,
    top_xi_formation,
    top_xi_summary,
    update_auction_assignments,
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
    assert automatic["expected_goals_total"] == pytest.approx(66)
    assert automatic["expected_assists_total"] == pytest.approx(33)
    assert automatic["expected_fantasy_average_sum"] == pytest.approx(72.6)

    custom_ids = [player["id"] for player in players[:11]]
    set_preferred_xi(league, custom_ids)
    assert top_xi_summary(league)["player_ids"] == custom_ids

    reset_preferred_xi(league)
    assert top_xi_summary(league)["player_ids"] == automatic["player_ids"]


def test_top_xi_uses_most_expensive_players_compatible_with_formation() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Campo",
        initial_budget=1000,
        roster_slots={"P": 2, "D": 5, "C": 5, "A": 4},
    )
    for role, count in {"P": 2, "D": 5, "C": 5, "A": 4}.items():
        for index in range(count):
            player = make_player(
                name=f"{role}{index}",
                team="Roma",
                role=role,
                quote=index + 1,
                expected_goals=1,
                expected_assists=0.5,
            )
            player["expected_fantasy_average"] = 6
            add_purchase(league, player, index + 1)
    league["preferred_formation"] = "4-3-3"

    summary = top_xi_summary(league)
    role_counts = {
        role: sum(1 for row in summary["players"] if row["role"] == role)
        for role in ("P", "D", "C", "A")
    }

    assert top_xi_formation(league) == "4-3-3"
    assert role_counts == {"P": 1, "D": 4, "C": 3, "A": 3}
    assert summary["expected_goals_total"] == 11
    assert summary["expected_assists_total"] == 5.5
    assert summary["expected_fantasy_average_sum"] == 66


def test_list_trade_analysis_preserves_roles_cost_and_budget() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Swap Lab",
        initial_budget=20,
        participants=None,
        game_mode=GAME_MODE_LIST,
        roster_slots={"P": 0, "D": 1, "C": 1, "A": 0},
    )
    owned = [
        make_player(name="D low", team="Roma", role="D", quote=8, expected_goals=1),
        make_player(name="C low", team="Roma", role="C", quote=12, expected_goals=1),
    ]
    candidates = [
        make_player(
            name="D high", team="Milan", role="D", quote=10,
            expected_goals=5, expected_assists=4, starter_probability=90,
        ),
        make_player(
            name="C high", team="Milan", role="C", quote=10,
            expected_goals=5, expected_assists=4, starter_probability=90,
        ),
    ]
    for player in owned:
        player.update({"expected_fantasy_average": 5.5, "reliability": 60, "risk": 30})
        add_purchase(league, player, player["quote"])
    for player in candidates:
        player.update({"expected_fantasy_average": 7.0, "reliability": 90, "risk": 5})

    analysis = list_trade_analysis(league, [*owned, *candidates])

    assert analysis["ready"] is True
    trade = analysis["trades"][0]
    assert trade["outgoing_total"] == trade["incoming_total"] == 20
    assert trade["projected_spent"] <= league["initial_budget"]
    assert sorted(row["role"] for row in trade["outgoing"]) == sorted(
        row["role"] for row in trade["incoming"]
    )
    assert {row["name"] for row in trade["incoming"]} == {"D high", "C high"}


def test_auction_tracks_every_manager_and_updates_comparable_prices() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Asta live",
        initial_budget=500,
        participants=3,
        game_mode=GAME_MODE_AUCTION,
        roster_slots={"P": 1, "D": 1, "C": 1, "A": 2},
    )
    lautaro = make_player(name="Lautaro", team="Inter", role="A", quote=35)
    douvikas = make_player(name="Douvikas", team="Como", role="A", quote=25)
    perrone = make_player(name="Perrone", team="Como", role="C", quote=15)
    lautaro.update({"fvm": 200, "tier": "Top", "expected_fantasy_average": 7.5})
    douvikas.update({"fvm": 160, "tier": "Buono", "expected_fantasy_average": 7.0})
    perrone.update({"fvm": 100, "tier": "Buono", "expected_fantasy_average": 6.5})
    managers = auction_managers(league)

    record_auction_purchase(league, managers[1]["id"], lautaro, 85)
    prices = auction_price_board(league, [lautaro, douvikas, perrone])

    assert auction_manager_summary(league, managers[1]["id"])["remaining_budget"] == 415
    assert prices[douvikas["id"]]["comparables"] == 1
    assert prices[douvikas["id"]]["updated"] != prices[douvikas["id"]]["initial"]
    assert prices[perrone["id"]]["comparables"] == 0


def test_custom_auction_tiers_are_isolated_and_do_not_drive_market_prices() -> None:
    workspace = new_workspace()
    first = create_league(
        workspace,
        "Asta uno",
        initial_budget=500,
        participants=2,
        game_mode=GAME_MODE_AUCTION,
    )
    second = create_league(
        workspace,
        "Asta due",
        initial_budget=500,
        participants=2,
        game_mode=GAME_MODE_AUCTION,
    )
    player = make_player(name="Dimarco", team="Inter", role="D", quote=32)
    tier = create_auction_tier(first, "Top difensori", "red")

    update_auction_assignments(
        first,
        [
            {
                "player": player,
                "manager_id": None,
                "price": 0,
                "update_assignment": False,
                "tier_id": tier["id"],
            }
        ],
    )

    assert auction_player_tier(first, player["id"])["name"] == "Top difensori"
    assert [tier["name"] for tier in second["auction_tiers"]] == [
        "Top",
        "Semi-top",
        "Terza fascia",
        "Quarta fascia",
        "Quinta fascia",
        "Scommesse",
        "Titolari",
    ]
    assert second["auction_player_tiers"] == {}

    delete_auction_tier(first, tier["id"])
    assert auction_player_tier(first, player["id"]) is None


def test_auction_default_tiers_have_independent_ids_per_league() -> None:
    workspace = new_workspace()
    first = create_league(
        workspace,
        "Prima asta",
        participants=2,
        game_mode=GAME_MODE_AUCTION,
    )
    second = create_league(
        workspace,
        "Seconda asta",
        participants=2,
        game_mode=GAME_MODE_AUCTION,
    )

    expected_names = [
        "Top",
        "Semi-top",
        "Terza fascia",
        "Quarta fascia",
        "Quinta fascia",
        "Scommesse",
        "Titolari",
    ]
    assert [tier["name"] for tier in first["auction_tiers"]] == expected_names
    assert [tier["name"] for tier in second["auction_tiers"]] == expected_names
    assert {tier["id"] for tier in first["auction_tiers"]}.isdisjoint(
        tier["id"] for tier in second["auction_tiers"]
    )


def test_existing_auction_without_tiers_receives_defaults_once() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Asta esistente",
        participants=2,
        game_mode=GAME_MODE_AUCTION,
    )
    league.pop("auction_tiers_initialized")
    league["auction_tiers"] = []

    normalized = normalize_workspace(workspace)
    normalized_league = normalized["leagues"][0]

    assert [tier["name"] for tier in normalized_league["auction_tiers"]] == [
        "Top",
        "Semi-top",
        "Terza fascia",
        "Quarta fascia",
        "Quinta fascia",
        "Scommesse",
        "Titolari",
    ]
    normalized_league["auction_tiers"] = []
    assert normalize_workspace(normalized)["leagues"][0]["auction_tiers"] == []


def test_strategic_auction_price_stops_one_above_richest_opponent() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Credito avversari",
        initial_budget=80,
        participants=3,
        game_mode=GAME_MODE_AUCTION,
        roster_slots={"P": 0, "D": 0, "C": 0, "A": 1},
    )
    filler_a = make_player(name="Spesa A", team="Roma", role="A", quote=1)
    filler_b = make_player(name="Spesa B", team="Milan", role="A", quote=1)
    target = make_player(name="Douvikas", team="Como", role="A", quote=25)
    filler_a.update({"fvm": 10, "tier": "Scommessa"})
    filler_b.update({"fvm": 10, "tier": "Scommessa"})
    target.update({"fvm": 600, "tier": "Top"})
    managers = auction_managers(league)
    record_auction_purchase(league, managers[1]["id"], filler_a, 50)
    record_auction_purchase(league, managers[2]["id"], filler_b, 50)

    estimate = auction_price_board(league, [filler_a, filler_b, target])[target["id"]]

    assert estimate["highest_opponent_credit"] == 30
    assert estimate["strategic"] == 31


def test_delete_league_keeps_other_fantacalci() -> None:
    workspace = new_workspace()
    first = create_league(workspace, "Da eliminare")
    second = create_league(workspace, "Da conservare")

    delete_league(workspace, first["id"])

    assert [league["name"] for league in workspace["leagues"]] == ["Da conservare"]
    assert workspace["active_league_id"] == second["id"]


def test_auction_grid_can_reprice_transfer_and_unassign_player() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Editor asta",
        initial_budget=100,
        participants=3,
        game_mode=GAME_MODE_AUCTION,
        roster_slots={"P": 1, "D": 1, "C": 1, "A": 1},
    )
    player = make_player(name="Provedel", team="Lazio", role="P", quote=2)
    managers = auction_managers(league)
    first_rival = str(managers[1]["id"])
    second_rival = str(managers[2]["id"])
    record_auction_purchase(league, first_rival, player, 5)

    update_auction_assignments(
        league,
        [{"player": player, "manager_id": first_rival, "price": 8}],
    )
    assignment = auction_player_assignment(league, player["id"])
    assert assignment is not None
    assert assignment["manager_id"] == first_rival
    assert assignment["purchase"]["price"] == 8

    update_auction_assignments(
        league,
        [{"player": player, "manager_id": second_rival, "price": 11}],
    )
    assignment = auction_player_assignment(league, player["id"])
    assert assignment is not None
    assert assignment["manager_id"] == second_rival
    assert assignment["purchase"]["price"] == 11
    assert auction_manager_summary(league, first_rival)["roster_size"] == 0

    update_auction_assignments(
        league,
        [{"player": player, "manager_id": None, "price": 0}],
    )
    assert auction_player_assignment(league, player["id"]) is None


def test_auction_grid_changes_are_atomic_when_one_price_is_invalid() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Editor atomico",
        initial_budget=20,
        participants=2,
        game_mode=GAME_MODE_AUCTION,
        roster_slots={"P": 2, "D": 0, "C": 0, "A": 0},
    )
    first = make_player(name="Portiere 1", team="Roma", role="P", quote=1)
    second = make_player(name="Portiere 2", team="Milan", role="P", quote=1)
    rival_id = str(auction_managers(league)[1]["id"])

    with pytest.raises(ValueError, match="Crediti insufficienti"):
        update_auction_assignments(
            league,
            [
                {"player": first, "manager_id": rival_id, "price": 5},
                {"player": second, "manager_id": rival_id, "price": 30},
            ],
        )

    assert auction_player_assignment(league, first["id"]) is None
    assert auction_player_assignment(league, second["id"]) is None
