from __future__ import annotations

from collections import Counter
from math import isnan, log1p, sqrt
from statistics import pstdev
from typing import Any

ESTIMATED_FIELDS: tuple[tuple[str, int, float, float], ...] = (
    ("starter_probability", 0, 0, 100),
    ("expected_appearances", 0, 0, 38),
    ("expected_goals", 1, 0, 40),
    ("expected_assists", 1, 0, 30),
    ("expected_fantasy_average", 2, 0, 15),
    ("reliability", 0, 0, 100),
    ("potential", 0, 0, 100),
    ("risk", 0, 0, 100),
    ("value", 0, 0, 100),
)


def enrich_missing_analysis(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill projections for official players that are absent from the seed analysis.

    Estimates use only already analysed players in the same Classic role and the
    two official market signals available for every new registration: quotation
    and FVM. Existing analysis is never overwritten.
    """

    references_by_role = {
        role: [
            player
            for player in players
            if str(player.get("role") or "") == role
            and _is_reference(player)
            and not player.get("analysis_estimated")
        ]
        for role in "PDCA"
    }
    for player in players:
        missing = [
            field
            for field, _, _, _ in ESTIMATED_FIELDS
            if _optional_number(player.get(field)) is None
        ]
        if not missing:
            continue
        references = references_by_role.get(str(player.get("role") or ""), [])
        comparables = _nearest_comparables(player, references)
        if not comparables:
            continue

        filled: list[str] = []
        for field, decimals, minimum, maximum in ESTIMATED_FIELDS:
            if field not in missing:
                continue
            estimate = _weighted_average(comparables, field)
            if estimate is None:
                continue
            player[field] = round(max(minimum, min(maximum, estimate)), decimals)
            filled.append(field)

        if _optional_number(player.get("predicted_quote")) is None:
            player["predicted_quote"] = round(
                max(1.0, _optional_number(player.get("quote")) or 1.0)
            )
            filled.append("predicted_quote")
        if not filled:
            continue

        comparable_names = [
            str(reference.get("name") or "")
            for reference, _ in comparables[:3]
            if reference.get("name")
        ]
        player["analysis_estimated"] = True
        player["analysis_estimated_fields"] = filled
        player["analysis_confidence"] = (
            "media"
            if _optional_number(player.get("quote")) is not None
            and _optional_number(player.get("fvm")) is not None
            and len(comparables) >= 6
            else "bassa"
        )
        player["analysis_comparables"] = comparable_names
        player["analysis_source"] = (
            "Stima automatica da quotazione, FVM e comparabili dello stesso ruolo"
        )
        player["data_quality"] = "Stima automatica"
        if not player.get("profile"):
            player["profile"] = "Nuovo innesto · stima da comparabili"
        if not player.get("status"):
            player["status"] = _status_from_starter(player.get("starter_probability"))
        if not player.get("tier"):
            player["tier"] = _weighted_mode(comparables, "tier") or "In valutazione"
        if not player.get("risk_source"):
            player["risk_source"] = "Stima automatica da comparabili"
    return players


def recalibrate_injury_risk(player: dict[str, Any]) -> float | None:
    """Blend the legacy risk with actual availability and squad importance.

    Missing matches are a useful signal for regular starters, but much less so
    for reserves. The starter-weighted availability term prevents technical
    exclusions from being treated like injuries for every player.
    """

    legacy = _optional_number(player.get("risk_base"))
    if legacy is None:
        legacy = _optional_number(player.get("risk"))
    if legacy is None:
        return None
    legacy = max(0.0, min(100.0, legacy))
    player.setdefault("risk_base", round(legacy, 1))

    appearances = _optional_number(player.get("appearances_previous"))
    expected = _optional_number(player.get("expected_appearances"))
    starter = _percentage(player.get("starter_probability"))
    reliability = _percentage(player.get("reliability"), 100 - legacy)
    if appearances is None or (not expected and not starter):
        player.setdefault(
            "risk_source",
            "Stima automatica da comparabili"
            if player.get("analysis_estimated")
            else "Indice storico disponibile",
        )
        return round(legacy, 1)

    expected_baseline = max(expected or 0.0, 38.0 * starter / 100.0)
    if expected_baseline <= 0:
        return round(legacy, 1)
    missed_share = max(
        0.0,
        min(100.0, (expected_baseline - appearances) / expected_baseline * 100.0),
    )
    starter_weight = 0.25 + 0.75 * starter / 100.0
    availability_risk = min(100.0, missed_share * 2.0 * starter_weight)
    recalibrated = (
        legacy * 0.30 + availability_risk * 0.55 + (100.0 - reliability) * 0.15
    )
    result = round(max(legacy * 0.75, min(100.0, recalibrated)), 1)
    player["risk"] = result
    player["risk_source"] = (
        "Disponibilita stagione precedente, titolarita, affidabilita e indice storico"
    )
    player["risk_availability_gap"] = round(missed_share, 1)
    player["risk_recalibrated"] = True
    return result


def _is_reference(player: dict[str, Any]) -> bool:
    required = (
        "starter_probability",
        "expected_appearances",
        "expected_fantasy_average",
        "reliability",
        "potential",
        "risk",
    )
    return all(_optional_number(player.get(field)) is not None for field in required)


def _nearest_comparables(
    player: dict[str, Any], references: list[dict[str, Any]], limit: int = 10
) -> list[tuple[dict[str, Any], float]]:
    if not references:
        return []
    quote_values = [
        log1p(_positive(reference.get("quote"))) for reference in references
    ]
    fvm_values = [log1p(_positive(reference.get("fvm"))) for reference in references]
    quote_scale = max(pstdev(quote_values), 0.35)
    fvm_scale = max(pstdev(fvm_values), 0.35)
    target_quote = log1p(_positive(player.get("quote")))
    target_fvm = log1p(_positive(player.get("fvm")))

    ranked: list[tuple[dict[str, Any], float]] = []
    for reference in references:
        quote_distance = (
            log1p(_positive(reference.get("quote"))) - target_quote
        ) / quote_scale
        fvm_distance = (log1p(_positive(reference.get("fvm"))) - target_fvm) / fvm_scale
        distance = sqrt(quote_distance**2 + fvm_distance**2)
        ranked.append((reference, 1.0 / (0.18 + distance)))
    return sorted(ranked, key=lambda item: item[1], reverse=True)[:limit]


def _weighted_average(
    comparables: list[tuple[dict[str, Any], float]], field: str
) -> float | None:
    values = [
        (value, weight)
        for reference, weight in comparables
        if (value := _optional_number(reference.get(field))) is not None
    ]
    if not values:
        return None
    total_weight = sum(weight for _, weight in values)
    return sum(value * weight for value, weight in values) / total_weight


def _weighted_mode(comparables: list[tuple[dict[str, Any], float]], field: str) -> str:
    scores: Counter[str] = Counter()
    for reference, weight in comparables:
        value = str(reference.get(field) or "").strip()
        if value:
            scores[value] += weight
    return scores.most_common(1)[0][0] if scores else ""


def _status_from_starter(value: Any) -> str:
    starter = _percentage(value)
    if starter >= 75:
        return "Titolare"
    if starter >= 50:
        return "In ballottaggio"
    return "Alternativa"


def _percentage(value: Any, default: float = 0.0) -> float:
    result = _optional_number(value)
    if result is None:
        return default
    if 0 < result <= 1:
        result *= 100
    return max(0.0, min(100.0, result))


def _positive(value: Any) -> float:
    return max(0.0, _optional_number(value) or 0.0)


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if isnan(result) else result
