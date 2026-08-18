from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from itertools import combinations
from typing import Any
from uuid import uuid4


DEFAULT_ROSTER_SLOTS = {"P": 3, "D": 7, "C": 7, "A": 5}
GAME_MODE_AUCTION = "auction"
GAME_MODE_LIST = "list"
GAME_MODES = {GAME_MODE_AUCTION, GAME_MODE_LIST}
ROLE_LABELS = {
    "P": "Portieri",
    "D": "Difensori",
    "C": "Centrocampisti",
    "A": "Attaccanti",
}
AUCTION_TIER_COLORS = {"red", "orange", "yellow", "green", "blue", "purple", "gray"}
FORMATIONS = {
    "4-3-3": {"P": 1, "D": 4, "C": 3, "A": 3},
    "4-4-2": {"P": 1, "D": 4, "C": 4, "A": 2},
    "3-4-3": {"P": 1, "D": 3, "C": 4, "A": 3},
    "3-5-2": {"P": 1, "D": 3, "C": 5, "A": 2},
    "5-3-2": {"P": 1, "D": 5, "C": 3, "A": 2},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_workspace() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": utc_now(),
        "active_league_id": None,
        "catalog": [],
        "catalog_meta": {},
        "leagues": [],
    }


def normalize_workspace(payload: dict[str, Any] | None) -> dict[str, Any]:
    workspace = deepcopy(payload) if isinstance(payload, dict) else new_workspace()
    workspace.setdefault("version", 1)
    workspace.setdefault("updated_at", utc_now())
    workspace.setdefault("active_league_id", None)
    workspace.setdefault("catalog", [])
    workspace.setdefault("catalog_meta", {})
    workspace.setdefault("leagues", [])
    if not isinstance(workspace["catalog"], list):
        workspace["catalog"] = []
    if not isinstance(workspace["catalog_meta"], dict):
        workspace["catalog_meta"] = {}
    if not isinstance(workspace["leagues"], list):
        workspace["leagues"] = []
    for league in workspace["leagues"]:
        _normalize_league(league)
    league_ids = [league.get("id") for league in workspace["leagues"]]
    if workspace.get("active_league_id") not in league_ids:
        workspace["active_league_id"] = league_ids[0] if league_ids else None
    return workspace


def create_league(
    workspace: dict[str, Any],
    name: str,
    initial_budget: int = 250,
    participants: int | None = 10,
    season: str = "2026/27",
    roster_slots: dict[str, int] | None = None,
    modifier_enabled: bool = True,
    captain_enabled: bool = False,
    game_mode: str = GAME_MODE_AUCTION,
) -> dict[str, Any]:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Inserisci un nome per il fanta.")
    if initial_budget <= 0:
        raise ValueError("Il budget deve essere maggiore di zero.")
    if game_mode not in GAME_MODES:
        raise ValueError("Modalita di gioco non riconosciuta.")
    if game_mode == GAME_MODE_AUCTION and (participants is None or participants < 2):
        raise ValueError("Servono almeno due partecipanti.")
    now = utc_now()
    slots = {role: int((roster_slots or DEFAULT_ROSTER_SLOTS).get(role, 0)) for role in ROLE_LABELS}
    if any(value < 0 for value in slots.values()) or sum(slots.values()) == 0:
        raise ValueError("La composizione della rosa non e valida.")
    league = {
        "id": uuid4().hex,
        "name": clean_name,
        "season": season.strip() or "2026/27",
        "game_mode": game_mode,
        "initial_budget": int(initial_budget),
        "participants": int(participants) if game_mode == GAME_MODE_AUCTION else None,
        "roster_slots": slots,
        "modifier_enabled": bool(modifier_enabled),
        "captain_enabled": bool(captain_enabled),
        "captain_player_id": None,
        "purchases": [],
        "auction_managers": _new_auction_managers(int(participants or 0))
        if game_mode == GAME_MODE_AUCTION else [],
        "auction_tiers": [],
        "auction_player_tiers": {},
        "watchlist": [],
        "analysis": "",
        "preferred_xi": [],
        "preferred_xi_customized": False,
        "preferred_formation": None,
        "sasa_analysis": "",
        "sasa_analysis_version": 0,
        "created_at": now,
        "updated_at": now,
    }
    workspace.setdefault("leagues", []).append(league)
    workspace["active_league_id"] = league["id"]
    touch_workspace(workspace)
    return league


def update_league_settings(
    league: dict[str, Any],
    *,
    name: str,
    initial_budget: int,
    participants: int | None,
    game_mode: str,
    modifier_enabled: bool,
    captain_enabled: bool,
    roster_slots: dict[str, int],
) -> None:
    clean_name = name.strip()
    spent = sum(_number(row.get("price")) for row in league.get("purchases", []))
    if not clean_name:
        raise ValueError("Inserisci un nome per il fanta.")
    if initial_budget < spent:
        raise ValueError(f"Il budget non puo essere inferiore ai {spent:.0f} crediti gia spesi.")
    opponent_spent = max(
        (
            sum(_number(row.get("price")) for row in manager.get("purchases", []))
            for manager in league.get("auction_managers", [])
            if not manager.get("is_user")
        ),
        default=0.0,
    )
    if game_mode == GAME_MODE_AUCTION and initial_budget < opponent_spent:
        raise ValueError(
            f"Il budget non puo essere inferiore ai {opponent_spent:.0f} crediti "
            "gia spesi da un avversario."
        )
    if game_mode not in GAME_MODES:
        raise ValueError("Modalita di gioco non riconosciuta.")
    if game_mode == GAME_MODE_AUCTION and (participants is None or participants < 2):
        raise ValueError("Servono almeno due partecipanti.")
    if game_mode == GAME_MODE_AUCTION:
        current_managers = league.get("auction_managers", [])
        if int(participants or 0) < len(current_managers):
            removed = current_managers[int(participants or 0):]
            if any(manager.get("purchases") for manager in removed):
                raise ValueError(
                    "Non puoi ridurre i partecipanti: una delle squadre da rimuovere ha gia acquisti."
                )
    if game_mode == GAME_MODE_LIST:
        list_spent = sum(
            _number(row.get("quote")) if row.get("quote") is not None else _number(row.get("price"))
            for row in league.get("purchases", [])
        )
        if initial_budget < list_spent:
            raise ValueError(
                f"Con i costi del listone servono almeno {list_spent:.0f} crediti di budget."
            )
    slots = {role: int(roster_slots.get(role, 0)) for role in ROLE_LABELS}
    if any(value < 0 for value in slots.values()) or sum(slots.values()) == 0:
        raise ValueError("La composizione della rosa non e valida.")
    current_counts = roster_summary(league)["role_counts"]
    for role, count in current_counts.items():
        if slots[role] < count:
            raise ValueError(
                f"Non puoi impostare meno di {count} slot per {ROLE_LABELS[role].lower()}: "
                "hai gia quei giocatori in rosa."
            )
    league.update(
        {
            "name": clean_name,
            "game_mode": game_mode,
            "initial_budget": int(initial_budget),
            "participants": int(participants) if game_mode == GAME_MODE_AUCTION else None,
            "roster_slots": slots,
            "modifier_enabled": bool(modifier_enabled),
            "captain_enabled": bool(captain_enabled),
            "updated_at": utc_now(),
        }
    )
    if not captain_enabled:
        league["captain_player_id"] = None
    if game_mode == GAME_MODE_LIST:
        for purchase in league.get("purchases", []):
            if purchase.get("quote") is not None:
                purchase["price"] = _number(purchase.get("quote"))
        league["auction_managers"] = []
    else:
        _resize_auction_managers(league, int(participants or 0))
    _invalidate_sasa(league)


def delete_league(workspace: dict[str, Any], league_id: str) -> None:
    workspace["leagues"] = [league for league in workspace.get("leagues", []) if league.get("id") != league_id]
    if workspace.get("active_league_id") == league_id:
        workspace["active_league_id"] = workspace["leagues"][0]["id"] if workspace["leagues"] else None
    touch_workspace(workspace)


def find_league(workspace: dict[str, Any], league_id: str | None) -> dict[str, Any] | None:
    return next((league for league in workspace.get("leagues", []) if league.get("id") == league_id), None)


def auction_managers(league: dict[str, Any]) -> list[dict[str, Any]]:
    if league.get("game_mode") != GAME_MODE_AUCTION:
        return []
    _resize_auction_managers(league, int(league.get("participants") or 0))
    return league["auction_managers"]


def rename_auction_manager(league: dict[str, Any], manager_id: str, name: str) -> None:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Il nome del partecipante non puo essere vuoto.")
    managers = auction_managers(league)
    manager = next((row for row in managers if row.get("id") == manager_id), None)
    if not manager:
        raise ValueError("Partecipante non trovato.")
    if any(
        row.get("id") != manager_id
        and str(row.get("name", "")).strip().casefold() == clean_name.casefold()
        for row in managers
    ):
        raise ValueError("Esiste gia un partecipante con questo nome.")
    manager["name"] = clean_name
    league["updated_at"] = utc_now()


def create_auction_tier(league: dict[str, Any], name: str, color: str) -> dict[str, Any]:
    if league.get("game_mode") != GAME_MODE_AUCTION:
        raise ValueError("Le fasce personalizzate sono disponibili solo per l'asta.")
    clean_name = name.strip()
    clean_color = color.strip().lower()
    if not clean_name:
        raise ValueError("Inserisci un nome per la fascia.")
    if clean_color not in AUCTION_TIER_COLORS:
        raise ValueError("Colore della fascia non riconosciuto.")
    tiers = league.setdefault("auction_tiers", [])
    if any(str(tier.get("name", "")).strip().casefold() == clean_name.casefold() for tier in tiers):
        raise ValueError("Esiste gia una fascia con questo nome.")
    tier = {"id": uuid4().hex, "name": clean_name, "color": clean_color}
    tiers.append(tier)
    league["updated_at"] = utc_now()
    return tier


def delete_auction_tier(league: dict[str, Any], tier_id: str) -> None:
    clean_id = str(tier_id)
    league["auction_tiers"] = [
        tier for tier in league.get("auction_tiers", []) if str(tier.get("id")) != clean_id
    ]
    assignments = league.setdefault("auction_player_tiers", {})
    league["auction_player_tiers"] = {
        str(player_id): assigned_tier
        for player_id, assigned_tier in assignments.items()
        if str(assigned_tier) != clean_id
    }
    league["updated_at"] = utc_now()


def auction_player_tier(league: dict[str, Any], player_id: str) -> dict[str, Any] | None:
    tier_id = str(league.get("auction_player_tiers", {}).get(str(player_id)) or "")
    return next(
        (tier for tier in league.get("auction_tiers", []) if str(tier.get("id")) == tier_id),
        None,
    )


def auction_manager_summary(league: dict[str, Any], manager_id: str) -> dict[str, Any]:
    manager = next((row for row in auction_managers(league) if row.get("id") == manager_id), None)
    if not manager:
        raise ValueError("Partecipante non trovato.")
    purchases = league.get("purchases", []) if manager.get("is_user") else manager.get("purchases", [])
    draft = {
        "initial_budget": league.get("initial_budget", 0),
        "roster_slots": league.get("roster_slots", DEFAULT_ROSTER_SLOTS),
        "purchases": purchases,
    }
    summary = roster_summary(draft)
    return {**summary, "manager": manager, "purchases": purchases}


def auction_taken_player_ids(league: dict[str, Any]) -> set[str]:
    taken = {str(row.get("player_id")) for row in league.get("purchases", [])}
    for manager in auction_managers(league):
        if manager.get("is_user"):
            continue
        taken.update(str(row.get("player_id")) for row in manager.get("purchases", []))
    return taken


def record_auction_purchase(
    league: dict[str, Any], manager_id: str, player: dict[str, Any], price: float
) -> dict[str, Any]:
    if league.get("game_mode") != GAME_MODE_AUCTION:
        raise ValueError("Questa funzione e disponibile solo per l'asta.")
    manager = next((row for row in auction_managers(league) if row.get("id") == manager_id), None)
    if not manager:
        raise ValueError("Partecipante non trovato.")
    player_id = str(player.get("id") or "")
    if player_id in auction_taken_player_ids(league):
        raise ValueError("Questo giocatore e gia stato acquistato.")
    if manager.get("is_user"):
        purchase = add_purchase(league, player, price)
    else:
        draft = {
            "game_mode": GAME_MODE_AUCTION,
            "initial_budget": league.get("initial_budget", 0),
            "roster_slots": deepcopy(league.get("roster_slots", DEFAULT_ROSTER_SLOTS)),
            "purchases": deepcopy(manager.get("purchases", [])),
            "watchlist": [],
            "preferred_xi": [],
        }
        purchase = add_purchase(draft, player, price)
        manager["purchases"] = draft["purchases"]
        league["updated_at"] = utc_now()
        _invalidate_sasa(league)
    return purchase


def remove_auction_purchase(league: dict[str, Any], manager_id: str, player_id: str) -> None:
    manager = next((row for row in auction_managers(league) if row.get("id") == manager_id), None)
    if not manager:
        raise ValueError("Partecipante non trovato.")
    if manager.get("is_user"):
        remove_purchase(league, player_id)
    else:
        manager["purchases"] = [
            row for row in manager.get("purchases", []) if str(row.get("player_id")) != player_id
        ]
        league["updated_at"] = utc_now()
        _invalidate_sasa(league)


def auction_player_assignment(
    league: dict[str, Any], player_id: str
) -> dict[str, Any] | None:
    clean_id = str(player_id)
    for manager in auction_managers(league):
        purchases = (
            league.get("purchases", [])
            if manager.get("is_user") else manager.get("purchases", [])
        )
        purchase = next(
            (row for row in purchases if str(row.get("player_id")) == clean_id),
            None,
        )
        if purchase:
            return {
                "manager_id": str(manager.get("id")),
                "manager_name": str(manager.get("name") or ""),
                "is_user": bool(manager.get("is_user")),
                "purchase": purchase,
            }
    return None


def update_auction_assignments(
    league: dict[str, Any], changes: list[dict[str, Any]]
) -> None:
    """Apply auction owner/price edits atomically across one or more players."""
    if league.get("game_mode") != GAME_MODE_AUCTION:
        raise ValueError("Questa funzione e disponibile solo per l'asta.")
    if not changes:
        return
    draft = deepcopy(league)
    seen: set[str] = set()
    for change in changes:
        player = change.get("player")
        if not isinstance(player, dict):
            raise ValueError("Giocatore non valido.")
        player_id = str(player.get("id") or "")
        if not player_id or player_id in seen:
            raise ValueError("Ogni giocatore puo essere modificato una sola volta.")
        seen.add(player_id)
        manager_id = change.get("manager_id")
        clean_manager_id = str(manager_id) if manager_id else None
        price = _number(change.get("price"))
        if price < 0:
            raise ValueError("Il prezzo non puo essere negativo.")
        if bool(change.get("update_assignment", True)):
            _apply_auction_assignment(draft, player, clean_manager_id, price)
        if "tier_id" in change:
            _apply_auction_player_tier(draft, player_id, change.get("tier_id"))
    league.clear()
    league.update(draft)


def _apply_auction_assignment(
    league: dict[str, Any],
    player: dict[str, Any],
    manager_id: str | None,
    price: float,
) -> None:
    player_id = str(player.get("id") or "")
    current = auction_player_assignment(league, player_id)
    current_manager_id = str(current.get("manager_id")) if current else None
    if manager_id is None:
        if current_manager_id:
            remove_auction_purchase(league, current_manager_id, player_id)
        return

    managers = auction_managers(league)
    if not any(str(manager.get("id")) == manager_id for manager in managers):
        raise ValueError("Partecipante non trovato.")
    if current_manager_id == manager_id and current:
        purchase = current["purchase"]
        manager_summary = auction_manager_summary(league, manager_id)
        available = manager_summary["remaining_budget"] + _number(purchase.get("price"))
        if price > available + 0.001:
            raise ValueError(
                f"Crediti insufficienti per {current.get('manager_name')}: "
                f"massimo {available:.0f}."
            )
        purchase["price"] = price
        league["updated_at"] = utc_now()
        _invalidate_sasa(league)
        return

    if current_manager_id:
        remove_auction_purchase(league, current_manager_id, player_id)
    record_auction_purchase(league, manager_id, player, price)


def _apply_auction_player_tier(
    league: dict[str, Any], player_id: str, tier_id: Any
) -> None:
    clean_tier_id = str(tier_id) if tier_id else None
    if clean_tier_id and not any(
        str(tier.get("id")) == clean_tier_id for tier in league.get("auction_tiers", [])
    ):
        raise ValueError("Fascia personalizzata non trovata.")
    assignments = league.setdefault("auction_player_tiers", {})
    if clean_tier_id:
        assignments[str(player_id)] = clean_tier_id
    else:
        assignments.pop(str(player_id), None)
    league["updated_at"] = utc_now()


def auction_price_board(
    league: dict[str, Any], catalog: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Return initial, market-adjusted and opponent-credit-aware auction prices."""
    if league.get("game_mode") != GAME_MODE_AUCTION:
        return {}
    managers = auction_managers(league)
    budget = float(league.get("initial_budget", 0) or 0)
    baseline_by_id = {
        str(player.get("id")): _initial_auction_price(player, budget) for player in catalog
    }
    groups: dict[tuple[str, str], list[float]] = {}
    catalog_by_id = {str(player.get("id")): player for player in catalog}
    for manager in managers:
        purchases = league.get("purchases", []) if manager.get("is_user") else manager.get("purchases", [])
        for purchase in purchases:
            player_id = str(purchase.get("player_id"))
            comparable = catalog_by_id.get(player_id, purchase)
            baseline = baseline_by_id.get(player_id) or _initial_auction_price(comparable, budget)
            if baseline <= 0:
                continue
            group = _auction_comparable_group(comparable)
            ratio = max(0.35, min(_number(purchase.get("price")) / baseline, 2.25))
            groups.setdefault(group, []).append(ratio)

    user_manager = next((row for row in managers if row.get("is_user")), None)
    user_summary = (
        auction_manager_summary(league, str(user_manager.get("id"))) if user_manager else None
    )
    opponent_credits = [
        auction_manager_summary(league, str(manager.get("id")))["remaining_budget"]
        for manager in managers
        if not manager.get("is_user")
    ]
    highest_opponent_credit = max(opponent_credits, default=budget)
    remaining_slots = int(user_summary["remaining_slots"] if user_summary else 0)
    own_credit = float(user_summary["remaining_budget"] if user_summary else budget)
    affordable = max(own_credit - max(remaining_slots - 1, 0), 0)

    board: dict[str, dict[str, Any]] = {}
    for player in catalog:
        player_id = str(player.get("id"))
        initial = baseline_by_id[player_id]
        comparable_ratios = groups.get(_auction_comparable_group(player), [])
        market_factor = _robust_average(comparable_ratios) if comparable_ratios else 1.0
        updated = max(1.0, round(initial * market_factor)) if initial > 0 else 0.0
        strategic = min(updated, highest_opponent_credit + 1, affordable)
        board[player_id] = {
            "initial": initial,
            "updated": updated,
            "strategic": max(strategic, 0.0),
            "comparables": len(comparable_ratios),
            "group": _auction_comparable_group(player)[1],
            "highest_opponent_credit": highest_opponent_credit,
        }
    return board


def _new_auction_managers(count: int) -> list[dict[str, Any]]:
    if count <= 0:
        return []
    managers = [
        {"id": uuid4().hex, "name": "La mia squadra", "is_user": True, "purchases": []}
    ]
    managers.extend(
        {
            "id": uuid4().hex,
            "name": f"Avversario {index}",
            "is_user": False,
            "purchases": [],
        }
        for index in range(1, count)
    )
    return managers


def _resize_auction_managers(league: dict[str, Any], count: int) -> None:
    managers = league.setdefault("auction_managers", [])
    if count <= 0:
        league["auction_managers"] = []
        return
    if not managers:
        league["auction_managers"] = _new_auction_managers(count)
        return
    if not any(manager.get("is_user") for manager in managers):
        managers[0]["is_user"] = True
    if len(managers) > count:
        removable = [manager for manager in reversed(managers) if not manager.get("is_user")]
        while len(managers) > count and removable:
            manager = removable.pop(0)
            if manager.get("purchases"):
                raise ValueError(
                    "Non puoi ridurre i partecipanti: una delle squadre da rimuovere ha gia acquisti."
                )
            managers.remove(manager)
    while len(managers) < count:
        managers.append(
            {
                "id": uuid4().hex,
                "name": f"Avversario {len(managers)}",
                "is_user": False,
                "purchases": [],
            }
        )


def _initial_auction_price(player: dict[str, Any], budget: float) -> float:
    fvm = _optional_number(player.get("fvm"))
    if fvm is not None and fvm > 0:
        return max(1.0, round(fvm * budget / 1000))
    quote = _number(player.get("quote"))
    predicted = _number(player.get("predicted_quote"))
    score = max(player_score(player), 0)
    proxy = max(quote * 2.1, predicted * 1.8, score * 0.7)
    return max(1.0, round(proxy * budget / 500)) if proxy > 0 else 1.0


def _auction_comparable_group(player: dict[str, Any]) -> tuple[str, str]:
    role = str(player.get("role", "")).upper()
    return role, "intero reparto"


def _robust_average(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 1.0
    if len(ordered) >= 5:
        trim = max(1, len(ordered) // 10)
        ordered = ordered[trim:-trim]
    return sum(ordered) / len(ordered)


def add_purchase(league: dict[str, Any], player: dict[str, Any], price: float) -> dict[str, Any]:
    clean_price = (
        _number(player.get("quote"))
        if league.get("game_mode") == GAME_MODE_LIST
        else float(price)
    )
    if clean_price < 0:
        raise ValueError("Il prezzo non puo essere negativo.")
    player_id = str(player.get("id", "")).strip()
    if not player_id:
        raise ValueError("Giocatore non valido.")
    if any(row.get("player_id") == player_id for row in league.get("purchases", [])):
        raise ValueError("Questo giocatore e gia nella rosa.")
    if league.get("game_mode") == GAME_MODE_AUCTION and any(
        row.get("player_id") == player_id
        for manager in league.get("auction_managers", [])
        if not manager.get("is_user")
        for row in manager.get("purchases", [])
    ):
        raise ValueError("Questo giocatore e gia stato acquistato da un altro partecipante.")

    summary = roster_summary(league)
    if clean_price > summary["remaining_budget"]:
        raise ValueError("Crediti insufficienti.")
    role = str(player.get("role", "")).upper()
    if role not in ROLE_LABELS:
        raise ValueError("Ruolo non riconosciuto.")
    role_limit = int(league.get("roster_slots", DEFAULT_ROSTER_SLOTS).get(role, 0))
    if summary["role_counts"][role] >= role_limit:
        raise ValueError(f"Hai gia completato gli slot {ROLE_LABELS[role].lower()}.")

    purchase = {
        "player_id": player_id,
        "name": str(player.get("name", "")).strip(),
        "team": str(player.get("team", "")).strip(),
        "role": role,
        "price": clean_price,
        "quote": _optional_number(player.get("quote")),
        "fvm": _optional_number(player.get("fvm")),
        "predicted_quote": _optional_number(player.get("predicted_quote")),
        "expected_goals": _optional_number(player.get("expected_goals")),
        "expected_assists": _optional_number(player.get("expected_assists")),
        "expected_fantasy_average": _optional_number(player.get("expected_fantasy_average")),
        "starter_probability": _optional_number(player.get("starter_probability")),
        "fantasy_score": player_score(player),
        "reliability": _optional_number(player.get("reliability")),
        "risk": _optional_number(player.get("risk")),
        "tier": player.get("tier"),
        "profile": player.get("profile"),
        "acquired_at": utc_now(),
    }
    league.setdefault("purchases", []).append(purchase)
    league["watchlist"] = [item for item in league.get("watchlist", []) if item != player_id]
    league["analysis"] = ""
    _invalidate_sasa(league)
    league["updated_at"] = utc_now()
    return purchase


def add_purchases_batch(
    league: dict[str, Any],
    players: list[dict[str, Any]],
    prices: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Add a selection atomically, so an invalid player never leaves a partial roster."""
    if not players:
        raise ValueError("Seleziona almeno un giocatore.")
    draft = deepcopy(league)
    purchases = []
    for player in players:
        player_id = str(player.get("id", ""))
        price = (prices or {}).get(player_id, _number(player.get("quote")))
        purchases.append(add_purchase(draft, player, price))
    league.clear()
    league.update(draft)
    return purchases


def role_balance_recommendation(
    league: dict[str, Any],
    catalog: list[dict[str, Any]],
    role: str,
    *,
    limit: int = 5,
) -> dict[str, Any] | None:
    """Suggest complementary profiles once at least half of a role is filled."""
    role = str(role).upper()
    if role not in ROLE_LABELS:
        return None
    summary = roster_summary(league)
    target = int(league.get("roster_slots", DEFAULT_ROSTER_SLOTS).get(role, 0))
    owned = [row for row in league.get("purchases", []) if row.get("role") == role]
    trigger = (target + 1) // 2
    if target <= 0 or len(owned) < trigger or len(owned) >= target:
        return None

    purchased_ids = {str(row.get("player_id")) for row in league.get("purchases", [])}
    available = [
        player
        for player in catalog
        if str(player.get("role", "")).upper() == role
        and str(player.get("id")) not in purchased_ids
        and _number(player.get("quote")) <= summary["remaining_budget"]
    ]
    if not available:
        return {
            "role": role,
            "count": len(owned),
            "target": target,
            "focus": "availability",
            "title": "Nessun profilo disponibile",
            "reason": "Non risultano giocatori acquistabili con il budget rimasto.",
            "candidates": [],
        }

    starter_average = _average(owned, "starter_probability")
    goal_average = _average(owned, "expected_goals")
    assist_average = _average(owned, "expected_assists")
    reliability_average = _average(owned, "reliability")
    fantasy_average = _average(owned, "expected_fantasy_average")
    pool_goal_median = _median(_number(player.get("expected_goals")) for player in available)
    pool_assist_median = _median(_number(player.get("expected_assists")) for player in available)
    pool_fantasy_median = _median(
        _number(player.get("expected_fantasy_average")) for player in available
    )

    if role == "P":
        if starter_average < 72:
            focus = "starter"
            title = "Serve un portiere titolare"
            reason = "La porta non ha ancora una base abbastanza stabile: privilegia presenze e affidabilita."
        else:
            focus = "reliability"
            title = "Completa con affidabilita"
            reason = "Hai gia titolarita: aggiungi un portiere con fantamedia e affidabilita migliori."
    elif role == "D" and league.get("modifier_enabled") and reliability_average < 76:
        focus = "reliability"
        title = "Rinforza il modificatore"
        reason = "I difensori scelti non garantiscono ancora abbastanza affidabilita per il modificatore."
    else:
        goal_floor = {"D": 1.2, "C": 3.0, "A": 8.0}.get(role, 0.0)
        goal_benchmark = max(goal_floor, pool_goal_median * 0.8)
        if goal_average < goal_benchmark:
            focus = "goals"
            title = "Aggiungi gol alla rosa"
            prefix = "Hai costruito una buona base di titolari, ma" if starter_average >= 72 else "Al reparto"
            reason = f"{prefix} manca produzione offensiva: cerca giocatori con piu gol attesi."
        elif assist_average < pool_assist_median * 0.75:
            focus = "assists"
            title = "Serve creativita"
            reason = "Il reparto ha finalizzazione, ma pochi assist attesi: completa con un creatore di gioco."
        elif starter_average < 72:
            focus = "starter"
            title = "Metti in sicurezza la titolarita"
            reason = "Il potenziale e buono, ma servono giocatori con maggiore continuita di impiego."
        elif fantasy_average < pool_fantasy_median * 0.9:
            focus = "fantasy_average"
            title = "Alza la fantamedia"
            reason = "Il reparto e equilibrato: il prossimo acquisto deve aumentare la qualita media."
        else:
            focus = "value"
            title = "Cerca valore senza doppioni"
            reason = "La struttura e equilibrata: privilegia il miglior rapporto tra costo, bonus e titolarita."

    ranked = sorted(
        available,
        key=lambda player: _recommendation_score(player, focus),
        reverse=True,
    )[: max(int(limit), 1)]
    return {
        "role": role,
        "count": len(owned),
        "target": target,
        "focus": focus,
        "title": title,
        "reason": reason,
        "candidates": ranked,
    }


def list_trade_analysis(
    league: dict[str, Any],
    catalog: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> dict[str, Any]:
    """Find exact-cost 1x1 and 2x2 upgrades for a complete list-mode roster."""
    summary = roster_summary(league)
    result = {
        "ready": False,
        "reason": "",
        "evaluated_players": len(league.get("purchases", [])),
        "spent": summary["spent"],
        "budget": float(league.get("initial_budget", 0) or 0),
        "weakest": [],
        "trades": [],
    }
    if league.get("game_mode") != GAME_MODE_LIST:
        result["reason"] = "Lo Swap Lab e disponibile per i fantacalci a listone."
        return result
    if not summary["complete"]:
        result["reason"] = "Completa la rosa per attivare lo Swap Lab."
        return result
    if summary["spent"] > result["budget"] + 0.001:
        result["reason"] = "La rosa supera il budget configurato."
        return result

    owned = list(league.get("purchases", []))
    owned_ids = {str(row.get("player_id")) for row in owned}
    available = [
        player
        for player in catalog
        if str(player.get("id")) not in owned_ids
        and str(player.get("role", "")).upper() in ROLE_LABELS
        and _number(player.get("quote")) >= 0
    ]
    result["weakest"] = sorted(owned, key=_roster_upgrade_score)[:3]

    outgoing_packages = [*(tuple([row]) for row in owned), *combinations(owned, 2)]
    outgoing_keys = {_trade_signature(package, outgoing=True) for package in outgoing_packages}
    incoming_by_key: dict[tuple[tuple[str, ...], int], list[tuple[float, tuple[dict[str, Any], ...]]]] = {}

    def remember(package: tuple[dict[str, Any], ...]) -> None:
        key = _trade_signature(package, outgoing=False)
        if key not in outgoing_keys:
            return
        bucket = incoming_by_key.setdefault(key, [])
        bucket.append((sum(_roster_upgrade_score(row) for row in package), package))
        bucket.sort(key=lambda item: item[0], reverse=True)
        del bucket[12:]

    for player in available:
        remember((player,))
    for package in combinations(available, 2):
        remember(package)

    proposals: list[dict[str, Any]] = []
    for outgoing in outgoing_packages:
        key = _trade_signature(outgoing, outgoing=True)
        candidates = incoming_by_key.get(key, [])
        if not candidates:
            continue
        outgoing_score = sum(_roster_upgrade_score(row) for row in outgoing)
        incoming_score, incoming = candidates[0]
        improvement = incoming_score - outgoing_score
        if improvement <= 0.05:
            continue
        outgoing_total = sum(_number(row.get("price")) for row in outgoing)
        incoming_total = sum(_number(row.get("quote")) for row in incoming)
        projected_spent = summary["spent"] - outgoing_total + incoming_total
        if abs(outgoing_total - incoming_total) > 0.001 or projected_spent > result["budget"] + 0.001:
            continue
        deltas = {
            "goals": _package_delta(outgoing, incoming, "expected_goals"),
            "assists": _package_delta(outgoing, incoming, "expected_assists"),
            "fantasy_average": _package_delta(
                outgoing, incoming, "expected_fantasy_average"
            ),
            "starter": _package_delta(outgoing, incoming, "starter_probability"),
        }
        proposals.append(
            {
                "outgoing": list(outgoing),
                "incoming": list(incoming),
                "outgoing_total": outgoing_total,
                "incoming_total": incoming_total,
                "projected_spent": projected_spent,
                "improvement": improvement,
                "deltas": deltas,
                "motivation": _trade_motivation(outgoing_total, deltas),
            }
        )

    proposals.sort(
        key=lambda item: (
            item["improvement"],
            item["deltas"]["fantasy_average"],
            item["deltas"]["goals"],
        ),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    seen_incoming: set[tuple[str, ...]] = set()
    for proposal in proposals:
        incoming_ids = tuple(sorted(str(row.get("id")) for row in proposal["incoming"]))
        if incoming_ids in seen_incoming:
            continue
        seen_incoming.add(incoming_ids)
        selected.append(proposal)
        if len(selected) >= max(int(limit), 1):
            break
    result["ready"] = True
    result["trades"] = selected
    if not selected:
        result["reason"] = "Non ho trovato cambi a costo identico che migliorino la rosa."
    return result


def _trade_signature(
    package: tuple[dict[str, Any], ...], *, outgoing: bool
) -> tuple[tuple[str, ...], int]:
    roles = tuple(sorted(str(row.get("role", "")).upper() for row in package))
    cost_field = "price" if outgoing else "quote"
    total_cents = int(round(sum(_number(row.get(cost_field)) for row in package) * 100))
    return roles, total_cents


def _roster_upgrade_score(player: dict[str, Any]) -> float:
    starter = _number(player.get("starter_probability"))
    if starter <= 1:
        starter *= 100
    return (
        _number(player.get("expected_fantasy_average")) * 13
        + _number(player.get("expected_goals")) * 2.8
        + _number(player.get("expected_assists")) * 2.1
        + starter * 0.09
        + _number(player.get("reliability")) * 0.05
        - _number(player.get("risk")) * 0.05
        + player_score(player) * 0.12
    )


def _package_delta(
    outgoing: tuple[dict[str, Any], ...],
    incoming: tuple[dict[str, Any], ...],
    field: str,
) -> float:
    return sum(_number(row.get(field)) for row in incoming) - sum(
        _number(row.get(field)) for row in outgoing
    )


def _trade_motivation(cost: float, deltas: dict[str, float]) -> str:
    gains = []
    labels = (
        ("fantasy_average", "somma FM attesa"),
        ("goals", "gol attesi"),
        ("assists", "assist attesi"),
        ("starter", "titolarita complessiva"),
    )
    for field, label in labels:
        value = deltas[field]
        if value > 0.05:
            suffix = " punti" if field == "starter" else ""
            gains.append(f"+{value:.1f} {label}{suffix}")
    improvement = ", ".join(gains[:3]) or "un profilo complessivamente piu forte"
    return (
        f"A parita di {cost:.0f} crediti ottieni {improvement}, "
        "senza cambiare gli slot di ruolo ne superare il budget."
    )


def _recommendation_score(player: dict[str, Any], focus: str) -> float:
    goals = _number(player.get("expected_goals"))
    assists = _number(player.get("expected_assists"))
    starter = _number(player.get("starter_probability"))
    reliability = _number(player.get("reliability"))
    fantasy_average = _number(player.get("expected_fantasy_average"))
    fantasy_score = _number(player.get("fantasy_score"))
    value = _number(player.get("value"))
    risk = _number(player.get("risk"))
    quote = _number(player.get("quote"))
    weights = {
        "goals": goals * 12 + assists * 2.5,
        "assists": assists * 11 + goals * 3,
        "starter": starter * 0.55 + reliability * 0.2,
        "reliability": reliability * 0.45 + starter * 0.25 - risk * 0.12,
        "fantasy_average": fantasy_average * 12 + fantasy_score * 0.45,
        "value": value * 0.35 + fantasy_score * 0.5 - quote * 0.08,
    }
    return (
        weights.get(focus, 0.0)
        + fantasy_average * 4
        + starter * 0.08
        + reliability * 0.05
        - risk * 0.04
    )


def _average(players: list[dict[str, Any]], field: str) -> float:
    return sum(_number(player.get(field)) for player in players) / max(len(players), 1)


def _median(values) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def remove_purchase(league: dict[str, Any], player_id: str) -> None:
    league["purchases"] = [row for row in league.get("purchases", []) if row.get("player_id") != player_id]
    league["analysis"] = ""
    _invalidate_sasa(league)
    league["preferred_xi"] = [
        item for item in league.get("preferred_xi", []) if item != player_id
    ]
    if league.get("captain_player_id") == player_id:
        league["captain_player_id"] = None
    league["updated_at"] = utc_now()


def selected_top_xi(league: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the saved XI, or the most expensive valid formation by default."""
    purchases = league.get("purchases", [])
    by_id = {str(row.get("player_id")): row for row in purchases}
    if league.get("preferred_xi_customized"):
        selected_ids = [
            str(player_id)
            for player_id in league.get("preferred_xi", [])
            if str(player_id) in by_id
        ][:11]
        return [by_id[player_id] for player_id in selected_ids]
    formation = top_xi_formation(league)
    formation_players = top_xi_for_formation(league, formation)
    if len(formation_players) == 11:
        return formation_players
    return sorted(
        purchases,
        key=lambda row: (
            _number(row.get("price")),
            _number(row.get("fantasy_score")),
            str(row.get("name", "")),
        ),
        reverse=True,
    )[:11]


def top_xi_formation(league: dict[str, Any]) -> str:
    preferred = str(league.get("preferred_formation") or "")
    if preferred in FORMATIONS:
        return preferred
    candidates = [
        (
            sum(_number(row.get("price")) for row in top_xi_for_formation(league, formation)),
            formation,
        )
        for formation in FORMATIONS
        if len(top_xi_for_formation(league, formation)) == 11
    ]
    return max(candidates, default=(0.0, "4-3-3"))[1]


def top_xi_for_formation(league: dict[str, Any], formation: str) -> list[dict[str, Any]]:
    required = FORMATIONS.get(formation)
    if not required:
        return []
    players: list[dict[str, Any]] = []
    for role in ("A", "C", "D", "P"):
        role_players = sorted(
            (row for row in league.get("purchases", []) if row.get("role") == role),
            key=lambda row: (
                _number(row.get("price")),
                _number(row.get("fantasy_score")),
                str(row.get("name", "")),
            ),
            reverse=True,
        )
        players.extend(role_players[: int(required.get(role, 0))])
    return players


def set_preferred_xi(
    league: dict[str, Any],
    player_ids: list[str],
    *,
    formation: str | None = None,
) -> None:
    clean_ids = list(dict.fromkeys(str(player_id) for player_id in player_ids))
    if len(clean_ids) != 11:
        raise ValueError("Seleziona esattamente 11 giocatori per la Top 11.")
    purchased_ids = {str(row.get("player_id")) for row in league.get("purchases", [])}
    if any(player_id not in purchased_ids for player_id in clean_ids):
        raise ValueError("La Top 11 puo contenere solo giocatori della tua rosa.")
    if formation is not None:
        required = FORMATIONS.get(formation)
        if not required:
            raise ValueError("Modulo non riconosciuto.")
        by_id = {str(row.get("player_id")): row for row in league.get("purchases", [])}
        role_counts = {role: 0 for role in ROLE_LABELS}
        for player_id in clean_ids:
            role = str(by_id[player_id].get("role", ""))
            if role in role_counts:
                role_counts[role] += 1
        if any(role_counts[role] != int(required.get(role, 0)) for role in ROLE_LABELS):
            raise ValueError(f"I giocatori scelti non rispettano il modulo {formation}.")
        league["preferred_formation"] = formation
    league["preferred_xi"] = clean_ids
    league["preferred_xi_customized"] = True
    _invalidate_sasa(league)
    league["updated_at"] = utc_now()


def reset_preferred_xi(league: dict[str, Any], *, formation: str | None = None) -> None:
    if formation is not None:
        if formation not in FORMATIONS:
            raise ValueError("Modulo non riconosciuto.")
        league["preferred_formation"] = formation
    league["preferred_xi"] = []
    league["preferred_xi_customized"] = False
    _invalidate_sasa(league)
    league["updated_at"] = utc_now()


def top_xi_summary(league: dict[str, Any]) -> dict[str, Any]:
    players = selected_top_xi(league)
    return {
        "players": players,
        "player_ids": [str(row.get("player_id")) for row in players],
        "count": len(players),
        "formation": top_xi_formation(league),
        "expected_goals_total": _known_sum(players, "expected_goals"),
        "expected_assists_total": _known_sum(players, "expected_assists"),
        "expected_fantasy_average_sum": _known_sum(players, "expected_fantasy_average"),
        "expected_goals_average": _known_average(players, "expected_goals"),
        "expected_assists_average": _known_average(players, "expected_assists"),
        "expected_fantasy_average": _known_average(players, "expected_fantasy_average"),
        "cost": sum(_number(row.get("price")) for row in players),
    }


def set_captain(league: dict[str, Any], player_id: str | None) -> None:
    if not league.get("captain_enabled"):
        raise ValueError("La regola del capitano non e attiva.")
    if player_id is None:
        league["captain_player_id"] = None
    elif not any(row.get("player_id") == player_id for row in league.get("purchases", [])):
        raise ValueError("Il capitano deve essere un giocatore della tua rosa.")
    else:
        league["captain_player_id"] = player_id
    league["analysis"] = ""
    _invalidate_sasa(league)
    league["updated_at"] = utc_now()


def toggle_watchlist(league: dict[str, Any], player_id: str) -> bool:
    watchlist = league.setdefault("watchlist", [])
    if player_id in watchlist:
        watchlist.remove(player_id)
        enabled = False
    else:
        watchlist.append(player_id)
        enabled = True
    league["updated_at"] = utc_now()
    return enabled


def roster_summary(league: dict[str, Any]) -> dict[str, Any]:
    purchases = league.get("purchases", [])
    slots = league.get("roster_slots", DEFAULT_ROSTER_SLOTS)
    role_counts = {role: 0 for role in ROLE_LABELS}
    for row in purchases:
        role = str(row.get("role", "")).upper()
        if role in role_counts:
            role_counts[role] += 1
    missing = {role: max(int(slots.get(role, 0)) - role_counts[role], 0) for role in ROLE_LABELS}
    spent = sum(_number(row.get("price")) for row in purchases)
    initial_budget = float(league.get("initial_budget", 0) or 0)
    remaining_slots = sum(missing.values())
    remaining_budget = max(initial_budget - spent, 0.0)
    return {
        "spent": spent,
        "remaining_budget": remaining_budget,
        "remaining_slots": remaining_slots,
        "credits_per_slot": remaining_budget / remaining_slots if remaining_slots else remaining_budget,
        "role_counts": role_counts,
        "missing": missing,
        "roster_size": len(purchases),
        "target_size": sum(int(value) for value in slots.values()),
        "complete": remaining_slots == 0,
        "expected_goals": sum(_number(row.get("expected_goals")) for row in purchases),
        "expected_assists": sum(_number(row.get("expected_assists")) for row in purchases),
        "modifier_ready": role_counts["P"] >= 1 and role_counts["D"] >= 4,
    }


def suggest_lineup(league: dict[str, Any]) -> dict[str, Any] | None:
    purchases = league.get("purchases", [])
    by_role = {
        role: sorted(
            (row for row in purchases if row.get("role") == role),
            key=lambda row: (_number(row.get("fantasy_score")), _number(row.get("quote"))),
            reverse=True,
        )
        for role in ROLE_LABELS
    }
    candidates: list[dict[str, Any]] = []
    for formation, required in FORMATIONS.items():
        if league.get("modifier_enabled") and required["D"] < 4:
            continue
        if any(len(by_role[role]) < count for role, count in required.items()):
            continue
        players = {role: by_role[role][:count] for role, count in required.items()}
        score = sum(_number(row.get("fantasy_score")) for rows in players.values() for row in rows)
        candidates.append({"formation": formation, "players": players, "score": score})
    return max(candidates, key=lambda item: item["score"], default=None)


def player_score(player: dict[str, Any]) -> float:
    explicit_score = _optional_number(player.get("fantasy_score"))
    if explicit_score is not None and explicit_score > 0:
        return explicit_score
    quote = _number(player.get("predicted_quote")) or _number(player.get("quote"))
    goals = _number(player.get("expected_goals"))
    assists = _number(player.get("expected_assists"))
    starter = _number(player.get("starter_probability"))
    if starter <= 1:
        starter *= 100
    return round(quote * 0.7 + goals * 5.5 + assists * 3.2 + starter * 0.08, 2)


def touch_workspace(workspace: dict[str, Any]) -> None:
    workspace["updated_at"] = utc_now()


def _normalize_league(league: dict[str, Any]) -> None:
    league.setdefault("season", "2026/27")
    league.setdefault("initial_budget", 250)
    league.setdefault("game_mode", GAME_MODE_AUCTION)
    if league.get("game_mode") not in GAME_MODES:
        league["game_mode"] = GAME_MODE_AUCTION
    league.setdefault("participants", 10 if league["game_mode"] == GAME_MODE_AUCTION else None)
    if league["game_mode"] == GAME_MODE_LIST:
        league["participants"] = None
    league.setdefault("roster_slots", deepcopy(DEFAULT_ROSTER_SLOTS))
    league.setdefault("modifier_enabled", True)
    league.setdefault("captain_enabled", False)
    league.setdefault("captain_player_id", None)
    league.setdefault("purchases", [])
    league.setdefault("auction_managers", [])
    if league["game_mode"] == GAME_MODE_AUCTION:
        _resize_auction_managers(league, int(league.get("participants") or 0))
        for manager in league["auction_managers"]:
            manager.setdefault("id", uuid4().hex)
            manager.setdefault("name", "Partecipante")
            manager.setdefault("is_user", False)
            manager.setdefault("purchases", [])
    else:
        league["auction_managers"] = []
    league.setdefault("auction_tiers", [])
    league.setdefault("auction_player_tiers", {})
    if not isinstance(league["auction_tiers"], list):
        league["auction_tiers"] = []
    if not isinstance(league["auction_player_tiers"], dict):
        league["auction_player_tiers"] = {}
    valid_tier_ids = set()
    for tier in league["auction_tiers"]:
        tier.setdefault("id", uuid4().hex)
        tier.setdefault("name", "Fascia")
        if str(tier.get("color", "")).lower() not in AUCTION_TIER_COLORS:
            tier["color"] = "gray"
        valid_tier_ids.add(str(tier["id"]))
    league["auction_player_tiers"] = {
        str(player_id): str(tier_id)
        for player_id, tier_id in league["auction_player_tiers"].items()
        if str(tier_id) in valid_tier_ids
    }
    league.setdefault("watchlist", [])
    league.setdefault("analysis", "")
    league.setdefault("preferred_xi", [])
    league.setdefault("preferred_xi_customized", False)
    league.setdefault("preferred_formation", None)
    league.setdefault("sasa_analysis", "")
    league.setdefault("sasa_analysis_version", 0)
    league.setdefault("updated_at", utc_now())


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _known_average(players: list[dict[str, Any]], field: str) -> float | None:
    values = [
        number
        for player in players
        if (number := _optional_number(player.get(field))) is not None
    ]
    return sum(values) / len(values) if values else None


def _known_sum(players: list[dict[str, Any]], field: str) -> float | None:
    values = [
        number
        for player in players
        if (number := _optional_number(player.get(field))) is not None
    ]
    return sum(values) if values else None


def _invalidate_sasa(league: dict[str, Any]) -> None:
    league["sasa_analysis"] = ""
    league["sasa_analysis_version"] = 0
