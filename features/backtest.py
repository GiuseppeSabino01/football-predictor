from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Any

import pandas as pd

from features.historical_stats import HistoricalStatsBuilder, frame_is_usable
from models.ensemble import EnsemblePredictor
from schemas import Match, MarketPick


@dataclass(slots=True)
class BacktestMarketMetrics:
    market: str
    samples: int
    hit_rate: float
    brier_score: float
    avg_probability: float
    calibration_gap: float
    reliability: str


@dataclass(slots=True)
class BacktestReport:
    generated_at: datetime
    start_date: str
    end_date: str
    samples: int
    markets: list[BacktestMarketMetrics]
    recent_rows: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class HistoricalBacktester:
    def __init__(self, predictor: EnsemblePredictor | None = None):
        self.predictor = predictor or EnsemblePredictor()

    def run(
        self,
        results: pd.DataFrame,
        *,
        max_matches: int = 160,
        min_team_matches: int = 5,
        min_h2h_matches: int = 0,
    ) -> BacktestReport:
        if not frame_is_usable(results):
            return _empty_report(["Storico non disponibile: impossibile misurare affidabilita."])

        frame = _clean_results(results)
        if frame.empty:
            return _empty_report(["Storico vuoto dopo la pulizia dei dati."])

        records = frame.sort_values("date").to_dict("records")
        candidates = list(reversed(records))[: max_matches * 4]
        evaluations: list[dict[str, Any]] = []
        recent_rows: list[dict[str, str]] = []

        for row in candidates:
            prior = frame[frame["date"] < row["date"]]
            if len(prior) < max(6, min_team_matches * 2):
                continue
            if not frame_is_usable(prior):
                continue

            builder = HistoricalStatsBuilder(prior)
            stats = builder.build(row["home_team"], row["away_team"])
            if stats.home_recent.matches < min_team_matches or stats.away_recent.matches < min_team_matches:
                continue
            if stats.h2h.matches < min_h2h_matches:
                continue

            match = _match_from_row(row)
            prediction = self.predictor.predict(match, historical_stats=stats)
            home_score = int(row["home_score"])
            away_score = int(row["away_score"])
            match_evaluations = _evaluate_prediction(prediction.picks, home_score, away_score)
            for evaluation in match_evaluations:
                evaluation["date"] = row["date"]
            if not match_evaluations:
                continue
            evaluations.extend(match_evaluations)
            recent_rows.extend(_recent_rows(row, match_evaluations))
            if _match_sample_count(evaluations) >= max_matches:
                break

        if not evaluations:
            return _empty_report(["Campione storico insufficiente per un backtest utile."])

        markets = [_metrics_for_market(market, evaluations) for market in _market_order(evaluations)]
        match_dates = [evaluation["date"] for evaluation in evaluations]
        return BacktestReport(
            generated_at=datetime.now(timezone.utc),
            start_date=str(min(match_dates)),
            end_date=str(max(match_dates)),
            samples=_match_sample_count(evaluations),
            markets=markets,
            recent_rows=recent_rows[:12],
            notes=[
                "Backtest su nazionali: ogni partita viene stimata usando solo storico precedente alla partita.",
                "Brier score: piu basso e' meglio; gap calibrazione: distanza tra probabilita media e hit-rate reale.",
                "ROI non calcolato: servirebbero quote bookmaker storiche gratuite e affidabili.",
            ],
        )


def _clean_results(results: pd.DataFrame) -> pd.DataFrame:
    frame = results.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    frame = frame.dropna(subset=["date", "home_team", "away_team", "home_score", "away_score"])
    frame["home_score"] = frame["home_score"].astype(int)
    frame["away_score"] = frame["away_score"].astype(int)
    return frame


def _match_from_row(row: dict[str, Any]) -> Match:
    return Match(
        id=f"backtest-{row['date']}-{row['home_team']}-{row['away_team']}".lower().replace(" ", "-"),
        source="backtest",
        competition="International Backtest",
        season=None,
        match_date=datetime.combine(row["date"], time.min, tzinfo=timezone.utc),
        home_team=str(row["home_team"]),
        away_team=str(row["away_team"]),
        status="FINISHED",
        raw={"neutral": True},
    )


def _evaluate_prediction(picks: list[MarketPick], home_score: int, away_score: int) -> list[dict[str, Any]]:
    evaluations: list[dict[str, Any]] = []
    evaluations.append(_evaluate_1x2(picks, home_score, away_score))
    evaluations.append(_evaluate_binary_market(picks, "Over/Under 2.5", home_score + away_score > 2.5, "Over 2.5"))
    evaluations.append(_evaluate_binary_market(picks, "Goal/No Goal", home_score > 0 and away_score > 0, "Goal"))
    return [evaluation for evaluation in evaluations if evaluation]


def _evaluate_1x2(picks: list[MarketPick], home_score: int, away_score: int) -> dict[str, Any] | None:
    market_picks = [pick for pick in picks if pick.market == "1X2"]
    if len(market_picks) != 3:
        return None
    top = max(market_picks, key=lambda pick: pick.average_probability)
    if home_score > away_score:
        actual_index = 0
        actual = market_picks[0].selection
    elif home_score == away_score:
        actual_index = 1
        actual = "Pareggio"
    else:
        actual_index = 2
        actual = market_picks[2].selection
    probabilities = [pick.average_probability for pick in market_picks]
    brier = sum((probability - (1.0 if index == actual_index else 0.0)) ** 2 for index, probability in enumerate(probabilities)) / 3
    return {
        "market": "1X2",
        "pick": top.selection,
        "probability": top.average_probability,
        "actual": actual,
        "hit": top.selection == actual,
        "brier": brier,
    }


def _evaluate_binary_market(
    picks: list[MarketPick],
    market: str,
    actual_is_positive: bool,
    positive_selection: str,
) -> dict[str, Any] | None:
    market_picks = [pick for pick in picks if pick.market == market]
    if len(market_picks) < 2:
        return None
    top = max(market_picks, key=lambda pick: pick.average_probability)
    positive_pick = next((pick for pick in market_picks if pick.selection == positive_selection), None)
    if positive_pick is None:
        return None
    actual = positive_selection if actual_is_positive else next(pick.selection for pick in market_picks if pick.selection != positive_selection)
    brier = (positive_pick.average_probability - (1.0 if actual_is_positive else 0.0)) ** 2
    return {
        "market": market,
        "pick": top.selection,
        "probability": top.average_probability,
        "actual": actual,
        "hit": top.selection == actual,
        "brier": brier,
    }


def _metrics_for_market(market: str, evaluations: list[dict[str, Any]]) -> BacktestMarketMetrics:
    rows = [evaluation for evaluation in evaluations if evaluation["market"] == market]
    samples = len(rows)
    hit_rate = sum(1 for row in rows if row["hit"]) / samples
    brier_score = sum(float(row["brier"]) for row in rows) / samples
    avg_probability = sum(float(row["probability"]) for row in rows) / samples
    calibration_gap = abs(avg_probability - hit_rate)
    return BacktestMarketMetrics(
        market=market,
        samples=samples,
        hit_rate=hit_rate,
        brier_score=brier_score,
        avg_probability=avg_probability,
        calibration_gap=calibration_gap,
        reliability=_reliability_label(samples, brier_score, calibration_gap),
    )


def _reliability_label(samples: int, brier_score: float, calibration_gap: float) -> str:
    if samples < 40:
        return "campione piccolo"
    if brier_score <= 0.18 and calibration_gap <= 0.08:
        return "solida"
    if brier_score <= 0.23 and calibration_gap <= 0.13:
        return "discreta"
    return "da calibrare"


def _market_order(evaluations: list[dict[str, Any]]) -> list[str]:
    preferred = ["1X2", "Over/Under 2.5", "Goal/No Goal"]
    present = {evaluation["market"] for evaluation in evaluations}
    return [market for market in preferred if market in present]


def _recent_rows(row: dict[str, Any], evaluations: list[dict[str, Any]]) -> list[dict[str, str]]:
    result = f"{int(row['home_score'])}-{int(row['away_score'])}"
    return [
        {
            "Data": str(row["date"]),
            "Partita": f"{row['home_team']} vs {row['away_team']}",
            "Risultato": result,
            "Mercato": evaluation["market"],
            "Pick": str(evaluation["pick"]),
            "Prob.": f"{float(evaluation['probability']):.1%}",
            "Reale": str(evaluation["actual"]),
            "OK": "Si" if evaluation["hit"] else "No",
        }
        for evaluation in evaluations
    ]


def _match_sample_count(evaluations: list[dict[str, Any]]) -> int:
    return len([evaluation for evaluation in evaluations if evaluation["market"] == "1X2"])


def _empty_report(notes: list[str]) -> BacktestReport:
    return BacktestReport(
        generated_at=datetime.now(timezone.utc),
        start_date="-",
        end_date="-",
        samples=0,
        markets=[],
        notes=notes,
    )
