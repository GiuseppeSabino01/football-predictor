from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import random
import re
from typing import Any

from config.settings import Settings
from nlp.gemini_client import GeminiClient
from schemas import Match, MatchPrediction
from services.predictor import PredictionService
from storage.sqlite_client import SQLiteStorage
from storage.supabase_client import SupabaseStorage


GROUPS = tuple("ABCDEFGHIJKL")
LLM_BATCH_SIZE = 12
KNOCKOUT_SOURCE_URL = "https://www.fifa.com/en/articles/knockout-stage-match-schedule-bracket"
SCHEDULE_SOURCE_URL = (
    "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/"
    "articles/match-schedule-fixtures-results-teams-stadiums"
)


@dataclass(slots=True)
class SimulatedResult:
    home_goals_90: int
    away_goals_90: int
    qualified_team: str | None = None
    resolution: str = "90"
    home_goals_aet: int | None = None
    away_goals_aet: int | None = None
    penalties_home: int | None = None
    penalties_away: int | None = None
    reason: str = ""


ROUND_OF_32 = [
    {"match_no": 73, "date": "2026-06-28", "venue": "Los Angeles Stadium", "a": ("group", "A", 2), "b": ("group", "B", 2)},
    {"match_no": 74, "date": "2026-06-29", "venue": "Boston Stadium", "a": ("group", "E", 1), "b": ("third", "ABCDF")},
    {"match_no": 75, "date": "2026-06-29", "venue": "Estadio Monterrey", "a": ("group", "F", 1), "b": ("group", "C", 2)},
    {"match_no": 76, "date": "2026-06-29", "venue": "Houston Stadium", "a": ("group", "C", 1), "b": ("group", "F", 2)},
    {"match_no": 77, "date": "2026-06-30", "venue": "New York New Jersey Stadium", "a": ("group", "I", 1), "b": ("third", "CDFGH")},
    {"match_no": 78, "date": "2026-06-30", "venue": "Dallas Stadium", "a": ("group", "E", 2), "b": ("group", "I", 2)},
    {"match_no": 79, "date": "2026-06-30", "venue": "Mexico City Stadium", "a": ("group", "A", 1), "b": ("third", "CEFHI")},
    {"match_no": 80, "date": "2026-07-01", "venue": "Atlanta Stadium", "a": ("group", "L", 1), "b": ("third", "EHIJK")},
    {"match_no": 81, "date": "2026-07-01", "venue": "San Francisco Bay Area Stadium", "a": ("group", "D", 1), "b": ("third", "BEFIJ")},
    {"match_no": 82, "date": "2026-07-01", "venue": "Seattle Stadium", "a": ("group", "G", 1), "b": ("third", "AEHIJ")},
    {"match_no": 83, "date": "2026-07-02", "venue": "Toronto Stadium", "a": ("group", "K", 2), "b": ("group", "L", 2)},
    {"match_no": 84, "date": "2026-07-02", "venue": "Los Angeles Stadium", "a": ("group", "H", 1), "b": ("group", "J", 2)},
    {"match_no": 85, "date": "2026-07-02", "venue": "BC Place Vancouver", "a": ("group", "B", 1), "b": ("third", "EFGIJ")},
    {"match_no": 86, "date": "2026-07-03", "venue": "Miami Stadium", "a": ("group", "J", 1), "b": ("group", "H", 2)},
    {"match_no": 87, "date": "2026-07-03", "venue": "Kansas City Stadium", "a": ("group", "K", 1), "b": ("third", "DEIJL")},
    {"match_no": 88, "date": "2026-07-03", "venue": "Dallas Stadium", "a": ("group", "D", 2), "b": ("group", "G", 2)},
]

NEXT_ROUNDS = [
    {"match_no": 89, "round": "Ottavi", "date": "2026-07-04", "venue": "Philadelphia Stadium", "a": 74, "b": 77},
    {"match_no": 90, "round": "Ottavi", "date": "2026-07-04", "venue": "Houston Stadium", "a": 73, "b": 75},
    {"match_no": 91, "round": "Ottavi", "date": "2026-07-05", "venue": "New York New Jersey Stadium", "a": 76, "b": 78},
    {"match_no": 92, "round": "Ottavi", "date": "2026-07-05", "venue": "Mexico City Stadium", "a": 79, "b": 80},
    {"match_no": 93, "round": "Ottavi", "date": "2026-07-06", "venue": "Dallas Stadium", "a": 83, "b": 84},
    {"match_no": 94, "round": "Ottavi", "date": "2026-07-06", "venue": "Seattle Stadium", "a": 81, "b": 82},
    {"match_no": 95, "round": "Ottavi", "date": "2026-07-07", "venue": "Atlanta Stadium", "a": 86, "b": 88},
    {"match_no": 96, "round": "Ottavi", "date": "2026-07-07", "venue": "BC Place Vancouver", "a": 85, "b": 87},
    {"match_no": 97, "round": "Quarti", "date": "2026-07-09", "venue": "Boston Stadium", "a": 89, "b": 90},
    {"match_no": 98, "round": "Quarti", "date": "2026-07-10", "venue": "Los Angeles Stadium", "a": 93, "b": 94},
    {"match_no": 99, "round": "Quarti", "date": "2026-07-11", "venue": "Miami Stadium", "a": 91, "b": 92},
    {"match_no": 100, "round": "Quarti", "date": "2026-07-11", "venue": "Kansas City Stadium", "a": 95, "b": 96},
    {"match_no": 101, "round": "Semifinale", "date": "2026-07-14", "venue": "Dallas Stadium", "a": 97, "b": 98},
    {"match_no": 102, "round": "Semifinale", "date": "2026-07-15", "venue": "Atlanta Stadium", "a": 99, "b": 100},
]


class WorldCupSimulator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.prediction_service = PredictionService(settings)
        self.gemini = GeminiClient(settings)
        self.sqlite_storage = SQLiteStorage(settings.sqlite_path)
        self.supabase_storage = SupabaseStorage(settings)

    def simulate(
        self,
        manual_overrides: dict[str, dict[str, int]] | None = None,
        label: str = "Road To New York",
        save: bool = True,
        use_llm: bool = True,
    ) -> dict[str, Any]:
        manual_overrides = manual_overrides or {}
        generated_at = datetime.now(timezone.utc)
        run_seed = generated_at.isoformat()
        run_id = hashlib.sha1(run_seed.encode("utf-8")).hexdigest()[:16]
        rng = random.Random(run_id)
        errors: list[str] = []

        matches = self.prediction_service.openligadb.worldcup_matches()
        group_matches = [match for match in matches if _is_group_stage_match(match)]
        group_matches.sort(key=lambda item: item.match_date)
        group_lookup = _build_group_lookup(group_matches)
        teams = sorted({team for match in group_matches for team in (match.home_team, match.away_team)})
        articles = self.prediction_service._load_news(teams, errors)
        ratings = self.prediction_service._load_team_ratings(WORLD_CUP_START, group_matches, errors)
        stats_builder = self.prediction_service._load_historical_stats(WORLD_CUP_START, group_matches, errors)

        group_prediction_rows: list[tuple[str, Match, MatchPrediction]] = []
        for match in group_matches:
            group = group_lookup.get(match.id) or _group_letter(match)
            if not group:
                continue
            prediction = self.prediction_service._predict_match(match, [], articles, errors, ratings, stats_builder)
            group_prediction_rows.append((group, match, prediction))

        group_results: dict[str, list[dict[str, Any]]] = {group: [] for group in GROUPS}
        group_prediction_results = self._results_for_predictions(
            [prediction for _, _, prediction in group_prediction_rows],
            knockout=False,
            errors=errors,
            manual_overrides=manual_overrides,
            use_llm=use_llm,
        )
        for group, match, prediction in group_prediction_rows:
            result = group_prediction_results.get(match.id) or _fallback_result(prediction, knockout=False)
            group_results[group].append(_group_match_payload(match, group, prediction, result))

        groups = {
            group: {
                "matches": group_results[group],
                "standings": _group_standings(group_results[group], rng),
            }
            for group in GROUPS
            if group_results[group]
        }
        third_rankings = _third_rankings(groups, rng)
        qualified_thirds = third_rankings[:8]
        third_assignments, assignment_warnings = _assign_thirds(qualified_thirds)
        errors.extend(assignment_warnings)

        knockout_matches: list[dict[str, Any]] = []
        knockout_index: dict[int, dict[str, Any]] = {}
        if len(groups) < len(GROUPS):
            errors.append(
                f"Bracket non simulato: trovati {len(groups)} gironi completi/parziali su {len(GROUPS)}. "
                "Evito placeholder tipo A2 o Terza classificata."
            )
        else:
            try:
                knockout_matches, knockout_index = self._simulate_knockout(
                    groups=groups,
                    third_assignments=third_assignments,
                    ratings=ratings,
                    stats_builder=stats_builder,
                    articles=articles,
                    errors=errors,
                    use_llm=use_llm,
                )
            except ValueError as exc:
                errors.append(f"Bracket non simulato: {exc}")
        final = knockout_index.get(104)
        third_place = knockout_index.get(103)
        payload: dict[str, Any] = {
            "run_id": run_id,
            "label": label,
            "generated_at": generated_at.isoformat(),
            "model": self.settings.gemini_model,
            "simulation_mode": "llm" if use_llm else "statistics",
            "source_urls": [KNOCKOUT_SOURCE_URL, SCHEDULE_SOURCE_URL],
            "champion": final.get("qualified_team") if final else None,
            "runner_up": final.get("loser") if final else None,
            "third_place": third_place.get("qualified_team") if third_place else None,
            "groups": groups,
            "third_rankings": qualified_thirds,
            "third_assignments": third_assignments,
            "knockout": knockout_matches,
            "warnings": errors,
            "manual_overrides": manual_overrides,
        }
        if save:
            self.save_simulation(payload)
        return payload

    def save_simulation(self, payload: dict[str, Any]) -> None:
        run_id = str(payload["run_id"])
        generated_at = str(payload["generated_at"])
        label = str(payload.get("label") or "Road To New York")
        model = str(payload.get("model") or self.settings.gemini_model)
        self.sqlite_storage.insert_worldcup_simulation(run_id, generated_at, label, model, payload)
        self.supabase_storage.insert_worldcup_simulation(run_id, generated_at, label, model, payload)

    def list_simulations(self, limit: int = 8) -> list[dict[str, Any]]:
        rows = self.supabase_storage.list_worldcup_simulations(limit)
        rows.extend(self.sqlite_storage.list_worldcup_simulations(limit))
        unique: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.get("run_id"):
                unique[str(row["run_id"])] = row
        return sorted(unique.values(), key=lambda item: item.get("generated_at", ""), reverse=True)[:limit]

    def latest_simulation(self) -> dict[str, Any] | None:
        rows = self.list_simulations(1)
        return rows[0]["payload"] if rows else None

    def _results_for_predictions(
        self,
        predictions: list[MatchPrediction],
        knockout: bool,
        errors: list[str],
        manual_overrides: dict[str, dict[str, int]] | None = None,
        use_llm: bool = True,
    ) -> dict[str, SimulatedResult]:
        manual_overrides = manual_overrides or {}
        results: dict[str, SimulatedResult] = {}
        pending: list[MatchPrediction] = []
        for prediction in predictions:
            match_id = prediction.match.id
            override = manual_overrides.get(match_id)
            if override:
                results[match_id] = SimulatedResult(
                    home_goals_90=max(0, int(override.get("home_goals", 0))),
                    away_goals_90=max(0, int(override.get("away_goals", 0))),
                    reason="Risultato modificato manualmente.",
                )
                continue
            actual = _actual_result(prediction.match)
            if actual:
                results[match_id] = actual
                continue
            results[match_id] = _fallback_result(prediction, knockout)
            pending.append(prediction)

        if not use_llm or not self.settings.has_gemini or not pending:
            return results

        for chunk in _chunks(pending, LLM_BATCH_SIZE):
            try:
                payload = self.gemini.generate_json(_batch_result_prompt(chunk, knockout))
            except Exception as exc:
                errors.append(f"Batch Gemini risultati non disponibile: {exc}")
                continue
            parsed = _parse_llm_batch_results(payload, chunk, knockout)
            for prediction in chunk:
                result = parsed.get(prediction.match.id)
                if not result:
                    continue
                if knockout:
                    result = _normalize_knockout_result(prediction, result)
                results[prediction.match.id] = result
        return results

    def _simulate_knockout(
        self,
        groups: dict[str, dict[str, Any]],
        third_assignments: dict[int, dict[str, Any]],
        ratings: dict[str, int],
        stats_builder: Any,
        articles: list[Any],
        errors: list[str],
        use_llm: bool,
    ) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
        results: list[dict[str, Any]] = []
        index: dict[int, dict[str, Any]] = {}

        for slot in ROUND_OF_32:
            home = _resolve_slot(slot["a"], groups, third_assignments, int(slot["match_no"]))
            away = _resolve_slot(slot["b"], groups, third_assignments, int(slot["match_no"]))
            row = self._simulate_knockout_match(slot, "Sedicesimi", home, away, ratings, stats_builder, articles, errors, use_llm)
            results.append(row)
            index[int(slot["match_no"])] = row

        for slot in NEXT_ROUNDS:
            home = index[int(slot["a"])]["qualified_team"]
            away = index[int(slot["b"])]["qualified_team"]
            row = self._simulate_knockout_match(slot, str(slot["round"]), home, away, ratings, stats_builder, articles, errors, use_llm)
            results.append(row)
            index[int(slot["match_no"])] = row

        bronze_slot = {"match_no": 103, "round": "Terzo posto", "date": "2026-07-18", "venue": "Miami Stadium"}
        bronze = self._simulate_knockout_match(
            bronze_slot,
            "Terzo posto",
            index[101]["loser"],
            index[102]["loser"],
            ratings,
            stats_builder,
            articles,
            errors,
            use_llm,
        )
        results.append(bronze)
        index[103] = bronze

        final_slot = {"match_no": 104, "round": "Finale", "date": "2026-07-19", "venue": "New York New Jersey Stadium"}
        final = self._simulate_knockout_match(
            final_slot,
            "Finale",
            index[101]["qualified_team"],
            index[102]["qualified_team"],
            ratings,
            stats_builder,
            articles,
            errors,
            use_llm,
        )
        results.append(final)
        index[104] = final
        return results, index

    def _simulate_knockout_match(
        self,
        slot: dict[str, Any],
        round_name: str,
        home: str,
        away: str,
        ratings: dict[str, int],
        stats_builder: Any,
        articles: list[Any],
        errors: list[str],
        use_llm: bool,
    ) -> dict[str, Any]:
        match = Match(
            id=f"worldcup-sim-{slot['match_no']}",
            source="simulation",
            competition="FIFA World Cup 2026",
            season=2026,
            match_date=datetime.fromisoformat(str(slot["date"])).replace(tzinfo=timezone.utc),
            home_team=home,
            away_team=away,
            status="SCHEDULED",
            venue=str(slot.get("venue", "")),
            stage=round_name,
            raw={"neutral": True},
        )
        prediction = self.prediction_service._predict_match(match, [], articles, errors, ratings, stats_builder)
        result = self._result_for_match(prediction, knockout=True, use_llm=use_llm)
        qualified = result.qualified_team or _fallback_qualified_team(prediction, result)
        loser = away if qualified == home else home
        return {
            "match_no": int(slot["match_no"]),
            "round": round_name,
            "date": str(slot["date"]),
            "venue": str(slot.get("venue", "")),
            "source_a": _slot_source_label(slot.get("a")),
            "source_b": _slot_source_label(slot.get("b")),
            "home_team": home,
            "away_team": away,
            "score_90": f"{result.home_goals_90}-{result.away_goals_90}",
            "score_aet": _score_aet(result),
            "penalties": _penalties(result),
            "resolution": result.resolution,
            "qualified_team": qualified,
            "loser": loser,
            "reason": result.reason,
            "confidence": prediction.confidence,
        }

    def _result_for_match(
        self,
        prediction: MatchPrediction,
        knockout: bool,
        override: dict[str, int] | None = None,
        use_llm: bool = True,
    ) -> SimulatedResult:
        if override:
            return SimulatedResult(
                home_goals_90=max(0, int(override.get("home_goals", 0))),
                away_goals_90=max(0, int(override.get("away_goals", 0))),
                reason="Risultato modificato manualmente.",
            )
        actual = _actual_result(prediction.match)
        if actual:
            return actual
        fallback = _fallback_result(prediction, knockout)
        if not use_llm or not self.settings.has_gemini:
            return fallback
        prompt = _result_prompt(prediction, knockout)
        try:
            payload = self.gemini.generate_json(prompt)
        except Exception as exc:
            prediction.warnings.append(f"Risultato Gemini non disponibile: {exc}")
            return fallback
        result = _parse_llm_result(payload, prediction, knockout)
        if not result:
            return fallback
        if knockout:
            return _normalize_knockout_result(prediction, result)
        return result


def _result_prompt(prediction: MatchPrediction, knockout: bool) -> str:
    markets = "\n".join(
        f"- {pick.market} | {pick.selection} | statistica {pick.probability:.3f} | "
        f"modello {pick.llm_probability if pick.llm_probability is not None else '-'}"
        for pick in prediction.picks[:14]
    )
    stats = "\n".join(f"- {note}" for note in prediction.stats_notes) or "Nessuna nota statistica."
    tables = []
    for title, rows in prediction.stats_tables.items():
        tables.append(title)
        for row in rows[:6]:
            tables.append(f"- {row.get('Data', '')}: {row.get('Partita', '')} {row.get('Risultato', '')}")
    mode = "eliminazione diretta" if knockout else "girone"
    return f"""
Sei un modello di simulazione calcistica per il Mondiale 2026.
Devi stimare il risultato della partita usando SOLO dati ricevuti.

Partita: {prediction.match.label}
Fase: {mode}
Risultato statistico iniziale: {prediction.exact_score}
Sintesi: {prediction.summary}

Statistiche:
{stats}

Storico:
{chr(10).join(tables) or "Nessuno storico."}

Mercati:
{markets}

Restituisci JSON valido.
Se fase e' girone:
{{
  "home_goals_90": 0,
  "away_goals_90": 0,
  "reason": "motivo breve in italiano"
}}

Se fase e' eliminazione diretta:
{{
  "home_goals_90": 0,
  "away_goals_90": 0,
  "home_goals_aet": 0,
  "away_goals_aet": 0,
  "penalties_home": null,
  "penalties_away": null,
  "qualified_team": "nome esatto squadra qualificata",
  "resolution": "90|ET|PEN",
  "reason": "motivo breve in italiano"
}}

Regole:
- Nei gironi il risultato si ferma al 90'.
- A eliminazione diretta, se pari al 90', puoi usare supplementari; se pari dopo supplementari, usa rigori.
- I gol devono essere interi tra 0 e 8.
- Usa solo JSON, senza markdown.
"""


def _batch_result_prompt(predictions: list[MatchPrediction], knockout: bool) -> str:
    mode = "eliminazione diretta" if knockout else "girone"
    matches = []
    for prediction in predictions:
        picks = [
            {
                "market": pick.market,
                "selection": pick.selection,
                "probability": round(float(pick.average_probability), 4),
            }
            for pick in prediction.picks
            if pick.market in {"1X2", "Over/Under 2.5", "Goal/No Goal", "Passaggio turno"}
        ][:12]
        matches.append(
            {
                "match_id": prediction.match.id,
                "home_team": prediction.match.home_team,
                "away_team": prediction.match.away_team,
                "phase": mode,
                "statistical_exact_score": prediction.exact_score,
                "summary": prediction.summary,
                "stats_notes": prediction.stats_notes[:5],
                "markets": picks,
            }
        )
    knockout_schema = """
    {
      "match_id": "id esatto ricevuto",
      "home_goals_90": 0,
      "away_goals_90": 0,
      "home_goals_aet": 0,
      "away_goals_aet": 0,
      "penalties_home": null,
      "penalties_away": null,
      "qualified_team": "nome esatto squadra qualificata",
      "resolution": "90|ET|PEN",
      "reason": "motivo breve in italiano"
    }
    """
    group_schema = """
    {
      "match_id": "id esatto ricevuto",
      "home_goals_90": 0,
      "away_goals_90": 0,
      "reason": "motivo breve in italiano"
    }
    """
    schema = knockout_schema if knockout else group_schema
    return f"""
Sei un simulatore calcistico per il Mondiale 2026.
Devi stimare risultati realistici usando SOLO i dati forniti.

Fase: {mode}
Partite:
{json_dumps(matches)}

Restituisci JSON valido in questo formato:
{{
  "results": [
    {schema}
  ]
}}

Regole:
- Rispondi con una riga per ogni match_id ricevuto.
- Non usare markdown.
- I gol devono essere interi tra 0 e 8.
- Nei gironi il risultato si ferma al 90'.
- A eliminazione diretta, se pari al 90', usa supplementari; se pari dopo supplementari, usa rigori.
- qualified_team deve essere esattamente una delle due squadre della partita.
"""


def _parse_llm_batch_results(
    payload: Any,
    predictions: list[MatchPrediction],
    knockout: bool,
) -> dict[str, SimulatedResult]:
    if isinstance(payload, dict):
        rows = payload.get("results") or payload.get("matches") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    if not isinstance(rows, list):
        return {}
    by_id = {prediction.match.id: prediction for prediction in predictions}
    results: dict[str, SimulatedResult] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        match_id = str(row.get("match_id") or row.get("id") or "")
        prediction = by_id.get(match_id)
        if not prediction:
            continue
        result = _parse_llm_result(row, prediction, knockout)
        if result:
            results[match_id] = result
    return results


def _chunks(items: list[MatchPrediction], size: int) -> list[list[MatchPrediction]]:
    return [items[index : index + size] for index in range(0, len(items), max(1, size))]


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _parse_llm_result(payload: Any, prediction: MatchPrediction, knockout: bool) -> SimulatedResult | None:
    if not isinstance(payload, dict):
        return None
    try:
        home = _bounded_goal(payload.get("home_goals_90"))
        away = _bounded_goal(payload.get("away_goals_90"))
    except (TypeError, ValueError):
        return None
    result = SimulatedResult(home_goals_90=home, away_goals_90=away)
    result.reason = str(payload.get("reason", "")).strip()
    if knockout:
        result.home_goals_aet = _optional_goal(payload.get("home_goals_aet"), home)
        result.away_goals_aet = _optional_goal(payload.get("away_goals_aet"), away)
        result.penalties_home = _optional_goal(payload.get("penalties_home"), None)
        result.penalties_away = _optional_goal(payload.get("penalties_away"), None)
        result.resolution = str(payload.get("resolution", "90")).strip().upper() or "90"
        qualified = str(payload.get("qualified_team", "")).strip()
        if qualified in {prediction.match.home_team, prediction.match.away_team}:
            result.qualified_team = qualified
    return result


def _fallback_result(prediction: MatchPrediction, knockout: bool) -> SimulatedResult:
    home, away = _fallback_score_from_probabilities(prediction)
    result = SimulatedResult(home_goals_90=home, away_goals_90=away, reason="Fallback statistico.")
    if knockout:
        result.qualified_team = _fallback_qualified_team(prediction, result)
        if home == away:
            result.resolution = "PEN"
            if result.qualified_team == prediction.match.home_team:
                result.penalties_home, result.penalties_away = 5, 4
            else:
                result.penalties_home, result.penalties_away = 4, 5
    return result


def _fallback_score_from_probabilities(prediction: MatchPrediction) -> tuple[int, int]:
    one_x_two = [pick for pick in prediction.picks if pick.market == "1X2"]
    home_probability = _selection_probability(one_x_two, prediction.match.home_team, 0.37)
    draw_probability = _selection_probability(one_x_two, "Pareggio", 0.29)
    away_probability = _selection_probability(one_x_two, prediction.match.away_team, 0.34)
    over_probability = _market_probability(prediction.picks, "Over/Under 2.5", "Over", 0.47)
    goal_probability = _market_probability(prediction.picks, "Goal/No Goal", "Goal", 0.50)

    parsed = _parse_score(prediction.exact_score)
    if parsed:
        home, away = parsed
        edge = abs(home_probability - away_probability)
        favorite_probability = max(home_probability, away_probability)
        if home != away or edge < 0.10 or favorite_probability < draw_probability + 0.08:
            return home, away

    seed = hashlib.sha1(
        f"{prediction.match.id}|{prediction.match.home_team}|{prediction.match.away_team}".encode("utf-8")
    ).hexdigest()
    rng = random.Random(seed)
    edge = home_probability - away_probability
    favorite_probability = max(home_probability, away_probability)

    if abs(edge) < 0.08 and draw_probability >= 0.25:
        if over_probability >= 0.60 and goal_probability >= 0.52:
            return (2, 2) if rng.random() < 0.35 else (1, 1)
        if goal_probability < 0.44:
            return (0, 0) if rng.random() < 0.45 else (1, 1)
        return (1, 1)

    favorite_goals = 1
    if favorite_probability >= 0.48 or over_probability >= 0.52:
        favorite_goals += 1
    if favorite_probability >= 0.62 or (over_probability >= 0.64 and rng.random() < 0.55):
        favorite_goals += 1
    underdog_goals = 0
    if goal_probability >= 0.50 and over_probability >= 0.43:
        underdog_goals = 1 if rng.random() < 0.72 else 0
    if favorite_goals == underdog_goals:
        favorite_goals += 1

    if edge >= 0:
        return favorite_goals, underdog_goals
    return underdog_goals, favorite_goals


def _selection_probability(picks: list[Any], selection: str, default: float) -> float:
    for pick in picks:
        if str(pick.selection).lower() == selection.lower():
            return float(pick.average_probability)
    return default


def _market_probability(picks: list[Any], market: str, selection_prefix: str, default: float) -> float:
    for pick in picks:
        if pick.market == market and str(pick.selection).lower().startswith(selection_prefix.lower()):
            return float(pick.average_probability)
    return default


def _parse_score(value: str) -> tuple[int, int] | None:
    try:
        home, away = [int(part.strip()) for part in value.split("-", 1)]
    except (ValueError, AttributeError):
        return None
    return max(0, home), max(0, away)


def _normalize_knockout_result(prediction: MatchPrediction, result: SimulatedResult) -> SimulatedResult:
    home_team = prediction.match.home_team
    away_team = prediction.match.away_team
    if result.home_goals_90 > result.away_goals_90:
        result.resolution = "90"
        result.qualified_team = home_team
        result.home_goals_aet = None
        result.away_goals_aet = None
        result.penalties_home = None
        result.penalties_away = None
        return result
    if result.away_goals_90 > result.home_goals_90:
        result.resolution = "90"
        result.qualified_team = away_team
        result.home_goals_aet = None
        result.away_goals_aet = None
        result.penalties_home = None
        result.penalties_away = None
        return result

    result.home_goals_aet = result.home_goals_aet if result.home_goals_aet is not None else result.home_goals_90
    result.away_goals_aet = result.away_goals_aet if result.away_goals_aet is not None else result.away_goals_90
    if result.home_goals_aet > result.away_goals_aet:
        result.resolution = "ET"
        result.qualified_team = home_team
        result.penalties_home = None
        result.penalties_away = None
        return result
    if result.away_goals_aet > result.home_goals_aet:
        result.resolution = "ET"
        result.qualified_team = away_team
        result.penalties_home = None
        result.penalties_away = None
        return result

    result.resolution = "PEN"
    if result.qualified_team not in {home_team, away_team}:
        result.qualified_team = _fallback_qualified_team(prediction, result)
    if (
        result.penalties_home is None
        or result.penalties_away is None
        or result.penalties_home == result.penalties_away
    ):
        if result.qualified_team == home_team:
            result.penalties_home, result.penalties_away = 5, 4
        else:
            result.penalties_home, result.penalties_away = 4, 5
    return result


def _fallback_qualified_team(prediction: MatchPrediction, result: SimulatedResult) -> str:
    if result.home_goals_90 > result.away_goals_90:
        return prediction.match.home_team
    if result.away_goals_90 > result.home_goals_90:
        return prediction.match.away_team
    passaggio = [pick for pick in prediction.picks if pick.market == "Passaggio turno"]
    if passaggio:
        return max(passaggio, key=lambda pick: pick.average_probability).selection
    one_x_two = [pick for pick in prediction.picks if pick.market == "1X2" and pick.selection != "Pareggio"]
    return max(one_x_two, key=lambda pick: pick.average_probability).selection if one_x_two else prediction.match.home_team


def _group_match_payload(match: Match, group: str, prediction: MatchPrediction, result: SimulatedResult) -> dict[str, Any]:
    return {
        "match_id": match.id,
        "date": match.match_date.date().isoformat(),
        "group": group,
        "home_team": match.home_team,
        "away_team": match.away_team,
        "score_90": f"{result.home_goals_90}-{result.away_goals_90}",
        "home_goals": result.home_goals_90,
        "away_goals": result.away_goals_90,
        "reason": result.reason,
        "confidence": prediction.confidence,
    }


def _group_standings(matches: list[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {}
    for match in matches:
        for team in (match["home_team"], match["away_team"]):
            table.setdefault(
                team,
                {
                    "team": team,
                    "played": 0,
                    "wins": 0,
                    "draws": 0,
                    "losses": 0,
                    "points": 0,
                    "goals_for": 0,
                    "goals_against": 0,
                    "goal_difference": 0,
                    "_random": rng.random(),
                },
            )
        home, away = match["home_team"], match["away_team"]
        hg, ag = int(match["home_goals"]), int(match["away_goals"])
        table[home]["played"] += 1
        table[away]["played"] += 1
        table[home]["goals_for"] += hg
        table[home]["goals_against"] += ag
        table[away]["goals_for"] += ag
        table[away]["goals_against"] += hg
        if hg > ag:
            table[home]["wins"] += 1
            table[away]["losses"] += 1
            table[home]["points"] += 3
        elif ag > hg:
            table[away]["wins"] += 1
            table[home]["losses"] += 1
            table[away]["points"] += 3
        else:
            table[home]["draws"] += 1
            table[away]["draws"] += 1
            table[home]["points"] += 1
            table[away]["points"] += 1
    for row in table.values():
        row["goal_difference"] = row["goals_for"] - row["goals_against"]
    ranked = sorted(
        table.values(),
        key=lambda row: (
            -row["points"],
            -row["goal_difference"],
            -row["goals_for"],
            row["goals_against"],
            row["_random"],
        ),
    )
    for pos, row in enumerate(ranked, start=1):
        row["position"] = pos
        row.pop("_random", None)
    return ranked


def _third_rankings(groups: dict[str, dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    rows = []
    for group, payload in groups.items():
        standings = payload.get("standings") or []
        if len(standings) >= 3:
            row = dict(standings[2])
            row["group"] = group
            row["_random"] = rng.random()
            rows.append(row)
    rows.sort(
        key=lambda row: (
            -row["points"],
            -row["goal_difference"],
            -row["goals_for"],
            row["goals_against"],
            row["_random"],
        )
    )
    for pos, row in enumerate(rows, start=1):
        row["third_rank"] = pos
        row.pop("_random", None)
    return rows


def _assign_thirds(qualified_thirds: list[dict[str, Any]]) -> tuple[dict[int, dict[str, Any]], list[str]]:
    available = {row["group"]: row for row in qualified_thirds}
    third_slots: list[tuple[int, list[str]]] = []
    for slot in ROUND_OF_32:
        candidate = slot.get("b")
        if isinstance(candidate, tuple) and candidate[0] == "third":
            third_slots.append((int(slot["match_no"]), list(str(candidate[1]))))

    ordered_slots = sorted(
        third_slots,
        key=lambda item: len([group for group in item[1] if group in available]),
    )
    chosen_by_match: dict[int, str] = {}

    def search(index: int, used: set[str]) -> bool:
        if index >= len(ordered_slots):
            return True
        match_no, allowed = ordered_slots[index]
        for group in allowed:
            if group not in available or group in used:
                continue
            chosen_by_match[match_no] = group
            if search(index + 1, used | {group}):
                return True
            chosen_by_match.pop(match_no, None)
        return False

    if search(0, set()):
        return {match_no: available[group] for match_no, group in chosen_by_match.items()}, []

    warnings: list[str] = []
    used: set[str] = set()
    assignments: dict[int, dict[str, Any]] = {}
    for match_no, allowed in third_slots:
        chosen = next((available[group] for group in allowed if group in available and group not in used), None)
        if chosen is None:
            chosen = next((row for row in qualified_thirds if row["group"] not in used), None)
            warnings.append(
                f"Assegnazione terza M{match_no}: combinazione non risolta con i vincoli disponibili."
            )
        if chosen:
            used.add(chosen["group"])
            assignments[match_no] = chosen
    return assignments, warnings


def _resolve_slot(slot: tuple, groups: dict[str, dict[str, Any]], third_assignments: dict[int, dict[str, Any]], match_no: int) -> str:
    if slot[0] == "third":
        row = third_assignments.get(match_no)
        if not row:
            raise ValueError(f"terza classificata non risolta per M{match_no}")
        return row["team"]
    _, group, position = slot
    standings = groups.get(group, {}).get("standings") or []
    if len(standings) < int(position):
        raise ValueError(f"slot {group}{position} non risolto")
    return standings[int(position) - 1]["team"]


def _slot_source_label(slot: Any) -> str:
    if isinstance(slot, int):
        return f"vincente M{slot:03d}"
    if not isinstance(slot, tuple) or not slot:
        return ""
    if slot[0] == "third":
        return f"terza da {slot[1]}"
    if slot[0] == "group":
        return f"{slot[1]}{slot[2]}"
    return ""


def _group_letter(match: Match) -> str | None:
    raw_group = match.raw.get("matchGroup") or match.raw.get("group") or {}
    value = f"{match.stage or ''} {raw_group.get('groupName', '')} {raw_group}".upper()
    match_obj = re.search(r"\bGROUP\s+([A-L])\b|\bGRUPPE\s+([A-L])\b|\bGIRONE\s+([A-L])\b", value)
    if match_obj:
        return next(part for part in match_obj.groups() if part)
    for letter in GROUPS:
        if f" {letter}" in value or value.endswith(letter):
            return letter
    return None


def _is_group_stage_match(match: Match) -> bool:
    raw_group = match.raw.get("matchGroup") or match.raw.get("group") or {}
    group_name = str(raw_group.get("groupName") or match.stage or "").lower()
    group_order = raw_group.get("groupOrderID")
    if "gruppenphase" in group_name or "group stage" in group_name or "gironi" in group_name:
        return True
    if isinstance(group_order, int) and 1 <= group_order <= 3:
        competition = match.competition.lower()
        return "world cup" in competition or "wm 2026" in competition
    return _group_letter(match) in GROUPS


def _build_group_lookup(matches: list[Match]) -> dict[str, str]:
    if not matches:
        return {}
    parent: dict[str, str] = {}

    def find(team: str) -> str:
        parent.setdefault(team, team)
        if parent[team] != team:
            parent[team] = find(parent[team])
        return parent[team]

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for match in matches:
        union(match.home_team, match.away_team)

    components: dict[str, set[str]] = {}
    for team in list(parent):
        components.setdefault(find(team), set()).add(team)

    component_rows = []
    for root, teams in components.items():
        first_match = min(
            (match.match_date for match in matches if match.home_team in teams and match.away_team in teams),
            default=datetime.max.replace(tzinfo=timezone.utc),
        )
        component_rows.append((first_match, sorted(teams), root))
    component_rows.sort(key=lambda item: (item[0], item[1]))

    group_by_root = {
        root: GROUPS[index]
        for index, (_, _, root) in enumerate(component_rows[: len(GROUPS)])
    }
    lookup: dict[str, str] = {}
    for match in matches:
        group = group_by_root.get(find(match.home_team))
        if group:
            lookup[match.id] = group
    return lookup


def _actual_result(match: Match) -> SimulatedResult | None:
    raw = match.raw or {}
    if not raw.get("matchIsFinished"):
        return None
    results = raw.get("matchResults") or []
    if not results:
        return None
    result = results[-1]
    try:
        return SimulatedResult(
            home_goals_90=int(result.get("pointsTeam1")),
            away_goals_90=int(result.get("pointsTeam2")),
            reason="Risultato reale OpenLigaDB.",
        )
    except (TypeError, ValueError):
        return None


def _bounded_goal(value: Any) -> int:
    return max(0, min(8, int(value)))


def _optional_goal(value: Any, default: int | None) -> int | None:
    if value is None:
        return default
    try:
        return _bounded_goal(value)
    except (TypeError, ValueError):
        return default


def _score_aet(result: SimulatedResult) -> str:
    if result.home_goals_aet is None or result.away_goals_aet is None:
        return "-"
    if result.home_goals_aet == result.home_goals_90 and result.away_goals_aet == result.away_goals_90:
        return "-"
    return f"{result.home_goals_aet}-{result.away_goals_aet}"


def _penalties(result: SimulatedResult) -> str:
    if result.penalties_home is None or result.penalties_away is None:
        return "-"
    return f"{result.penalties_home}-{result.penalties_away}"


WORLD_CUP_START = date(2026, 6, 11)
