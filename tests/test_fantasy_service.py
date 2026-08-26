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
    auction_trade_analysis,
    create_auction_tier,
    create_league,
    delete_auction_tier,
    delete_league,
    list_trade_analysis,
    new_workspace,
    normalize_workspace,
    player_note,
    record_auction_purchase,
    remove_purchase,
    reset_preferred_xi,
    role_balance_recommendation,
    roster_summary,
    set_auction_trade_exclusions,
    set_captain,
    set_preferred_xi,
    suggest_lineup,
    top_xi_formation,
    top_xi_summary,
    update_auction_assignments,
    update_league_settings,
    update_list_assignments,
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


def test_list_board_updates_roster_and_personal_tier_atomically() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Listone modificabile",
        initial_budget=50,
        participants=None,
        game_mode=GAME_MODE_LIST,
        roster_slots={"P": 1, "D": 1, "C": 1, "A": 1},
    )
    player = make_player(name="Molina N.", team="ROM", role="D", quote=18)
    top_tier = next(
        tier for tier in league["auction_tiers"] if tier["name"] == "Top"
    )

    update_list_assignments(
        league,
        [{"player": player, "in_roster": True, "tier_id": top_tier["id"]}],
    )

    assert [row["name"] for row in league["purchases"]] == ["Molina N."]
    assert auction_player_tier(league, player["id"])["name"] == "Top"

    update_list_assignments(
        league,
        [{"player": player, "in_roster": False}],
    )

    assert league["purchases"] == []
    assert auction_player_tier(league, player["id"])["name"] == "Top"


def test_player_note_is_saved_and_removed_from_the_list_board() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Listone con note",
        participants=None,
        game_mode=GAME_MODE_LIST,
    )
    player = make_player(name="Meret", team="NAP", role="P", quote=18)

    update_list_assignments(
        league,
        [{
            "player": player,
            "in_roster": False,
            "note": "Da prendere insieme a Milinkovic",
        }],
    )

    assert player_note(league, player["id"]) == "Da prendere insieme a Milinkovic"

    update_list_assignments(
        league,
        [{"player": player, "in_roster": False, "note": ""}],
    )
    assert player_note(league, player["id"]) == ""

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


def test_auction_trade_analysis_matches_reciprocal_role_needs() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Scambi asta",
        initial_budget=500,
        participants=2,
        game_mode=GAME_MODE_AUCTION,
        roster_slots={"P": 0, "D": 0, "C": 2, "A": 2},
    )
    managers = auction_managers(league)

    def player(name: str, role: str, goals: float, assists: float) -> dict:
        item = make_player(
            name=name,
            team="TEST",
            role=role,
            quote=20,
            expected_goals=goals,
            expected_assists=assists,
            starter_probability=85,
        )
        item.update(
            {
                "fvm": 80,
                "expected_fantasy_average": 6.8,
                "reliability": 82,
                "risk": 18,
            }
        )
        return item

    attackers = [
        player("Attaccante uno", "A", 8, 3),
        player("Attaccante due", "A", 7, 4),
    ]
    midfielders = [
        player("Centrocampista uno", "C", 7, 4),
        player("Centrocampista due", "C", 8, 3),
    ]
    for item in attackers:
        record_auction_purchase(league, managers[0]["id"], item, 30)
    for item in midfielders:
        record_auction_purchase(league, managers[1]["id"], item, 30)
    excluded_id = attackers[0]["id"]
    set_auction_trade_exclusions(league, [excluded_id])

    analysis = auction_trade_analysis(
        league, [*attackers, *midfielders], limit=5
    )

    assert analysis["ready"] is True
    assert analysis["evaluated_opponents"] == 1
    assert analysis["trades"]
    assert all(trade["user_improvement"] >= 4 for trade in analysis["trades"])
    assert all(
        trade["opponent_improvement"] >= 1.5 for trade in analysis["trades"]
    )
    assert all(trade["fairness"] >= 80 for trade in analysis["trades"])
    assert all(
        0 <= trade["user_improvement"] <= 15
        and 0 <= trade["opponent_improvement"] <= 15
        and trade["gain_gap"] <= 5
        for trade in analysis["trades"]
    )
    assert analysis["excluded_players"] == 1
    assert all(
        excluded_id
        not in {str(player.get("id")) for player in trade["outgoing"]}
        for trade in analysis["trades"]
    )
    first = analysis["trades"][0]
    assert {row["role"] for row in first["outgoing"]} == {"A"}
    assert {row["role"] for row in first["incoming"]} == {"C"}


def test_auction_trade_analysis_rejects_lopsided_star_trade() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Niente regali",
        initial_budget=500,
        participants=2,
        game_mode=GAME_MODE_AUCTION,
        roster_slots={"P": 0, "D": 0, "C": 1, "A": 1},
    )
    managers = auction_managers(league)
    varela = make_player(
        name="Varela",
        team="LAZ",
        role="C",
        quote=8,
        expected_goals=1,
        expected_assists=1,
        starter_probability=65,
    )
    varela.update(
        {"fvm": 35, "expected_fantasy_average": 6.1, "reliability": 62, "risk": 28}
    )
    lautaro = make_player(
        name="Lautaro",
        team="INT",
        role="A",
        quote=38,
        expected_goals=22,
        expected_assists=6,
        starter_probability=92,
    )
    lautaro.update(
        {"fvm": 300, "expected_fantasy_average": 8.1, "reliability": 90, "risk": 12}
    )
    record_auction_purchase(league, managers[0]["id"], varela, 10)
    record_auction_purchase(league, managers[1]["id"], lautaro, 120)

    analysis = auction_trade_analysis(league, [varela, lautaro])

    assert analysis["ready"] is True
    assert analysis["trades"] == []
    assert "equilibrio dei valori" in analysis["reason"]


def test_auction_trade_analysis_can_balance_value_with_three_for_three() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Scambio tre per tre",
        initial_budget=500,
        participants=2,
        game_mode=GAME_MODE_AUCTION,
        roster_slots={"P": 0, "D": 0, "C": 3, "A": 3},
    )
    managers = auction_managers(league)

    def player(
        name: str,
        role: str,
        *,
        fantasy_average: float,
        goals: float,
        assists: float,
        quote: float,
        fvm: float,
        starter: float,
        reliability: float,
        risk: float,
    ) -> dict:
        item = make_player(
            name=name,
            team="TEST",
            role=role,
            quote=quote,
            expected_goals=goals,
            expected_assists=assists,
            starter_probability=starter,
        )
        item.update(
            {
                "fvm": fvm,
                "expected_fantasy_average": fantasy_average,
                "reliability": reliability,
                "risk": risk,
            }
        )
        return item

    attackers = [
        player(
            "A top",
            "A",
            fantasy_average=8.8,
            goals=28,
            assists=8,
            quote=45,
            fvm=350,
            starter=95,
            reliability=92,
            risk=8,
        ),
        *[
            player(
                f"A riserva {index}",
                "A",
                fantasy_average=5.2,
                goals=0,
                assists=0,
                quote=1,
                fvm=5,
                starter=35,
                reliability=40,
                risk=50,
            )
            for index in range(2)
        ],
    ]
    midfielders = [
        player(
            f"C equilibrato {index}",
            "C",
            fantasy_average=6.8,
            goals=5,
            assists=4,
            quote=18,
            fvm=90,
            starter=82,
            reliability=80,
            risk=20,
        )
        for index in range(3)
    ]
    for index, item in enumerate(attackers):
        record_auction_purchase(
            league, managers[0]["id"], item, 130 if index == 0 else 1
        )
    for item in midfielders:
        record_auction_purchase(league, managers[1]["id"], item, 30)

    analysis = auction_trade_analysis(league, [*attackers, *midfielders])

    assert analysis["trades"]
    assert len(analysis["trades"][0]["outgoing"]) == 3
    assert len(analysis["trades"][0]["incoming"]) == 3
    assert analysis["trades"][0]["fairness"] >= 80


def test_auction_trade_analysis_returns_best_balanced_fallbacks() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Scambi sotto soglia",
        initial_budget=500,
        participants=2,
        game_mode=GAME_MODE_AUCTION,
        roster_slots={"P": 0, "D": 0, "C": 1, "A": 0},
    )
    managers = auction_managers(league)
    own = make_player(name="Mediano mio", team="ROM", role="C", quote=15)
    rival = make_player(name="Mediano rivale", team="MIL", role="C", quote=15)
    for player in (own, rival):
        player.update(
            {
                "fvm": 70,
                "expected_fantasy_average": 6.5,
                "expected_goals": 2,
                "expected_assists": 3,
                "starter_probability": 80,
                "reliability": 80,
                "risk": 20,
            }
        )
    record_auction_purchase(league, managers[0]["id"], own, 25)
    record_auction_purchase(league, managers[1]["id"], rival, 25)

    analysis = auction_trade_analysis(league, [own, rival], limit=10)

    assert analysis["ready"] is True
    assert analysis["fallback"] is True
    assert len(analysis["trades"]) == 1
    assert analysis["trades"][0]["meets_threshold"] is False
    assert analysis["trades"][0]["fairness"] == 100
    assert analysis["trades"][0]["gain_gap"] == 0
    assert "migliori candidati" in analysis["reason"]


def test_auction_trade_exclusions_are_normalized_and_removed_with_player() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Intoccabili",
        initial_budget=500,
        participants=2,
        game_mode=GAME_MODE_AUCTION,
        roster_slots={"P": 0, "D": 0, "C": 0, "A": 2},
    )
    manager_id = auction_managers(league)[0]["id"]
    leao = make_player(name="Leao", team="MIL", role="A", quote=35)
    record_auction_purchase(league, manager_id, leao, 100)

    selected = set_auction_trade_exclusions(
        league, [leao["id"], "non-mio", leao["id"]]
    )

    assert selected == [leao["id"]]
    assert normalize_workspace(workspace)["leagues"][0][
        "auction_trade_excluded_player_ids"
    ] == [leao["id"]]

    remove_purchase(league, leao["id"])
    assert league["auction_trade_excluded_player_ids"] == []


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


def test_auction_prices_follow_budget_saved_or_spent_in_other_roles() -> None:
    def build_league(other_roles_spent: tuple[int, int, int]) -> dict:
        workspace = new_workspace()
        league = create_league(
            workspace,
            "Pressione tra reparti",
            initial_budget=500,
            participants=2,
            game_mode=GAME_MODE_AUCTION,
            roster_slots={"P": 1, "D": 1, "C": 1, "A": 2},
        )
        user_id = auction_managers(league)[0]["id"]
        for role, price in zip(("P", "D", "C"), other_roles_spent, strict=True):
            player = make_player(
                name=f"Acquisto {role}", team="TEST", role=role, quote=1
            )
            record_auction_purchase(league, user_id, player, price)
        return league

    high_spend = build_league((20, 100, 180))
    low_spend = build_league((10, 50, 120))
    malen = make_player(name="Malen", team="ROM", role="A", quote=34)
    thuram = make_player(name="Thuram", team="INT", role="A", quote=30)
    malen["fvm"] = 414
    thuram["fvm"] = 264

    malen_price = auction_price_board(high_spend, [malen])[malen["id"]]
    thuram_price = auction_price_board(low_spend, [thuram])[thuram["id"]]

    assert malen_price["initial"] == 207
    assert malen_price["updated"] == 186
    assert malen_price["cross_role_factor"] == pytest.approx(0.90)
    assert malen_price["other_departments_delta"] == pytest.approx(-40)
    assert malen_price["updated"] <= malen_price["affordable"]
    assert thuram_price["initial"] == 132
    assert thuram_price["updated"] == 158
    assert thuram_price["cross_role_factor"] == pytest.approx(1.20)
    assert thuram_price["other_departments_delta"] == pytest.approx(80)


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
