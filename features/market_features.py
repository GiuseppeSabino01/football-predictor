from __future__ import annotations


def fair_odd(probability: float) -> float | None:
    if probability <= 0:
        return None
    return round(1 / probability, 2)


def value_score(probability: float, market_odd: float | None) -> float | None:
    if not market_odd:
        return None
    return round((probability * market_odd) - 1, 3)


def recommendation(probability: float, market_odd: float | None, min_value: float = 0.05) -> str:
    score = value_score(probability, market_odd)
    if score is None:
        return "No-bet"
    if score >= min_value:
        return "Value"
    if score > 0:
        return "Lean"
    return "No-bet"


def normalize_probabilities(values: dict[str, float]) -> dict[str, float]:
    total = sum(max(v, 0.0) for v in values.values())
    if total <= 0:
        return {key: 1 / len(values) for key in values}
    return {key: max(value, 0.0) / total for key, value in values.items()}


def implied_1x2_from_odds(odds_rows: list[dict]) -> dict[str, float]:
    values: dict[str, float] = {}
    for odd_payload in odds_rows:
        for bookmaker in odd_payload.get("bookmakers", []):
            for bet in bookmaker.get("bets", []):
                if str(bet.get("name", "")).lower() not in {"match winner", "winner"}:
                    continue
                for value in bet.get("values", []):
                    label = str(value.get("value", "")).lower()
                    odd = _to_float(value.get("odd"))
                    if not odd:
                        continue
                    if label in {"home", "1"}:
                        values["home"] = 1 / odd
                    elif label in {"draw", "x"}:
                        values["draw"] = 1 / odd
                    elif label in {"away", "2"}:
                        values["away"] = 1 / odd
                if {"home", "draw", "away"}.issubset(values):
                    return normalize_probabilities(values)
    return {}


def market_odd_for_selection(odds_rows: list[dict], selection: str) -> float | None:
    selection = selection.lower()
    wanted = {"home": {"home", "1"}, "draw": {"draw", "x"}, "away": {"away", "2"}}.get(selection, {selection})
    for odd_payload in odds_rows:
        for bookmaker in odd_payload.get("bookmakers", []):
            for bet in bookmaker.get("bets", []):
                if str(bet.get("name", "")).lower() not in {"match winner", "winner"}:
                    continue
                for value in bet.get("values", []):
                    if str(value.get("value", "")).lower() in wanted:
                        return _to_float(value.get("odd"))
    return None


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

