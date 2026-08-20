from __future__ import annotations

from typing import Any, Iterable


PERCENTILE_METRICS: tuple[tuple[str, str, bool], ...] = (
    ("expected_fantasy_average", "Fantamedia", False),
    ("bonus", "Bonus", False),
    ("starter_probability", "Titolarita", False),
    ("reliability", "Affidabilita", False),
    ("potential", "Potenziale", False),
    ("value", "Valore", False),
    ("risk", "Integrita", True),
)


def optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def number(value: Any, default: float = 0.0) -> float:
    parsed = optional_number(value)
    return default if parsed is None else parsed


def ratio(numerator: Any, denominator: Any) -> float | None:
    parsed_denominator = optional_number(denominator)
    parsed_numerator = optional_number(numerator)
    if parsed_denominator in (None, 0) or parsed_numerator is None:
        return None
    return parsed_numerator / parsed_denominator


def bonus_propensity(player: dict[str, Any], catalog: Iterable[dict[str, Any]]) -> float:
    """Estimate bonus propensity from expected and historical bonus rates.

    The source list can contain a legacy bonus field encoded either as a
    percentage or as the placeholder value 1. It is deliberately ignored:
    the score is rebuilt from goals and assists per expected/actual appearance,
    then ranked against players in the same role.
    """

    def signal(row: dict[str, Any]) -> float:
        expected_goals = number(row.get("expected_goals"))
        expected_assists = number(row.get("expected_assists"))
        expected_appearances = number(row.get("expected_appearances"))
        if expected_appearances <= 0:
            expected_appearances = number(row.get("appearances_previous"))
        if expected_appearances <= 0:
            starter = number(row.get("starter_probability"))
            expected_appearances = 38 * (starter if starter <= 1 else starter / 100)
        expected_rate = (3 * expected_goals + expected_assists) / max(expected_appearances, 1)

        appearances = number(row.get("appearances_previous"))
        historical_rate = None
        if appearances > 0:
            historical_rate = (
                3 * number(row.get("goals_previous"))
                + number(row.get("assists_previous"))
            ) / appearances
        if historical_rate is None:
            return expected_rate
        return 0.7 * expected_rate + 0.3 * historical_rate

    role = str(player.get("role") or "")
    peers = [row for row in catalog if str(row.get("role") or "") == role]
    target = signal(player)
    values = [signal(row) for row in peers]
    if not values:
        return round(min(target * 45, 100), 1)

    lower = sum(value < target for value in values)
    equal = sum(abs(value - target) < 1e-9 for value in values)
    percentile = ((lower + equal * 0.5) / len(values)) * 100
    ordered = sorted(values)
    reference = ordered[max(0, int(len(ordered) * 0.75) - 1)]
    absolute = min(target / max(reference, 0.01) * 60, 100)
    return round(max(0.0, min(100.0, percentile * 0.75 + absolute * 0.25)), 1)

def player_derived_stats(player: dict[str, Any]) -> dict[str, float | None]:
    appearances = number(player.get("appearances_previous"))
    expected_appearances = number(player.get("expected_appearances"))
    goals = number(player.get("goals_previous"))
    assists = number(player.get("assists_previous"))
    expected_goals = number(player.get("expected_goals"))
    expected_assists = number(player.get("expected_assists"))
    quote = number(player.get("quote"))
    expected_fm = optional_number(player.get("expected_fantasy_average"))
    previous_fm = optional_number(player.get("fantasy_average_previous"))
    cards = number(player.get("yellow_cards")) + number(player.get("red_cards"))
    predicted_quote = optional_number(player.get("predicted_quote"))
    initial_quote = optional_number(player.get("initial_quote"))
    penalties_taken = number(player.get("penalties_taken"))
    penalties_scored = number(player.get("penalties_scored"))
    xg = optional_number(player.get("xg_previous"))
    xa = optional_number(player.get("xa_previous"))

    previous_bonus_points = goals * 3 + assists
    expected_bonus_points = expected_goals * 3 + expected_assists
    expected_involvements = expected_goals + expected_assists
    previous_involvements = goals + assists
    data_fields = (
        "appearances_previous",
        "average_rating_previous",
        "fantasy_average_previous",
        "goals_previous",
        "assists_previous",
        "xg_previous",
        "xa_previous",
        "expected_appearances",
        "expected_goals",
        "expected_assists",
        "expected_fantasy_average",
        "starter_probability",
        "reliability",
        "bonus",
        "potential",
        "risk",
        "value",
    )
    available_fields = sum(optional_number(player.get(field)) is not None for field in data_fields)

    return {
        "previous_goal_involvements": previous_involvements,
        "expected_goal_involvements": expected_involvements,
        "previous_bonus_points": previous_bonus_points,
        "expected_bonus_points": expected_bonus_points,
        "goals_per_appearance": ratio(goals, appearances),
        "assists_per_appearance": ratio(assists, appearances),
        "goal_involvements_per_appearance": ratio(previous_involvements, appearances),
        "bonus_points_per_appearance": ratio(previous_bonus_points, appearances),
        "expected_goals_per_appearance": ratio(expected_goals, expected_appearances),
        "expected_assists_per_appearance": ratio(expected_assists, expected_appearances),
        "expected_involvements_per_appearance": ratio(expected_involvements, expected_appearances),
        "expected_bonus_per_appearance": ratio(expected_bonus_points, expected_appearances),
        "xgi_previous": None if xg is None and xa is None else number(xg) + number(xa),
        "xg_per_appearance": ratio(xg, appearances),
        "xa_per_appearance": ratio(xa, appearances),
        "cards_per_appearance": ratio(cards, appearances),
        "goals_conceded_per_appearance": ratio(player.get("goals_conceded"), appearances),
        "penalty_conversion": ratio(penalties_scored * 100, penalties_taken),
        "expected_availability": ratio(expected_appearances * 100, 38),
        "fantasy_average_delta": (
            None if expected_fm is None or previous_fm is None else expected_fm - previous_fm
        ),
        "current_quote_delta": (
            None if initial_quote is None else quote - initial_quote
        ),
        "predicted_quote_delta": (
            None if predicted_quote is None else predicted_quote - quote
        ),
        "fantasy_average_per_credit": ratio(expected_fm, quote),
        "expected_bonus_per_credit": ratio(expected_bonus_points, quote),
        "score_per_credit": ratio(player.get("fantasy_score"), quote),
        "fvm_per_credit": ratio(player.get("fvm"), quote),
        "data_coverage": available_fields / len(data_fields) * 100,
    }


def role_percentiles(
    player: dict[str, Any],
    catalog: Iterable[dict[str, Any]],
) -> dict[str, float | None]:
    role = str(player.get("role") or "")
    peers = [row for row in catalog if str(row.get("role") or "") == role]
    result: dict[str, float | None] = {}
    for field, _, inverse in PERCENTILE_METRICS:
        target = optional_number(player.get(field))
        values = [
            value
            for value in (optional_number(row.get(field)) for row in peers)
            if value is not None
        ]
        if target is None or not values:
            result[field] = None
            continue
        below = sum(value < target for value in values)
        equal = sum(value == target for value in values)
        percentile = (below + equal * 0.5) / len(values) * 100
        result[field] = 100 - percentile if inverse else percentile
    return result


def pareto_frontier(
    players: Iterable[dict[str, Any]],
    *,
    cost_field: str = "quote",
    value_field: str = "expected_fantasy_average",
) -> list[dict[str, Any]]:
    candidates = [
        player
        for player in players
        if number(player.get(cost_field)) > 0 and optional_number(player.get(value_field)) is not None
    ]
    candidates.sort(
        key=lambda player: (
            number(player.get(cost_field)),
            -number(player.get(value_field)),
        )
    )
    frontier: list[dict[str, Any]] = []
    best_value = float("-inf")
    for player in candidates:
        value = number(player.get(value_field))
        if value > best_value:
            frontier.append(player)
            best_value = value
    return frontier
