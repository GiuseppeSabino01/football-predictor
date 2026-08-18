from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from fantasy.service import player_score


CATALOG_COLUMNS = [
    "name",
    "team",
    "role",
    "quote",
    "predicted_quote",
    "goals_previous",
    "xg_previous",
    "expected_goals",
    "assists_previous",
    "expected_assists",
    "starter_probability",
]

COLUMN_ALIASES = {
    "name": {"nome", "calciatore", "giocatore", "player", "nome giocatore"},
    "surname": {"cognome", "surname"},
    "team": {"squadra", "team", "club"},
    "role": {"r", "ruolo", "role", "ruolo classic", "ruolo classico"},
    "quote": {"qt a", "qa", "quotazione", "quotazione attuale", "costo", "price"},
    "predicted_quote": {"quotazione prevista", "quotazione prevista fine anno", "qt prevista", "fvm", "fvm classic"},
    "goals_previous": {"gol 25 26", "gol 2025 26", "gol scorso anno", "gol stagione precedente"},
    "xg_previous": {"xg 25 26", "xg 2025 26", "xg scorso anno"},
    "expected_goals": {"gol attesi", "gol attesi 26 27", "gol previsti", "expected goals"},
    "assists_previous": {"assist 25 26", "assist 2025 26", "assist scorso anno"},
    "expected_assists": {"assist attesi", "assist attesi 26 27", "assist previsti", "expected assists"},
    "starter_probability": {"titolarita", "titolarita prevista", "probabilita titolare", "starter probability"},
}


def read_catalog_file(file: BinaryIO, filename: str) -> list[dict[str, Any]]:
    suffix = Path(filename).suffix.lower()
    raw = file.read()
    if suffix == ".csv":
        dataframe = _read_csv(raw)
    elif suffix == ".xlsx":
        dataframe = pd.read_excel(io.BytesIO(raw))
    else:
        raise ValueError("Formato non supportato. Carica un file CSV o XLSX.")
    return normalize_catalog_dataframe(dataframe)


def normalize_catalog_dataframe(dataframe: pd.DataFrame) -> list[dict[str, Any]]:
    if dataframe.empty:
        raise ValueError("Il file non contiene giocatori.")
    mapped = _mapped_columns(dataframe.columns)
    name_column = mapped.get("name") or mapped.get("surname")
    if not name_column or not mapped.get("role"):
        raise ValueError("Non riconosco le colonne del nome e del ruolo.")

    players: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, raw_row in dataframe.iterrows():
        name = _text(raw_row.get(name_column))
        surname_column = mapped.get("surname")
        if surname_column and surname_column != name_column:
            surname = _text(raw_row.get(surname_column))
            if surname and surname.lower() not in name.lower():
                name = f"{name} {surname}".strip()
        role = normalize_role(raw_row.get(mapped["role"]))
        team = _text(raw_row.get(mapped.get("team")))
        if not name or not role:
            continue
        player_id = make_player_id(name, team, role)
        if player_id in seen:
            continue
        seen.add(player_id)
        player: dict[str, Any] = {"id": player_id, "name": name, "team": team, "role": role}
        for field in CATALOG_COLUMNS[3:]:
            source_column = mapped.get(field)
            player[field] = _optional_number(raw_row.get(source_column)) if source_column else None
        player["fantasy_score"] = player_score(player)
        players.append(player)
    if not players:
        raise ValueError("Non ho trovato righe valide nel file.")
    return players


def make_player(
    *,
    name: str,
    team: str,
    role: str,
    quote: float = 0,
    predicted_quote: float = 0,
    expected_goals: float = 0,
    expected_assists: float = 0,
    starter_probability: float = 0,
) -> dict[str, Any]:
    clean_name = name.strip()
    clean_role = normalize_role(role)
    if not clean_name or not clean_role:
        raise ValueError("Nome e ruolo sono obbligatori.")
    player = {
        "id": make_player_id(clean_name, team, clean_role),
        "name": clean_name,
        "team": team.strip(),
        "role": clean_role,
        "quote": float(quote),
        "predicted_quote": float(predicted_quote),
        "goals_previous": None,
        "xg_previous": None,
        "expected_goals": float(expected_goals),
        "assists_previous": None,
        "expected_assists": float(expected_assists),
        "starter_probability": float(starter_probability),
    }
    player["fantasy_score"] = player_score(player)
    return player


def merge_catalog(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {str(player.get("id")): dict(player) for player in existing if player.get("id")}
    for player in incoming:
        player_id = str(player.get("id", ""))
        if not player_id:
            continue
        previous = merged.get(player_id, {})
        merged[player_id] = {**previous, **player}
    return sorted(merged.values(), key=lambda player: (str(player.get("role", "")), str(player.get("name", ""))))


def catalog_dataframe(players: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for player in players:
        rows.append(
            {
                "Giocatore": player.get("name", ""),
                "Squadra": player.get("team", ""),
                "Ruolo": player.get("role", ""),
                "Quotazione": player.get("quote"),
                "Quotazione prevista": player.get("predicted_quote"),
                "Gol 25/26": player.get("goals_previous"),
                "xG 25/26": player.get("xg_previous"),
                "Gol attesi": player.get("expected_goals"),
                "Assist 25/26": player.get("assists_previous"),
                "Assist attesi": player.get("expected_assists"),
                "Titolarita %": player.get("starter_probability"),
                "Indice": player.get("fantasy_score"),
                "_id": player.get("id", ""),
            }
        )
    return pd.DataFrame(rows)


def normalize_role(value: Any) -> str:
    raw = _normalize(value)
    if raw in {"p", "por", "portiere", "portieri"}:
        return "P"
    if raw in {"d", "dc", "dd", "ds", "difensore", "difensori"} or raw.startswith("d "):
        return "D"
    if raw in {"c", "m", "e", "w", "t", "centrocampista", "centrocampisti"}:
        return "C"
    if raw in {"a", "pc", "attaccante", "attaccanti", "punta"}:
        return "A"
    first = raw[:1].upper()
    return first if first in {"P", "D", "C", "A"} else ""


def make_player_id(name: str, team: str, role: str) -> str:
    raw = "|".join((_normalize(name), _normalize(team), role.upper()))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _mapped_columns(columns: Any) -> dict[str, str]:
    normalized = {str(column): _normalize(column) for column in columns}
    mapped: dict[str, str] = {}
    for target, aliases in COLUMN_ALIASES.items():
        alias_values = {_normalize(alias) for alias in aliases}
        exact = next((column for column, value in normalized.items() if value in alias_values), None)
        if exact:
            mapped[target] = exact
    return mapped


def _read_csv(raw: bytes) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(raw), sep=None, engine="python", encoding=encoding)
        except (UnicodeDecodeError, pd.errors.ParserError) as error:
            last_error = error
    raise ValueError(f"CSV non leggibile: {last_error}")


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _optional_number(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str):
        value = value.strip().replace("%", "").replace(",", ".")
        if not value or value == "-":
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
