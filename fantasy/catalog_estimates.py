from __future__ import annotations

from math import isnan
from typing import Any

from fantasy.player_history import attach_player_history

ANALYSIS_FIELDS: tuple[tuple[str, int, float, float], ...] = (
    ("starter_probability", 0, 0, 100),
    ("expected_appearances", 0, 0, 38),
    ("expected_goals", 1, 0, 40),
    ("expected_assists", 1, 0, 30),
    ("expected_fantasy_average", 2, 0, 15),
    ("reliability", 0, 0, 100),
    ("potential", 0, 0, 100),
    ("value", 0, 0, 100),
)


def enrich_missing_analysis(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Analyse new registrations from their real career statistics.

    Market quotation and FVM are deliberately excluded from the calculation.
    Existing seed analysis is never overwritten.
    """
    attach_player_history(players)
    for player in players:
        missing = [
            field
            for field, _, _, _ in ANALYSIS_FIELDS
            if _optional_number(player.get(field)) is None
        ]
        if not missing:
            continue
        seasons = _history_seasons(player)
        if not seasons:
            continue
        projections = _historical_projections(player, seasons)
        filled: list[str] = []
        for field, decimals, minimum, maximum in ANALYSIS_FIELDS:
            if field not in missing or projections.get(field) is None:
                continue
            value = float(projections[field])
            player[field] = round(max(minimum, min(maximum, value)), decimals)
            filled.append(field)
        if not filled:
            continue
        total_appearances = sum(
            _optional_number(season.get("appearances")) or 0 for season in seasons
        )
        season_count = len(seasons)
        player["analysis_estimated"] = False
        player["analysis_historical"] = True
        player["analysis_historical_fields"] = filled
        player["analysis_confidence"] = (
            "alta"
            if season_count >= 3 and total_appearances >= 70
            else "media"
            if total_appearances >= 25
            else "bassa"
        )
        player.pop("analysis_comparables", None)
        history_source = str(player.get("history_source") or "ESPN")
        player["analysis_source"] = (
            f"Analisi statistica {history_source} · ultime {season_count} "
            "stagioni disponibili"
        )
        player["data_quality"] = f"Storico reale · {season_count} stagioni"
        if not player.get("profile"):
            player["profile"] = "Nuovo innesto · analisi della carriera recente"
        if not player.get("status"):
            player["status"] = _status_from_starter(player.get("starter_probability"))
        if not player.get("tier"):
            player["tier"] = _tier_from_projection(player)
    return players


def recalibrate_injury_risk(player: dict[str, Any]) -> float | None:
    """Calculate risk from up to five completed seasons of real availability.

    Only seasons in which the player had a meaningful first-team role are used,
    so tactical exclusions of reserves are not mistaken for injuries. Current
    injury status is intentionally not part of this score.
    """

    legacy = _optional_number(player.get("risk_base"))
    if legacy is None:
        legacy = _optional_number(player.get("risk"))
    if legacy is not None:
        legacy = max(0.0, min(100.0, legacy))
        player.setdefault("risk_base", round(legacy, 1))

    seasons = _history_seasons(player)
    meaningful: list[tuple[dict[str, Any], float]] = []
    for season in seasons:
        appearances = _optional_number(season.get("appearances"))
        starts = _optional_number(season.get("starts")) or 0.0
        matches = _optional_number(season.get("league_matches")) or 38.0
        if appearances is None or matches <= 0:
            continue
        start_share = starts / max(appearances, 1.0)
        if (
            appearances >= 24
            or starts >= 15
            or start_share >= 0.55
            and appearances >= 12
        ):
            meaningful.append((season, min(1.0, max(0.0, appearances / matches))))

    if not meaningful:
        if seasons:
            # A reserve or a very young player does not provide enough minutes
            # to turn absences into an injury signal. Keep a neutral, explicit
            # low-sample index rather than fabricating missed matches.
            result = round(legacy if legacy is not None else 25.0, 1)
            player["risk"] = result
            player["risk_source"] = (
                f"Storico reale disponibile per {len(seasons)} stagioni, ma con "
                "campione ridotto"
            )
            player["risk_history_seasons"] = len(seasons)
            player["risk_recalibrated"] = True
            return result
        if legacy is None:
            return None
        player["risk"] = round(legacy, 1)
        player.setdefault("risk_source", "Indice storico disponibile")
        return round(legacy, 1)

    # Entries are newest first. Recency weights make the latest completed
    # seasons more relevant without discarding older recurrent absences.
    weights = list(range(len(meaningful), 0, -1))
    missed = [1.0 - availability for _, availability in meaningful]
    weighted_missing = sum(
        value * weight for value, weight in zip(missed, weights, strict=False)
    ) / sum(weights)
    age = _optional_number(player.get("age"))
    if age is not None and age < 21:
        result = round(min(40.0, 20.0 + weighted_missing * 20.0), 1)
        player["risk"] = result
        player["risk_source"] = (
            f"Disponibilita reale in {len(meaningful)} stagioni giovanili; "
            "campione ancora breve"
        )
        player["risk_availability_gap"] = round(weighted_missing * 100.0, 1)
        player["risk_history_seasons"] = len(meaningful)
        player["risk_recalibrated"] = True
        return result
    if len(meaningful) == 1 and legacy is None:
        result = round(min(35.0, 25.0 + weighted_missing * 20.0), 1)
        player["risk"] = result
        player["risk_source"] = (
            "Disponibilita reale nell'unica stagione con impiego significativo; "
            "campione ridotto"
        )
        player["risk_availability_gap"] = round(weighted_missing * 100.0, 1)
        player["risk_history_seasons"] = 1
        player["risk_recalibrated"] = True
        return result
    recurrent_share = sum(value >= 0.20 for value in missed) / len(missed)
    recent_missing = missed[0]
    historical_risk = min(
        100.0,
        weighted_missing * 125.0 + recurrent_share * 25.0 + recent_missing * 20.0,
    )
    if legacy is None:
        result = round(historical_risk, 1)
    else:
        history_weight = 0.80 if len(meaningful) >= 3 else 0.65
        result = round(
            historical_risk * history_weight + legacy * (1.0 - history_weight), 1
        )
    player["risk"] = result
    player["risk_source"] = (
        f"Disponibilita reale nelle ultime {len(meaningful)} stagioni complete; "
        "piu peso alle recenti"
    )
    player["risk_availability_gap"] = round(weighted_missing * 100.0, 1)
    player["risk_history_seasons"] = len(meaningful)
    player["risk_recalibrated"] = True
    return result


def _history_seasons(player: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        season for season in player.get("history_5y", []) if isinstance(season, dict)
    ][:5]


def _historical_projections(
    player: dict[str, Any], seasons: list[dict[str, Any]]
) -> dict[str, float]:
    weights = list(range(len(seasons), 0, -1))

    def weighted(field: str, default: float = 0.0) -> float:
        values = [
            (_optional_number(season.get(field)), weight)
            for season, weight in zip(seasons, weights, strict=False)
        ]
        present = [(value, weight) for value, weight in values if value is not None]
        if not present:
            return default
        return sum(value * weight for value, weight in present) / sum(
            weight for _, weight in present
        )

    appearances = max(1.0, weighted("appearances"))
    starts = weighted("starts")
    expected_appearances = min(38.0, appearances)
    starter_probability = max(0.0, min(100.0, starts / appearances * 100.0))
    adjusted_goals = sum(
        (_optional_number(season.get("goals")) or 0.0)
        * _competition_factor(season.get("league"))
        * weight
        for season, weight in zip(seasons, weights, strict=False)
    ) / sum(weights)
    adjusted_assists = sum(
        (_optional_number(season.get("assists")) or 0.0)
        * _competition_factor(season.get("league"))
        * weight
        for season, weight in zip(seasons, weights, strict=False)
    ) / sum(weights)
    goals_rate = adjusted_goals / appearances
    assists_rate = adjusted_assists / appearances
    cards_rate = (
        weighted("yellow_cards") * 0.15 + weighted("red_cards") * 0.5
    ) / appearances
    role = str(player.get("role") or "")
    if role == "P":
        conceded_rate = weighted("goals_conceded") / appearances
        expected_fantasy_average = 6.0 - conceded_rate
    else:
        role_base = {"D": 5.90, "C": 6.00, "A": 6.05}.get(role, 5.90)
        expected_fantasy_average = (
            role_base + goals_rate * 3.0 + assists_rate - cards_rate
        )
    league_matches = max(1.0, weighted("league_matches", 38.0))
    availability = min(1.0, appearances / league_matches)
    sample_factor = min(
        1.0,
        sum(_optional_number(season.get("appearances")) or 0.0 for season in seasons)
        / 80.0,
    )
    reliability = availability * 78.0 + sample_factor * 22.0
    age = _optional_number(player.get("age"))
    age_potential = (
        72.0 if age is None else max(35.0, 92.0 - max(0.0, age - 21.0) * 3.2)
    )
    recent_output = (
        (_optional_number(seasons[0].get("goals")) or 0.0)
        + (_optional_number(seasons[0].get("assists")) or 0.0)
    ) / max(1.0, _optional_number(seasons[0].get("appearances")) or 1.0)
    potential = min(100.0, age_potential + min(12.0, recent_output * 30.0))
    value = min(
        100.0,
        expected_fantasy_average * 8.0 + reliability * 0.25 + potential * 0.25,
    )
    return {
        "starter_probability": starter_probability,
        "expected_appearances": expected_appearances,
        "expected_goals": goals_rate * expected_appearances,
        "expected_assists": assists_rate * expected_appearances,
        "expected_fantasy_average": expected_fantasy_average,
        "reliability": reliability,
        "potential": potential,
        "value": value,
    }


def _tier_from_projection(player: dict[str, Any]) -> str:
    starter = _percentage(player.get("starter_probability"))
    expected = _optional_number(player.get("expected_fantasy_average")) or 0.0
    if starter >= 75 and expected >= 7.0:
        return "Top"
    if starter >= 65 and expected >= 6.4:
        return "Buono"
    if starter >= 40:
        return "Rotazione"
    return "Scommessa"


def _competition_factor(value: Any) -> float:
    leagues = str(value or "").casefold()
    if any(term in leagues for term in ("primavera", ".u17", ".u18", ".u19")):
        return 0.45
    if "ita.4" in leagues:
        return 0.50
    if "ita.3" in leagues:
        return 0.62
    if any(term in leagues for term in (".2", "eng.2")):
        return 0.76
    if any(term in leagues for term in ("arg.1", "chi.1", "bra.1")):
        return 0.85
    if any(term in leagues for term in ("por.1", "ned.1", "bel.1", "sco.1")):
        return 0.90
    return 1.0


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
