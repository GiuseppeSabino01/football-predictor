from __future__ import annotations

from hashlib import sha1
import re
from typing import Any, Iterable

from fantasy.service import FORMATIONS, ROLE_LABELS, roster_summary


FIXTURE_SOURCE_URL = (
    "https://www.legaseriea.it/serie-a/news/"
    "date-orari-e-programmazione-tv-delle-prime-cinque-giornate"
)


# Le prime cinque giornate sono pubblicate dalla Lega Serie A. Tenere i dati qui rende
# il Decision Center utilizzabile anche quando il sito sorgente non risponde.
OFFICIAL_FIXTURES_2026_27: tuple[tuple[tuple[str, str], ...], ...] = (
    (
        ("INTER", "MONZA"), ("UDINESE", "COMO"), ("GENOA", "NAPOLI"),
        ("PARMA", "CAGLIARI"), ("FROSINONE", "JUVENTUS"), ("VENEZIA", "LECCE"),
        ("ATALANTA", "SASSUOLO"), ("TORINO", "MILAN"), ("BOLOGNA", "LAZIO"),
        ("ROMA", "FIORENTINA"),
    ),
    (
        ("MILAN", "VENEZIA"), ("FIORENTINA", "FROSINONE"), ("MONZA", "UDINESE"),
        ("SASSUOLO", "TORINO"), ("JUVENTUS", "PARMA"), ("NAPOLI", "COMO"),
        ("CAGLIARI", "INTER"), ("LAZIO", "GENOA"), ("LECCE", "ROMA"),
        ("ATALANTA", "BOLOGNA"),
    ),
    (
        ("GENOA", "COMO"), ("INTER", "NAPOLI"), ("FIORENTINA", "TORINO"),
        ("ROMA", "ATALANTA"), ("JUVENTUS", "MILAN"), ("FROSINONE", "VENEZIA"),
        ("PARMA", "MONZA"), ("BOLOGNA", "SASSUOLO"), ("CAGLIARI", "LECCE"),
        ("UDINESE", "LAZIO"),
    ),
    (
        ("VENEZIA", "FIORENTINA"), ("GENOA", "FROSINONE"),
        ("ATALANTA", "CAGLIARI"), ("LAZIO", "MILAN"), ("SASSUOLO", "JUVENTUS"),
        ("LECCE", "MONZA"), ("INTER", "UDINESE"), ("COMO", "PARMA"),
        ("NAPOLI", "BOLOGNA"), ("TORINO", "ROMA"),
    ),
    (
        ("MONZA", "SASSUOLO"), ("BOLOGNA", "TORINO"), ("UDINESE", "CAGLIARI"),
        ("ROMA", "INTER"), ("VENEZIA", "LAZIO"), ("FIORENTINA", "NAPOLI"),
        ("FROSINONE", "COMO"), ("PARMA", "GENOA"), ("ATALANTA", "JUVENTUS"),
        ("MILAN", "LECCE"),
    ),
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
        player["decision_score"] = weekly_player_score(
            player, fixture.get("difficulty") if fixture else None
        )
    candidates: list[dict[str, Any]] = []
    for formation, required in FORMATIONS.items():
        selected: list[dict[str, Any]] = []
        feasible = True
        for role, count in required.items():
            role_players = sorted(
                (player for player in players if str(player.get("role")) == role),
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
            players,
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
        searchable = " ".join(
            [str(item.get("title") or ""), str(item.get("summary") or "")]
        )
        news_tokens = _name_tokens(searchable)
        name_matches = len(player_tokens & news_tokens)
        if not name_matches:
            continue
        score = name_matches * 10 + len(team_tokens & news_tokens)
        ranked.append((score, item))
    return [item for _, item in sorted(ranked, key=lambda row: row[0], reverse=True)]


def _physical_risk_reason(player: dict[str, Any], risk: float, status: str) -> str:
    reasons = [f"indice di rischio {risk:.0f}/100"]
    expected_appearances = number(player.get("expected_appearances"))
    reliability = number(player.get("reliability"))
    starter = number(player.get("starter_probability"))
    if status:
        reasons.append(f"stato listone: {status}")
    if expected_appearances and expected_appearances < 27:
        reasons.append(f"solo {expected_appearances:.0f} presenze attese")
    if reliability and reliability < 70:
        reasons.append(f"affidabilita {reliability:.0f}/100")
    if starter and starter < 60:
        reasons.append(f"titolarita {starter:.0f}%")
    return ", ".join(reasons)


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
    available_news = news_items or []
    alerts: list[dict[str, Any]] = []
    seen_players: set[str] = set()
    used_news_urls: set[str] = set()
    for player in relevant:
        player_id = str(player.get("player_id") or player.get("id") or "")
        if player_id in seen_players:
            continue
        seen_players.add(player_id)
        name = str(player.get("name") or "Giocatore")
        risk = number(player.get("risk"))
        starter = number(player.get("starter_probability"))
        status = str(player.get("status") or "").strip()
        related_news = _related_news(player, available_news)
        evidence = related_news[0] if related_news else None
        if risk >= 40:
            reason = _physical_risk_reason(player, risk, status)
            if evidence:
                evidence_title = str(evidence.get("title") or "")
                evidence_summary = str(evidence.get("summary") or "").strip()
                if evidence_summary and evidence_summary.casefold() != evidence_title.casefold():
                    reason = f"{reason}. {evidence_summary}"
                source = str(evidence.get("source") or "Fantacalcio.it")
                url = evidence.get("url")
                if url:
                    used_news_urls.add(str(url))
            else:
                evidence_title = ""
                source = "Modello statistico"
                url = None
                reason = (
                    f"{reason}. Non risulta una notizia recente verificata associata: "
                    "il segnale deriva dagli indicatori del giocatore."
                )
            alerts.append(
                {
                    "id": _alert_id(
                        league.get("id"), player_id, "risk", round(risk),
                        (evidence or {}).get("url"),
                    ),
                    "severity": "high" if risk >= 60 else "medium",
                    "title": f"Rischio fisico: {name}",
                    "message": reason,
                    "evidence_title": evidence_title,
                    "has_news": bool(evidence),
                    "player_id": player_id,
                    "source": source,
                    "url": url,
                }
            )
        if starter and starter < 55:
            alerts.append(
                {
                    "id": _alert_id(league.get("id"), player_id, "starter", round(starter)),
                    "severity": "medium",
                    "title": f"Titolarita da monitorare: {name}",
                    "message": f"Probabilita di titolarita {starter:.0f}%. Valuta un'alternativa nella Top 11.",
                    "player_id": player_id,
                    "source": "Analisi rosa",
                    "url": None,
                }
            )
        lowered_status = status.casefold()
        if status and any(word in lowered_status for word in ("infortun", "squal", "dubb", "indispon")):
            status_evidence = evidence if evidence and str(evidence.get("url") or "") not in used_news_urls else None
            if status_evidence and status_evidence.get("url"):
                used_news_urls.add(str(status_evidence.get("url")))
            alerts.append(
                {
                    "id": _alert_id(league.get("id"), player_id, "status", lowered_status),
                    "severity": "high",
                    "title": f"Aggiornamento disponibilita: {name}",
                    "message": f"Motivo registrato nel listone: {status}.",
                    "evidence_title": str((status_evidence or {}).get("title") or ""),
                    "has_news": bool(status_evidence),
                    "player_id": player_id,
                    "source": str((status_evidence or {}).get("source") or "Listone"),
                    "url": (status_evidence or {}).get("url"),
                }
            )
    for player in relevant:
        for item in _related_news(player, available_news)[:2]:
            url = str(item.get("url") or "")
            if url in used_news_urls:
                continue
            used_news_urls.add(url)
            title = str(item.get("title") or "")
            summary = str(item.get("summary") or "").strip()
            alerts.append(
                {
                    "id": _alert_id(league.get("id"), url, title),
                    "severity": "news",
                    "title": f"Notizia su {player.get('name')}",
                    "message": summary or "Aggiornamento recente collegato alla tua rosa o watchlist.",
                    "evidence_title": title,
                    "has_news": True,
                    "player_id": str(player.get("player_id") or player.get("id") or ""),
                    "source": str(item.get("source") or "Fantacalcio.it"),
                    "url": item.get("url"),
                }
            )
    severity_order = {"high": 0, "medium": 1, "news": 2, "low": 3}
    return sorted(alerts, key=lambda alert: severity_order.get(str(alert.get("severity")), 9))
