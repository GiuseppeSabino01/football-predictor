from __future__ import annotations

from datetime import datetime, timezone

from features.confidence import confidence_level
from features.historical_stats import MatchHistoricalStats
from features.market_features import (
    fair_odd,
    implied_1x2_from_odds,
    market_odd_for_selection,
    recommendation,
    value_score,
)
from features.news_features import apply_news_adjustments
from features.team_strength import blend_probabilities, rating_based_1x2
from models.poisson import both_teams_to_score, exact_score_for_outcome, over_under_25, score_matrix
from models.shots_model import ShotsModel
from schemas import MarketPick, Match, MatchPrediction, NewsSignal


class EnsemblePredictor:
    def __init__(self):
        self.shots_model = ShotsModel()

    def predict(
        self,
        match: Match,
        odds_rows: list[dict] | None = None,
        news_signals: list[NewsSignal] | None = None,
        lineups: list[dict] | None = None,
        team_ratings: dict[str, int] | None = None,
        historical_stats: MatchHistoricalStats | None = None,
    ) -> MatchPrediction:
        odds_rows = odds_rows or []
        news_signals = news_signals or []

        odds_probs = implied_1x2_from_odds(odds_rows)
        rating_probs = rating_based_1x2(
            match.home_team,
            match.away_team,
            team_ratings,
            neutral=self._is_neutral_match(match),
        )
        stats_xg = self._xg_from_historical_stats(historical_stats)
        stats_probs = self._probabilities_from_xg(stats_xg) if stats_xg else None

        if odds_probs and stats_probs and rating_probs:
            base_probs = self._blend_many([(odds_probs, 0.42), (stats_probs, 0.40), (rating_probs, 0.18)])
        elif stats_probs and rating_probs:
            base_probs = blend_probabilities(stats_probs, rating_probs, primary_weight=0.72)
        elif odds_probs and rating_probs:
            base_probs = blend_probabilities(odds_probs, rating_probs, primary_weight=0.60)
        else:
            base_probs = stats_probs or odds_probs or rating_probs or self._fallback_1x2(match)
        probs = apply_news_adjustments(base_probs, news_signals, match.home_team, match.away_team)
        if stats_xg:
            probability_xg = self._xg_from_probabilities(probs, match)
            home_xg = (stats_xg[0] * 0.70) + (probability_xg[0] * 0.30)
            away_xg = (stats_xg[1] * 0.70) + (probability_xg[1] * 0.30)
        else:
            home_xg, away_xg = self._xg_from_probabilities(probs, match)
        matrix = score_matrix(home_xg, away_xg)
        matrix = self._apply_h2h_score_boost(matrix, historical_stats)

        has_odds = bool(implied_1x2_from_odds(odds_rows))
        confidence = confidence_level(
            has_market_odds=has_odds,
            has_news=bool(news_signals),
            data_source_count=1 + int(has_odds) + int(bool(historical_stats and historical_stats.has_meaningful_data)),
            signals=news_signals,
            has_historical_stats=bool(historical_stats and historical_stats.has_meaningful_data),
            has_team_ratings=bool(rating_probs),
        )

        picks = []
        picks.extend(self._one_x_two_picks(match, probs, odds_rows, confidence))
        picks.extend(self._double_chance_picks(probs, confidence))
        picks.extend(self._probability_market_picks(over_under_25(matrix), "Over/Under 2.5", confidence))
        picks.extend(self._probability_market_picks(both_teams_to_score(matrix), "Goal/No Goal", confidence))
        picks.extend(self._knockout_pick(match, probs, confidence))
        picks.extend(self.shots_model.team_shots(match.home_team, match.away_team, home_xg, away_xg))
        picks.extend(self.shots_model.player_props(lineups))

        warnings = []
        if not has_odds:
            if stats_probs:
                warnings.append("Quote mercato non disponibili: modello basato su storico, Elo, Poisson e news.")
            elif rating_probs:
                warnings.append("Quote mercato non disponibili: modello basato su Elo nazionale, Poisson e news.")
            else:
                warnings.append("Quote mercato e rating squadra non disponibili: modello basato su baseline.")
        if any("tiri" in p.market.lower() or "angoli" in p.market.lower() for p in picks):
            warnings.append("Mercati tiri e angoli: usare con cautela, stimati indirettamente da xG e volume atteso.")
        if not news_signals:
            warnings.append("Nessun segnale news concreto estratto dalle fonti italiane disponibili.")

        top = max((pick for pick in picks if pick.market == "1X2"), key=lambda p: p.probability)
        top_outcome = max(probs, key=probs.get)
        predicted_score = exact_score_for_outcome(matrix, top_outcome)
        summary = (
            f"Pick principale: {top.selection} al {top.probability:.1%}. "
            f"Risultato esatto stimato: {predicted_score}."
        )
        return MatchPrediction(
            match=match,
            generated_at=datetime.now(timezone.utc),
            picks=picks,
            exact_score=predicted_score,
            confidence=confidence,
            summary=summary,
            news_signals=news_signals,
            stats_notes=historical_stats.notes if historical_stats else [],
            stats_tables=historical_stats.result_tables(match.home_team, match.away_team) if historical_stats else {},
            warnings=warnings,
        )

    @staticmethod
    def _fallback_1x2(match: Match) -> dict[str, float]:
        if "world cup" in match.competition.lower() or match.raw.get("neutral"):
            return {"home": 0.37, "draw": 0.29, "away": 0.34}
        return {"home": 0.43, "draw": 0.27, "away": 0.30}

    @staticmethod
    def _is_neutral_match(match: Match) -> bool:
        competition = match.competition.lower()
        if "world cup" in competition or "wm 2026" in competition:
            return True
        return bool(match.raw.get("neutral", False))

    @staticmethod
    def _xg_from_probabilities(probabilities: dict[str, float], match: Match) -> tuple[float, float]:
        home_edge = probabilities["home"] - probabilities["away"]
        base_total = 2.55 if "world cup" not in match.competition.lower() else 2.35
        home_xg = max(0.45, min(3.1, (base_total / 2) + home_edge * 1.35))
        away_xg = max(0.45, min(3.1, (base_total / 2) - home_edge * 1.10))
        return home_xg, away_xg

    @staticmethod
    def _xg_from_historical_stats(stats: MatchHistoricalStats | None) -> tuple[float, float] | None:
        if not stats or not stats.has_meaningful_data:
            return None

        home = stats.home_recent
        away = stats.away_recent
        home_level = stats.home_vs_away_level
        away_level = stats.away_vs_home_level
        h2h = stats.h2h
        recent_home_xg = (home.avg_goals_for * 0.45) + (away.avg_goals_against * 0.35)
        recent_away_xg = (away.avg_goals_for * 0.45) + (home.avg_goals_against * 0.35)
        home_xg = recent_home_xg
        away_xg = recent_away_xg

        if home_level.matches >= 2 or away_level.matches >= 2:
            similar_home_xg = home_level.avg_goals_for if home_level.matches else recent_home_xg
            if away_level.matches:
                similar_home_xg = (similar_home_xg * 0.58) + (away_level.avg_goals_against * 0.42)
            similar_away_xg = away_level.avg_goals_for if away_level.matches else recent_away_xg
            if home_level.matches:
                similar_away_xg = (similar_away_xg * 0.58) + (home_level.avg_goals_against * 0.42)
            home_xg = (home_xg * 0.42) + (similar_home_xg * 0.58)
            away_xg = (away_xg * 0.42) + (similar_away_xg * 0.58)

        if h2h.matches >= 2 and h2h.avg_home_goals is not None and h2h.avg_away_goals is not None:
            h2h_weight = min(0.46, 0.18 + h2h.matches * 0.055)
            home_xg = (home_xg * (1 - h2h_weight)) + (h2h.avg_home_goals * h2h_weight)
            away_xg = (away_xg * (1 - h2h_weight)) + (h2h.avg_away_goals * h2h_weight)

        if home.scored_rate >= 0.80:
            home_xg += 0.12
        if away.scored_rate >= 0.80:
            away_xg += 0.12
        if home.conceded_rate >= 0.80:
            away_xg += 0.10
        if away.conceded_rate >= 0.80:
            home_xg += 0.10
        form_edge = (home.points_per_game - away.points_per_game) / 3
        similar_edge = 0.0
        if home_level.matches and away_level.matches:
            similar_edge = (home_level.points_per_game - away_level.points_per_game) / 3
        home_xg += (form_edge * 0.13) + (similar_edge * 0.22)
        away_xg -= (form_edge * 0.13) + (similar_edge * 0.22)

        return max(0.25, min(3.8, home_xg)), max(0.25, min(3.8, away_xg))

    @staticmethod
    def _probabilities_from_xg(xg: tuple[float, float]) -> dict[str, float]:
        matrix = score_matrix(xg[0], xg[1])
        home = sum(prob for (home_goals, away_goals), prob in matrix.items() if home_goals > away_goals)
        draw = sum(prob for (home_goals, away_goals), prob in matrix.items() if home_goals == away_goals)
        away = sum(prob for (home_goals, away_goals), prob in matrix.items() if home_goals < away_goals)
        return {"home": home, "draw": draw, "away": away}

    @staticmethod
    def _apply_h2h_score_boost(
        matrix: dict[tuple[int, int], float],
        stats: MatchHistoricalStats | None,
    ) -> dict[tuple[int, int], float]:
        if not stats or stats.h2h.matches < 3 or not stats.h2h.most_common_score:
            return matrix
        score, frequency = stats.h2h.most_common_score
        if frequency < 0.35:
            return matrix
        boosted = dict(matrix)
        boosted[score] = boosted.get(score, 0.0) * (1 + min(2.2, frequency * 3.0))
        total = sum(boosted.values())
        return {key: value / total for key, value in boosted.items()}

    @staticmethod
    def _blend_many(weighted_probabilities: list[tuple[dict[str, float], float]]) -> dict[str, float]:
        blended = {"home": 0.0, "draw": 0.0, "away": 0.0}
        total_weight = sum(weight for _, weight in weighted_probabilities)
        for probabilities, weight in weighted_probabilities:
            for key in blended:
                blended[key] += probabilities[key] * weight
        return {key: value / total_weight for key, value in blended.items()}

    @staticmethod
    def _one_x_two_picks(
        match: Match, probabilities: dict[str, float], odds_rows: list[dict], confidence: str
    ) -> list[MarketPick]:
        labels = {
            "home": match.home_team,
            "draw": "Pareggio",
            "away": match.away_team,
        }
        picks: list[MarketPick] = []
        for key, label in labels.items():
            probability = probabilities[key]
            market_odd = market_odd_for_selection(odds_rows, key)
            picks.append(
                MarketPick(
                    market="1X2",
                    selection=label,
                    probability=round(probability, 3),
                    fair_odd=fair_odd(probability),
                    market_odd=market_odd,
                    value_score=value_score(probability, market_odd),
                    recommendation=recommendation(probability, market_odd),
                    confidence=confidence,
                )
            )
        return picks

    @staticmethod
    def _double_chance_picks(probabilities: dict[str, float], confidence: str) -> list[MarketPick]:
        values = {
            "1X": probabilities["home"] + probabilities["draw"],
            "X2": probabilities["draw"] + probabilities["away"],
            "12": probabilities["home"] + probabilities["away"],
        }
        return [
            MarketPick(
                market="Doppia chance",
                selection=selection,
                probability=round(probability, 3),
                fair_odd=fair_odd(probability),
                recommendation="Lean" if probability >= 0.68 else "No-bet",
                confidence=confidence,
            )
            for selection, probability in values.items()
        ]

    @staticmethod
    def _probability_market_picks(values: dict[str, float], market: str, confidence: str) -> list[MarketPick]:
        return [
            MarketPick(
                market=market,
                selection=selection,
                probability=round(probability, 3),
                fair_odd=fair_odd(probability),
                recommendation="Lean" if probability >= 0.56 else "No-bet",
                confidence=confidence,
            )
            for selection, probability in values.items()
        ]

    @staticmethod
    def _knockout_pick(match: Match, probabilities: dict[str, float], confidence: str) -> list[MarketPick]:
        stage = f"{match.stage or ''} {match.competition}".lower()
        if not any(word in stage for word in ["round of", "quarter", "semi", "final", "knockout"]):
            return []
        home_adv = probabilities["home"] + probabilities["draw"] * 0.5
        away_adv = probabilities["away"] + probabilities["draw"] * 0.5
        return [
            MarketPick(
                market="Passaggio turno",
                selection=match.home_team,
                probability=round(home_adv, 3),
                fair_odd=fair_odd(home_adv),
                recommendation="Lean" if home_adv >= 0.58 else "No-bet",
                confidence=confidence,
            ),
            MarketPick(
                market="Passaggio turno",
                selection=match.away_team,
                probability=round(away_adv, 3),
                fair_odd=fair_odd(away_adv),
                recommendation="Lean" if away_adv >= 0.58 else "No-bet",
                confidence=confidence,
            ),
        ]
