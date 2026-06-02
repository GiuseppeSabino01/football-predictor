from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import feedparser
import requests

from config.settings import Settings
from config.team_aliases import aliases_for
from schemas import NewsArticle


ITALIAN_RSS_FEEDS = {
    "Gazzetta": "https://www.gazzetta.it/rss/calcio.xml",
    "Corriere dello Sport": "https://www.corrieredellosport.it/rss/calcio",
}


class ItalianRssNewsClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def fetch(self, teams: list[str], max_articles: int = 40) -> list[NewsArticle]:
        team_terms = self._team_terms(teams)
        articles: list[NewsArticle] = []

        for source, url in ITALIAN_RSS_FEEDS.items():
            try:
                response = requests.get(
                    url,
                    timeout=self.settings.request_timeout_seconds,
                    verify=self.settings.verify_ssl,
                )
                response.raise_for_status()
                feed = feedparser.parse(response.content)
            except Exception:
                continue

            for entry in feed.entries:
                title = str(getattr(entry, "title", "") or "")
                summary = str(getattr(entry, "summary", "") or "")
                link = str(getattr(entry, "link", "") or "")
                haystack = f"{title} {summary}".lower()
                relevance = self._relevance_score(haystack, team_terms)
                if team_terms and relevance <= 0:
                    continue
                published_at = self._published_at(entry)
                articles.append(
                    NewsArticle(
                        id=hashlib.sha1(f"{source}:{link}:{title}".encode("utf-8")).hexdigest(),
                        source=source,
                        title=title,
                        summary=summary,
                        url=link,
                        published_at=published_at,
                        relevance_score=relevance,
                        freshness_label=self._freshness_label(published_at),
                    )
                )
                if len(articles) >= max_articles:
                    return articles
        return articles

    @staticmethod
    def _published_at(entry: object) -> datetime | None:
        parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if not parsed:
            return None
        return datetime(*parsed[:6])

    @staticmethod
    def _team_terms(teams: list[str]) -> list[str]:
        terms: list[str] = []
        for team in teams:
            terms.extend(alias.lower() for alias in aliases_for(team))
        return sorted(set(terms))

    @staticmethod
    def _relevance_score(haystack: str, team_terms: list[str]) -> float:
        if not team_terms:
            return 0.0
        hits = sum(1 for term in team_terms if term and term in haystack)
        return min(1.0, hits / 2)

    @staticmethod
    def _freshness_label(published_at: datetime | None) -> str:
        if not published_at:
            return "data sconosciuta"
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - published_at.astimezone(timezone.utc)).total_seconds() / 3600
        if age_hours <= 24:
            return "ultime 24h"
        if age_hours <= 72:
            return "ultimi 3 giorni"
        if age_hours <= 168:
            return "ultima settimana"
        return "vecchia"
