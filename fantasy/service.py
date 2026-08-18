from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
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
        "watchlist": [],
        "analysis": "",
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
    if game_mode not in GAME_MODES:
        raise ValueError("Modalita di gioco non riconosciuta.")
    if game_mode == GAME_MODE_AUCTION and (participants is None or participants < 2):
        raise ValueError("Servono almeno due partecipanti.")
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


def delete_league(workspace: dict[str, Any], league_id: str) -> None:
    workspace["leagues"] = [league for league in workspace.get("leagues", []) if league.get("id") != league_id]
    if workspace.get("active_league_id") == league_id:
        workspace["active_league_id"] = workspace["leagues"][0]["id"] if workspace["leagues"] else None
    touch_workspace(workspace)


def find_league(workspace: dict[str, Any], league_id: str | None) -> dict[str, Any] | None:
    return next((league for league in workspace.get("leagues", []) if league.get("id") == league_id), None)


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
    league["updated_at"] = utc_now()
    return purchase


def remove_purchase(league: dict[str, Any], player_id: str) -> None:
    league["purchases"] = [row for row in league.get("purchases", []) if row.get("player_id") != player_id]
    league["analysis"] = ""
    if league.get("captain_player_id") == player_id:
        league["captain_player_id"] = None
    league["updated_at"] = utc_now()


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
    league.setdefault("watchlist", [])
    league.setdefault("analysis", "")
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
