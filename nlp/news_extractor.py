from __future__ import annotations

from nlp.gemini_client import GeminiClient
from nlp.prompts import NEWS_EXTRACTION_PROMPT
from schemas import NewsArticle, NewsSignal


class NewsSignalExtractor:
    def __init__(self, gemini: GeminiClient):
        self.gemini = gemini

    def extract(self, articles: list[NewsArticle], teams: list[str], max_articles: int = 4) -> list[NewsSignal]:
        signals: list[NewsSignal] = []
        for article in articles[:max_articles]:
            prompt = NEWS_EXTRACTION_PROMPT.format(
                teams=", ".join(teams),
                source=article.source,
                title=article.title,
                summary=article.summary,
                url=article.url,
            )
            try:
                rows = self.gemini.generate_json(prompt)
            except Exception:
                continue

            if not isinstance(rows, list):
                continue
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
                        source_url=article.url,
                        reason=str(row.get("reason", "")),
                        availability=row.get("availability"),
                        certainty=str(row.get("certainty", "unknown")),
                    )
                )
        return signals
