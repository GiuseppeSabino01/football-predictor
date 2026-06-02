from __future__ import annotations

from datetime import date, datetime, timezone

from config.competitions import DEFAULT_COMPETITIONS, SUPPORTED_COMPETITIONS, WORLD_CUP_KEYS
from config.settings import Settings
from data_sources.api_football import APIFootballClient
from data_sources.football_data_org import FootballDataOrgClient
from data_sources.international_results import InternationalResultsClient
from data_sources.national_elo import NationalEloClient
from data_sources.openligadb import OpenLigaDBClient
from data_sources.rss_italian_news import ItalianRssNewsClient
from features.historical_stats import HistoricalStatsBuilder, frame_is_usable
from models.ensemble import EnsemblePredictor
from nlp.gemini_client import GeminiClient
from nlp.market_probability import LLMMarketProbabilityEstimator
from nlp.news_extractor import NewsSignalExtractor
from schemas import Match, MatchPrediction, NewsArticle, NewsSignal
from storage.llm_cache import apply_llm_payload
from storage.sqlite_client import SQLiteStorage
from storage.supabase_client import SupabaseStorage


class PredictionService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_football = APIFootballClient(settings)
        self.football_data_org = FootballDataOrgClient(settings)
        self.international_results = InternationalResultsClient(settings)
        self.national_elo = NationalEloClient(settings)
        self.openligadb = OpenLigaDBClient(settings)
        self.news_client = ItalianRssNewsClient(settings)
        self.gemini = GeminiClient(settings)
        self.news_extractor = NewsSignalExtractor(self.gemini)
        self.llm_probability = LLMMarketProbabilityEstimator(self.gemini)
        self.predictor = EnsemblePredictor()
        self.sqlite_storage = SQLiteStorage(settings.sqlite_path)
        self.supabase_storage = SupabaseStorage(settings)

    def predictions_for_date(self, target_date: date, worldcup_only: bool = False) -> tuple[list[MatchPrediction], list[str]]:
        errors: list[str] = []
        competitions = self._competitions(worldcup_only)
        matches = self._load_matches(target_date, competitions, errors, worldcup_only)
        if not matches:
            return [], errors

        teams = sorted({team for match in matches for team in (match.home_team, match.away_team)})
        articles = self._load_news(teams, errors)
        team_ratings = self._load_team_ratings(target_date, matches, errors)
        stats_builder = self._load_historical_stats(target_date, matches, errors)
        predictions = [
            self._predict_match(match, [], articles, errors, team_ratings, stats_builder)
            for match in matches
        ]
        return predictions, errors

    def predict_single(self, home: str, away: str, competition: str = "Manuale") -> MatchPrediction:
        match = Match(
            id=f"manual-{home}-{away}".lower().replace(" ", "-"),
            source="manual",
            competition=competition,
            season=None,
            match_date=datetime.now(timezone.utc),
            home_team=home,
            away_team=away,
        )
        return self.predictor.predict(match)

    def enrich_prediction_with_gemini(self, prediction: MatchPrediction) -> MatchPrediction:
        if not self.settings.has_gemini:
            prediction.warnings.append("Gemini non configurato: impossibile calcolare la probabilita modello.")
            return prediction

        teams = [prediction.match.home_team, prediction.match.away_team]
        errors: list[str] = []
        articles = prediction.news_articles
        if not articles:
            articles = self._load_news(teams, errors)
            articles = self._relevant_articles(prediction.match, articles)
            prediction.news_articles = articles

        signals = self._load_signals(articles, teams, errors)
        prediction.news_signals = [
            signal
            for signal in signals
            if self._team_name_matches(signal.team, prediction.match.home_team)
            or self._team_name_matches(signal.team, prediction.match.away_team)
        ]
        for error in errors:
            prediction.warnings.append(error)
        return self.llm_probability.enrich(prediction, articles)

    def load_cached_gemini_prediction(self, cache_key: str, base_prediction: MatchPrediction) -> MatchPrediction | None:
        payload = self.supabase_storage.load_llm_prediction(cache_key)
        if payload is None:
            payload = self.sqlite_storage.load_llm_prediction(cache_key)
        if payload is None:
            return None
        return apply_llm_payload(base_prediction, payload)

    def save_cached_gemini_prediction(self, cache_key: str, prediction: MatchPrediction) -> bool:
        if not any(pick.llm_probability is not None for pick in prediction.picks):
            return False

        saved = False
        try:
            self.sqlite_storage.upsert_llm_prediction(cache_key, prediction, self.settings.gemini_model)
            saved = True
        except Exception:
            saved = False
        if self.supabase_storage.upsert_llm_prediction(cache_key, prediction, self.settings.gemini_model):
            saved = True
        return saved

    def _load_matches(
        self,
        target_date: date,
        competitions: list,
        errors: list[str],
        worldcup_only: bool,
    ) -> list[Match]:
        matches: list[Match] = []
        if worldcup_only:
            try:
                matches = self.openligadb.worldcup_matches_for_date(target_date)
            except Exception as exc:
                errors.append(f"OpenLigaDB Mondiali non disponibile: {exc}")
            if matches:
                return matches

        try:
            matches = self.api_football.fixtures_for_date(target_date, competitions)
        except Exception as exc:
            errors.append(f"API-Football fixture non disponibili: {exc}")

        if matches:
            return matches

        try:
            matches = self.football_data_org.matches_for_date(target_date)
        except Exception as exc:
            errors.append(f"football-data.org fixture non disponibili: {exc}")
            return []
        if matches:
            return matches

        if any(competition.key == "worldcup" for competition in competitions):
            try:
                return self.openligadb.worldcup_matches_for_date(target_date)
            except Exception as exc:
                errors.append(f"OpenLigaDB Mondiali non disponibile: {exc}")
        return []

    def _load_news(self, teams: list[str], errors: list[str]) -> list[NewsArticle]:
        try:
            return self.news_client.fetch(teams)
        except Exception as exc:
            errors.append(f"News RSS non disponibili: {exc}")
            return []

    def _load_signals(self, articles: list[NewsArticle], teams: list[str], errors: list[str]) -> list[NewsSignal]:
        if not articles or not self.settings.has_gemini:
            return []
        try:
            return self.news_extractor.extract(articles, teams)
        except Exception as exc:
            errors.append(f"Gemini news extractor non disponibile: {exc}")
            return []

    def _load_team_ratings(
        self,
        target_date: date,
        matches: list[Match],
        errors: list[str],
    ) -> dict[str, int]:
        if not any("world cup" in match.competition.lower() or "wm 2026" in match.competition.lower() for match in matches):
            return {}
        try:
            ratings = self.national_elo.ratings_for_date(target_date)
        except Exception as exc:
            errors.append(f"Elo nazionali online non disponibili, uso seed locale: {exc}")
            return {}
        if not ratings:
            errors.append("Elo nazionali online vuoti, uso seed locale.")
        return ratings

    def _load_historical_stats(
        self,
        target_date: date,
        matches: list[Match],
        errors: list[str],
    ) -> HistoricalStatsBuilder | None:
        if not any("world cup" in match.competition.lower() or "wm 2026" in match.competition.lower() for match in matches):
            return None
        try:
            frame = self.international_results.load(target_date)
        except Exception as exc:
            errors.append(f"Storico nazionali non disponibile: {exc}")
            return None
        if not frame_is_usable(frame):
            errors.append("Storico nazionali vuoto o non utilizzabile.")
            return None
        return HistoricalStatsBuilder(frame)

    def _predict_match(
        self,
        match: Match,
        signals: list[NewsSignal],
        articles: list[NewsArticle],
        errors: list[str],
        team_ratings: dict[str, int] | None = None,
        stats_builder: HistoricalStatsBuilder | None = None,
    ) -> MatchPrediction:
        relevant_signals = [
            signal
            for signal in signals
            if self._team_name_matches(signal.team, match.home_team)
            or self._team_name_matches(signal.team, match.away_team)
        ]
        relevant_articles = self._relevant_articles(match, articles)
        odds_rows = []
        lineups = []
        if match.source == "api-football":
            try:
                odds_rows = self.api_football.odds_for_fixture(match.id)
            except Exception as exc:
                errors.append(f"Quote non disponibili per {match.label}: {exc}")
            try:
                lineups = self.api_football.lineups_for_fixture(match.id)
            except Exception:
                lineups = []
        historical_stats = stats_builder.build(match.home_team, match.away_team) if stats_builder else None
        prediction = self.predictor.predict(
            match,
            odds_rows=odds_rows,
            news_signals=relevant_signals,
            lineups=lineups,
            team_ratings=team_ratings,
            historical_stats=historical_stats,
        )
        prediction.news_articles = relevant_articles
        return prediction

    @staticmethod
    def _relevant_articles(match: Match, articles: list[NewsArticle]) -> list[NewsArticle]:
        from config.team_aliases import aliases_for

        terms = {
            term.lower()
            for team in (match.home_team, match.away_team)
            for term in aliases_for(team)
        }
        relevant: list[NewsArticle] = []
        for article in articles:
            haystack = f"{article.title} {article.summary}".lower()
            if any(term and term in haystack for term in terms):
                relevant.append(article)
        return sorted(relevant, key=lambda item: (item.relevance_score, item.published_at is not None), reverse=True)

    @staticmethod
    def _team_name_matches(candidate: str, team: str) -> bool:
        from config.team_aliases import aliases_for

        candidate_lower = candidate.lower()
        return any(candidate_lower == alias.lower() for alias in aliases_for(team))

    @staticmethod
    def _competitions(worldcup_only: bool) -> list:
        keys = WORLD_CUP_KEYS if worldcup_only else DEFAULT_COMPETITIONS
        return [SUPPORTED_COMPETITIONS[key] for key in keys]
