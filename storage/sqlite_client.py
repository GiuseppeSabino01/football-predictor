from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from schemas import Match, MatchPrediction, NewsArticle, NewsSignal


class SQLiteStorage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        with self._connect() as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))

    def upsert_matches(self, matches: list[Match]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                insert into matches (
                    id, source, competition, season, match_date, home_team, away_team,
                    status, venue, stage, raw_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    source=excluded.source,
                    competition=excluded.competition,
                    season=excluded.season,
                    match_date=excluded.match_date,
                    home_team=excluded.home_team,
                    away_team=excluded.away_team,
                    status=excluded.status,
                    venue=excluded.venue,
                    stage=excluded.stage,
                    raw_json=excluded.raw_json
                """,
                [
                    (
                        match.id,
                        match.source,
                        match.competition,
                        match.season,
                        match.match_date.isoformat(),
                        match.home_team,
                        match.away_team,
                        match.status,
                        match.venue,
                        match.stage,
                        json.dumps(match.raw),
                    )
                    for match in matches
                ],
            )

    def upsert_articles(self, articles: list[NewsArticle]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                insert into news_articles (id, source, title, summary, url, published_at)
                values (?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    source=excluded.source,
                    title=excluded.title,
                    summary=excluded.summary,
                    url=excluded.url,
                    published_at=excluded.published_at
                """,
                [
                    (
                        article.id,
                        article.source,
                        article.title,
                        article.summary,
                        article.url,
                        article.published_at.isoformat() if article.published_at else None,
                    )
                    for article in articles
                ],
            )

    def insert_signals(self, signals: list[NewsSignal]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                insert into news_signals (
                    team, player, signal_type, severity, confidence, source_url, reason, availability
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        signal.team,
                        signal.player,
                        signal.signal_type,
                        signal.severity,
                        signal.confidence,
                        signal.source_url,
                        signal.reason,
                        signal.availability,
                    )
                    for signal in signals
                ],
            )

    def insert_prediction(self, prediction: MatchPrediction) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                insert into predictions (
                    match_id, generated_at, market, selection, probability, fair_odd,
                    market_odd, value_score, recommendation, confidence
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        prediction.match.id,
                        prediction.generated_at.isoformat(),
                        pick.market,
                        pick.selection,
                        pick.probability,
                        pick.fair_odd,
                        pick.market_odd,
                        pick.value_score,
                        pick.recommendation,
                        pick.confidence,
                    )
                    for pick in prediction.picks
                ],
            )

