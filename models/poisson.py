from __future__ import annotations

import math


def poisson_probability(lmbda: float, goals: int) -> float:
    return (math.exp(-lmbda) * (lmbda**goals)) / math.factorial(goals)


def score_matrix(home_xg: float, away_xg: float, max_goals: int = 7) -> dict[tuple[int, int], float]:
    matrix: dict[tuple[int, int], float] = {}
    for home_goals in range(max_goals + 1):
        for away_goals in range(max_goals + 1):
            matrix[(home_goals, away_goals)] = poisson_probability(home_xg, home_goals) * poisson_probability(
                away_xg, away_goals
            )
    total = sum(matrix.values())
    return {score: probability / total for score, probability in matrix.items()}


def exact_score(matrix: dict[tuple[int, int], float]) -> str:
    home_goals, away_goals = max(matrix, key=matrix.get)
    return f"{home_goals}-{away_goals}"


def over_under_25(matrix: dict[tuple[int, int], float]) -> dict[str, float]:
    over = sum(prob for (home, away), prob in matrix.items() if home + away > 2.5)
    return {"Over 2.5": over, "Under 2.5": 1 - over}


def both_teams_to_score(matrix: dict[tuple[int, int], float]) -> dict[str, float]:
    yes = sum(prob for (home, away), prob in matrix.items() if home > 0 and away > 0)
    return {"Goal": yes, "No Goal": 1 - yes}

