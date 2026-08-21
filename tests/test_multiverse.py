import math
from dataclasses import FrozenInstanceError

import pytest

from fantasy.catalog import make_player
from fantasy.multiverse import SIMULATION_COUNTS, legal_max_bid, simulate_multiverse
from fantasy.service import (
    auction_managers,
    build_auction_snapshot,
    create_league,
    new_workspace,
    record_auction_purchase,
    run_auction_multiverse,
)


def _catalog() -> list[dict]:
    players = []
    for role_index, role in enumerate(("P", "D", "C", "A")):
        for index in range(6):
            player = make_player(
                name=f"{role}{index}",
                team=("Inter", "Roma", "Milan")[index % 3],
                role=role,
                quote=4 + index,
                expected_goals=index if role != "P" else 0,
                expected_assists=index / 2,
                starter_probability=65 + index * 5,
            )
            player.update(
                {
                    "fvm": 15 + role_index * 5 + index * 8,
                    "expected_fantasy_average": 5.8 + index / 10,
                    "bonus": 30 + index * 10,
                    "reliability": 55 + index * 6,
                    "potential": 45 + index * 8,
                    "risk": 30 - index * 3,
                    "fantasy_score": 20 + role_index + index * 10,
                    "tier": "Top" if index == 5 else "Titolari",
                }
            )
            players.append(player)
    return players


def _league(name: str = "Multiverso"):
    workspace = new_workspace()
    league = create_league(
        workspace,
        name,
        initial_budget=80,
        participants=3,
        roster_slots={"P": 1, "D": 1, "C": 1, "A": 1},
    )
    return workspace, league


def _assert_finite(value):
    if isinstance(value, dict):
        for item in value.values():
            _assert_finite(item)
    elif isinstance(value, list):
        for item in value:
            _assert_finite(item)
    elif isinstance(value, float):
        assert math.isfinite(value)


def test_same_seed_returns_the_same_multiverse_result() -> None:
    _, league = _league()
    snapshot = build_auction_snapshot(league, _catalog())

    first = simulate_multiverse(snapshot, mode="rapida", seed=12345)
    second = simulate_multiverse(snapshot, mode="rapida", seed=12345)

    assert first == second
    assert first["simulation_count"] == SIMULATION_COUNTS["rapida"]


def test_simulation_respects_budget_slots_uniqueness_and_reserve() -> None:
    _, league = _league()

    result = run_auction_multiverse(league, _catalog(), mode="rapida", seed=7)

    assert result["diagnostics"] == {
        "negative_budget": 0,
        "slot_overflow": 0,
        "duplicate_assignment": 0,
        "reserve_violation": 0,
    }
    assert result["completion_probability"] == 1
    assert result["expected_remaining_budget"] >= 0


def test_already_purchased_player_is_excluded_from_snapshot_and_results() -> None:
    _, league = _league()
    catalog = _catalog()
    sold = catalog[-1]
    rival = auction_managers(league)[1]
    record_auction_purchase(league, rival["id"], sold, 10)

    snapshot = build_auction_snapshot(league, catalog)
    result = simulate_multiverse(snapshot, mode="rapida", seed=8)

    assert sold["id"] not in {player.player_id for player in snapshot.available_players}
    assert sold["id"] not in {
        player["player_id"] for player in result["most_common_final_roster"]
    }


def test_legal_max_bid_keeps_minimum_credit_for_later_slots() -> None:
    assert legal_max_bid(20, 4, 1) == 17
    assert legal_max_bid(20, 4, 2) == 14
    assert legal_max_bid(3, 4, 1) == 0


def test_snapshot_is_immutable() -> None:
    _, league = _league()
    snapshot = build_auction_snapshot(league, _catalog())

    with pytest.raises(FrozenInstanceError):
        snapshot.total_budget = 100  # type: ignore[misc]


def test_cache_key_changes_after_real_purchase() -> None:
    _, league = _league()
    catalog = _catalog()
    before = run_auction_multiverse(league, catalog, mode="rapida", seed=9)
    user = next(manager for manager in auction_managers(league) if manager.get("is_user"))
    record_auction_purchase(league, user["id"], catalog[0], 2)

    after = run_auction_multiverse(league, catalog, mode="rapida", seed=9)

    assert before["state_hash"] != after["state_hash"]
    assert len(build_auction_snapshot(league, catalog).available_players) == len(catalog) - 1


def test_two_fantasies_never_share_multiverse_state() -> None:
    workspace = new_workspace()
    first = create_league(workspace, "Prima", participants=2)
    second = create_league(workspace, "Seconda", participants=2)
    catalog = _catalog()

    first_result = run_auction_multiverse(first, catalog, mode="rapida", seed=10)
    second_result = run_auction_multiverse(second, catalog, mode="rapida", seed=10)

    assert first_result["state_hash"] != second_result["state_hash"]


def test_missing_player_metrics_do_not_generate_nan() -> None:
    _, league = _league()
    catalog = [
        make_player(name=f"{role}{index}", team="Roma", role=role, quote=1)
        for role in ("P", "D", "C", "A")
        for index in range(4)
    ]

    result = run_auction_multiverse(league, catalog, mode="rapida", seed=11)

    _assert_finite(result)


def test_watchlist_players_are_reported_as_personal_targets() -> None:
    _, league = _league()
    catalog = _catalog()
    target = catalog[-1]
    league["watchlist"] = [target["id"]]

    result = run_auction_multiverse(league, catalog, mode="rapida", seed=12)

    target_result = result["probability_of_acquiring_targets"][target["id"]]
    assert target_result["name"] == target["name"]
    assert 0 <= target_result["probability"] <= 1


def test_per_role_mode_does_not_reopen_previous_departments() -> None:
    _, league = _league()
    league["auction_mode"] = "per_ruolo"
    league["auction_current_role"] = "C"

    result = run_auction_multiverse(league, _catalog(), mode="rapida", seed=13)

    assert result["completion_probability"] == 0
    assert result["fragile_roles"][0]["role"] in {"P", "D"}
