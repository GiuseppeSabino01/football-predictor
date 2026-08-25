from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from hashlib import sha1
from typing import Any, Iterable

from fantasy.service import FORMATIONS, ROLE_LABELS, roster_summary

FIXTURE_SOURCE_URL = (
    "https://www.legaseriea.it/serie-a/news/"
    "calendario-della-serie-a-enilive-2026-27"
)


def _parse_fixture_calendar(raw: str) -> tuple[tuple[tuple[str, str], ...], ...]:
    rounds: list[tuple[tuple[str, str], ...]] = []
    for line in raw.strip().splitlines():
        matches = []
        for match in line.split(";"):
            home, away = match.strip().split("-")
            matches.append((home, away))
        rounds.append(tuple(matches))
    return tuple(rounds)


# Calendario ufficiale Lega Serie A 2026/27. Il fallback locale mantiene disponibili
# tutte le 38 giornate anche se la pagina della Lega non risponde al caricamento.
OFFICIAL_FIXTURES_2026_27 = _parse_fixture_calendar(
    """
ATALANTA-SASSUOLO;BOLOGNA-LAZIO;FROSINONE-JUVENTUS;GENOA-NAPOLI;INTER-MONZA;PARMA-CAGLIARI;ROMA-FIORENTINA;TORINO-MILAN;UDINESE-COMO;VENEZIA-LECCE
ATALANTA-BOLOGNA;CAGLIARI-INTER;FIORENTINA-FROSINONE;JUVENTUS-PARMA;LAZIO-GENOA;LECCE-ROMA;MILAN-VENEZIA;MONZA-UDINESE;NAPOLI-COMO;SASSUOLO-TORINO
BOLOGNA-SASSUOLO;CAGLIARI-LECCE;FIORENTINA-TORINO;FROSINONE-VENEZIA;GENOA-COMO;INTER-NAPOLI;JUVENTUS-MILAN;PARMA-MONZA;ROMA-ATALANTA;UDINESE-LAZIO
ATALANTA-CAGLIARI;COMO-PARMA;GENOA-FROSINONE;INTER-UDINESE;LAZIO-MILAN;LECCE-MONZA;NAPOLI-BOLOGNA;SASSUOLO-JUVENTUS;TORINO-ROMA;VENEZIA-FIORENTINA
BOLOGNA-TORINO;FIORENTINA-NAPOLI;FROSINONE-COMO;JUVENTUS-ATALANTA;MILAN-LECCE;MONZA-SASSUOLO;PARMA-GENOA;ROMA-INTER;UDINESE-CAGLIARI;VENEZIA-LAZIO
ATALANTA-VENEZIA;CAGLIARI-JUVENTUS;COMO-ROMA;GENOA-FIORENTINA;INTER-PARMA;LAZIO-MONZA;LECCE-BOLOGNA;NAPOLI-FROSINONE;SASSUOLO-MILAN;TORINO-UDINESE
BOLOGNA-INTER;FIORENTINA-COMO;FROSINONE-SASSUOLO;JUVENTUS-LAZIO;MILAN-ATALANTA;MONZA-CAGLIARI;PARMA-TORINO;ROMA-GENOA;UDINESE-LECCE;VENEZIA-NAPOLI
ATALANTA-FROSINONE;CAGLIARI-BOLOGNA;COMO-SASSUOLO;GENOA-VENEZIA;INTER-FIORENTINA;LAZIO-PARMA;LECCE-JUVENTUS;NAPOLI-ROMA;TORINO-MONZA;UDINESE-MILAN
FIORENTINA-ATALANTA;FROSINONE-LECCE;GENOA-JUVENTUS;MILAN-BOLOGNA;MONZA-NAPOLI;PARMA-UDINESE;ROMA-CAGLIARI;SASSUOLO-LAZIO;TORINO-COMO;VENEZIA-INTER
ATALANTA-PARMA;BOLOGNA-MONZA;COMO-VENEZIA;FROSINONE-TORINO;JUVENTUS-NAPOLI;LAZIO-CAGLIARI;LECCE-GENOA;MILAN-INTER;SASSUOLO-FIORENTINA;UDINESE-ROMA
CAGLIARI-FROSINONE;FIORENTINA-JUVENTUS;GENOA-MILAN;INTER-COMO;MONZA-ATALANTA;NAPOLI-LAZIO;PARMA-BOLOGNA;ROMA-SASSUOLO;TORINO-LECCE;VENEZIA-UDINESE
ATALANTA-INTER;BOLOGNA-UDINESE;COMO-CAGLIARI;JUVENTUS-VENEZIA;LAZIO-LECCE;MILAN-FROSINONE;MONZA-FIORENTINA;NAPOLI-TORINO;PARMA-ROMA;SASSUOLO-GENOA
CAGLIARI-MILAN;COMO-JUVENTUS;FROSINONE-PARMA;INTER-GENOA;LECCE-ATALANTA;ROMA-MONZA;SASSUOLO-NAPOLI;TORINO-LAZIO;UDINESE-FIORENTINA;VENEZIA-BOLOGNA
BOLOGNA-ROMA;FIORENTINA-CAGLIARI;FROSINONE-INTER;GENOA-TORINO;JUVENTUS-UDINESE;LAZIO-ATALANTA;MILAN-PARMA;MONZA-COMO;NAPOLI-LECCE;VENEZIA-SASSUOLO
ATALANTA-GENOA;CAGLIARI-VENEZIA;COMO-BOLOGNA;INTER-TORINO;JUVENTUS-MONZA;LAZIO-ROMA;LECCE-SASSUOLO;NAPOLI-MILAN;PARMA-FIORENTINA;UDINESE-FROSINONE
ATALANTA-NAPOLI;FIORENTINA-BOLOGNA;FROSINONE-LAZIO;GENOA-UDINESE;LECCE-INTER;MILAN-COMO;ROMA-JUVENTUS;SASSUOLO-PARMA;TORINO-CAGLIARI;VENEZIA-MONZA
BOLOGNA-JUVENTUS;CAGLIARI-GENOA;COMO-LECCE;FIORENTINA-LAZIO;INTER-SASSUOLO;MONZA-MILAN;PARMA-NAPOLI;ROMA-FROSINONE;TORINO-VENEZIA;UDINESE-ATALANTA
ATALANTA-COMO;FROSINONE-BOLOGNA;GENOA-MONZA;JUVENTUS-TORINO;LAZIO-INTER;LECCE-PARMA;MILAN-FIORENTINA;NAPOLI-CAGLIARI;SASSUOLO-UDINESE;VENEZIA-ROMA
BOLOGNA-GENOA;CAGLIARI-SASSUOLO;COMO-LAZIO;FIORENTINA-LECCE;INTER-JUVENTUS;MONZA-FROSINONE;PARMA-VENEZIA;ROMA-MILAN;TORINO-ATALANTA;UDINESE-NAPOLI
ATALANTA-ROMA;CAGLIARI-COMO;JUVENTUS-GENOA;LAZIO-BOLOGNA;LECCE-UDINESE;MILAN-TORINO;NAPOLI-FIORENTINA;PARMA-INTER;SASSUOLO-MONZA;VENEZIA-FROSINONE
BOLOGNA-ATALANTA;COMO-NAPOLI;FIORENTINA-SASSUOLO;FROSINONE-MILAN;GENOA-PARMA;INTER-VENEZIA;JUVENTUS-CAGLIARI;LECCE-TORINO;MONZA-LAZIO;ROMA-UDINESE
ATALANTA-FIORENTINA;CAGLIARI-PARMA;GENOA-LECCE;LAZIO-VENEZIA;MILAN-JUVENTUS;MONZA-ROMA;NAPOLI-INTER;SASSUOLO-COMO;TORINO-FROSINONE;UDINESE-BOLOGNA
ATALANTA-LAZIO;BOLOGNA-MILAN;COMO-MONZA;FIORENTINA-UDINESE;INTER-CAGLIARI;JUVENTUS-SASSUOLO;LECCE-NAPOLI;PARMA-FROSINONE;ROMA-TORINO;VENEZIA-GENOA
BOLOGNA-COMO;CAGLIARI-LAZIO;FROSINONE-FIORENTINA;GENOA-ATALANTA;INTER-MILAN;MONZA-LECCE;NAPOLI-JUVENTUS;PARMA-ROMA;TORINO-SASSUOLO;UDINESE-VENEZIA
ATALANTA-MONZA;COMO-TORINO;FIORENTINA-INTER;JUVENTUS-BOLOGNA;LAZIO-NAPOLI;LECCE-FROSINONE;MILAN-GENOA;SASSUOLO-ROMA;UDINESE-PARMA;VENEZIA-CAGLIARI
BOLOGNA-LECCE;CAGLIARI-UDINESE;COMO-MILAN;FROSINONE-NAPOLI;GENOA-LAZIO;INTER-ATALANTA;MONZA-JUVENTUS;PARMA-SASSUOLO;ROMA-VENEZIA;TORINO-FIORENTINA
ATALANTA-TORINO;FIORENTINA-VENEZIA;JUVENTUS-ROMA;LAZIO-FROSINONE;LECCE-COMO;MILAN-CAGLIARI;MONZA-GENOA;NAPOLI-PARMA;SASSUOLO-BOLOGNA;UDINESE-INTER
BOLOGNA-NAPOLI;CAGLIARI-FIORENTINA;COMO-UDINESE;FROSINONE-MONZA;GENOA-ROMA;LAZIO-JUVENTUS;MILAN-SASSUOLO;PARMA-LECCE;TORINO-INTER;VENEZIA-ATALANTA
ATALANTA-MILAN;FIORENTINA-GENOA;INTER-FROSINONE;JUVENTUS-COMO;MONZA-BOLOGNA;NAPOLI-VENEZIA;PARMA-LAZIO;ROMA-LECCE;SASSUOLO-CAGLIARI;UDINESE-TORINO
CAGLIARI-NAPOLI;COMO-FIORENTINA;FROSINONE-UDINESE;GENOA-INTER;LECCE-LAZIO;MILAN-MONZA;ROMA-BOLOGNA;SASSUOLO-ATALANTA;TORINO-JUVENTUS;VENEZIA-PARMA
BOLOGNA-VENEZIA;CAGLIARI-ATALANTA;FIORENTINA-MILAN;FROSINONE-GENOA;INTER-ROMA;JUVENTUS-LECCE;LAZIO-TORINO;NAPOLI-SASSUOLO;PARMA-COMO;UDINESE-MONZA
ATALANTA-UDINESE;BOLOGNA-CAGLIARI;COMO-FROSINONE;FIORENTINA-PARMA;MILAN-NAPOLI;MONZA-INTER;ROMA-LAZIO;SASSUOLO-LECCE;TORINO-GENOA;VENEZIA-JUVENTUS
CAGLIARI-MONZA;FROSINONE-ROMA;GENOA-SASSUOLO;INTER-BOLOGNA;JUVENTUS-FIORENTINA;LAZIO-COMO;LECCE-MILAN;NAPOLI-UDINESE;PARMA-ATALANTA;VENEZIA-TORINO
ATALANTA-JUVENTUS;BOLOGNA-FIORENTINA;COMO-INTER;LECCE-CAGLIARI;MILAN-LAZIO;MONZA-VENEZIA;ROMA-NAPOLI;SASSUOLO-FROSINONE;TORINO-PARMA;UDINESE-GENOA
FIORENTINA-ROMA;FROSINONE-ATALANTA;GENOA-CAGLIARI;INTER-LECCE;LAZIO-SASSUOLO;NAPOLI-MONZA;PARMA-MILAN;TORINO-BOLOGNA;UDINESE-JUVENTUS;VENEZIA-COMO
BOLOGNA-FROSINONE;CAGLIARI-TORINO;COMO-ATALANTA;JUVENTUS-INTER;LAZIO-UDINESE;LECCE-FIORENTINA;MILAN-ROMA;MONZA-PARMA;NAPOLI-GENOA;SASSUOLO-VENEZIA
ATALANTA-LECCE;FIORENTINA-MONZA;FROSINONE-CAGLIARI;GENOA-BOLOGNA;INTER-LAZIO;PARMA-JUVENTUS;ROMA-COMO;TORINO-NAPOLI;UDINESE-SASSUOLO;VENEZIA-MILAN
BOLOGNA-PARMA;CAGLIARI-ROMA;COMO-GENOA;JUVENTUS-FROSINONE;LAZIO-FIORENTINA;LECCE-VENEZIA;MILAN-UDINESE;MONZA-TORINO;NAPOLI-ATALANTA;SASSUOLO-INTER
"""
)


MATCHDAY_DATES_2026_27: tuple[date, ...] = tuple(
    datetime.strptime(value, "%Y-%m-%d").date()
    for value in (
        "2026-08-23", "2026-08-30", "2026-09-06", "2026-09-13", "2026-09-20",
        "2026-10-11", "2026-10-18", "2026-10-25", "2026-10-28", "2026-11-01",
        "2026-11-08", "2026-11-22", "2026-11-29", "2026-12-06", "2026-12-13",
        "2026-12-20", "2027-01-03", "2027-01-06", "2027-01-10", "2027-01-17",
        "2027-01-24", "2027-01-31", "2027-02-07", "2027-02-14", "2027-02-21",
        "2027-02-28", "2027-03-07", "2027-03-14", "2027-03-21", "2027-04-04",
        "2027-04-11", "2027-04-18", "2027-04-25", "2027-05-02", "2027-05-09",
        "2027-05-16", "2027-05-23", "2027-05-30",
    )
)


TEAM_ALIASES = {
    "ATA": "ATALANTA", "ATALANTA": "ATALANTA", "BOL": "BOLOGNA",
    "BOLOGNA": "BOLOGNA", "CAG": "CAGLIARI", "CAGLIARI": "CAGLIARI",
    "COM": "COMO", "COMO": "COMO", "FIO": "FIORENTINA",
    "FIORENTINA": "FIORENTINA", "FRO": "FROSINONE", "FROSINONE": "FROSINONE",
    "GEN": "GENOA", "GENOA": "GENOA", "INT": "INTER", "INTER": "INTER",
    "JUV": "JUVENTUS", "JUVENTUS": "JUVENTUS", "LAZ": "LAZIO", "LAZIO": "LAZIO",
    "LEC": "LECCE", "LECCE": "LECCE", "MIL": "MILAN", "MILAN": "MILAN",
    "MON": "MONZA", "MONZA": "MONZA", "NAP": "NAPOLI", "NAPOLI": "NAPOLI",
    "PAR": "PARMA", "PARMA": "PARMA", "ROM": "ROMA", "ROMA": "ROMA",
    "SAS": "SASSUOLO", "SASSUOLO": "SASSUOLO", "TOR": "TORINO",
    "TORINO": "TORINO", "UDI": "UDINESE", "UDINESE": "UDINESE",
    "VEN": "VENEZIA", "VENEZIA": "VENEZIA",
}


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_team(team: Any) -> str:
    clean = str(team or "").strip().upper()
    return TEAM_ALIASES.get(clean, clean)


def season_next_matchday(today: date | None = None) -> int:
    reference = today or date.today()
    for matchday, scheduled_date in enumerate(MATCHDAY_DATES_2026_27, start=1):
        if scheduled_date >= reference:
            return matchday
    return 38


def matchday_date(matchday: int) -> date | None:
    index = int(matchday) - 1
    if 0 <= index < len(MATCHDAY_DATES_2026_27):
        return MATCHDAY_DATES_2026_27[index]
    return None


def fixtures_for_team(team: Any, *, start_matchday: int = 1, limit: int = 5) -> list[dict[str, Any]]:
    normalized = normalize_team(team)
    fixtures: list[dict[str, Any]] = []
    start_index = max(int(start_matchday) - 1, 0)
    for matchday_index, matches in enumerate(
        OFFICIAL_FIXTURES_2026_27[start_index:], start=start_index + 1
    ):
        for home, away in matches:
            if normalized not in {home, away}:
                continue
            fixtures.append(
                {
                    "matchday": matchday_index,
                    "home": home,
                    "away": away,
                    "opponent": away if normalized == home else home,
                    "venue": "C" if normalized == home else "T",
                }
            )
            break
        if len(fixtures) >= limit:
            break
    return fixtures


def team_strengths(catalog: Iterable[dict[str, Any]]) -> dict[str, float]:
    by_team: dict[str, list[float]] = {}
    for player in catalog:
        team = normalize_team(player.get("team"))
        if not team:
            continue
        score = number(player.get("fantasy_score"))
        if score <= 0:
            score = (
                number(player.get("expected_fantasy_average")) * 7
                + number(player.get("starter_probability")) * 0.12
                + number(player.get("expected_goals")) * 1.7
                + number(player.get("expected_assists"))
            )
        by_team.setdefault(team, []).append(score)
    raw = {
        team: sum(sorted(values, reverse=True)[:15]) / max(min(len(values), 15), 1)
        for team, values in by_team.items()
    }
    if not raw:
        return {}
    ordered = sorted(set(raw.values()))
    denominator = max(len(ordered) - 1, 1)
    return {
        team: round(1 + 4 * ordered.index(value) / denominator, 2)
        for team, value in raw.items()
    }


def fixture_difficulty(team: Any, fixture: dict[str, Any], strengths: dict[str, float]) -> float:
    opponent_strength = strengths.get(normalize_team(fixture.get("opponent")), 3.0)
    venue_adjustment = -0.25 if fixture.get("venue") == "C" else 0.25
    return round(max(1.0, min(5.0, opponent_strength + venue_adjustment)), 1)


def fixture_outlook(
    team: Any,
    catalog: Iterable[dict[str, Any]],
    *,
    start_matchday: int = 1,
    limit: int = 5,
) -> list[dict[str, Any]]:
    strengths = team_strengths(catalog)
    return [
        {**fixture, "difficulty": fixture_difficulty(team, fixture, strengths)}
        for fixture in fixtures_for_team(team, start_matchday=start_matchday, limit=limit)
    ]


def _enrich_purchase(row: dict[str, Any], catalog_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    player = catalog_by_id.get(str(row.get("player_id")), {})
    return {**player, **row}


def weekly_player_score(
    player: dict[str, Any], difficulty: float | None = None
) -> float:
    fixture_bonus = 0.0 if difficulty is None else (3.0 - difficulty) * 2.4
    starter = number(player.get("starter_probability"))
    reliability = number(player.get("reliability"))
    risk = number(player.get("risk"))
    return round(
        number(player.get("expected_fantasy_average")) * 10
        + starter * 0.17
        + reliability * 0.06
        - risk * 0.09
        + number(player.get("expected_goals")) * 1.25
        + number(player.get("expected_assists")) * 0.95
        + (2.0 if number(player.get("penalty_taker")) == 1 else 0)
        + (1.0 if number(player.get("set_pieces")) == 1 else 0)
        + fixture_bonus,
        2,
    )


def recommend_lineup(
    league: dict[str, Any],
    catalog: list[dict[str, Any]],
    *,
    matchday: int = 1,
    news_items: list[dict[str, Any]] | None = None,
    next_matchday_number: int | None = None,
) -> dict[str, Any]:
    catalog_by_id = {str(player.get("id")): player for player in catalog}
    players = [
        _enrich_purchase(row, catalog_by_id) for row in league.get("purchases", [])
    ]
    strengths = team_strengths(catalog)
    fixture_by_team: dict[str, dict[str, Any]] = {}
    for player in players:
        team = normalize_team(player.get("team"))
        if team in fixture_by_team:
            continue
        fixture = next(iter(fixtures_for_team(team, start_matchday=matchday, limit=1)), None)
        if fixture:
            fixture_by_team[team] = {
                **fixture,
                "difficulty": fixture_difficulty(team, fixture, strengths),
            }
    for player in players:
        fixture = fixture_by_team.get(normalize_team(player.get("team")))
        player["decision_fixture"] = fixture
        availability = player_availability(
            player,
            news_items or [],
            matchday=int(matchday),
            next_matchday_number=next_matchday_number,
        )
        player.update(availability)
        base_score = weekly_player_score(
            player, fixture.get("difficulty") if fixture else None
        )
        availability_adjustment = (
            (number(availability.get("appearance_probability")) - 75) * 0.22
        )
        if availability.get("availability_status") == "bench":
            availability_adjustment -= 10
        if availability.get("availability_unavailable"):
            availability_adjustment -= 1000
        player["decision_score"] = round(base_score + availability_adjustment, 2)
    available_players = [
        player for player in players if not player.get("availability_unavailable")
    ]
    candidates: list[dict[str, Any]] = []
    for formation, required in FORMATIONS.items():
        selected: list[dict[str, Any]] = []
        feasible = True
        for role, count in required.items():
            role_players = sorted(
                (
                    player for player in available_players
                    if str(player.get("role")) == role
                ),
                key=lambda player: (number(player.get("decision_score")), number(player.get("price"))),
                reverse=True,
            )
            if len(role_players) < int(count):
                feasible = False
                break
            selected.extend(role_players[: int(count)])
        if feasible:
            candidates.append(
                {
                    "formation": formation,
                    "players": selected,
                    "score": sum(number(player.get("decision_score")) for player in selected),
                }
            )
    if not candidates:
        fallback = sorted(
            available_players,
            key=lambda player: number(player.get("decision_score")),
            reverse=True,
        )[:11]
        return {
            "formation": None,
            "players": fallback,
            "bench": [player for player in players if player not in fallback],
            "captain": fallback[0] if fallback else None,
            "complete": False,
            "score": sum(number(player.get("decision_score")) for player in fallback),
            "fixture_by_team": fixture_by_team,
            "all_players": players,
        }
    best = max(candidates, key=lambda item: number(item.get("score")))
    selected_ids = {str(player.get("player_id")) for player in best["players"]}
    bench = sorted(
        (player for player in players if str(player.get("player_id")) not in selected_ids),
        key=lambda player: number(player.get("decision_score")),
        reverse=True,
    )
    captain = max(
        best["players"],
        key=lambda player: (
            number(player.get("expected_goals")) * 3
            + number(player.get("expected_assists")) * 1.5
            + number(player.get("expected_fantasy_average"))
            + number(player.get("starter_probability")) * 0.03
        ),
        default=None,
    )
    return {
        **best,
        "bench": bench,
        "captain": captain,
        "complete": True,
        "fixture_by_team": fixture_by_team,
        "all_players": players,
    }


def best_rotation_pairs(
    league: dict[str, Any],
    catalog: list[dict[str, Any]],
    *,
    start_matchday: int = 1,
    limit: int = 5,
) -> list[dict[str, Any]]:
    strengths = team_strengths(catalog)
    pairs: list[dict[str, Any]] = []
    purchases = league.get("purchases", [])
    for role in ROLE_LABELS:
        role_players = [player for player in purchases if player.get("role") == role]
        for first_index, first in enumerate(role_players):
            for second in role_players[first_index + 1:]:
                if normalize_team(first.get("team")) == normalize_team(second.get("team")):
                    continue
                first_fixtures = fixtures_for_team(first.get("team"), start_matchday=start_matchday, limit=limit)
                second_fixtures = fixtures_for_team(second.get("team"), start_matchday=start_matchday, limit=limit)
                if not first_fixtures or len(first_fixtures) != len(second_fixtures):
                    continue
                best_each_week = [
                    min(
                        fixture_difficulty(first.get("team"), one, strengths),
                        fixture_difficulty(second.get("team"), two, strengths),
                    )
                    for one, two in zip(first_fixtures, second_fixtures)
                ]
                pairs.append(
                    {
                        "role": role,
                        "first": first,
                        "second": second,
                        "average_difficulty": round(sum(best_each_week) / len(best_each_week), 2),
                        "weekly_best": best_each_week,
                    }
                )
    return sorted(pairs, key=lambda row: row["average_difficulty"])[:5]


def simulate_purchase(
    league: dict[str, Any], player: dict[str, Any], price: float
) -> dict[str, Any]:
    summary = roster_summary(league)
    player_id = str(player.get("id") or "")
    role = str(player.get("role") or "")
    errors: list[str] = []
    if any(str(row.get("player_id")) == player_id for row in league.get("purchases", [])):
        errors.append("Il giocatore e gia nella tua rosa.")
    if price < 0:
        errors.append("Il prezzo non puo essere negativo.")
    if price > summary["remaining_budget"]:
        errors.append("Il prezzo supera i crediti rimasti.")
    role_limit = int(league.get("roster_slots", {}).get(role, 0))
    if summary["role_counts"].get(role, 0) >= role_limit:
        errors.append(f"Gli slot {ROLE_LABELS.get(role, role).lower()} sono gia completi.")
    current_goals = sum(number(row.get("expected_goals")) for row in league.get("purchases", []))
    current_assists = sum(number(row.get("expected_assists")) for row in league.get("purchases", []))
    current_fm = sum(number(row.get("expected_fantasy_average")) for row in league.get("purchases", []))
    score = number(player.get("fantasy_score"))
    value_score = score / max(price, 1)
    if errors:
        verdict = "Operazione non valida"
    elif value_score >= 2.5 and number(player.get("starter_probability")) >= 70:
        verdict = "Impatto molto positivo"
    elif value_score >= 1.4 or number(player.get("expected_fantasy_average")) >= 6.5:
        verdict = "Operazione equilibrata"
    else:
        verdict = "Prezzo da rinegoziare"
    return {
        "valid": not errors,
        "errors": errors,
        "verdict": verdict,
        "before": {
            "remaining_budget": summary["remaining_budget"],
            "roster_size": summary["roster_size"],
            "goals": current_goals,
            "assists": current_assists,
            "fantasy_average_sum": current_fm,
        },
        "after": {
            "remaining_budget": max(summary["remaining_budget"] - price, 0),
            "roster_size": summary["roster_size"] + (0 if errors else 1),
            "goals": current_goals + number(player.get("expected_goals")),
            "assists": current_assists + number(player.get("expected_assists")),
            "fantasy_average_sum": current_fm + number(player.get("expected_fantasy_average")),
        },
        "price": float(price),
        "value_score": round(value_score, 2),
    }


def _alert_id(*parts: Any) -> str:
    payload = "|".join(str(part or "") for part in parts)
    return sha1(payload.encode("utf-8")).hexdigest()[:16]


def _name_tokens(name: Any) -> set[str]:
    ignored = {"del", "della", "dei", "di", "da", "de", "dos", "van", "von"}
    return {
        token
        for token in re.findall(r"[a-zà-ÿ]+", str(name or "").casefold())
        if len(token) >= 3 and token not in ignored
    }


def _related_news(
    player: dict[str, Any], news_items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    player_tokens = _name_tokens(player.get("name"))
    team_tokens = _name_tokens(normalize_team(player.get("team")))
    if not player_tokens:
        return []
    ranked: list[tuple[int, dict[str, Any]]] = []
    for item in news_items:
        evidence_name = str(item.get("player_name") or "").strip()
        if evidence_name:
            evidence_tokens = _name_tokens(evidence_name)
            evidence_initials = {
                token
                for token in re.findall(
                    r"[a-zà-ÿ]+", evidence_name.casefold()
                )
                if len(token) == 1
            }
            player_identity_words = re.findall(
                r"[a-zà-ÿ]+", str(player.get("name") or "").casefold()
            )
            evidence_team = normalize_team(item.get("team"))
            player_team = normalize_team(player.get("team"))
            same_identity = bool(evidence_tokens) and (
                evidence_tokens.issubset(player_tokens)
                or player_tokens.issubset(evidence_tokens)
            )
            initials_match = all(
                any(word.startswith(initial) for word in player_identity_words)
                for initial in evidence_initials
            )
            if not same_identity or (
                evidence_team and player_team and evidence_team != player_team
            ) or not initials_match:
                continue
            ranked.append((100 + len(evidence_tokens), item))
            continue
        searchable = " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("summary") or ""),
                str(item.get("body") or ""),
            ]
        )
        news_tokens = _name_tokens(searchable)
        name_matches = len(player_tokens & news_tokens)
        if not name_matches:
            continue
        score = name_matches * 10 + len(team_tokens & news_tokens)
        ranked.append((score, item))
    return [item for _, item in sorted(ranked, key=lambda row: row[0], reverse=True)]


def _is_published_news(item: dict[str, Any]) -> bool:
    title = str(item.get("title") or "").strip()
    source = str(item.get("source") or "").strip()
    url = str(item.get("url") or "").strip()
    return bool(title and source and url.startswith("http") and item.get("verified") is True)


def _clamp(value: Any, minimum: float = 0, maximum: float = 100) -> float:
    return max(minimum, min(maximum, number(value)))


def _news_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(field) or "") for field in ("title", "summary", "body")
    ).strip()


def _player_news_context(player: dict[str, Any], item: dict[str, Any]) -> str:
    text = _news_text(item)
    folded = text.casefold()
    tokens = sorted(_name_tokens(player.get("name")), key=len, reverse=True)
    positions = [
        match.start()
        for token in tokens
        for match in [re.search(rf"(?<!\w){re.escape(token)}(?!\w)", folded)]
        if match
    ]
    if not positions:
        return ""
    position = min(positions)
    return folded[max(position - 180, 0): position + 260]


def _direct_player_news_context(
    player: dict[str, Any], item: dict[str, Any]
) -> str:
    """Return headline clauses that explicitly mention the player.

    Availability signals must be high precision: an injury elsewhere in a long
    article is not evidence that every player named in that article is injured.
    """
    title = str(item.get("title") or "").casefold()
    tokens = sorted(_name_tokens(player.get("name")), key=len, reverse=True)
    if not title or not tokens:
        return ""
    clauses = re.split(
        r"[.;:!?|–—]+|\b(?:mentre|invece|però|pero)\b",
        title,
    )
    related = [
        clause.strip()
        for clause in clauses
        if any(
            re.search(rf"(?<!\w){re.escape(token)}(?!\w)", clause)
            for token in tokens
        )
    ]
    return " ".join(related)


def _contains_signal_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(
        bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text))
        if len(term) <= 3 else term in text
        for term in terms
    )


def _explicit_unavailable_until(text: str) -> int | None:
    patterns = (
        r"(?:fuori|out|indisponibil\w*|stop|salter\w*)[^.]{0,90}?fino[^.]{0,40}?(\d{1,2})\s*(?:ª|a|°)?\s*giornata",
        r"fino[^.]{0,45}?(?:alla|al)?\s*(\d{1,2})\s*(?:ª|a|°)?\s*giornata",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return max(1, min(38, int(match.group(1))))
    return None


def _explicit_return_matchday(text: str) -> int | None:
    match = re.search(
        r"(?:rientr\w*|torner\w*|ritorn\w*)[^.]{0,70}?(?:alla|per la|in)\s*"
        r"(\d{1,2})\s*(?:ª|a|°)?\s*giornata",
        text,
    )
    if not match:
        return None
    return max(1, min(38, int(match.group(1))))


ITALIAN_MONTHS = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)


def _explicit_return_month(text: str) -> str:
    months = "|".join(ITALIAN_MONTHS)
    match = re.search(
        rf"(?:rientr\w*|torn\w*|ritorn\w*|recuper\w*|convocabil\w*)"
        rf"[^.]{{0,100}}?(?:a|in|entro|per|da|dalla)\s+"
        rf"((?:(?:inizio|fine|metà|meta|seconda metà di|seconda meta di)\s+)?"
        rf"(?:{months}))",
        text,
    )
    return match.group(1).replace("meta", "metà") if match else ""


def _estimated_return_date(text: str, published_at: Any) -> str:
    number_words = {"una": 1, "uno": 1, "due": 2, "tre": 3, "quattro": 4}
    match = re.search(
        r"(?:stop|fuori|out|indisponibil\w*|tempi[^.]{0,30})[^.]{0,90}?"
        r"(\d{1,2}|una|uno|due|tre|quattro)\s*(settimane?|mesi?)",
        text,
    )
    if not match or not published_at:
        return ""
    raw_amount = match.group(1)
    amount = int(raw_amount) if raw_amount.isdigit() else number_words[raw_amount]
    days = amount * (7 if match.group(2).startswith("settiman") else 30)
    try:
        published = datetime.fromisoformat(str(published_at)).date()
    except ValueError:
        return ""
    return (published + timedelta(days=days)).isoformat()


def injury_return_label(signal: dict[str, Any], *, today: date | None = None) -> str:
    """Turn published return evidence into a concise Italian list-board label."""
    return_matchday = int(number(signal.get("return_matchday"))) or None
    if return_matchday:
        return f"Rientro previsto alla {return_matchday}ª giornata"
    month = str(signal.get("return_month") or "").strip().casefold()
    if month:
        return f"Ipotesi rientro: {month}"
    raw_date = str(signal.get("estimated_return_date") or "")
    if raw_date:
        try:
            target = date.fromisoformat(raw_date[:10])
        except ValueError:
            target = None
        if target:
            remaining = (target - (today or datetime.now(UTC).date())).days
            month_label = ITALIAN_MONTHS[target.month - 1]
            if remaining > 45:
                months = max(2, round(remaining / 30))
                return f"Rientro stimato tra circa {months} mesi ({month_label})"
            if remaining > 10:
                weeks = max(2, round(remaining / 7))
                return f"Rientro stimato tra circa {weeks} settimane ({month_label})"
            if remaining >= 0:
                return f"Rientro stimato entro {month_label}"
            return "Rientro in verifica"
    unavailable_until = int(number(signal.get("unavailable_until_matchday"))) or None
    if unavailable_until:
        return f"Indisponibile fino alla {unavailable_until}ª giornata"
    return "Rientro da definire"


def _percentage(value: Any, fallback: float) -> float:
    if value is None or value == "":
        return _clamp(fallback)
    result = number(value)
    if 0 < result <= 1:
        result *= 100
    return _clamp(result)


def _base_appearance_estimate(player: dict[str, Any]) -> tuple[float, dict[str, float]]:
    """Build an individual next-round appearance estimate from season signals.

    Titolarita in the bundled analysis is intentionally coarse.  Combining it
    with projected and previous appearances, reliability, injury risk and a
    role-specific substitute rate avoids turning the four catalog bands into
    four repeated appearance percentages.
    """
    starter = _percentage(player.get("starter_probability"), 50)
    expected_appearances = number(player.get("expected_appearances"))
    projected_presence = (
        _clamp(expected_appearances / 38 * 100)
        if expected_appearances > 0 else starter
    )
    previous_appearances = number(player.get("appearances_previous"))
    previous_presence = (
        _clamp(previous_appearances / 38 * 100)
        if previous_appearances > 0 else projected_presence
    )
    reliability = _percentage(player.get("reliability"), 70)
    injury_risk = _percentage(player.get("risk"), 25)
    start_estimate = _clamp(
        starter * 0.42
        + projected_presence * 0.28
        + previous_presence * 0.10
        + reliability * 0.12
        + (100 - injury_risk) * 0.08
    )
    role = str(player.get("role") or "").upper()
    role_substitute_rate = {"P": 0.03, "D": 0.14, "C": 0.28, "A": 0.36}.get(role, 0.22)
    substitute_rate = max(
        0.02,
        min(
            0.50,
            role_substitute_rate
            + (reliability - 70) * 0.0015
            - injury_risk * 0.0012,
        ),
    )
    appearance = _clamp(
        start_estimate + (100 - start_estimate) * substitute_rate,
        maximum=99,
    )
    return appearance, {
        "starter": round(starter, 1),
        "projected_presence": round(projected_presence, 1),
        "previous_presence": round(previous_presence, 1),
        "reliability": round(reliability, 1),
        "injury_risk": round(injury_risk, 1),
        "substitute_rate": round(substitute_rate * 100, 1),
    }


def player_availability(
    player: dict[str, Any],
    news_items: list[dict[str, Any]] | None,
    *,
    matchday: int,
    next_matchday_number: int | None = None,
) -> dict[str, Any]:
    """Estimate appearance chance, using published evidence for short-term changes.

    The catalog probability remains the baseline. Injury, suspension and probable-lineup
    signals are accepted only from published, verified links; bench/starter signals are
    deliberately restricted to the immediately upcoming round.
    """
    base_probability, model_components = _base_appearance_estimate(player)
    probability = base_probability
    upcoming = int(next_matchday_number or season_next_matchday())
    result: dict[str, Any] = {
        "appearance_probability": round(probability),
        "availability_status": "model",
        "availability_label": "Stima impiego",
        "availability_reason": (
            f"Titolarita {model_components['starter']:.0f}% · presenze attese "
            f"{model_components['projected_presence']:.0f}% · affidabilita "
            f"{model_components['reliability']:.0f}/100 · rischio "
            f"{model_components['injury_risk']:.0f}/100 · subentro ruolo "
            f"{model_components['substitute_rate']:.0f}%."
        ),
        "availability_source": "Listone e modello SaSa",
        "availability_url": "",
        "availability_unavailable": False,
        "unavailable_until_matchday": None,
        "return_matchday": None,
        "return_month": "",
        "estimated_return_date": "",
        "availability_has_news": False,
        "appearance_model_components": model_components,
    }
    published = [
        item for item in (news_items or [])
        if _is_published_news(item) and _related_news(player, [item])
    ]
    injury_terms = (
        "infortun", "lesion", "problema muscolare", "operat", "stop", "indispon",
        "non convoc", "salta", "out", "allenamento a parte", "si ferma", "ko",
    )
    suspension_terms = ("squalificat", "squalifica")
    recovered_terms = (
        "recuperato", "a disposizione", "rientrato in gruppo", "torna in gruppo",
        "regolarmente in gruppo",
    )
    bench_terms = (
        "parte dalla panchina", "verso la panchina", "rischia la panchina",
        "possibile panchina", "inizialmente in panchina", "non dovrebbe partire titolare",
    )
    starter_terms = (
        "probabile titolare", "dal primo minuto", "parte titolare", "verso una maglia da titolare",
    )
    for item in published:
        item_matchday = int(number(item.get("matchday"))) or None
        if item_matchday and item_matchday != int(matchday):
            continue
        context = _player_news_context(player, item)
        if not context:
            continue
        direct_context = _direct_player_news_context(player, item)
        status = str(item.get("status") or "").strip().casefold()
        unavailable_until = int(number(item.get("unavailable_until_matchday"))) or None
        return_matchday = int(number(item.get("return_matchday"))) or None
        unavailable_until = unavailable_until or _explicit_unavailable_until(context)
        return_matchday = return_matchday or _explicit_return_matchday(context)
        return_month = _explicit_return_month(context)
        estimated_return_date = _estimated_return_date(
            context, item.get("published_at")
        )
        if return_matchday and unavailable_until is None:
            unavailable_until = max(return_matchday - 1, 0)
        source = str(item.get("source") or "Fonte pubblicata")
        url = str(item.get("url") or "")
        title = str(item.get("title") or "Notizia pubblicata")
        evidence_update = {
            "availability_source": source,
            "availability_url": url,
            "availability_has_news": True,
            "availability_news_title": title,
            "unavailable_until_matchday": unavailable_until,
            "return_matchday": return_matchday,
            "return_month": return_month,
            "estimated_return_date": estimated_return_date,
        }
        explicit_probability = item.get("appearance_probability")
        if explicit_probability is not None:
            probability = _clamp(explicit_probability)
        if status in {"recovered", "available"} or _contains_signal_term(
            direct_context, recovered_terms
        ):
            probability = max(probability, 82)
            result.update(
                {
                    **evidence_update,
                    "availability_status": "starter" if status == "starter" else "available",
                    "availability_label": "Disponibile",
                    "availability_reason": title,
                    "availability_unavailable": False,
                }
            )
            break
        is_suspended = status == "suspended" or _contains_signal_term(
            direct_context, suspension_terms
        )
        is_injured = status == "injured" or _contains_signal_term(
            direct_context, injury_terms
        )
        still_out = unavailable_until is None or int(matchday) <= unavailable_until
        if is_suspended or (is_injured and still_out):
            probability = 0 if is_suspended else min(probability, 8)
            if unavailable_until:
                duration = f"fino alla G{unavailable_until}"
            else:
                duration = "con rientro non ancora comunicato"
            result.update(
                {
                    **evidence_update,
                    "availability_status": "suspended" if is_suspended else "injured",
                    "availability_label": "Squalificato" if is_suspended else "Indisponibile",
                    "availability_reason": f"{title} · {duration}",
                    "availability_unavailable": True,
                }
            )
            break
        if is_injured and not still_out:
            probability = max(min(probability, 82), 65)
            result.update(
                {
                    **evidence_update,
                    "availability_status": "returning",
                    "availability_label": "Rientro previsto",
                    "availability_reason": title,
                    "availability_unavailable": False,
                }
            )
            break
        if int(matchday) != upcoming:
            continue
        if status == "bench" or _contains_signal_term(direct_context, bench_terms):
            bench_ceiling = item.get("appearance_probability")
            if bench_ceiling is None:
                bench_ceiling = max(25, probability * 0.62)
            probability = min(probability, _clamp(bench_ceiling))
            result.update(
                {
                    **evidence_update,
                    "availability_status": "bench",
                    "availability_label": "Possibile panchina",
                    "availability_reason": title,
                    "availability_unavailable": False,
                }
            )
            break
        elif status == "starter" or _contains_signal_term(
            direct_context, starter_terms
        ):
            starter_floor = item.get("appearance_probability")
            if starter_floor is None:
                starter_floor = min(98, probability + 8)
            probability = max(probability, _clamp(starter_floor))
            result.update(
                {
                    **evidence_update,
                    "availability_status": "starter",
                    "availability_label": "Probabile titolare",
                    "availability_reason": title,
                    "availability_unavailable": False,
                }
            )
            break
    result["appearance_probability"] = int(round(_clamp(probability)))
    return result


def _news_alert_kind(item: dict[str, Any]) -> tuple[str, str]:
    searchable = " ".join(
        [str(item.get("title") or ""), str(item.get("summary") or "")]
    ).casefold()
    if "squal" in searchable:
        return "Squalifica", "high"
    if any(
        keyword in searchable
        for keyword in (
            "infortun", "lesion", "problema muscolare", "operazione", "operato",
            "stop", "indispon", "out", "salta", "recupero", "allenamento a parte",
        )
    ):
        return "Disponibilita", "high"
    return "Notizia", "news"


def build_roster_alerts(
    league: dict[str, Any],
    catalog: list[dict[str, Any]],
    news_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    catalog_by_id = {str(player.get("id")): player for player in catalog}
    watched_ids = {str(player_id) for player_id in league.get("watchlist", [])}
    relevant = [
        _enrich_purchase(row, catalog_by_id) for row in league.get("purchases", [])
    ] + [catalog_by_id[player_id] for player_id in watched_ids if player_id in catalog_by_id]
    available_news = [item for item in (news_items or []) if _is_published_news(item)]
    alerts: list[dict[str, Any]] = []
    used_news_urls: set[str] = set()
    for item in available_news:
        url = str(item.get("url") or "")
        if url in used_news_urls:
            continue
        matched_players = [
            player for player in relevant if _related_news(player, [item])
        ]
        if not matched_players:
            continue
        used_news_urls.add(url)
        names = list(
            dict.fromkeys(str(player.get("name") or "Giocatore") for player in matched_players)
        )
        kind, severity = _news_alert_kind(item)
        title = str(item.get("title") or "")
        summary = str(item.get("summary") or "").strip()
        alerts.append(
            {
                "id": _alert_id(league.get("id"), url, title),
                "severity": severity,
                "title": f"{kind}: {', '.join(names)}",
                "message": summary or (
                    f"La notizia pubblicata cita {', '.join(names)} della tua rosa o watchlist."
                ),
                "evidence_title": title,
                "has_news": True,
                "player_id": str(
                    matched_players[0].get("player_id")
                    or matched_players[0].get("id")
                    or ""
                ),
                "source": str(item.get("source")),
                "url": item.get("url"),
            }
        )
    severity_order = {"high": 0, "medium": 1, "news": 2, "low": 3}
    return sorted(alerts, key=lambda alert: severity_order.get(str(alert.get("severity")), 9))
