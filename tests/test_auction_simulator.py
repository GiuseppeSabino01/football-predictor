from copy import deepcopy

import pytest

from fantasy.catalog import make_player
from fantasy.service import (
    auction_manager_summary,
    auction_managers,
    auction_taken_player_ids,
    create_league,
    new_workspace,
    record_auction_purchase,
    simulate_auction_purchases,
)


def _catalog() -> list[dict]:
    players = []
    for role_index, role in enumerate(("P", "D", "C", "A")):
        for index in range(20):
            player = make_player(
                name=f"{role} simulato {index}",
                team=("Inter", "Roma", "Milan", "Napoli")[index % 4],
                role=role,
                quote=2 + index,
                expected_goals=index / 3,
                expected_assists=index / 4,
                starter_probability=55 + index,
            )
            player["fvm"] = 5 + role_index * 5 + index * 3
            players.append(player)
    return players


def _league(name: str = "Simulazione") -> dict:
    workspace = new_workspace()
    return create_league(
        workspace,
        name,
        initial_budget=250,
        participants=4,
        roster_slots={"P": 2, "D": 4, "C": 4, "A": 3},
    )


def test_simulation_adds_requested_players_to_every_manager_legally() -> None:
    league = _league()

    generated = simulate_auction_purchases(league, _catalog(), 10, seed=42)

    assert len(generated) == 40
    assert len(auction_taken_player_ids(league)) == 40
    for manager in auction_managers(league):
        summary = auction_manager_summary(league, str(manager["id"]))
        assert summary["roster_size"] == 10
        assert summary["remaining_budget"] >= summary["remaining_slots"]
        assert all(
            summary["role_counts"][role] <= league["roster_slots"][role]
            for role in league["roster_slots"]
        )


def test_simulation_is_repeatable_with_the_same_seed() -> None:
    first = _league("Prima")
    second = _league("Seconda")
    catalog = _catalog()

    simulate_auction_purchases(first, catalog, 6, seed=123)
    simulate_auction_purchases(second, catalog, 6, seed=123)

    first_rosters = [
        [(row["player_id"], row["role"], row["price"]) for row in summary["purchases"]]
        for manager in auction_managers(first)
        for summary in [auction_manager_summary(first, str(manager["id"]))]
    ]
    second_rosters = [
        [(row["player_id"], row["role"], row["price"]) for row in summary["purchases"]]
        for manager in auction_managers(second)
        for summary in [auction_manager_summary(second, str(manager["id"]))]
    ]
    assert first_rosters == second_rosters


def test_simulation_adds_to_existing_rosters_without_overwriting_them() -> None:
    league = _league()
    catalog = _catalog()
    first_manager = auction_managers(league)[0]
    existing = catalog[0]
    record_auction_purchase(league, str(first_manager["id"]), existing, 2)

    simulate_auction_purchases(league, catalog, 2, seed=9)

    assert existing["id"] in auction_taken_player_ids(league)
    assert auction_manager_summary(league, str(first_manager["id"]))["roster_size"] == 3
    assert all(
        auction_manager_summary(league, str(manager["id"]))["roster_size"] == 2
        for manager in auction_managers(league)[1:]
    )


def test_invalid_request_is_atomic() -> None:
    league = _league()
    original = deepcopy(league)

    with pytest.raises(ValueError, match="slot disponibili"):
        simulate_auction_purchases(league, _catalog(), 14, seed=1)

    assert league == original
