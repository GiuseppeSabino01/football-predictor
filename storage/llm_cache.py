from __future__ import annotations

from copy import deepcopy
from typing import Any

from schemas import MatchPrediction, NewsSignal


def llm_payload(prediction: MatchPrediction, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "generated_at": prediction.generated_at.isoformat(),
        "llm_summary": prediction.llm_summary,
        "picks": [
            {
                "market": pick.market,
                "selection": pick.selection,
                "llm_probability": pick.llm_probability,
            }
            for pick in prediction.picks
            if pick.llm_probability is not None
        ],
        "news_signals": [
            {
                "team": signal.team,
                "player": signal.player,
                "signal_type": signal.signal_type,
                "severity": signal.severity,
                "confidence": signal.confidence,
                "source_url": signal.source_url,
                "reason": signal.reason,
                "availability": signal.availability,
                "certainty": signal.certainty,
            }
            for signal in prediction.news_signals
        ],
    }


def apply_llm_payload(prediction: MatchPrediction, payload: dict[str, Any]) -> MatchPrediction | None:
    rows = payload.get("picks")
    if not isinstance(rows, list) or not rows:
        return None

    probabilities: dict[tuple[str, str], float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        market = str(row.get("market", "")).strip().lower()
        selection = str(row.get("selection", "")).strip().lower()
        if not market or not selection:
            continue
        try:
            probability = float(row.get("llm_probability"))
        except (TypeError, ValueError):
            continue
        probabilities[(market, selection)] = min(max(probability, 0.0), 1.0)

    if not probabilities:
        return None

    enriched = deepcopy(prediction)
    for pick in enriched.picks:
        key = (pick.market.strip().lower(), pick.selection.strip().lower())
        if key in probabilities:
            pick.llm_probability = probabilities[key]

    summary = payload.get("llm_summary")
    if isinstance(summary, str) and summary.strip():
        enriched.llm_summary = summary.strip()

    enriched.news_signals = _news_signals_from_payload(payload)
    one_x_two = [pick for pick in enriched.picks if pick.market == "1X2"]
    if one_x_two:
        top = max(one_x_two, key=lambda pick: pick.average_probability)
        enriched.summary = (
            f"Pick principale media: {top.selection} al {top.average_probability:.1%}. "
            f"Risultato esatto statistico stimato: {enriched.exact_score}."
        )
    return enriched


def _news_signals_from_payload(payload: dict[str, Any]) -> list[NewsSignal]:
    rows = payload.get("news_signals")
    if not isinstance(rows, list):
        return []

    signals: list[NewsSignal] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("team"):
            continue
        signals.append(
            NewsSignal(
                team=str(row.get("team", "")),
                player=row.get("player"),
                signal_type=str(row.get("signal_type", "other")),
                severity=str(row.get("severity", "low")),
                confidence=float(row.get("confidence", 0.3) or 0.3),
                source_url=str(row.get("source_url", "")),
                reason=str(row.get("reason", "")),
                availability=row.get("availability"),
                certainty=str(row.get("certainty", "unknown")),
            )
        )
    return signals
