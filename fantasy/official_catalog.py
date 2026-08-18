from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import io
from pathlib import Path
import re
import unicodedata
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

from fantasy.catalog import make_player_id, normalize_catalog_dataframe, normalize_role
from fantasy.service import player_score


OFFICIAL_CATALOG_URL = "https://www.fantacalcio.it/quotazioni-fantacalcio"
SEED_CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "fantacalcio_seed_2026_27.csv"
MINIMUM_VALID_PLAYERS = 400


@lru_cache(maxsize=1)
def load_seed_catalog() -> list[dict]:
    dataframe = pd.read_csv(SEED_CATALOG_PATH)
    players: list[dict] = []
    for raw in dataframe.to_dict(orient="records"):
        role = normalize_role(raw.get("role"))
        name = _text(raw.get("name"))
        team = _text(raw.get("team"))
        if not name or not role:
            continue
        player = {
            key: _clean_value(value)
            for key, value in raw.items()
        }
        player.update(
            {
                "id": make_player_id(name, team, role),
                "name": name,
                "team": team,
                "role": role,
                "source": "Analisi Fantacalcio 2026/27",
            }
        )
        starter = _number(player.get("starter_probability"))
        player["starter_probability"] = starter * 100 if 0 < starter <= 1 else starter
        player["fantasy_score"] = _number(player.get("fantasy_score")) or player_score(player)
        players.append(player)
    return players


def fetch_official_catalog(timeout: int = 18) -> dict:
    checked_at = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        ),
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
    }
    try:
        response = session.get(OFFICIAL_CATALOG_URL, headers=headers, timeout=timeout)
        response.raise_for_status()
        html = response.text
        players = _download_excel_catalog(session, html, headers, timeout)
        method = "Excel ufficiale"
        if not _valid_role_distribution(players):
            players = parse_official_html(html, load_seed_catalog())
            method = "Pagina ufficiale"
        if not _valid_role_distribution(players):
            counts = _role_counts(players)
            raise ValueError(f"Listone incompleto o ruoli non validi: {counts}")
        return {
            "players": players,
            "checked_at": checked_at,
            "source": "Fantacalcio.it",
            "source_url": OFFICIAL_CATALOG_URL,
            "remote_ok": True,
            "message": f"{method} aggiornato correttamente",
        }
    except Exception as error:
        return {
            "players": [],
            "checked_at": checked_at,
            "source": "Fantacalcio.it",
            "source_url": OFFICIAL_CATALOG_URL,
            "remote_ok": False,
            "message": f"Fonte non raggiungibile: {error}",
        }


def parse_official_html(html: str, seed_players: list[dict] | None = None) -> list[dict]:
    seed_players = seed_players or load_seed_catalog()
    seed_by_name = _players_by_name(seed_players)
    known_teams = {str(player.get("team", "")).upper() for player in seed_players}
    soup = BeautifulSoup(html, "html.parser")
    tables = [
        table for table in soup.find_all("table")
        if "fvm" in table.get_text(" ", strip=True).lower()
    ]
    players: list[dict] = []
    seen: set[str] = set()
    for table in tables:
        for row in table.find_all("tr"):
            anchor = row.find("a", href=re.compile(r"/serie-a/squadre/", re.I))
            if not anchor:
                continue
            name = anchor.get_text(" ", strip=True)
            cells = row.find_all("td")
            texts = [cell.get_text(" ", strip=True) for cell in cells]
            team_index = next(
                (index for index, value in enumerate(texts) if value.upper() in known_teams),
                None,
            )
            if team_index is None:
                anchor_index = next(
                    (index for index, cell in enumerate(cells) if cell.find("a", href=re.compile(r"/serie-a/squadre/", re.I))),
                    None,
                )
                if anchor_index is not None:
                    team_index = next(
                        (
                            index
                            for index in range(anchor_index + 1, len(texts))
                            if texts[index]
                            and _number_from_text(texts[index]) is None
                            and texts[index].upper() not in {"P", "D", "C", "A"}
                        ),
                        None,
                    )
            if team_index is None:
                continue
            team = texts[team_index].upper()
            numbers = [_number_from_text(value) for value in texts[team_index + 1 :]]
            numbers = [value for value in numbers if value is not None]
            if len(numbers) < 3:
                continue
            seed_match = _unique_seed_match(seed_by_name, name)
            role = str(seed_match.get("role")) if seed_match else _detect_role(row)
            if role not in {"P", "D", "C", "A"}:
                continue
            player_id = str(seed_match.get("id")) if seed_match else make_player_id(name, team, role)
            if player_id in seen:
                continue
            seen.add(player_id)
            players.append(
                {
                    "id": player_id,
                    "name": name,
                    "team": team,
                    "role": role,
                    "initial_quote": numbers[0],
                    "quote": numbers[1],
                    "fvm": numbers[-1],
                    "source": "Fantacalcio.it",
                }
            )
    return players


def merge_catalog_updates(
    current_players: list[dict] | None,
    official_players: list[dict] | None,
    *,
    authoritative: bool = False,
) -> list[dict]:
    base = [deepcopy(player) for player in load_seed_catalog()]
    base = _merge_preserving_analysis(base, current_players or [])
    if authoritative and official_players:
        base = _authoritative_official_catalog(base, official_players)
    else:
        base = _merge_official(base, official_players or [])
    for player in base:
        player["fantasy_score"] = player_score(player)
    return sorted(
        base,
        key=lambda player: (
            "PDCA".find(str(player.get("role", ""))),
            -_number(player.get("quote")),
            str(player.get("name", "")),
        ),
    )


def catalog_fingerprint(players: list[dict]) -> tuple:
    return tuple(
        sorted(
            (
                str(player.get("id", "")),
                str(player.get("team", "")),
                str(player.get("role", "")),
                _number(player.get("quote")),
                _number(player.get("fvm")),
            )
            for player in players
        )
    )


def _download_excel_catalog(
    session: requests.Session,
    html: str,
    headers: dict[str, str],
    timeout: int,
) -> list[dict]:
    match = re.search(r"(?:https?://[^\"']+)?/api/v1/Excel/prices/\d+/\d+", html, re.I)
    if not match:
        return []
    download_url = urljoin(OFFICIAL_CATALOG_URL, match.group(0))
    response = session.get(
        download_url,
        headers={**headers, "Referer": OFFICIAL_CATALOG_URL, "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*"},
        timeout=timeout,
    )
    if response.status_code >= 400 or not response.content.startswith(b"PK"):
        return []
    dataframe = pd.read_excel(io.BytesIO(response.content))
    return normalize_catalog_dataframe(dataframe)


def _merge_preserving_analysis(base: list[dict], current: list[dict]) -> list[dict]:
    by_id = {str(player.get("id")): player for player in base if player.get("id")}
    by_name = _players_by_name(base)
    for player in current:
        target = by_id.get(str(player.get("id")))
        if target is None:
            target = _unique_seed_match(by_name, str(player.get("name", "")))
        if target is None:
            copied = deepcopy(player)
            base.append(copied)
            by_id[str(copied.get("id"))] = copied
            by_name.setdefault(_normalize_name(copied.get("name")), []).append(copied)
        else:
            stable_id = target.get("id")
            stable_role = target.get("role")
            target.update(deepcopy(player))
            target["id"] = stable_id
            target["role"] = stable_role
    return base


def _merge_official(base: list[dict], official: list[dict]) -> list[dict]:
    by_id = {str(player.get("id")): player for player in base if player.get("id")}
    by_name = _players_by_name(base)
    for update in official:
        target = by_id.get(str(update.get("id")))
        if target is None:
            target = _unique_seed_match(by_name, str(update.get("name", "")))
        if target is None:
            copied = deepcopy(update)
            copied.setdefault(
                "id",
                make_player_id(
                    str(copied.get("name", "")),
                    str(copied.get("team", "")),
                    str(copied.get("role", "")),
                ),
            )
            base.append(copied)
            by_id[str(copied.get("id"))] = copied
            by_name.setdefault(_normalize_name(copied.get("name")), []).append(copied)
            continue
        for field in ("name", "team", "initial_quote", "quote", "fvm", "source"):
            if update.get(field) not in (None, ""):
                target[field] = update[field]
    return base


def _authoritative_official_catalog(analysis: list[dict], official: list[dict]) -> list[dict]:
    by_id = {str(player.get("id")): player for player in analysis if player.get("id")}
    by_name = _players_by_name(analysis)
    result: list[dict] = []
    seen: set[str] = set()
    for update in official:
        enriched = by_id.get(str(update.get("id")))
        if enriched is None:
            enriched = _unique_seed_match(by_name, str(update.get("name", "")))
        stable_id = str(enriched.get("id")) if enriched else ""
        stable_role = str(enriched.get("role")) if enriched else ""
        player = deepcopy(enriched) if enriched else {}
        player.update(deepcopy(update))
        if stable_id:
            player["id"] = stable_id
        if stable_role:
            player["role"] = stable_role
        player.setdefault(
            "id",
            make_player_id(
                str(player.get("name", "")),
                str(player.get("team", "")),
                str(player.get("role", "")),
            ),
        )
        player_id = str(player.get("id"))
        if player_id and player_id not in seen:
            seen.add(player_id)
            result.append(player)
    return result


def _detect_role(row) -> str:
    for cell in row.find_all(["td", "th"]):
        exact = cell.get_text(" ", strip=True).upper()
        if exact in {"P", "D", "C", "A"}:
            return exact

    tokens: list[str] = []
    for tag in row.find_all(True):
        for value in tag.attrs.values():
            if isinstance(value, list):
                tokens.extend(str(item) for item in value)
            else:
                tokens.append(str(value))
        tokens.append(str(tag.get("title", "")))
        tokens.append(str(tag.get("alt", "")))
    raw = " ".join(tokens).lower()
    for role, word in {
        "P": "portiere",
        "D": "difensore",
        "C": "centrocampista",
        "A": "attaccante",
    }.items():
        if re.search(rf"\b{word}\b", raw):
            return role
    explicit = re.search(r"(?:role|ruolo|position)[-_](p|d|c|a)(?:$|[_\s-])", raw)
    if explicit:
        return explicit.group(1).upper()
    return ""


def _role_counts(players: list[dict]) -> dict[str, int]:
    return {
        role: sum(str(player.get("role", "")).upper() == role for player in players)
        for role in ("P", "D", "C", "A")
    }


def _valid_role_distribution(players: list[dict]) -> bool:
    if len(players) < MINIMUM_VALID_PLAYERS:
        return False
    counts = _role_counts(players)
    return counts["P"] >= 20 and counts["D"] >= 80 and counts["C"] >= 80 and counts["A"] >= 40


def _players_by_name(players: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for player in players:
        result.setdefault(_normalize_name(player.get("name")), []).append(player)
    return result


def _unique_seed_match(by_name: dict[str, list[dict]], name: str) -> dict | None:
    matches = by_name.get(_normalize_name(name), [])
    return matches[0] if len(matches) == 1 else None


def _normalize_name(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _number_from_text(value: str) -> float | None:
    match = re.fullmatch(r"\s*(-?\d+(?:[.,]\d+)?)\s*", value)
    return float(match.group(1).replace(",", ".")) if match else None


def _clean_value(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()
