from __future__ import annotations

from schemas import NewsSignal


def confidence_level(
    *,
    has_market_odds: bool,
    has_news: bool,
    data_source_count: int,
    signals: list[NewsSignal],
    has_historical_stats: bool = False,
    has_team_ratings: bool = False,
    is_player_prop: bool = False,
) -> str:
    score = 0
    if has_market_odds:
        score += 2
    if has_historical_stats:
        score += 2
    if has_team_ratings:
        score += 1
    if has_news:
        score += 1
    if data_source_count >= 2:
        score += 1
    if any(signal.confidence >= 0.75 for signal in signals):
        score += 1
    if is_player_prop:
        score -= 2

    if score >= 4:
        return "alta"
    if score >= 2:
        return "media"
    return "bassa"
