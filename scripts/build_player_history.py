from __future__ import annotations

import difflib
import gzip
import hashlib
import json
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fantasy.official_catalog import fetch_official_catalog, merge_catalog_updates

OUTPUT = ROOT / "data" / "player_history_5y_2026_27.json.gz"
CACHE_DIR = ROOT / ".history_cache"
HEADERS = {"User-Agent": "Mozilla/5.0 fantasy-decision-center/1.0"}
TEAM_IDS = {
    "MIL": 103,
    "ROM": 104,
    "ATA": 105,
    "BOL": 107,
    "CAG": 2925,
    "COM": 2572,
    "FIO": 109,
    "FRO": 4057,
    "GEN": 3263,
    "INT": 110,
    "JUV": 111,
    "LAZ": 112,
    "LEC": 113,
    "MON": 4007,
    "NAP": 114,
    "PAR": 115,
    "SAS": 3997,
    "TOR": 239,
    "UDI": 118,
    "VEN": 17530,
}
MANUAL_ESPN_IDS = {
    ("lolic", "FRO"): "333979",
    ("romero d", "PAR"): "301980",
    ("russo a", "SAS"): "276823",
}
MANUAL_HISTORY = {
    ("romero d", "PAR"): {
        "name": "Romero D.",
        "espn_name": "José David Romero",
        "age": 23,
        "source": "ESPN",
        "source_url": "https://www.espn.com/soccer/player/stats/_/id/301980",
        "seasons": [
            {
                "year": 2025,
                "season": "2025",
                "competition": "Argentine Liga Profesional",
                "team": "Tigre",
                "league": "arg.1",
                "league_matches": 38,
                "appearances": 21,
                "starts": 13,
                "goals": 5,
                "assists": 2,
                "yellow_cards": 1,
                "red_cards": 0,
            },
            {
                "year": 2024,
                "season": "2024",
                "competition": "Liga Profesional / Primera Division de Chile",
                "team": "Talleres / Union La Calera",
                "league": "arg.1 + chi.1",
                "league_matches": 38,
                "appearances": 11,
                "starts": 11,
                "goals": 7,
                "assists": 0,
                "yellow_cards": 1,
                "red_cards": 0,
            },
            {
                "year": 2023,
                "season": "2023",
                "competition": "Argentine Liga Profesional",
                "team": "Talleres",
                "league": "arg.1",
                "league_matches": 38,
                "appearances": 9,
                "starts": 0,
                "goals": 2,
                "assists": 1,
                "yellow_cards": 0,
                "red_cards": 0,
            },
            {
                "year": 2022,
                "season": "2022",
                "competition": "Argentine Liga Profesional",
                "team": "Talleres",
                "league": "arg.1",
                "league_matches": 38,
                "appearances": 3,
                "starts": 0,
                "goals": 1,
                "assists": 0,
                "yellow_cards": 0,
                "red_cards": 0,
            },
            {
                "year": 2021,
                "season": "2021",
                "competition": "Copa LPF",
                "team": "Talleres",
                "league": "arg.1",
                "league_matches": 38,
                "appearances": 7,
                "starts": 1,
                "goals": 1,
                "assists": 0,
                "yellow_cards": 0,
                "red_cards": 0,
            },
        ],
    },
    ("penev", "LEC"): {
        "name": "Penev",
        "espn_name": "Plamen Penev",
        "age": 18,
        "source": "BeSoccer",
        "source_url": "https://www.besoccer.com/player/plamen-penev-3367142",
        "seasons": [
            {
                "year": 2025,
                "season": "2025-26",
                "competition": "Primavera 1 e Coppa Italia Primavera",
                "team": "Lecce U20",
                "league": "ita.primavera.1",
                "league_matches": 41,
                "appearances": 41,
                "starts": 41,
                "goals": 0,
                "assists": 0,
                "yellow_cards": 1,
                "red_cards": 0,
                "goals_conceded": 58,
            },
            {
                "year": 2024,
                "season": "2024-25",
                "competition": "Under 18",
                "team": "Lecce U18",
                "league": "ita.u18",
                "league_matches": 34,
                "appearances": 12,
                "starts": 12,
                "goals": 0,
                "assists": 0,
                "yellow_cards": 0,
                "red_cards": 0,
                "goals_conceded": 22,
            },
        ],
    },
    ("laerke", "LEC"): {
        "name": "Laerke",
        "espn_name": "Hjalte Laerke",
        "age": 19,
        "source": "US Lecce / CalcioLecce",
        "source_url": "https://www.calciolecce.it/2026/06/11/la-grande-annata-con-la-primavera-del-lecce-vale-a-laerke-leuropeo-under-19/",
        "seasons": [
            {
                "year": 2025,
                "season": "2025-26",
                "competition": "Primavera 1",
                "team": "Lecce Primavera",
                "league": "ita.primavera.1",
                "league_matches": 36,
                "appearances": 36,
                "starts": 29,
                "goals": 4,
                "assists": 11,
                "yellow_cards": 1,
                "red_cards": 0,
            }
        ],
    },
    ("cinquegrano", "SAS"): {
        "name": "Cinquegrano",
        "espn_name": "Simone Cinquegrano",
        "age": 22,
        "source": "BeSoccer",
        "source_url": "https://www.besoccer.com/player/simone-cinquegrano-3194731",
        "seasons": [
            {
                "year": 2025,
                "season": "2025-26",
                "competition": "Serie C",
                "team": "Inter U23",
                "league": "ita.3",
                "league_matches": 38,
                "appearances": 37,
                "starts": 34,
                "goals": 2,
                "assists": 2,
                "yellow_cards": 8,
                "red_cards": 0,
            },
            {
                "year": 2024,
                "season": "2024-25",
                "competition": "Serie C",
                "team": "Rimini",
                "league": "ita.3",
                "league_matches": 38,
                "appearances": 38,
                "starts": 28,
                "goals": 3,
                "assists": 2,
                "yellow_cards": 3,
                "red_cards": 0,
            },
            {
                "year": 2023,
                "season": "2023-24",
                "competition": "Primavera 1",
                "team": "Sassuolo U20",
                "league": "ita.primavera.1",
                "league_matches": 34,
                "appearances": 32,
                "starts": 28,
                "goals": 4,
                "assists": 1,
                "yellow_cards": 4,
                "red_cards": 0,
            },
            {
                "year": 2022,
                "season": "2022-23",
                "competition": "Primavera 1",
                "team": "Sassuolo U20",
                "league": "ita.primavera.1",
                "league_matches": 34,
                "appearances": 22,
                "starts": 6,
                "goals": 0,
                "assists": 1,
                "yellow_cards": 2,
                "red_cards": 0,
            },
        ],
    },
    ("lontani", "PAR"): {
        "name": "Lontani",
        "espn_name": "Simone Lontani",
        "age": 18,
        "source": "Parma Calcio / BeSoccer",
        "source_url": "https://www.parmacalcio1913.com/news/simone-lontani-e-un-nuovo-giocatore-del-parma-calcio/",
        "seasons": [
            {
                "year": 2025,
                "season": "2025-26",
                "competition": "Primavera 1 e Serie D",
                "team": "Milan U20 / Milan Futuro",
                "league": "ita.primavera.1 + ita.4",
                "league_matches": 38,
                "appearances": 26,
                "starts": 21,
                "goals": 10,
                "assists": 3,
                "yellow_cards": 5,
                "red_cards": 1,
            },
            {
                "year": 2024,
                "season": "2024-25",
                "competition": "Under 17 / Primavera 1",
                "team": "Milan",
                "league": "ita.u17 + ita.primavera.1",
                "league_matches": 34,
                "appearances": 25,
                "starts": 22,
                "goals": 15,
                "assists": 0,
                "yellow_cards": 0,
                "red_cards": 0,
            },
        ],
    },
}


def main() -> None:
    official = fetch_official_catalog(timeout=30)
    if not official.get("remote_ok"):
        raise RuntimeError(str(official.get("message") or "Listone non disponibile"))
    players = merge_catalog_updates([], official["players"], authoritative=True)
    rosters = _current_rosters()
    identities = _match_identities(players, rosters)
    print(
        f"Matched {sum(bool(item.get('espn_id')) for item in identities.values())}/{len(players)} players"
    )

    career_pages = _parallel_map(
        {
            player_id: _stats_url(identity["espn_id"])
            for player_id, identity in identities.items()
            if identity.get("espn_id")
        },
        _fetch_json_payload,
        workers=24,
    )
    team_jobs: dict[str, str] = {}
    player_teams: dict[str, list[str]] = {}
    for player_id, payload in career_pages.items():
        team_ids = _team_filter_ids(payload)
        player_teams[player_id] = team_ids
        espn_id = identities[player_id]["espn_id"]
        for team_id in team_ids:
            job_id = f"{player_id}|{team_id}"
            team_jobs[job_id] = _stats_url(espn_id, team=team_id)
    print(f"Loading {len(team_jobs)} club histories")
    team_pages = _parallel_map(team_jobs, _fetch_json_payload, workers=32)

    extra_jobs: dict[str, str] = {}
    records_by_player: dict[str, list[dict[str, Any]]] = {
        player_id: [] for player_id in identities
    }
    for job_id, payload in team_pages.items():
        player_id, team_id = job_id.split("|", 1)
        records_by_player[player_id].extend(_history_rows(payload, team_id))
        selected, available = _league_filters(payload)
        espn_id = identities[player_id]["espn_id"]
        for league in available:
            if league != selected:
                extra_jobs[f"{player_id}|{team_id}|{league}"] = _stats_url(
                    espn_id, team=team_id, league=league
                )
    if extra_jobs:
        print(f"Loading {len(extra_jobs)} additional domestic-league histories")
        extra_pages = _parallel_map(extra_jobs, _fetch_json_payload, workers=32)
        for job_id, payload in extra_pages.items():
            player_id, team_id, _ = job_id.split("|", 2)
            records_by_player[player_id].extend(_history_rows(payload, team_id))

    roster_jobs: dict[str, str] = {}
    for player_id, rows in records_by_player.items():
        for row in rows:
            if row.get("appearances") is not None:
                continue
            league = str(row.get("league") or "")
            team_id = str(row.get("team_id") or "")
            year = int(row.get("year") or 0)
            if league and team_id and year:
                roster_jobs[f"{league}|{team_id}|{year}"] = (
                    "https://site.api.espn.com/apis/site/v2/sports/soccer/"
                    f"{league}/teams/{team_id}/roster?season={year}"
                )
    print(f"Loading {len(roster_jobs)} historical team rosters")
    roster_pages = _parallel_map(roster_jobs, _fetch_json, workers=32)

    output_players: dict[str, dict[str, Any]] = {}
    for player in players:
        player_id = str(player.get("id") or "")
        manual = MANUAL_HISTORY.get(
            (_normalize(player.get("name")), player.get("team"))
        )
        if manual:
            output_players[player_id] = manual
            continue
        identity = identities.get(player_id, {})
        espn_id = str(identity.get("espn_id") or "")
        if not espn_id:
            continue
        completed: list[dict[str, Any]] = []
        for row in records_by_player.get(player_id, []):
            roster_key = f"{row.get('league')}|{row.get('team_id')}|{row.get('year')}"
            roster = roster_pages.get(roster_key, {})
            stats = _roster_player_stats(roster, espn_id)
            if stats:
                row.update(stats)
            if row.get("appearances") is None:
                row["appearances"] = row.get("starts")
                row["appearance_source"] = "starts_only"
            completed.append(row)
        seasons = _aggregate_seasons(completed)
        if not seasons:
            continue
        output_players[player_id] = {
            "name": player.get("name"),
            "team": player.get("team"),
            "role": player.get("role"),
            "espn_id": espn_id,
            "espn_name": identity.get("espn_name"),
            "age": identity.get("age"),
            "source": "ESPN",
            "source_url": _stats_url(espn_id),
            "seasons": seasons,
        }

    payload = {
        "generated_at": datetime.now(UTC).date().isoformat(),
        "window": "2021-22 / 2025-26",
        "description": (
            "Presenze, titolarita e rendimento nelle ultime cinque stagioni "
            "complete disponibili. Nessun dato di infortunio corrente."
        ),
        "players": output_players,
    }
    with gzip.open(OUTPUT, "wt", encoding="utf-8", compresslevel=9) as target:
        json.dump(
            payload,
            target,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    print(f"Saved {len(output_players)}/{len(players)} histories to {OUTPUT}")


def _current_rosters() -> dict[str, list[dict[str, Any]]]:
    jobs = {
        code: (
            "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.1/"
            f"teams/{team_id}/roster"
        )
        for code, team_id in TEAM_IDS.items()
    }
    payloads = _parallel_map(jobs, _fetch_json, workers=20)
    return {
        code: payload.get("athletes", []) if isinstance(payload, dict) else []
        for code, payload in payloads.items()
    }


def _match_identities(
    players: list[dict[str, Any]], rosters: dict[str, list[dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    identities: dict[str, dict[str, Any]] = {}
    for player in players:
        player_id = str(player.get("id") or "")
        name = str(player.get("name") or "")
        team = str(player.get("team") or "")
        manual_id = MANUAL_ESPN_IDS.get((_normalize(name), team))
        candidates = [
            (_name_score(name, str(athlete.get("fullName") or "")), athlete)
            for athlete in rosters.get(team, [])
        ]
        score, athlete = max(candidates, default=(0.0, {}), key=lambda item: item[0])
        if manual_id:
            athlete = {"id": manual_id, "fullName": name}
            score = 1.0
        if score < 0.70:
            search = _search_player(name, team)
            if search:
                athlete = search
                score = _name_score(name, str(search.get("fullName") or ""))
        identities[player_id] = {
            "espn_id": str(athlete.get("id") or "") if score >= 0.58 else "",
            "espn_name": athlete.get("fullName"),
            "age": athlete.get("age"),
            "match_score": round(score, 3),
        }
    return identities


def _search_player(name: str, team: str) -> dict[str, Any] | None:
    try:
        payload = _fetch_json(
            "https://site.api.espn.com/apis/search/v2",
            params={"query": name, "limit": 10},
        )
    except RuntimeError:
        return None
    candidates: list[dict[str, Any]] = []
    for group in payload.get("results", []):
        if group.get("type") != "player":
            continue
        for item in group.get("contents", []):
            if item.get("sport") != "soccer":
                continue
            uid = str(item.get("uid") or "")
            match = re.search(r"~a:(\d+)", uid)
            if not match:
                continue
            candidates.append(
                {
                    "id": match.group(1),
                    "fullName": item.get("displayName"),
                    "age": None,
                    "team_hint": item.get("subtitle"),
                }
            )
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            _name_score(name, str(item.get("fullName") or ""))
            + (
                0.08
                if team.casefold() in str(item.get("team_hint") or "").casefold()
                else 0
            )
        ),
    )


def _fetch_json_payload(url: str) -> dict[str, Any]:
    html = _get(url).text
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        marker = "window['__espnfitt__']="
        if marker not in text:
            continue
        raw = text.split(marker, 1)[1].strip().rstrip(";")
        try:
            return json.loads(raw)
        except ValueError:
            continue
    return {}


def _fetch_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return _get(url, params=params).json()
    except ValueError:
        return {}


def _get(url: str, params: dict[str, Any] | None = None) -> requests.Response:
    cache_key = hashlib.sha256(
        (url + "?" + json.dumps(params or {}, sort_keys=True)).encode("utf-8")
    ).hexdigest()
    cache_path = CACHE_DIR / cache_key
    if cache_path.exists():
        response = requests.Response()
        response.status_code = 200
        response._content = cache_path.read_bytes()
        response.url = url
        response.encoding = "utf-8"
        return response
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=25)
            response.raise_for_status()
            CACHE_DIR.mkdir(exist_ok=True)
            cache_path.write_bytes(response.content)
            return response
        except requests.RequestException as error:
            last_error = error
            time.sleep(0.35 * (attempt + 1))
    raise RuntimeError(str(last_error or "Request failed"))


def _parallel_map(
    jobs: dict[str, str], function, *, workers: int
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    if not jobs:
        return results
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(function, url): key for key, url in jobs.items()}
        for done, future in enumerate(as_completed(futures), start=1):
            key = futures[future]
            try:
                results[key] = future.result()
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                results[key] = {}
                print(f"WARN {key}: {error}")
            if done % 100 == 0:
                print(f"  {done}/{len(jobs)}")
    return results


def _stats_url(espn_id: str, *, team: str = "", league: str = "") -> str:
    query = []
    if team:
        query.append(f"team={team}")
    if league:
        query.append(f"type={league}")
    suffix = "?" + "&".join(query) if query else ""
    return f"https://www.espn.com/soccer/player/stats/_/id/{espn_id}{suffix}"


def _player_stat(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("page", {}).get("content", {}).get("player", {}).get("stat", {})


def _team_filter_ids(payload: dict[str, Any]) -> list[str]:
    for item in _player_stat(payload).get("ftr", []):
        if item.get("fld") == "team":
            return [str(option.get("id")) for option in item.get("itm", [])]
    return []


def _league_filters(payload: dict[str, Any]) -> tuple[str, list[str]]:
    for item in _player_stat(payload).get("ftr", []):
        if item.get("fld") == "type":
            available = [
                str(option.get("id"))
                for option in item.get("itm", [])
                if _is_domestic_league(str(option.get("id") or ""))
            ]
            return str(item.get("val") or ""), available
    return "", []


def _is_domestic_league(value: str) -> bool:
    lowered = value.casefold()
    if any(term in lowered for term in ("cup", "copa", "super", "uefa", "fifa")):
        return False
    return bool(re.search(r"(?:^|\.)[123]$", lowered))


def _history_rows(payload: dict[str, Any], team_id: str) -> list[dict[str, Any]]:
    stat = _player_stat(payload)
    selected_league, _ = _league_filters(payload)
    if not _is_domestic_league(selected_league):
        return []
    rows: list[dict[str, Any]] = []
    for table in stat.get("tbl", []):
        columns = [
            str(column.get("data") or column.get("ttl") or "")
            if isinstance(column, dict)
            else str(column)
            for column in table.get("col", [])
        ]
        for values in table.get("row", []):
            if not values:
                continue
            match = re.match(r"(20\d{2})", str(values[0]))
            if not match:
                continue
            year = int(match.group(1))
            if year < 2021 or year > 2025:
                continue
            row = {
                column: value for column, value in zip(columns, values, strict=False)
            }
            team_value = row.get("Team") if isinstance(row.get("Team"), dict) else {}
            rows.append(
                {
                    "year": year,
                    "season": str(values[0]).split(" ", 1)[0],
                    "competition": str(values[0]),
                    "team": str(team_value.get("name") or ""),
                    "team_id": team_id,
                    "league": selected_league,
                    "league_matches": _league_matches(selected_league),
                    "appearances": None,
                    "starts": _number(row.get("STRT")),
                    "goals": _number(row.get("G")),
                    "assists": _number(row.get("A")),
                    "yellow_cards": _number(row.get("YC")),
                    "red_cards": _number(row.get("RC")),
                    "goals_conceded": _number(row.get("GA")),
                    "saves": _number(row.get("SV")),
                }
            )
    return rows


def _roster_player_stats(payload: dict[str, Any], espn_id: str) -> dict[str, Any]:
    athlete = next(
        (
            item
            for item in payload.get("athletes", [])
            if str(item.get("id") or "") == espn_id
        ),
        None,
    )
    if not athlete:
        return {}
    values: dict[str, float] = {}
    categories = athlete.get("statistics", {}).get("splits", {}).get("categories", [])
    for category in categories:
        for stat in category.get("stats", []):
            value = _number(stat.get("value"))
            if value is not None:
                values[str(stat.get("name") or "")] = value
    return {
        "appearances": values.get("appearances"),
        "starts": (
            values.get("appearances", 0) - values.get("subIns", 0)
            if values.get("appearances") is not None
            else None
        ),
        "goals": values.get("totalGoals"),
        "assists": values.get("goalAssists"),
        "yellow_cards": values.get("yellowCards"),
        "red_cards": values.get("redCards"),
        "goals_conceded": values.get("goalsConceded"),
        "saves": values.get("saves"),
        "appearance_source": "team_roster",
    }


def _aggregate_seasons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[int, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            int(row.get("year") or 0),
            str(row.get("team_id")),
            str(row.get("league")),
            str(row.get("competition")),
        )
        current = unique.get(key)
        if current is None or (
            current.get("appearance_source") == "starts_only"
            and row.get("appearance_source") != "starts_only"
        ):
            unique[key] = dict(row)
    by_year: dict[int, list[dict[str, Any]]] = {}
    for row in unique.values():
        by_year.setdefault(int(row["year"]), []).append(row)
    result: list[dict[str, Any]] = []
    for year in sorted(by_year, reverse=True)[:5]:
        items = by_year[year]
        aggregate = {
            "year": year,
            "season": f"{year}-{str(year + 1)[-2:]}",
            "competition": " + ".join(
                sorted({str(item.get("competition") or "") for item in items})
            ),
            "team": " + ".join(
                sorted(
                    {str(item.get("team") or "") for item in items if item.get("team")}
                )
            ),
            "league": " + ".join(
                sorted({str(item.get("league") or "") for item in items})
            ),
            "league_matches": max(
                float(item.get("league_matches") or 38) for item in items
            ),
        }
        for field in (
            "appearances",
            "starts",
            "goals",
            "assists",
            "yellow_cards",
            "red_cards",
            "goals_conceded",
            "saves",
        ):
            values = [item.get(field) for item in items if item.get(field) is not None]
            aggregate[field] = (
                round(sum(float(value) for value in values), 1) if values else None
            )
        aggregate["appearances"] = min(
            aggregate["league_matches"], aggregate.get("appearances") or 0
        )
        result.append(aggregate)
    return result


def _league_matches(league: str) -> int:
    if league in {"ger.1", "ned.1", "por.1", "bel.1", "sco.1"}:
        return 34
    if league in {"fra.1"}:
        return 34
    if league in {"usa.1"}:
        return 34
    return 38


def _name_score(left: str, right: str) -> float:
    left_tokens = _normalize(left).split()
    right_tokens = _normalize(right).split()
    if not left_tokens or not right_tokens:
        return 0.0
    left_text = " ".join(left_tokens)
    right_text = " ".join(right_tokens)
    score = difflib.SequenceMatcher(None, left_text, right_text).ratio()
    overlap = len(set(left_tokens) & set(right_tokens)) / max(
        1, min(len(left_tokens), len(right_tokens))
    )
    score = max(score, overlap * 0.82 + 0.18)
    if (
        len(left_tokens) >= 2
        and len(left_tokens[-1]) == 1
        and left_tokens[0] in right_tokens
        and any(
            token.startswith(left_tokens[-1])
            for token in right_tokens
            if token != left_tokens[0]
        )
    ):
        score = max(score, 0.99)
    return score


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "", "--") else None
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
