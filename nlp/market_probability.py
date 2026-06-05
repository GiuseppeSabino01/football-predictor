from __future__ import annotations

from collections import defaultdict

from features.market_features import normalize_probabilities
from nlp.gemini_client import GeminiClient
from nlp.prompts import LLM_MARKET_PROBABILITY_PROMPT
from schemas import MarketPick, MatchPrediction, NewsArticle, NewsSignal


class LLMMarketProbabilityEstimator:
    def __init__(self, gemini: GeminiClient):
        self.gemini = gemini

    def enrich(
        self,
        prediction: MatchPrediction,
        articles: list[NewsArticle],
    ) -> MatchPrediction:
        if not prediction.picks:
            return prediction

        prompt = LLM_MARKET_PROBABILITY_PROMPT.format(
            match_label=prediction.match.label,
            competition=prediction.match.competition,
            stats_notes="\n".join(f"- {note}" for note in prediction.stats_notes) or "Nessuna statistica.",
            stats_tables=self._format_tables(prediction.stats_tables),
            news_context=self._format_news(prediction.news_signals, articles),
            markets=self._format_markets(prediction.picks),
        )
        try:
            payload = self.gemini.generate_json(prompt)
        except Exception as exc:
            prediction.warnings.append(f"Probabilita Gemini non disponibili: {exc}")
            return prediction

        if not isinstance(payload, dict):
            prediction.warnings.append("Probabilita Gemini non disponibili: risposta non strutturata.")
            return prediction
        rows = payload.get("probabilities")
        if not isinstance(rows, list):
            prediction.warnings.append("Probabilita Gemini non disponibili: campo probabilities mancante.")
            return prediction

        probabilities = self._normalize_rows(rows)
        for pick in prediction.picks:
            key = self._key(pick.market, pick.selection)
            if key in probabilities:
                pick.llm_probability = probabilities[key]
        if probabilities and all(pick.llm_probability is None for pick in prediction.picks):
            prediction.warnings.append("Probabilita Gemini ricevute ma non allineate ai mercati della tabella.")

        summary = payload.get("summary")
        if isinstance(summary, str) and summary.strip():
            prediction.llm_summary = summary.strip()
        one_x_two = [pick for pick in prediction.picks if pick.market == "1X2"]
        if one_x_two:
            top = max(one_x_two, key=lambda pick: pick.average_probability)
            prediction.summary = (
                f"Pick principale media: {top.selection} al {top.average_probability:.1%}. "
                f"Risultato esatto statistico stimato: {prediction.exact_score}."
            )
        return prediction

    @staticmethod
    def _format_tables(tables: dict[str, list[dict[str, str]]]) -> str:
        if not tables:
            return "Nessun risultato storico disponibile."
        lines: list[str] = []
        for title, rows in tables.items():
            if not rows:
                continue
            lines.append(title)
            for row in rows:
                lines.append(
                    f"- {row.get('Data', '')}: {row.get('Partita', '')} "
                    f"{row.get('Risultato', '')}, vincitore {row.get('Vincitore', '')}"
                )
        return "\n".join(lines) or "Nessun risultato storico disponibile."

    @staticmethod
    def _format_news(signals: list[NewsSignal], articles: list[NewsArticle]) -> str:
        lines: list[str] = []
        if signals:
            lines.append("Segnali estratti:")
            for signal in signals[:8]:
                lines.append(
                    f"- {signal.team}: {signal.signal_type}, severity {signal.severity}, "
                    f"certainty {signal.certainty}, confidence {signal.confidence:.0%}. {signal.reason}"
                )
        if articles:
            lines.append("Articoli trovati:")
            for article in articles[:8]:
                lines.append(
                    f"- {article.source} ({article.freshness_label}, relevance {article.relevance_score:.1f}): "
                    f"{article.title}. {article.summary}"
                )
        return "\n".join(lines) or "Nessuna news rilevante disponibile."

    @staticmethod
    def _format_markets(picks: list[MarketPick]) -> str:
        lines = []
        for pick in picks:
            if pick.probability <= 0:
                continue
            lines.append(
                f"- market={pick.market} | selection={pick.selection} | "
                f"probabilita_statistica={pick.probability:.4f}"
            )
        return "\n".join(lines)

    @classmethod
    def _normalize_rows(cls, rows: list[object]) -> dict[tuple[str, str], float]:
        grouped: dict[str, dict[str, float]] = defaultdict(dict)
        for row in rows:
            if not isinstance(row, dict):
                continue
            market = str(row.get("market", "")).strip()
            selection = str(row.get("selection", "")).strip()
            if not market or not selection:
                continue
            try:
                probability = float(row.get("probability"))
            except (TypeError, ValueError):
                continue
            grouped[market][selection] = min(max(probability, 0.0), 1.0)

        normalized: dict[tuple[str, str], float] = {}
        for market, values in grouped.items():
            if market in {"1X2", "Over/Under 2.5", "Goal/No Goal", "Passaggio turno"}:
                values = normalize_probabilities(values)
            for selection, probability in values.items():
                normalized[cls._key(market, selection)] = round(probability, 4)
        return normalized

    @staticmethod
    def _key(market: str, selection: str) -> tuple[str, str]:
        return market.strip().lower(), selection.strip().lower()
