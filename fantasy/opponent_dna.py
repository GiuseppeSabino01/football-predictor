from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from math import ceil, sqrt
from typing import Any

ROLES = ("P", "D", "C", "A")
PHASES = ("iniziale", "centrale", "finale")
STYLE_FIELDS = {
    "bonus_preference": "bonus",
    "starter_preference": "starter_probability",
    "reliability_preference": "reliability",
    "potential_preference": "potential",
}


def build_opponent_dna(
    league: dict[str, Any], catalog: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build deterministic, explainable behavioural profiles for auction managers."""
    managers = list(league.get("auction_managers", []))
    events = _weighted_events(league)
    catalog_by_id = {
        str(player.get("id")): player for player in catalog if player.get("id")
    }
    purchases_by_manager = _purchases_by_manager(league)
    top_player_ids = _top_role_player_ids(catalog)
    raw_profiles = {
        str(manager.get("id")): _raw_profile(
            manager,
            events,
            purchases_by_manager.get(str(manager.get("id")), {}),
            catalog_by_id,
            top_player_ids,
            league,
        )
        for manager in managers
    }
    league_averages = _league_averages(raw_profiles.values())
    profiles = []
    for manager in managers:
        manager_id = str(manager.get("id"))
        raw = raw_profiles[manager_id]
        profiles.append(
            _finalize_profile(
                manager,
                raw,
                league_averages,
                catalog,
                league,
            )
        )
    return profiles


def dna_buyer_multiplier(
    profile: dict[str, Any],
    *,
    role: str,
    tier: str | None = None,
    team: str | None = None,
    player: dict[str, Any] | None = None,
    stage_urgency: float = 50.0,
) -> float:
    """Translate a FantaDNA profile into the bounded multiplier used by simulations."""
    role_data = profile.get("role_preferences", {}).get(str(role).upper(), {})
    adjusted_role_share = _score(
        role_data.get("adjusted_spend_share"), default=0.0
    )
    league_role_share = _score(role_data.get("league_spend_share"), default=0.0)
    role_affinity = _clip(
        50 + (adjusted_role_share - league_role_share) * 100, 0, 100
    )

    tier_affinity = 50.0
    if tier:
        tier_share = _score(
            profile.get("tier_preferences", {}).get(str(tier), 0.0), default=0.0
        )
        tier_affinity = _clip(50 + (tier_share - 0.25) * 100, 0, 100)

    team_affinity = 50.0
    if team:
        preference = next(
            (
                item
                for item in profile.get("team_preferences", [])
                if str(item.get("team", "")).casefold() == str(team).casefold()
            ),
            None,
        )
        if preference:
            team_affinity = min(
                100.0,
                50.0 + max(float(preference.get("overrepresentation", 0)), 0.0) * 100,
            )

    style_affinity = _player_style_affinity(profile, player or {})
    multiplier = (
        1
        + 0.25 * _centered(profile.get("aggression_score", 50))
        + 0.20 * _centered(role_affinity)
        + 0.15 * _centered(tier_affinity)
        + 0.10 * _centered(team_affinity)
        + 0.15 * _centered(style_affinity)
        + 0.15 * _centered(stage_urgency)
    )
    confidence_factor = {"bassa": 0.25, "media": 0.65, "alta": 1.0}.get(
        str(profile.get("confidence")), 0.25
    )
    multiplier = 1 + (multiplier - 1) * confidence_factor
    return round(_clip(multiplier, 0.65, 1.45), 4)


def _weighted_events(league: dict[str, Any]) -> list[dict[str, Any]]:
    current = [dict(event, _temporal_weight=1.0) for event in league.get("auction_sale_events", [])]
    historical = []
    for event in league.get("auction_history", []):
        offset = int(_number(event.get("season_offset"), 3))
        weight = {1: 0.65, 2: 0.40}.get(offset, 0.20)
        historical.append(dict(event, _temporal_weight=weight))
    return [*current, *historical]


def _purchases_by_manager(league: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for manager in league.get("auction_managers", []):
        manager_id = str(manager.get("id"))
        purchases = (
            league.get("purchases", [])
            if manager.get("is_user")
            else manager.get("purchases", [])
        )
        result[manager_id] = {
            str(purchase.get("player_id")): purchase for purchase in purchases
        }
    return result


def _top_role_player_ids(catalog: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for role in ROLES:
        players = [player for player in catalog if str(player.get("role", "")).upper() == role]
        players.sort(key=_player_index, reverse=True)
        result.update(
            str(player.get("id")) for player in players[: max(ceil(len(players) * 0.20), 1)]
        )
    return result


def _raw_profile(
    manager: dict[str, Any],
    all_events: list[dict[str, Any]],
    purchases: dict[str, dict[str, Any]],
    catalog_by_id: dict[str, dict[str, Any]],
    top_player_ids: set[str],
    league: dict[str, Any],
) -> dict[str, Any]:
    manager_id = str(manager.get("id"))
    events = [event for event in all_events if str(event.get("manager_id")) == manager_id]
    current_events = [
        event for event in league.get("auction_sale_events", [])
        if str(event.get("manager_id")) == manager_id
    ]
    effective_sample = sum(_number(event.get("_temporal_weight"), 1) for event in events)
    weights = [
        max(_number(event.get("paid_price")), 0.0)
        * _number(event.get("_temporal_weight"), 1.0)
        for event in events
    ]
    total_spent = sum(weights)
    initial_budget = max(_number(league.get("initial_budget")), 0.0)
    price_ratios = [
        max(_number(event.get("paid_price")), 0.0)
        / max(_number(event.get("expected_price_at_sale")), 1.0)
        for event in events
    ]
    temporal_weights = [_number(event.get("_temporal_weight"), 1.0) for event in events]
    aggression = _weighted_median(price_ratios, temporal_weights) if events else None
    top_spent = sum(
        weight
        for event, weight in zip(events, weights)
        if str(event.get("player_id")) in top_player_ids
    )
    top_share = top_spent / initial_budget if initial_budget else None
    concentration = (
        sum((weight / total_spent) ** 2 for weight in weights) if total_spent else None
    )

    role_spend = {role: 0.0 for role in ROLES}
    role_counts = {role: 0.0 for role in ROLES}
    phase_spend = {phase: 0.0 for phase in PHASES}
    phase_counts = {phase: 0.0 for phase in PHASES}
    team_counts: defaultdict[str, float] = defaultdict(float)
    team_purchase_counts: Counter[str] = Counter()
    tier_spend: defaultdict[str, float] = defaultdict(float)
    style_values: dict[str, list[tuple[float, float]]] = defaultdict(list)
    injury_values: list[tuple[float, float]] = []

    for event, price_weight in zip(events, weights):
        role = str(event.get("role", "")).upper()
        if role in role_spend:
            role_spend[role] += price_weight
            role_counts[role] += _number(event.get("_temporal_weight"), 1.0)
        phase = _auction_phase(_number(event.get("auction_progress")))
        phase_spend[phase] += price_weight
        phase_counts[phase] += _number(event.get("_temporal_weight"), 1.0)
        player_id = str(event.get("player_id"))
        player = {**catalog_by_id.get(player_id, {}), **purchases.get(player_id, {})}
        team = str(event.get("team") or player.get("team") or "").strip()
        if team:
            team_counts[team] += _number(event.get("_temporal_weight"), 1.0)
            team_purchase_counts[team] += 1
        tier = _personal_tier_name(league, player_id) or str(player.get("tier") or "").strip()
        if tier:
            tier_spend[tier] += price_weight
        for output_field, player_field in STYLE_FIELDS.items():
            value = _percent_value(player.get(player_field))
            if value is not None:
                style_values[output_field].append((value, price_weight))
        injury = _percent_value(player.get("risk"))
        if injury is not None:
            injury_values.append((100 - injury, price_weight))

    phase_total_count = sum(phase_counts.values())
    phase_preferences = {
        phase: {
            "purchase_share": phase_counts[phase] / phase_total_count if phase_total_count else 0.0,
            "spend_share": phase_spend[phase] / initial_budget if initial_budget else 0.0,
            "relative_spend_share": phase_spend[phase] / total_spent if total_spent else 0.0,
        }
        for phase in PHASES
    }
    patience = (
        sum(
            phase_preferences[phase]["relative_spend_share"] * phase_score
            for phase, phase_score in zip(PHASES, (0, 50, 100))
        )
        if total_spent else None
    )
    slots = league.get("roster_slots", {})
    total_slots = max(sum(int(slots.get(role, 0)) for role in ROLES), 1)
    return {
        "sample_size": len(events),
        "effective_sample_size": effective_sample,
        "total_spent": sum(
            max(_number(event.get("paid_price")), 0.0) for event in current_events
        ),
        "aggression": aggression,
        "top_share": top_share,
        "concentration": concentration,
        "patience": patience,
        "role_preferences": {
            role: {
                "spend_share": role_spend[role] / initial_budget if initial_budget else 0.0,
                "purchase_share": role_counts[role] / effective_sample if effective_sample else 0.0,
                "slot_share": int(slots.get(role, 0)) / total_slots,
            }
            for role in ROLES
        },
        "phase_preferences": phase_preferences,
        "team_counts": team_counts,
        "team_purchase_counts": team_purchase_counts,
        "tier_preferences": {
            tier: spend / total_spent for tier, spend in tier_spend.items()
        } if total_spent else {},
        **{
            field: _weighted_average(values)
            for field, values in style_values.items()
        },
        "low_injury_risk_preference": _weighted_average(injury_values),
    }


def _league_averages(raw_profiles: Iterable[dict[str, Any]]) -> dict[str, Any]:
    profiles = list(raw_profiles)
    observed = [profile for profile in profiles if profile.get("effective_sample_size", 0) > 0]
    defaults = {
        "aggression": 1.0,
        "top_share": 0.20,
        "concentration": 0.50,
        "patience": 50.0,
        "bonus_preference": 50.0,
        "starter_preference": 50.0,
        "reliability_preference": 50.0,
        "potential_preference": 50.0,
        "low_injury_risk_preference": 50.0,
    }
    averages: dict[str, Any] = {}
    for field, default in defaults.items():
        values = [float(profile[field]) for profile in observed if profile.get(field) is not None]
        averages[field] = sum(values) / len(values) if values else default
    averages["role_preferences"] = {}
    for role in ROLES:
        values = [
            float(profile["role_preferences"][role]["spend_share"])
            for profile in observed
        ]
        averages["role_preferences"][role] = sum(values) / len(values) if values else 0.0
    return averages


def _finalize_profile(
    manager: dict[str, Any],
    raw: dict[str, Any],
    league_averages: dict[str, Any],
    catalog: list[dict[str, Any]],
    league: dict[str, Any],
) -> dict[str, Any]:
    sample_size = int(raw.get("sample_size", 0))
    effective_sample = float(raw.get("effective_sample_size", 0))
    confidence = "bassa" if sample_size < 5 else "media" if sample_size < 15 else "alta"
    shrink_weight = effective_sample / (effective_sample + 8) if effective_sample else 0.0
    adjusted = {
        field: _shrink(raw.get(field), league_averages[field], shrink_weight)
        for field in (
            "aggression", "top_share", "concentration", "patience",
            "bonus_preference", "starter_preference", "reliability_preference",
            "potential_preference", "low_injury_risk_preference",
        )
    }
    aggression_average = max(float(league_averages["aggression"]), 0.01)
    aggression_score = _clip(
        50 + ((float(adjusted["aggression"]) / aggression_average) - 1) * 100,
        0,
        100,
    )
    if sample_size == 0:
        aggression_score = 50.0

    neutral = sample_size == 0

    role_preferences = {}
    for role in ROLES:
        role_raw = raw["role_preferences"][role]
        league_share = float(league_averages["role_preferences"][role])
        role_preferences[role] = {
            **role_raw,
            "league_spend_share": league_share,
            "adjusted_spend_share": _shrink(
                role_raw.get("spend_share"), league_share, shrink_weight
            ),
        }

    team_preferences = _team_preferences(raw, catalog, sample_size)
    evidence = _evidence(
        raw,
        adjusted,
        league_averages,
        role_preferences,
        team_preferences,
        confidence,
        league,
    )
    return {
        "manager_id": str(manager.get("id")),
        "manager_name": str(manager.get("name") or "Partecipante"),
        "is_user": bool(manager.get("is_user")),
        "sample_size": sample_size,
        "effective_sample_size": round(effective_sample, 2),
        "confidence": confidence,
        "shrinkage_weight": round(shrink_weight, 4),
        "aggression_score": round(aggression_score, 1),
        "top_player_bias": 50.0 if neutral else round(float(adjusted["top_share"]) * 100, 1),
        "budget_concentration": 50.0 if neutral else round(float(adjusted["concentration"]) * 100, 1),
        "patience_score": 50.0 if neutral else round(float(adjusted["patience"]), 1),
        "bonus_preference": 50.0 if neutral else round(float(adjusted["bonus_preference"]), 1),
        "starter_preference": 50.0 if neutral else round(float(adjusted["starter_preference"]), 1),
        "reliability_preference": 50.0 if neutral else round(float(adjusted["reliability_preference"]), 1),
        "potential_preference": 50.0 if neutral else round(float(adjusted["potential_preference"]), 1),
        "low_injury_risk_preference": round(
            float(adjusted["low_injury_risk_preference"]), 1
        ) if not neutral else 50.0,
        "role_preferences": role_preferences,
        "team_preferences": team_preferences,
        "auction_phase_preferences": raw["phase_preferences"],
        "tier_preferences": raw["tier_preferences"],
        "total_spent": round(float(raw.get("total_spent", 0)), 1),
        "league_benchmarks": {
            "aggression_score": 50.0,
            "top_player_bias": round(float(league_averages["top_share"]) * 100, 1),
            "budget_concentration": round(
                float(league_averages["concentration"]) * 100, 1
            ),
            "patience_score": round(float(league_averages["patience"]), 1),
            "bonus_preference": round(float(league_averages["bonus_preference"]), 1),
            "starter_preference": round(float(league_averages["starter_preference"]), 1),
            "reliability_preference": round(
                float(league_averages["reliability_preference"]), 1
            ),
            "potential_preference": round(
                float(league_averages["potential_preference"]), 1
            ),
            "low_injury_risk_preference": round(
                float(league_averages["low_injury_risk_preference"]), 1
            ),
        },
        "evidence": evidence,
    }


def _team_preferences(
    raw: dict[str, Any], catalog: list[dict[str, Any]], sample_size: int
) -> list[dict[str, Any]]:
    if sample_size < 5:
        return []
    catalog_teams = Counter(
        str(player.get("team") or "").strip() for player in catalog if player.get("team")
    )
    catalog_total = sum(catalog_teams.values())
    preferences = []
    effective_sample = max(float(raw.get("effective_sample_size", 0)), 1.0)
    ranked_teams = sorted(
        raw["team_counts"], key=lambda team: raw["team_counts"][team], reverse=True
    )
    for team in ranked_teams:
        weighted_count = float(raw["team_counts"][team])
        purchase_count = int(raw["team_purchase_counts"][team])
        observed_share = weighted_count / effective_sample
        availability_share = catalog_teams.get(team, 0) / catalog_total if catalog_total else 0.0
        standard_error = sqrt(
            max(availability_share * (1 - availability_share), 0) / max(sample_size, 1)
        )
        significant = observed_share > availability_share + max(0.10, 1.64 * standard_error)
        if purchase_count >= 3 or (purchase_count >= 2 and significant):
            preferences.append(
                {
                    "team": team,
                    "purchases": purchase_count,
                    "observed_share": round(observed_share, 4),
                    "availability_share": round(availability_share, 4),
                    "overrepresentation": round(observed_share - availability_share, 4),
                }
            )
    return preferences


def _evidence(
    raw: dict[str, Any],
    adjusted: dict[str, float],
    league_averages: dict[str, Any],
    role_preferences: dict[str, dict[str, float]],
    team_preferences: list[dict[str, Any]],
    confidence: str,
    league: dict[str, Any],
) -> list[str]:
    sample_size = int(raw.get("sample_size", 0))
    if sample_size == 0:
        return [
            "Nessun acquisto analizzato: profilo neutrale in attesa di dati reali.",
            "I punteggi resteranno vicini alla media della lega finché il campione è ridotto.",
        ]
    prefix = "Segnale preliminare: " if confidence == "bassa" else ""
    ratio = float(raw.get("aggression") or 1.0)
    league_ratio = float(league_averages.get("aggression") or 1.0)
    delta = (ratio / max(league_ratio, 0.01) - 1) * 100
    evidence = [
        f"{sample_size} acquisti analizzati; confidenza {confidence}.",
        (
            f"{prefix}prezzo mediano {ratio:.2f}× quello atteso, {abs(delta):.0f}% "
            f"{'sopra' if delta >= 0 else 'sotto'} la media della lega."
        ),
    ]
    top_share = float(raw.get("top_share") or 0)
    league_top_share = float(league_averages.get("top_share") or 0)
    evidence.append(
        f"{prefix}destina il {top_share:.0%} del budget iniziale ai top 20% del ruolo, "
        f"contro il {league_top_share:.0%} medio della lega."
    )
    concentration = float(raw.get("concentration") or 0)
    league_concentration = float(league_averages.get("concentration") or 0)
    evidence.append(
        f"{prefix}concentrazione del budget {concentration * 100:.0f}/100, "
        f"media lega {league_concentration * 100:.0f}/100."
    )
    budget = float(league.get("initial_budget") or 0)
    spent_share = float(raw.get("total_spent", 0)) / budget if budget else 0.0
    evidence.append(f"Ha utilizzato il {spent_share:.0%} del budget iniziale.")
    role, role_data = max(
        role_preferences.items(), key=lambda item: item[1]["adjusted_spend_share"]
    )
    role_delta = role_data["adjusted_spend_share"] - role_data["league_spend_share"]
    if abs(role_delta) >= 0.03:
        evidence.append(
            f"{prefix}sul ruolo {role} usa il {role_data['spend_share']:.0%} del budget iniziale, "
            f"{abs(role_delta):.0%} {'più' if role_delta > 0 else 'meno'} della media corretta della lega."
        )
    if team_preferences:
        team = team_preferences[0]
        evidence.append(
            f"Preferenza osservabile per {team['team']}: {team['purchases']} acquisti "
            f"({team['observed_share']:.0%} del campione)."
        )
    late_share = raw["phase_preferences"]["finale"]["relative_spend_share"]
    if late_share >= 0.45:
        evidence.append(f"{prefix}concentra il {late_share:.0%} della spesa nella fase finale.")
    return evidence


def _player_style_affinity(profile: dict[str, Any], player: dict[str, Any]) -> float:
    comparisons = []
    for preference_field, player_field in STYLE_FIELDS.items():
        player_value = _percent_value(player.get(player_field))
        if player_value is None:
            continue
        preference = float(profile.get(preference_field, 50))
        comparisons.append(50 + ((player_value - 50) * (preference - 50)) / 50)
    risk = _percent_value(player.get("risk"))
    if risk is not None:
        preference = float(profile.get("low_injury_risk_preference", 50))
        comparisons.append(50 + (((100 - risk) - 50) * (preference - 50)) / 50)
    return sum(comparisons) / len(comparisons) if comparisons else 50.0


def _personal_tier_name(league: dict[str, Any], player_id: str) -> str:
    tier_id = str(league.get("auction_player_tiers", {}).get(player_id) or "")
    return next(
        (
            str(tier.get("name") or "").strip()
            for tier in league.get("auction_tiers", [])
            if str(tier.get("id")) == tier_id
        ),
        "",
    )


def _auction_phase(progress: float) -> str:
    if progress <= 0.33:
        return "iniziale"
    if progress <= 0.66:
        return "centrale"
    return "finale"


def _player_index(player: dict[str, Any]) -> float:
    explicit = _number(player.get("index")) or _number(player.get("fantasy_score"))
    if explicit:
        return explicit
    return (
        _number(player.get("expected_fantasy_average")) * 10
        + _number(player.get("expected_goals")) * 2
        + _number(player.get("expected_assists"))
        + (_percent_value(player.get("starter_probability")) or 0) * 0.1
    )


def _weighted_average(values: list[tuple[float, float]]) -> float | None:
    if not values:
        return None
    total_weight = sum(max(weight, 0) for _, weight in values)
    if total_weight <= 0:
        return sum(value for value, _ in values) / len(values)
    return sum(value * max(weight, 0) for value, weight in values) / total_weight


def _weighted_median(values: list[float], weights: list[float]) -> float:
    ordered = sorted(zip(values, weights), key=lambda item: item[0])
    threshold = sum(max(weight, 0) for _, weight in ordered) / 2
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += max(weight, 0)
        if cumulative >= threshold:
            return value
    return ordered[-1][0] if ordered else 1.0


def _shrink(value: Any, league_average: float, weight: float) -> float:
    observed = float(league_average if value is None else value)
    return weight * observed + (1 - weight) * float(league_average)


def _percent_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    parsed = _number(value)
    if 0 < parsed <= 1:
        parsed *= 100
    return _clip(parsed, 0, 100)


def _score(value: Any, default: float) -> float:
    parsed = _number(value, default)
    return _clip(parsed, 0, 1)


def _centered(score: Any) -> float:
    return (_clip(_number(score, 50), 0, 100) - 50) / 50


def _clip(value: float, lower: float, upper: float) -> float:
    return min(max(float(value), lower), upper)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)
