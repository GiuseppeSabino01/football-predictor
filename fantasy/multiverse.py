from __future__ import annotations

import json
import random
from copy import deepcopy
from dataclasses import asdict, dataclass
from functools import lru_cache
from hashlib import sha256
from math import ceil
from statistics import NormalDist, median
from typing import Any

ROLE_ORDER = ("P", "D", "C", "A")
ROLE_INDEX = {role: index for index, role in enumerate(ROLE_ORDER)}
SIMULATION_COUNTS = {"rapida": 250, "standard": 1_000, "approfondita": 5_000}
FORMATIONS = (
    {"P": 1, "D": 4, "C": 3, "A": 3},
    {"P": 1, "D": 4, "C": 4, "A": 2},
    {"P": 1, "D": 3, "C": 4, "A": 3},
    {"P": 1, "D": 3, "C": 5, "A": 2},
    {"P": 1, "D": 5, "C": 3, "A": 2},
)
NORMAL_Z_TABLE = tuple(
    NormalDist().inv_cdf((index + 0.5) / 512) for index in range(512)
)


@dataclass(frozen=True, slots=True)
class OwnedPlayerState:
    player_id: str
    name: str
    role: str
    utility: float


@dataclass(frozen=True, slots=True)
class ParticipantState:
    manager_id: str
    name: str
    initial_budget: int
    remaining_budget: int
    roster: tuple[str, ...]
    roster_players: tuple[OwnedPlayerState, ...]
    remaining_slots_by_role: tuple[int, int, int, int]
    dna_confidence: str
    dna_sample_size: int


@dataclass(frozen=True, slots=True)
class PlayerState:
    player_id: str
    name: str
    role: str
    team: str
    quotation: float
    initial_price: float
    updated_price: float
    strategic_max: float
    expected_fantasy_average: float | None
    expected_goals: float | None
    expected_assists: float | None
    bonus_propensity: float | None
    starter_probability: float | None
    reliability: float | None
    injury_risk: float | None
    potential: float | None
    index: float | None
    personal_tier: str | None
    utility: float
    viable: bool
    buyer_multipliers: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class SaleEventState:
    event_id: str
    player_id: str
    manager_id: str
    role: str
    paid_price: int
    nomination_number: int


@dataclass(frozen=True, slots=True)
class AuctionSnapshot:
    fantasy_id: str
    user_manager_id: str
    total_budget: int
    min_bid: int
    auction_mode: str
    current_role: str | None
    roster_rules: tuple[int, int, int, int]
    participants: tuple[ParticipantState, ...]
    available_players: tuple[PlayerState, ...]
    sold_players: tuple[SaleEventState, ...]
    personal_tiers: tuple[tuple[str, str], ...]
    personal_targets: tuple[str, ...]
    risk_profile: str
    modifier_enabled: bool
    state_version: int


def legal_max_bid(remaining_budget: float, remaining_total_slots: int, min_bid: int) -> int:
    if remaining_total_slots <= 0:
        return 0
    return max(
        int(remaining_budget) - int(min_bid) * (int(remaining_total_slots) - 1),
        0,
    )


def snapshot_fingerprint(snapshot: AuctionSnapshot) -> str:
    payload = json.dumps(asdict(snapshot), sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def simulate_multiverse(
    snapshot: AuctionSnapshot,
    *,
    mode: str = "standard",
    seed: int | None = None,
) -> dict[str, Any]:
    if mode not in SIMULATION_COUNTS:
        raise ValueError("Modalita di simulazione non riconosciuta.")
    state_hash = snapshot_fingerprint(snapshot)
    clean_seed = int(seed if seed is not None else int(state_hash[:8], 16))
    result = _simulate_cached(snapshot, SIMULATION_COUNTS[mode], clean_seed)
    return deepcopy({**result, "mode": mode, "state_hash": state_hash})


def compute_role_utilities(catalog: list[dict[str, Any]]) -> dict[str, float]:
    """Return the 0-100 role percentile used internally for roster strength."""
    by_role: dict[str, list[tuple[str, float]]] = {role: [] for role in ROLE_ORDER}
    role_metric_values: dict[str, dict[str, list[float]]] = {
        role: {field: [] for field in ("expected_fantasy_average",)}
        for role in ROLE_ORDER
    }
    for player in catalog:
        player_id = str(player.get("id") or "")
        role = str(player.get("role") or "").upper()
        if not player_id or role not in ROLE_INDEX:
            continue
        explicit = _optional_number(player.get("index"))
        if explicit is None:
            explicit = _optional_number(player.get("fantasy_score"))
        if explicit is not None:
            by_role[role].append((player_id, explicit))
        fantasy_average = _optional_number(player.get("expected_fantasy_average"))
        if fantasy_average is not None:
            role_metric_values[role]["expected_fantasy_average"].append(fantasy_average)

    explicit_percentiles = {
        player_id: percentile
        for role in ROLE_ORDER
        for player_id, percentile in _percentile_pairs(by_role[role])
    }
    utilities: dict[str, float] = {}
    for player in catalog:
        player_id = str(player.get("id") or "")
        role = str(player.get("role") or "").upper()
        if not player_id or role not in ROLE_INDEX:
            continue
        if player_id in explicit_percentiles:
            utilities[player_id] = explicit_percentiles[player_id]
            continue
        fantasy_average = _optional_number(player.get("expected_fantasy_average"))
        fantasy_percentile = _percentile_value(
            fantasy_average,
            role_metric_values[role]["expected_fantasy_average"],
        )
        utilities[player_id] = _clip(
            0.30 * fantasy_percentile
            + 0.25 * _percent(player.get("bonus"))
            + 0.20 * _percent(player.get("starter_probability"))
            + 0.10 * _percent(player.get("reliability"))
            + 0.10 * _percent(player.get("potential"))
            - 0.05 * _percent(player.get("risk")),
            0,
            100,
        )
    return utilities


def viable_player_ids(
    catalog: list[dict[str, Any]], utilities: dict[str, float]
) -> set[str]:
    viable: set[str] = set()
    for role in ROLE_ORDER:
        rows = sorted(
            (
                (str(player.get("id")), utilities.get(str(player.get("id")), 0.0))
                for player in catalog
                if str(player.get("role") or "").upper() == role
            ),
            key=lambda item: item[1],
        )
        if not rows:
            continue
        threshold = rows[max(ceil(len(rows) * 0.25) - 1, 0)][1]
        viable.update(player_id for player_id, utility in rows if utility >= threshold)
    return viable


@lru_cache(maxsize=24)
def _simulate_cached(
    snapshot: AuctionSnapshot, simulation_count: int, seed: int
) -> dict[str, Any]:
    participants = snapshot.participants
    players = snapshot.available_players
    participant_count = len(participants)
    user_index = next(
        (
            index for index, participant in enumerate(participants)
            if participant.manager_id == snapshot.user_manager_id
        ),
        0,
    )
    role_player_indices = {
        role: [index for index, player in enumerate(players) if player.role == role]
        for role in ROLE_ORDER
    }
    initial_viable = {
        role: sum(players[index].viable for index in indices)
        for role, indices in role_player_indices.items()
    }
    market_prices = tuple(
        _market_price(player, snapshot.total_budget) for player in players
    )
    role_indices = tuple(ROLE_INDEX[player.role] for player in players)
    confidence_factors = tuple(
        {"bassa": 0.25, "media": 0.65, "alta": 1.0}.get(
            participant.dna_confidence, 0.25
        )
        for participant in participants
    )
    uncertain_participants = tuple(
        participant.dna_confidence == "bassa" or participant.dna_sample_size < 5
        for participant in participants
    )
    user_risk_multiplier = {
        "prudente": 0.90,
        "bilanciato": 1.0,
        "aggressivo": 1.10,
    }.get(snapshot.risk_profile, 1.0)
    initial_role_demand = {
        role: sum(
            participant.remaining_slots_by_role[ROLE_INDEX[role]]
            for participant in participants
        )
        for role in ROLE_ORDER
    }
    nomination_bases = tuple(
        market_prices[index]
        * (
            1
            + min(
                initial_role_demand[player.role]
                / max(len(role_player_indices[player.role]), 1),
                1,
            )
        )
        * (
            sum(player.buyer_multipliers)
            / max(len(player.buyer_multipliers), 1)
        )
        for index, player in enumerate(players)
    )
    target_ids = set(snapshot.personal_targets)
    target_names = {
        player.player_id: player.name for player in players if player.player_id in target_ids
    }
    for participant in participants:
        for owned in participant.roster_players:
            if owned.player_id in target_ids:
                target_names[owned.player_id] = owned.name

    completion_values: list[bool] = []
    strength_values: list[float] = []
    budget_values: list[int] = []
    target_wins = {player_id: 0 for player_id in target_ids}
    acquired_counts = {index: 0 for index in range(len(players))}
    role_completion = {role: 0 for role in ROLE_ORDER}
    role_strength_samples: dict[str, list[float]] = {role: [] for role in ROLE_ORDER}
    violations = {
        "negative_budget": 0,
        "slot_overflow": 0,
        "duplicate_assignment": 0,
        "reserve_violation": 0,
    }
    cached_order: list[int] | None = None

    for simulation_index in range(simulation_count):
        rng = random.Random(seed + simulation_index * 104_729)
        budgets = [participant.remaining_budget for participant in participants]
        slots = [list(participant.remaining_slots_by_role) for participant in participants]
        remaining_slot_totals = [sum(row) for row in slots]
        global_remaining_slots = sum(remaining_slot_totals)
        acquired: list[list[int]] = [[] for _ in participants]
        assigned: set[int] = set()
        viable_remaining = dict(initial_viable)
        if cached_order is None or simulation_index % 4 == 0:
            cached_order = _nomination_order(
                snapshot, role_player_indices, nomination_bases, rng
            )
        order = cached_order

        for step, player_index in enumerate(order):
            if global_remaining_slots <= 0:
                break
            player = players[player_index]
            role_index = role_indices[player_index]
            if viable_remaining[player.role] > 0 and player.viable:
                viable_remaining[player.role] -= 1
            remaining_role_slots = sum(row[role_index] for row in slots)
            if remaining_role_slots <= 0:
                continue
            scarcity_ratio = remaining_role_slots / max(viable_remaining[player.role] + 1, 1)
            scarcity_multiplier = _clip(0.90 + 0.15 * scarcity_ratio, 0.85, 1.30)
            progress = step / max(len(order) - 1, 1)
            highest = (-1, -1, -1, 0)
            second = (-1, -1, -1, 0)
            market_price = market_prices[player_index]
            high_potential = _is_high_potential(player)
            for bidder_index in range(participant_count):
                if slots[bidder_index][role_index] <= 0:
                    continue
                remaining_total_slots = remaining_slot_totals[bidder_index]
                legal_max = max(
                    budgets[bidder_index]
                    - snapshot.min_bid * (remaining_total_slots - 1),
                    0,
                )
                if legal_max < snapshot.min_bid:
                    continue
                urgency = min(
                    max(
                        30
                        + 50 * progress
                        + 40
                        * slots[bidder_index][role_index]
                        / max(remaining_total_slots, 1),
                        0,
                    ),
                    100,
                )
                multiplier = min(max(
                    player.buyer_multipliers[bidder_index]
                    + 0.15
                    * ((urgency - 50) / 50)
                    * confidence_factors[bidder_index],
                    0.65,
                ), 1.45)
                if bidder_index == user_index:
                    multiplier = min(
                        max(multiplier * user_risk_multiplier, 0.65), 1.45
                    )
                sigma = 0.18 if (
                    uncertain_participants[bidder_index] or high_potential
                ) else 0.12
                random_variation = min(
                    max(
                        1 + sigma * NORMAL_Z_TABLE[int(rng.random() * 512)],
                        0.45,
                    ),
                    1.75,
                )
                willingness = (
                    market_price
                    * scarcity_multiplier
                    * multiplier
                    * random_variation
                )
                bid = min(max(round(willingness), snapshot.min_bid), legal_max)
                tie_breaker = (bidder_index + simulation_index) % participant_count
                candidate = (bid, tie_breaker, bidder_index, legal_max)
                if candidate > highest:
                    second = highest
                    highest = candidate
                elif candidate > second:
                    second = candidate

            if highest[2] < 0:
                continue
            highest_bid, _, winner, winner_legal_max = highest
            if second[2] >= 0:
                winning_price = min(highest_bid, second[0] + snapshot.min_bid)
            else:
                lone_price = round(
                    market_price * (0.55 + 0.25 * rng.random())
                )
                winning_price = min(
                    highest_bid, max(snapshot.min_bid, int(lone_price))
                )
            winning_price = min(
                winning_price,
                winner_legal_max,
            )
            if winning_price < snapshot.min_bid:
                continue
            if player_index in assigned:
                violations["duplicate_assignment"] += 1
                continue
            budgets[winner] -= winning_price
            slots[winner][role_index] -= 1
            remaining_slot_totals[winner] -= 1
            global_remaining_slots -= 1
            acquired[winner].append(player_index)
            assigned.add(player_index)
            if budgets[winner] < snapshot.min_bid * remaining_slot_totals[winner]:
                violations["reserve_violation"] += 1

        user_acquired = acquired[user_index]
        complete = sum(slots[user_index]) == 0
        completion_values.append(complete)
        strength_values.append(_roster_strength(snapshot, user_index, user_acquired))
        budget_values.append(budgets[user_index])
        final_user_ids = {
            *participants[user_index].roster,
            *(players[index].player_id for index in user_acquired),
        }
        for target_id in target_ids:
            if target_id in final_user_ids:
                target_wins[target_id] += 1
        for player_index in user_acquired:
            acquired_counts[player_index] += 1
        for role, role_index in ROLE_INDEX.items():
            if slots[user_index][role_index] == 0:
                role_completion[role] += 1
            role_utilities = [
                owned.utility
                for owned in participants[user_index].roster_players
                if owned.role == role
            ] + [players[index].utility for index in user_acquired if players[index].role == role]
            role_strength_samples[role].append(
                sum(role_utilities) / len(role_utilities) if role_utilities else 0.0
            )
        if any(budget < 0 for budget in budgets):
            violations["negative_budget"] += 1
        if any(slot < 0 for row in slots for slot in row):
            violations["slot_overflow"] += 1

    target_probabilities = {
        player_id: {
            "name": target_names.get(player_id, player_id),
            "probability": target_wins[player_id] / simulation_count,
        }
        for player_id in sorted(target_ids)
    }
    common_players = sorted(
        (
            {
                "player_id": players[index].player_id,
                "name": players[index].name,
                "role": players[index].role,
                "probability": count / simulation_count,
                "utility": players[index].utility,
            }
            for index, count in acquired_counts.items()
            if count > 0
        ),
        key=lambda row: (row["probability"], row["utility"]),
        reverse=True,
    )
    fragile_roles = sorted(
        (
            {
                "role": role,
                "completion_probability": role_completion[role] / simulation_count,
                "median_strength": round(median(role_strength_samples[role]), 2),
            }
            for role in ROLE_ORDER
            if snapshot.roster_rules[ROLE_INDEX[role]] > 0
        ),
        key=lambda row: (row["completion_probability"], row["median_strength"]),
    )
    alternatives = sorted(
        (
            row for row in common_players
            if row["player_id"] not in target_ids
        ),
        key=lambda row: row["probability"] * (0.5 + row["utility"] / 100),
        reverse=True,
    )[:5]
    warnings = _warnings(completion_values, fragile_roles, target_probabilities)
    return {
        "simulation_count": simulation_count,
        "seed": seed,
        "completion_probability": sum(completion_values) / simulation_count,
        "median_roster_strength": round(median(strength_values), 2),
        "p10_roster_strength": round(_quantile(strength_values, 0.10), 2),
        "p90_roster_strength": round(_quantile(strength_values, 0.90), 2),
        "expected_remaining_budget": round(sum(budget_values) / simulation_count, 2),
        "probability_of_acquiring_targets": target_probabilities,
        "most_common_final_roster": common_players[:10],
        "fragile_roles": fragile_roles,
        "likely_missing_targets": [
            value for value in target_probabilities.values()
            if value["probability"] < 0.50
        ],
        "best_available_alternatives": alternatives,
        "warnings": warnings,
        "roster_strength_distribution": [round(value, 2) for value in strength_values],
        "diagnostics": violations,
    }


def _nomination_order(
    snapshot: AuctionSnapshot,
    role_player_indices: dict[str, list[int]],
    nomination_bases: tuple[float, ...],
    rng: random.Random,
) -> list[int]:
    def score(player_index: int) -> float:
        return nomination_bases[player_index] * _clip(
            1 + 0.22 * NORMAL_Z_TABLE[int(rng.random() * 512)], 0.40, 1.70
        )

    if snapshot.auction_mode == "per_ruolo":
        current_role = snapshot.current_role if snapshot.current_role in ROLE_INDEX else "P"
        roles = ROLE_ORDER[ROLE_INDEX[current_role]:]
        return [
            player_index
            for role in roles
            for player_index in sorted(role_player_indices[role], key=score, reverse=True)
        ]
    return sorted(
        range(len(snapshot.available_players)), key=score, reverse=True
    )


def _roster_strength(
    snapshot: AuctionSnapshot, user_index: int, acquired_indices: list[int]
) -> float:
    by_role: dict[str, list[float]] = {role: [] for role in ROLE_ORDER}
    for owned in snapshot.participants[user_index].roster_players:
        by_role[owned.role].append(owned.utility)
    for player_index in acquired_indices:
        player = snapshot.available_players[player_index]
        by_role[player.role].append(player.utility)
    for values in by_role.values():
        values.sort(reverse=True)

    candidates = []
    for formation in FORMATIONS:
        if snapshot.modifier_enabled and formation["D"] < 4:
            continue
        if any(len(by_role[role]) < count for role, count in formation.items()):
            continue
        weighted_sum = 0.0
        total_weight = 0.0
        for role in ROLE_ORDER:
            starters = formation[role]
            bench_weight = 0.25 if role == "P" else 0.40
            for index, utility in enumerate(by_role[role]):
                weight = 1.0 if index < starters else bench_weight
                weighted_sum += utility * weight
                total_weight += weight
        candidates.append(weighted_sum / max(total_weight, 1.0))
    if candidates:
        return max(candidates)

    weighted_sum = 0.0
    total_weight = 0.0
    fallback_starters = {"P": 1, "D": 4 if snapshot.modifier_enabled else 3, "C": 3, "A": 3}
    for role in ROLE_ORDER:
        for index, utility in enumerate(by_role[role]):
            weight = 1.0 if index < fallback_starters[role] else (0.25 if role == "P" else 0.40)
            weighted_sum += utility * weight
            total_weight += weight
    return weighted_sum / max(total_weight, 1.0)


def _market_price(player: PlayerState, total_budget: int) -> float:
    if player.updated_price > 0:
        return player.updated_price
    if player.initial_price > 0:
        return player.initial_price
    return max(player.quotation * total_budget / 500, 1.0)


def _is_high_potential(player: PlayerState) -> bool:
    return (player.potential or 0) >= 75 or str(player.personal_tier or "").casefold() == "scommesse"


def _warnings(
    completion_values: list[bool],
    fragile_roles: list[dict[str, Any]],
    target_probabilities: dict[str, dict[str, Any]],
) -> list[str]:
    warnings = []
    completion = sum(completion_values) / max(len(completion_values), 1)
    if completion < 0.80:
        warnings.append(
            f"Probabilita di completare la rosa limitata al {completion:.0%}."
        )
    if fragile_roles and fragile_roles[0]["completion_probability"] < 0.90:
        warnings.append(
            f"Il reparto {fragile_roles[0]['role']} e il piu fragile: "
            f"completamento {fragile_roles[0]['completion_probability']:.0%}."
        )
    missing = [
        value["name"] for value in target_probabilities.values()
        if value["probability"] < 0.50
    ]
    if missing:
        warnings.append("Obiettivi a rischio: " + ", ".join(missing[:3]) + ".")
    return warnings


def _percentile_pairs(rows: list[tuple[str, float]]) -> list[tuple[str, float]]:
    if not rows:
        return []
    ordered = sorted(rows, key=lambda item: item[1])
    if len(ordered) == 1:
        return [(ordered[0][0], 50.0)]
    return [
        (player_id, 100 * index / (len(ordered) - 1))
        for index, (player_id, _value) in enumerate(ordered)
    ]


def _percentile_value(value: float | None, population: list[float]) -> float:
    if value is None or not population:
        return 50.0
    below_or_equal = sum(item <= value for item in population)
    return 100 * below_or_equal / len(population)


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _percent(value: Any) -> float:
    parsed = _number(value)
    if 0 < parsed <= 1:
        parsed *= 100
    return _clip(parsed, 0, 100)


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _clip(value: float, lower: float, upper: float) -> float:
    return min(max(float(value), lower), upper)
