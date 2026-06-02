from __future__ import annotations

from config.team_aliases import aliases_for
from features.market_features import normalize_probabilities
from schemas import NewsSignal


SEVERITY_MULTIPLIER = {"low": 0.02, "medium": 0.05, "high": 0.09}
NEGATIVE_SIGNALS = {"injury", "suspension", "rotation"}
POSITIVE_SIGNALS = {"morale", "lineup", "tactical"}


def apply_news_adjustments(
    probabilities: dict[str, float],
    signals: list[NewsSignal],
    home_team: str,
    away_team: str,
) -> dict[str, float]:
    adjusted = dict(probabilities)
    home_names = {name.lower() for name in aliases_for(home_team)}
    away_names = {name.lower() for name in aliases_for(away_team)}

    for signal in signals:
        team = signal.team.lower()
        target = "home" if _matches(team, home_names) else "away" if _matches(team, away_names) else None
        if not target:
            continue
        amount = SEVERITY_MULTIPLIER.get(signal.severity, 0.02) * min(max(signal.confidence, 0.0), 1.0)
        if signal.certainty == "rumor":
            amount *= 0.45
        if signal.signal_type in NEGATIVE_SIGNALS or signal.availability in {"out", "doubtful"}:
            adjusted[target] = adjusted.get(target, 0.0) - amount
            adjusted["draw"] = adjusted.get("draw", 0.0) + amount * 0.35
            other = "away" if target == "home" else "home"
            adjusted[other] = adjusted.get(other, 0.0) + amount * 0.65
        elif signal.signal_type in POSITIVE_SIGNALS:
            adjusted[target] = adjusted.get(target, 0.0) + amount
            other = "away" if target == "home" else "home"
            adjusted[other] = adjusted.get(other, 0.0) - amount * 0.65
            adjusted["draw"] = adjusted.get("draw", 0.0) - amount * 0.35

    return normalize_probabilities(adjusted)


def _matches(team: str, candidates: set[str]) -> bool:
    return any(team == candidate or team in candidate or candidate in team for candidate in candidates)
