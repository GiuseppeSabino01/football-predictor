from __future__ import annotations

import math

from features.market_features import normalize_probabilities


def empirical_1x2(home_xg: float, away_xg: float) -> dict[str, float]:
    """Estimate 1X2 probabilities directly from the expected-goal profile."""
    goal_gap = home_xg - away_xg
    total_xg = home_xg + away_xg
    draw = _clamp(
        0.29 - abs(goal_gap) * 0.085 - max(0.0, total_xg - 2.7) * 0.025,
        0.16,
        0.31,
    )
    home_share = _logistic(1.55 * goal_gap)
    decisive = 1 - draw
    return normalize_probabilities(
        {
            "home": decisive * home_share,
            "draw": draw,
            "away": decisive * (1 - home_share),
        }
    )


def empirical_over_under_25(
    home_xg: float,
    away_xg: float,
    historical_rate: float | None = None,
) -> dict[str, float]:
    model_over = _logistic(1.45 * ((home_xg + away_xg) - 2.55))
    over = _blend_rate(model_over, historical_rate)
    return {"Over 2.5": over, "Under 2.5": 1 - over}


def empirical_both_teams_to_score(
    home_xg: float,
    away_xg: float,
    historical_rate: float | None = None,
) -> dict[str, float]:
    total_xg = home_xg + away_xg
    lower_attack = min(home_xg, away_xg)
    model_yes = _logistic(0.95 * (total_xg - 2.55) + 1.10 * (lower_attack - 1.0))
    yes = _blend_rate(model_yes, historical_rate)
    return {"Goal": yes, "No Goal": 1 - yes}


def empirical_scoreline(
    home_xg: float,
    away_xg: float,
    outcome: str,
    probabilities: dict[str, float],
) -> str:
    """Build a deterministic scoreline from xG, strength gap and 1X2 confidence."""
    if outcome == "draw":
        total_xg = home_xg + away_xg
        goals = 2 if total_xg >= 3.45 else 1 if total_xg >= 1.65 else 0
        return f"{goals}-{goals}"
    if outcome not in {"home", "away"}:
        return f"{_round_goals(home_xg)}-{_round_goals(away_xg)}"

    winner_xg = home_xg if outcome == "home" else away_xg
    loser_xg = away_xg if outcome == "home" else home_xg
    xg_gap = winner_xg - loser_xg
    outcome_probability = probabilities.get(outcome, 0.0)

    if outcome_probability >= 0.62 and xg_gap >= 1.0:
        winner_goals = max(2, _round_goals(winner_xg + 0.45))
        loser_goals = 0 if loser_xg <= 0.95 else _round_goals(loser_xg)
        if winner_goals <= loser_goals:
            winner_goals = loser_goals + 1
        return _ordered_score(outcome, winner_goals, loser_goals)

    if outcome_probability >= 0.46 or xg_gap >= 0.45:
        home_goals = _round_goals(home_xg)
        away_goals = _round_goals(away_xg)
        if outcome == "home" and home_goals <= away_goals:
            home_goals = away_goals + 1
        elif outcome == "away" and away_goals <= home_goals:
            away_goals = home_goals + 1
        return f"{min(home_goals, 7)}-{min(away_goals, 7)}"

    if home_xg + away_xg >= 3.15:
        loser_goals = max(1, _round_goals(loser_xg))
        return _ordered_score(outcome, loser_goals + 1, loser_goals)
    return _ordered_score(outcome, 1, 0)


def _blend_rate(model_rate: float, historical_rate: float | None) -> float:
    if historical_rate is None:
        return _clamp(model_rate, 0.08, 0.92)
    blended = model_rate * 0.72 + _clamp(historical_rate, 0.0, 1.0) * 0.28
    return _clamp(blended, 0.08, 0.92)


def _round_goals(value: float) -> int:
    return max(0, math.floor(value + 0.5))


def _ordered_score(outcome: str, winner_goals: int, loser_goals: int) -> str:
    if outcome == "home":
        return f"{winner_goals}-{loser_goals}"
    return f"{loser_goals}-{winner_goals}"


def _logistic(value: float) -> float:
    return 1 / (1 + math.exp(-value))


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
