"""Mantra auction rules and exact, no-malus lineup assignment.

Positions follow the official Fantacalcio 2026/27 module grid. Classic roles
remain untouched in stored records; unknown Mantra roles are never guessed.
"""
from __future__ import annotations

import re
from typing import Any, Callable

CLASSIC = "classic"
MANTRA = "mantra"
MANTRA_ROLES = ("Por", "Dc", "B", "Dd", "Ds", "E", "M", "C", "T", "W", "A", "Pc")
# Rows run from goalkeeper to attack. A slash means alternative eligible roles.
MANTRA_FORMATIONS = {
    "3-4-3": (("Por",), ("Dc", "Dc", "Dc/B"), ("E", "M/C", "C", "E"), ("W/A", "A/Pc", "W/A")),
    "3-4-1-2": (("Por",), ("Dc", "Dc", "Dc/B"), ("E", "M/C", "C", "E"), ("T",), ("A/Pc", "A/Pc")),
    "3-4-2-1": (("Por",), ("Dc", "Dc", "Dc/B"), ("E/W", "M", "M/C", "E"), ("T", "T/A"), ("A/Pc",)),
    "3-5-2": (("Por",), ("Dc", "Dc", "Dc/B"), ("E/W", "M/C", "M", "C", "E"), ("A/Pc", "A/Pc")),
    "3-5-1-1": (("Por",), ("Dc", "Dc", "Dc/B"), ("E/W", "M", "C", "M", "E/W"), ("T/A",), ("A/Pc",)),
    "4-3-3": (("Por",), ("Dd", "Dc", "Dc", "Ds"), ("M/C", "M", "C"), ("W/A", "A/Pc", "W/A")),
    "4-3-1-2": (("Por",), ("Dd", "Dc", "Dc", "Ds"), ("M/C", "M", "C"), ("T",), ("T/A/Pc", "A/Pc")),
    "4-4-2": (("Por",), ("Dd", "Dc", "Dc", "Ds"), ("E/W", "M/C", "C", "E"), ("A/Pc", "A/Pc")),
    "4-1-4-1": (("Por",), ("Dd", "Dc", "Dc", "Ds"), ("M",), ("E/W", "C/T", "T", "W"), ("A/Pc",)),
    "4-4-1-1": (("Por",), ("Dd", "Dc", "Dc", "Ds"), ("E/W", "M", "C", "E/W"), ("T/A",), ("A/Pc",)),
    "4-2-3-1": (("Por",), ("Dd", "Dc", "Dc", "Ds"), ("M", "M/C"), ("W/T", "T", "W/A"), ("A/Pc",)),
}


def is_mantra(league: dict[str, Any]) -> bool:
    return league.get("game_mode") == "auction" and league.get("scoring_system") == MANTRA


def mantra_roles(value: Any) -> tuple[str, ...]:
    if isinstance(value, dict):
        value = value.get("mantra_role", "")
    if isinstance(value, (list, tuple)):
        value = "/".join(str(v) for v in value)
    canonical = {r.casefold(): r for r in MANTRA_ROLES}
    canonical["p"] = "Por"
    return tuple(dict.fromkeys(
        canonical[token.casefold()]
        for token in re.split(r"[/;,\s|]+", str(value or "").strip())
        if token.casefold() in canonical
    ))


def role_display(player: dict[str, Any], league: dict[str, Any]) -> str:
    if is_mantra(league):
        return "/".join(mantra_roles(player)) or "N/D"
    return str(player.get("role") or "")


def formation_slots(formation: str) -> tuple[str, ...]:
    return tuple(slot for row in MANTRA_FORMATIONS.get(formation, ()) for slot in row)


def eligible(player: dict[str, Any], slot: str) -> bool:
    return bool(set(mantra_roles(player)) & set(slot.split("/")))


def solve_lineup(
    players: list[dict[str, Any]],
    formation: str,
    score: Callable[[dict[str, Any]], float] | None = None,
) -> list[dict[str, Any]]:
    """Maximum-cardinality, then maximum-weight bipartite matching (11 slots).

    Each player is considered once, so multi-role eligibility cannot place a
    player twice. Missing positions are left empty, never filled out of role.
    """
    slots = formation_slots(formation)
    if not slots:
        return []
    score = score or (lambda p: float(p.get("fantasy_score") or 0))
    unique: dict[str, dict[str, Any]] = {}
    for player in players:
        key = str(player.get("player_id") or player.get("id") or "")
        if key:
            unique.setdefault(key, player)
    states: dict[int, tuple[float, tuple[tuple[int, dict[str, Any]], ...]]] = {0: (0.0, ())}
    for player in unique.values():
        possible = [i for i, slot in enumerate(slots) if eligible(player, slot)]
        if not possible:
            continue
        weight = float(score(player))
        updates = dict(states)
        for mask, (total, selected) in states.items():
            for index in possible:
                bit = 1 << index
                if mask & bit:
                    continue
                new_mask = mask | bit
                if new_mask not in updates or total + weight > updates[new_mask][0]:
                    updates[new_mask] = (total + weight, (*selected, (index, player)))
        states = updates
    best_mask = max(states, key=lambda mask: (mask.bit_count(), states[mask][0]))
    return [
        {**player, "lineup_slot": slots[index], "lineup_index": index}
        for index, player in sorted(states[best_mask][1], key=lambda item: item[0])
    ]


def best_lineup(players: list[dict[str, Any]], score=None) -> dict[str, Any]:
    options = [
        {"formation": formation, "players": solve_lineup(players, formation, score)}
        for formation in MANTRA_FORMATIONS
    ]
    score = score or (lambda p: float(p.get("fantasy_score") or 0))
    best = max(options, key=lambda option: (
        len(option["players"]), sum(score(p) for p in option["players"])
    ))
    return {**best, "complete": len(best["players"]) == 11,
            "score": sum(score(p) for p in best["players"])}


def roster_limits(league: dict[str, Any]) -> tuple[int, int]:
    """Total Mantra roster range, never quotas for individual roles.

    Old P/movement configurations migrate to the requested 22–30 range.
    """
    configured = league.get("mantra_roster_slots") or {}
    return int(configured.get("min", 22)), int(configured.get("max", 30))


def can_purchase(league: dict[str, Any], player: dict[str, Any]) -> bool:
    _, maximum = roster_limits(league)
    return len(league.get("purchases", [])) < maximum
