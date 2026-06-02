from __future__ import annotations


def brier_score(probability: float, outcome: int) -> float:
    return (probability - outcome) ** 2


def log_loss(probability: float, outcome: int, eps: float = 1e-12) -> float:
    import math

    probability = min(max(probability, eps), 1 - eps)
    return -(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability))

