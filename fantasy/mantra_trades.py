"""Balanced Mantra trade candidates with exact positional coverage checks."""
from __future__ import annotations

from functools import lru_cache
from itertools import combinations

from fantasy.mantra import best_lineup, eligible, formation_slots, mantra_roles, roster_limits, solve_lineup


def _number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _quality(player):
    return max(_number(player.get("expected_fantasy_average")) * 10
               + _number(player.get("starter_probability")) * .15
               + _number(player.get("reliability")) * .1, 1)


def _value(player):
    return _quality(player) + _number(player.get("mantra_fvm")) * .15


def mantra_trade_analysis(league, catalog, *, limit=10):
    by_id = {str(p.get("id")): p for p in catalog}

    def enrich(roster):
        return [{**by_id.get(str(p.get("player_id")), {}), **p} for p in roster]

    own = enrich(league.get("purchases", []))
    excluded = set(league.get("auction_trade_excluded_player_ids", []))
    pool = [p for p in own if p.get("player_id") not in excluded and mantra_roles(p)]
    rivals = [(m, enrich(m.get("purchases", []))) for m in league.get("auction_managers", []) if not m.get("is_user") and m.get("purchases")]
    result = {"ready": bool(own and rivals), "trades": [], "evaluated_opponents": len(rivals),
              "evaluated_players": len(own) + sum(len(r) for _, r in rivals),
              "excluded_players": len(own) - len(pool), "fallback": False,
              "reason": "Registra le rose degli avversari per valutare scambi Mantra."}
    if not result["ready"]:
        return result
    _, maximum = roster_limits(league)
    own_ids = frozenset(str(p["player_id"]) for p in own)
    universe = {str(p["player_id"]): p for p in own}
    for _, roster in rivals:
        universe.update({str(p["player_id"]): p for p in roster})
    own_module = league.get("preferred_formation") or best_lineup(own)["formation"]

    @lru_cache(maxsize=2048)
    def utility(ids, module):
        roster = [universe[pid] for pid in ids]
        selected = solve_lineup(roster, module, _quality)
        count = len(selected)
        return count, sum(_quality(p) for p in selected) + .12 * sum(_quality(p) for p in roster)

    def legal(ids):
        return len(ids) <= maximum

    def profile(roster, module):
        slots = formation_slots(module)
        available = [sum(eligible(p, slot) for p in roster) for slot in slots]
        return slots, available

    def player_utility(player, profile_data):
        slots, available = profile_data
        return _quality(player) * (1 + max((.6 / max(n, 1) for slot, n in zip(slots, available, strict=True) if eligible(player, slot)), default=0))

    def packages(roster, size):
        # Bounded search: prioritize surplus/lower-value players, preserve stars.
        candidates = sorted(roster, key=_value)[:16]
        return [(combo, sum(_value(p) for p in combo)) for combo in combinations(candidates, size)]

    own_before = utility(tuple(sorted(own_ids)), own_module)
    own_profile = profile(own, own_module)
    proposals = []
    for manager, rival in rivals:
        rival_ids = frozenset(str(p["player_id"]) for p in rival)
        module = best_lineup(rival)["formation"]
        rival_before = utility(tuple(sorted(rival_ids)), module)
        rival_profile = profile(rival, module)
        # Compute positional weights once per player, not for every pair of
        # 3-player packages (up to 560 x 560 combinations per opponent).
        weights = {
            str(p["player_id"]): (player_utility(p, own_profile), player_utility(p, rival_profile))
            for p in [*pool, *rival]
        }

        def weighted_packages(roster, size):
            return [(combo, value,
                     sum(weights[str(p["player_id"])][0] for p in combo),
                     sum(weights[str(p["player_id"])][1] for p in combo))
                    for combo, value in packages(roster, size)]

        screened = []
        for size in (1, 2, 3):
            candidates = []
            incoming_packages = weighted_packages([p for p in rival if mantra_roles(p)], size)
            for outgoing, out_value, out_own, out_rival in weighted_packages(pool, size):
                for incoming, in_value, in_own, in_rival in incoming_packages:
                    gap = abs(out_value - in_value) / max(out_value, in_value, 1)
                    if gap > {1: .15, 2: .18, 3: .20}[size]:
                        continue
                    gain = in_own - out_own
                    rival_gain = out_rival - in_rival
                    if gain < 0 or rival_gain < 0:
                        continue
                    candidates.append((min(gain, rival_gain) + .1 * gain, outgoing, incoming, gap))
            candidates.sort(key=lambda c: c[0], reverse=True)
            screened.extend(candidates[:12])
        for _, outgoing, incoming, gap in screened:
            out_ids = {str(p["player_id"]) for p in outgoing}
            in_ids = {str(p["player_id"]) for p in incoming}
            after_ids = (own_ids - out_ids) | in_ids
            rival_after_ids = (rival_ids - in_ids) | out_ids
            if not legal(after_ids) or not legal(rival_after_ids):
                continue
            after = utility(tuple(sorted(after_ids)), own_module)
            rival_after = utility(tuple(sorted(rival_after_ids)), module)
            if after[0] < own_before[0] or rival_after[0] < rival_before[0]:
                continue
            gain = 100 * (after[1] - own_before[1]) / max(own_before[1], 1)
            rival_gain = 100 * (rival_after[1] - rival_before[1]) / max(rival_before[1], 1)
            if min(gain, rival_gain) < -1e-6 or max(gain, rival_gain) > 15 or abs(gain - rival_gain) > 5:
                continue
            deltas = {key: sum(_number(p.get(field)) for p in incoming) - sum(_number(p.get(field)) for p in outgoing)
                      for key, field in {"goals": "expected_goals", "assists": "expected_assists", "fantasy_average": "expected_fantasy_average"}.items()}
            proposals.append({"outgoing": list(outgoing), "incoming": list(incoming),
                              "opponent_name": manager.get("name"), "opponent_id": manager.get("id"),
                              "user_improvement": round(gain, 1), "opponent_improvement": round(rival_gain, 1),
                              "gain_gap": round(abs(gain - rival_gain), 1), "value_gap": round(gap * 100, 1),
                              "fairness": round(100 * (1 - gap), 1), "deltas": deltas,
                              "meets_threshold": gain >= 4 and rival_gain >= 1.5,
                              "motivation": f"Ruoli multipli valutati sul {own_module} e sul {module} dell'avversario; nessuna perdita di copertura senza malus. Il beneficio misura l'undici piu una quota della profondita della rosa, non una probabilita di vittoria.",
                              "_rank": min(gain, rival_gain) + .25 * gain - gap})
    proposals.sort(key=lambda p: (p["meets_threshold"], p["_rank"]), reverse=True)
    seen = set()
    for proposal in proposals:
        key = (proposal["opponent_id"], tuple(sorted(str(p["player_id"]) for p in proposal["outgoing"])), tuple(sorted(str(p["player_id"]) for p in proposal["incoming"])))
        if key not in seen:
            seen.add(key)
            result["trades"].append(proposal)
        if len(result["trades"]) >= max(limit, 1):
            break
    result["fallback"] = bool(result["trades"] and not result["trades"][0]["meets_threshold"])
    result["reason"] = "Migliori proposte Mantra sotto soglia, senza peggiorare la copertura tattica." if result["fallback"] else "Nessuno scambio Mantra equilibrato con copertura compatibile trovato."
    return result
