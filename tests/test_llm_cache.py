from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from schemas import Match, MatchPrediction, MarketPick, NewsSignal
from storage.llm_cache import apply_llm_payload
from storage.sqlite_client import SQLiteStorage


def test_sqlite_llm_prediction_cache_roundtrip():
    match = Match(
        id="fixture-1",
        source="test",
        competition="Test Cup",
        season=2026,
        match_date=datetime(2026, 6, 12, tzinfo=timezone.utc),
        home_team="Italia",
        away_team="Francia",
    )
    prediction = MatchPrediction(
        match=match,
        generated_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
        picks=[
            MarketPick(market="1X2", selection="Italia", probability=0.4, llm_probability=0.45),
            MarketPick(market="1X2", selection="Pareggio", probability=0.3, llm_probability=0.28),
            MarketPick(market="1X2", selection="Francia", probability=0.3, llm_probability=0.27),
        ],
        exact_score="1-1",
        confidence="media",
        summary="Pick principale media: Italia al 42.5%.",
        llm_summary="Italia leggermente avanti.",
        news_signals=[
            NewsSignal(
                team="Italia",
                player=None,
                signal_type="form",
                severity="medium",
                confidence=0.7,
                source_url="https://example.test",
                reason="Forma positiva.",
            )
        ],
    )

    db_path = Path(".pytest_tmp") / "llm_cache.sqlite3"
    db_path.parent.mkdir(exist_ok=True)
    db_path.unlink(missing_ok=True)

    storage = SQLiteStorage(db_path)
    storage.upsert_llm_prediction("fixture-key", prediction, "gemini-test")

    payload = storage.load_llm_prediction("fixture-key")
    clean_prediction = MatchPrediction(
        match=match,
        generated_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
        picks=[
            MarketPick(market="1X2", selection="Italia", probability=0.4),
            MarketPick(market="1X2", selection="Pareggio", probability=0.3),
            MarketPick(market="1X2", selection="Francia", probability=0.3),
        ],
        exact_score="1-1",
        confidence="media",
        summary="Pick principale statistico: Italia al 40.0%.",
    )

    enriched = apply_llm_payload(clean_prediction, payload or {})

    assert enriched is not None
    assert [pick.llm_probability for pick in enriched.picks] == [0.45, 0.28, 0.27]
    assert enriched.llm_summary == "Italia leggermente avanti."
    assert enriched.news_signals[0].team == "Italia"
