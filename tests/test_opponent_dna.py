import pytest

from fantasy.catalog import make_player
from fantasy.opponent_dna import dna_buyer_multiplier
from fantasy.service import (
    GAME_MODE_AUCTION,
    auction_managers,
    auction_player_assignment,
    create_league,
    new_workspace,
    opponent_dna_profiles,
    record_auction_purchase,
    update_auction_assignments,
)


def _league(name: str = "FantaDNA", *, participants: int = 3):
    workspace = new_workspace()
    league = create_league(
        workspace,
        name,
        initial_budget=250,
        participants=participants,
        game_mode=GAME_MODE_AUCTION,
        roster_slots={"P": 1, "D": 2, "C": 2, "A": 2},
    )
    return workspace, league


def _player(index: int, role: str = "A", team: str = "Inter"):
    player = make_player(
        name=f"Giocatore {index}",
        team=team,
        role=role,
        quote=10 + index,
        expected_goals=3 + index,
        expected_assists=2,
        starter_probability=75 + index,
    )
    player.update(
        {
            "fvm": 40 + index * 10,
            "bonus": min(55 + index * 4, 100),
            "reliability": min(60 + index * 3, 100),
            "potential": min(65 + index * 2, 100),
            "risk": max(30 - index, 0),
            "fantasy_score": 40 + index * 5,
            "tier": "Top" if index >= 4 else "Titolari",
        }
    )
    return player


def _profile(league, catalog, manager_id):
    return next(
        profile for profile in opponent_dna_profiles(league, catalog)
        if profile["manager_id"] == str(manager_id)
    )


def test_fantadna_without_data_is_neutral_and_low_confidence() -> None:
    _, league = _league()
    rival = auction_managers(league)[1]

    profile = _profile(league, [_player(1)], rival["id"])

    assert profile["sample_size"] == 0
    assert profile["confidence"] == "bassa"
    assert profile["aggression_score"] == 50
    assert profile["top_player_bias"] == 50
    assert profile["budget_concentration"] == 50
    assert profile["patience_score"] == 50
    assert "Nessun acquisto" in profile["evidence"][0]


def test_few_purchases_have_low_confidence_and_regression_to_league_mean() -> None:
    _, league = _league()
    managers = auction_managers(league)
    catalog = [_player(index) for index in range(1, 5)]
    for player in catalog[:2]:
        record_auction_purchase(league, managers[1]["id"], player, 35)
    record_auction_purchase(league, managers[2]["id"], catalog[2], 5)

    profile = _profile(league, catalog, managers[1]["id"])

    assert profile["sample_size"] == 2
    assert profile["confidence"] == "bassa"
    assert profile["shrinkage_weight"] == pytest.approx(0.2)
    assert any("Segnale preliminare" in evidence for evidence in profile["evidence"])


def test_price_or_owner_correction_updates_one_sale_event() -> None:
    _, league = _league()
    managers = auction_managers(league)
    player = _player(1)
    first_rival = str(managers[1]["id"])
    second_rival = str(managers[2]["id"])
    record_auction_purchase(league, first_rival, player, 12)
    event_id = league["auction_sale_events"][0]["event_id"]

    update_auction_assignments(
        league, [{"player": player, "manager_id": first_rival, "price": 17}]
    )
    update_auction_assignments(
        league, [{"player": player, "manager_id": second_rival, "price": 19}]
    )

    assert len(league["auction_sale_events"]) == 1
    event = league["auction_sale_events"][0]
    assert event["event_id"] == event_id
    assert event["manager_id"] == second_rival
    assert event["paid_price"] == 19
    assert auction_player_assignment(league, player["id"])["manager_id"] == second_rival


def test_unassigned_removes_sale_event_and_resets_assignment() -> None:
    _, league = _league()
    rival_id = str(auction_managers(league)[1]["id"])
    player = _player(1)
    record_auction_purchase(league, rival_id, player, 12)

    update_auction_assignments(
        league, [{"player": player, "manager_id": None, "price": 0}]
    )

    assert auction_player_assignment(league, player["id"]) is None
    assert league["auction_sale_events"] == []


def test_fantadna_is_separated_by_fantasy_id() -> None:
    workspace = new_workspace()
    first = create_league(workspace, "Prima", participants=2)
    second = create_league(workspace, "Seconda", participants=2)
    first_rival = auction_managers(first)[1]
    second_rival = auction_managers(second)[1]
    player = _player(1)
    record_auction_purchase(first, first_rival["id"], player, 30)

    first_profile = _profile(first, [player], first_rival["id"])
    second_profile = _profile(second, [player], second_rival["id"])

    assert first_profile["sample_size"] == 1
    assert second_profile["sample_size"] == 0
    assert first["auction_sale_events"][0]["fantasy_id"] == first["id"]
    assert second["auction_sale_events"] == []


def test_team_preference_requires_a_credible_sample() -> None:
    _, league = _league(participants=2)
    rival = auction_managers(league)[1]
    roles = ("P", "D", "D", "C", "C", "A", "A")
    catalog = [
        _player(index, role=role, team="Inter" if index < 5 else "Roma")
        for index, role in enumerate(roles)
    ]
    for player in catalog[:5]:
        record_auction_purchase(league, rival["id"], player, 10 + len(league["auction_sale_events"]))

    profile = _profile(league, catalog, rival["id"])

    assert profile["confidence"] == "media"
    assert profile["team_preferences"][0]["team"] == "Inter"
    assert profile["team_preferences"][0]["purchases"] >= 3


def test_low_confidence_dampens_buyer_multiplier() -> None:
    neutral = {
        "confidence": "bassa",
        "aggression_score": 100,
        "role_preferences": {"A": {"adjusted_spend_share": 1}},
        "team_preferences": [],
        "tier_preferences": {},
    }
    confident = {**neutral, "confidence": "alta"}

    low = dna_buyer_multiplier(neutral, role="A", stage_urgency=100)
    high = dna_buyer_multiplier(confident, role="A", stage_urgency=100)

    assert 1 < low < high <= 1.45
