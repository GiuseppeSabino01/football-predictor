from __future__ import annotations

import math


def poisson_probability(lmbda: float, goals: int) -> float:
    return (math.exp(-lmbda) * (lmbda**goals)) / math.factorial(goals)


def score_matrix(
    home_xg: float, away_xg: float, max_goals: int = 7
) -> dict[tuple[int, int], float]:
    matrix: dict[tuple[int, int], float] = {}
    for home_goals in range(max_goals + 1):
        for away_goals in range(max_goals + 1):
            matrix[(home_goals, away_goals)] = poisson_probability(
                home_xg, home_goals
            ) * poisson_probability(away_xg, away_goals)
    total = sum(matrix.values())
    return {score: probability / total for score, probability in matrix.items()}


def exact_score(matrix: dict[tuple[int, int], float]) -> str:
    home_goals, away_goals = max(matrix, key=matrix.get)
    return f"{home_goals}-{away_goals}"


def exact_score_for_outcome(matrix: dict[tuple[int, int], float], outcome: str) -> str:
    if outcome == "home":
        candidates = {
            score: prob for score, prob in matrix.items() if score[0] > score[1]
        }
    elif outcome == "away":
        candidates = {
            score: prob for score, prob in matrix.items() if score[0] < score[1]
        }
    elif outcome == "draw":
        candidates = {
            score: prob for score, prob in matrix.items() if score[0] == score[1]
        }
    else:
        candidates = {}
    if not candidates:
        return exact_score(matrix)
    home_goals, away_goals = max(candidates, key=candidates.get)
    return f"{home_goals}-{away_goals}"


def representative_score_for_outcome(
    matrix: dict[tuple[int, int], float], outcome: str
) -> str:
    """Return a central, plausible scoreline instead of the repetitive Poisson mode.

    The independent Poisson mode is often 1-0/0-1 even when the expected-goal
    profile points to a wider or higher-scoring win. This function remains
    deterministic: it uses the matrix means, the outcome probability and the
    strength gap, then falls back to the modal score for genuinely tight games.
    """
    if not matrix:
        return "0-0"

    home_xg = sum(home * probability for (home, _), probability in matrix.items())
    away_xg = sum(away * probability for (_, away), probability in matrix.items())
    outcome_probability = sum(
        probability
        for (home, away), probability in matrix.items()
        if _matches_outcome(home, away, outcome)
    )

    if outcome == "draw":
        total_xg = home_xg + away_xg
        goals = 2 if total_xg >= 3.45 else 1 if total_xg >= 1.65 else 0
        return f"{goals}-{goals}"

    if outcome not in {"home", "away"}:
        return exact_score(matrix)

    winner_xg = home_xg if outcome == "home" else away_xg
    loser_xg = away_xg if outcome == "home" else home_xg
    xg_gap = winner_xg - loser_xg

    # Vittorie nette: il valore centrale della distribuzione descrive meglio
    # il divario rispetto al singolo picco 1-0/0-1.
    if outcome_probability >= 0.62 and xg_gap >= 1.0:
        winner_goals = max(2, _round_goals(winner_xg + 0.45))
        loser_goals = 0 if loser_xg <= 0.95 else _round_goals(loser_xg)
        if winner_goals <= loser_goals:
            winner_goals = loser_goals + 1
        return _ordered_score(outcome, winner_goals, loser_goals)

    # Favoriti credibili ma non dominanti: arrotondiamo gli xG e imponiamo
    # soltanto la coerenza con l'esito 1X2. Esempio tipico: 0.9-1.6 -> 1-2.
    if outcome_probability >= 0.46 or xg_gap >= 0.45:
        home_goals = _round_goals(home_xg)
        away_goals = _round_goals(away_xg)
        if outcome == "home" and home_goals <= away_goals:
            home_goals = away_goals + 1
        elif outcome == "away" and away_goals <= home_goals:
            away_goals = home_goals + 1
        candidate = (min(home_goals, 7), min(away_goals, 7))
        modal_probability = max(
            probability
            for score, probability in matrix.items()
            if _matches_outcome(*score, outcome)
        )
        if matrix.get(candidate, 0.0) >= modal_probability * 0.35:
            return f"{candidate[0]}-{candidate[1]}"

    return exact_score_for_outcome(matrix, outcome)


def _matches_outcome(home: int, away: int, outcome: str) -> bool:
    if outcome == "home":
        return home > away
    if outcome == "away":
        return away > home
    if outcome == "draw":
        return home == away
    return False


def _round_goals(value: float) -> int:
    return max(0, math.floor(value + 0.5))


def _ordered_score(outcome: str, winner_goals: int, loser_goals: int) -> str:
    if outcome == "home":
        return f"{winner_goals}-{loser_goals}"
    return f"{loser_goals}-{winner_goals}"


def over_under_25(matrix: dict[tuple[int, int], float]) -> dict[str, float]:
    over = sum(prob for (home, away), prob in matrix.items() if home + away > 2.5)
    return {"Over 2.5": over, "Under 2.5": 1 - over}


def both_teams_to_score(matrix: dict[tuple[int, int], float]) -> dict[str, float]:
    yes = sum(prob for (home, away), prob in matrix.items() if home > 0 and away > 0)
    return {"Goal": yes, "No Goal": 1 - yes}
