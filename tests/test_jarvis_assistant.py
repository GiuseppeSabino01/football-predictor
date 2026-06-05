from __future__ import annotations

from datetime import datetime, timezone

from nlp.jarvis_assistant import JarvisAssistant
from schemas import Match, MatchPrediction, MarketPick


class _SettingsWithoutGemini:
    has_gemini = False


class _GeminiStub:
    settings = _SettingsWithoutGemini()


def test_jarvis_fallback_uses_statistical_pick_without_gemini():
    match = Match(
        id="fixture-jarvis",
        source="test",
        competition="Test Cup",
        season=2026,
        match_date=datetime(2026, 6, 12, tzinfo=timezone.utc),
        home_team="Messico",
        away_team="USA",
    )
    prediction = MatchPrediction(
        match=match,
        generated_at=datetime(2026, 6, 5, tzinfo=timezone.utc),
        picks=[
            MarketPick(market="1X2", selection="Messico", probability=0.56),
            MarketPick(market="1X2", selection="Pareggio", probability=0.25),
            MarketPick(market="1X2", selection="USA", probability=0.19),
        ],
        exact_score="1-0",
        confidence="media",
        summary="Pick principale statistico: Messico al 56.0%.",
    )

    reply = JarvisAssistant(_GeminiStub()).answer_text(prediction, "Chi vince?")

    assert "Messico" in reply.answer
    assert "56.0%" in reply.answer
    assert reply.warnings
