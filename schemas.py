from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Match:
    id: str
    source: str
    competition: str
    season: int | None
    match_date: datetime
    home_team: str
    away_team: str
    status: str = "SCHEDULED"
    venue: str | None = None
    stage: str | None = None
    league_id: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.home_team} vs {self.away_team}"


@dataclass(slots=True)
class NewsArticle:
    id: str
    source: str
    title: str
    summary: str
    url: str
    published_at: datetime | None = None
    relevance_score: float = 0.0
    freshness_label: str = "unknown"


@dataclass(slots=True)
class NewsSignal:
    team: str
    player: str | None
    signal_type: str
    severity: str
    confidence: float
    source_url: str
    reason: str
    availability: str | None = None
    certainty: str = "unknown"


@dataclass(slots=True)
class MarketPick:
    market: str
    selection: str
    probability: float
    llm_probability: float | None = None
    fair_odd: float | None = None
    market_odd: float | None = None
    value_score: float | None = None
    recommendation: str = "No-bet"
    confidence: str = "bassa"
    notes: list[str] = field(default_factory=list)

    @property
    def has_bookmaker_odd(self) -> bool:
        return self.market_odd is not None

    @property
    def average_probability(self) -> float:
        if self.llm_probability is None:
            return self.probability
        return (self.probability + self.llm_probability) / 2


@dataclass(slots=True)
class MatchPrediction:
    match: Match
    generated_at: datetime
    picks: list[MarketPick]
    exact_score: str
    confidence: str
    summary: str
    news_signals: list[NewsSignal] = field(default_factory=list)
    news_articles: list[NewsArticle] = field(default_factory=list)
    llm_summary: str | None = None
    stats_notes: list[str] = field(default_factory=list)
    stats_tables: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
