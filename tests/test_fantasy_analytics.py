from fantasy.analytics import pareto_frontier, player_derived_stats, role_percentiles


def test_player_derived_stats_builds_bonus_efficiency_and_deltas():
    stats = player_derived_stats(
        {
            "appearances_previous": 20,
            "expected_appearances": 30,
            "goals_previous": 8,
            "assists_previous": 4,
            "expected_goals": 10,
            "expected_assists": 5,
            "fantasy_average_previous": 7.0,
            "expected_fantasy_average": 7.5,
            "quote": 25,
            "initial_quote": 20,
            "predicted_quote": 30,
            "penalties_scored": 3,
            "penalties_taken": 4,
        }
    )

    assert stats["expected_goal_involvements"] == 15
    assert stats["expected_bonus_points"] == 35
    assert stats["expected_bonus_per_appearance"] == 35 / 30
    assert stats["fantasy_average_delta"] == 0.5
    assert stats["current_quote_delta"] == 5
    assert stats["predicted_quote_delta"] == 5
    assert stats["penalty_conversion"] == 75


def test_role_percentiles_compare_only_role_and_invert_risk():
    catalog = [
        {"id": "low", "role": "A", "bonus": 20, "risk": 80},
        {"id": "mid", "role": "A", "bonus": 50, "risk": 50},
        {"id": "high", "role": "A", "bonus": 80, "risk": 20},
        {"id": "other", "role": "D", "bonus": 100, "risk": 0},
    ]

    result = role_percentiles(catalog[2], catalog)

    assert result["bonus"] > 80
    assert result["risk"] > 80


def test_pareto_frontier_keeps_only_successive_value_improvements():
    players = [
        {"name": "A", "quote": 5, "expected_fantasy_average": 6.5},
        {"name": "B", "quote": 8, "expected_fantasy_average": 6.2},
        {"name": "C", "quote": 10, "expected_fantasy_average": 7.0},
        {"name": "D", "quote": 15, "expected_fantasy_average": 6.9},
    ]

    assert [row["name"] for row in pareto_frontier(players)] == ["A", "C"]


def test_pareto_frontier_can_use_updated_auction_spend() -> None:
    players = [
        {"name": "A", "quote": 20, "updated_spend": 5, "expected_fantasy_average": 6.5},
        {"name": "B", "quote": 5, "updated_spend": 8, "expected_fantasy_average": 6.2},
        {
            "name": "C",
            "quote": 10,
            "updated_spend": 10,
            "expected_fantasy_average": 7.0,
        },
    ]

    frontier = pareto_frontier(players, cost_field="updated_spend")

    assert [row["name"] for row in frontier] == ["A", "C"]
