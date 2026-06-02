from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
import streamlit as st

from config.settings import load_settings
from features.market_features import fair_odd, recommendation, value_score
from services.predictor import PredictionService
from schemas import MatchPrediction, MarketPick


st.set_page_config(page_title="Football Betting Predictor", layout="wide")
SESSION_SCHEMA_VERSION = "gemini-on-demand-v2"


def settings():
    return load_settings()


def require_login() -> bool:
    app_password = settings().app_password
    if not app_password:
        st.warning("APP_PASSWORD non configurata. Aggiungila nel file .env o nei secrets Streamlit.")
        return True
    if st.session_state.get("logged_in"):
        return True

    st.title("Football Betting Predictor")
    password = st.text_input("Password", type="password")
    if st.button("Entra", type="primary"):
        if password == app_password:
            st.session_state["logged_in"] = True
            st.rerun()
        st.error("Password non corretta.")
    return False


@st.cache_data(ttl=900, show_spinner=False)
def load_predictions(target_date: date, worldcup_only: bool) -> tuple[list[MatchPrediction], list[str]]:
    service = PredictionService(settings())
    return service.predictions_for_date(target_date, worldcup_only)


def main() -> None:
    if not require_login():
        return
    init_session_state()

    st.title("Football Betting Predictor")
    st.caption("Analisi betting personale: probabilita, value, news e warning dati.")

    with st.sidebar:
        st.subheader("Filtro")
        page = st.radio("Vista", ["Oggi", "Mondiali 2026", "Predict manuale", "Config"], label_visibility="collapsed")
        target_date = st.date_input("Data", value=date.today())
        if page == "Mondiali 2026" and target_date < date(2026, 6, 11):
            target_date = st.date_input("Data Mondiali", value=date(2026, 6, 11), key="worldcup_date")
        refresh = st.button("Aggiorna dati", type="primary")
        if refresh:
            load_predictions.clear()
            st.session_state.pop("llm_predictions", None)
            st.session_state.pop("llm_requested_predictions", None)

    if page == "Config":
        render_config()
    elif page == "Predict manuale":
        render_manual_prediction()
    else:
        render_predictions(target_date, worldcup_only=page == "Mondiali 2026")


def init_session_state() -> None:
    if st.session_state.get("session_schema_version") == SESSION_SCHEMA_VERSION:
        return
    load_predictions.clear()
    st.session_state["session_schema_version"] = SESSION_SCHEMA_VERSION
    st.session_state.pop("llm_predictions", None)
    st.session_state.pop("llm_requested_predictions", None)
    st.session_state.pop("manual_prediction", None)


def render_config() -> None:
    cfg = settings()
    st.subheader("Stato configurazione")
    rows = [
        ("Gemini", cfg.has_gemini),
        ("API-Football", cfg.has_api_football),
        ("football-data.org", cfg.has_football_data_org),
        ("Supabase", cfg.has_supabase),
        ("Password app", bool(cfg.app_password)),
    ]
    for name, ok in rows:
        st.write(f"{name}: {'OK' if ok else 'mancante'}")
    st.write(f"Modello Gemini: `{cfg.gemini_model}`")
    st.info("Le chiavi non vengono mostrate. Se qualcosa risulta mancante, controlla .env o Streamlit secrets.")


def render_manual_prediction() -> None:
    left, right = st.columns(2)
    home = left.text_input("Squadra casa", value="France")
    away = right.text_input("Squadra trasferta", value="Brazil")
    competition = st.text_input("Competizione", value="Manuale")
    if st.button("Calcola pronostico"):
        st.session_state["manual_prediction"] = PredictionService(settings()).predict_single(home, away, competition)
    if "manual_prediction" in st.session_state:
        render_prediction_card(st.session_state["manual_prediction"])


def render_predictions(target_date: date, worldcup_only: bool) -> None:
    with st.spinner("Carico partite, quote, news e pronostici..."):
        predictions, errors = load_predictions(target_date, worldcup_only)

    if errors:
        with st.expander("Warning fonti dati", expanded=False):
            for error in errors:
                st.warning(error)

    if not predictions:
        st.info("Nessuna partita trovata per questa data nelle competizioni configurate.")
        if worldcup_only:
            st.caption("Per i Mondiali prova dall'11 giugno 2026 in avanti.")
        return

    st.subheader(f"Pronostici del {target_date.isoformat()}")
    for prediction in predictions:
        render_prediction_card(prediction)


def render_prediction_card(prediction: MatchPrediction) -> None:
    base_prediction = _without_gemini_output(prediction)
    prediction_key = _prediction_cache_key(prediction)
    requested = bool(st.session_state.get("llm_requested_predictions", {}).get(prediction_key))
    cached_prediction = st.session_state.get("llm_predictions", {}).get(prediction_key) if requested else None
    if requested and cached_prediction:
        prediction = cached_prediction
    else:
        prediction = base_prediction

    match = prediction.match
    with st.container(border=True):
        top = max((pick for pick in prediction.picks if pick.market == "1X2"), key=lambda p: p.average_probability)
        cols = st.columns([2.2, 1, 1, 1])
        cols[0].subheader(match.label)
        cols[0].caption(f"{match.competition} | {match.stage or 'fase non specificata'}")
        cols[1].metric("Pick", top.selection)
        cols[2].metric("Prob. media", f"{top.average_probability:.1%}")
        cols[3].metric("Confidenza", prediction.confidence)

        st.write(prediction.summary)
        render_gemini_probability_button(base_prediction, prediction, prediction_key)
        manual_odds = render_manual_odds_inputs(prediction)
        if not any(pick.market_odd for pick in prediction.picks) and not manual_odds:
            st.info(
                "Quote bookmaker non disponibili da fonti gratuite per questa partita. "
                "La tabella mostra quote medie; il value betting e' valutabile solo inserendo quote reali."
            )
        render_market_table(prediction.picks, manual_odds)

        if prediction.news_signals:
            with st.expander("News e segnali Gemini"):
                for signal in prediction.news_signals:
                    st.write(
                        f"- {signal.team}: {signal.signal_type} / {signal.severity} "
                        f"({signal.confidence:.0%}) - {signal.reason}"
                    )
                    st.caption(signal.source_url)

        if prediction.news_articles:
            with st.expander("Articoli news trovati", expanded=False):
                for article in prediction.news_articles:
                    st.write(
                        f"- {article.source} | {article.freshness_label} | "
                        f"rilevanza {article.relevance_score:.1f}: [{article.title}]({article.url})"
                    )
                    if article.summary:
                        st.caption(article.summary)

        if prediction.llm_summary:
            with st.expander("Sintesi Gemini", expanded=False):
                st.write(prediction.llm_summary)

        if prediction.stats_notes or prediction.stats_tables:
            with st.expander("Statistiche usate dal modello", expanded=False):
                for note in prediction.stats_notes:
                    st.write(f"- {note}")
                for title, rows in prediction.stats_tables.items():
                    if not rows:
                        continue
                    st.markdown(f"**{title}**")
                    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        if prediction.warnings:
            with st.expander("Warning"):
                for warning in prediction.warnings:
                    st.warning(warning)


def render_gemini_probability_button(
    base_prediction: MatchPrediction,
    displayed_prediction: MatchPrediction,
    prediction_key: str,
) -> None:
    has_model_probability = any(pick.llm_probability is not None for pick in displayed_prediction.picks)
    button_label = "Ricalcola probabilita Gemini" if has_model_probability else "Calcola probabilita Gemini"
    col_button, col_hint = st.columns([1.1, 3])
    if col_button.button(button_label, key=f"gemini_{prediction_key}"):
        service = PredictionService(settings())
        prediction_to_enrich = deepcopy(base_prediction)
        with st.spinner(f"Calcolo Gemini per {prediction_to_enrich.match.label}..."):
            enriched_prediction = service.enrich_prediction_with_gemini(prediction_to_enrich)
        st.session_state.setdefault("llm_requested_predictions", {})[prediction_key] = True
        st.session_state.setdefault("llm_predictions", {})[prediction_key] = enriched_prediction
        st.rerun()
    if has_model_probability:
        col_hint.caption("Probabilita modello calcolata per questa partita.")
    else:
        col_hint.caption("Gemini non parte in automatico: clicca solo sulla partita che vuoi analizzare.")


def _prediction_cache_key(prediction: MatchPrediction) -> str:
    match = prediction.match
    raw = "|".join(
        [
            match.id,
            match.match_date.isoformat(),
            match.home_team,
            match.away_team,
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _without_gemini_output(prediction: MatchPrediction) -> MatchPrediction:
    clean = deepcopy(prediction)
    for pick in clean.picks:
        pick.llm_probability = None
    clean.llm_summary = None
    clean.news_signals = []
    clean.warnings = [warning for warning in clean.warnings if "gemini" not in warning.lower()]
    one_x_two = [pick for pick in clean.picks if pick.market == "1X2"]
    if one_x_two:
        top = max(one_x_two, key=lambda pick: pick.probability)
        clean.summary = (
            f"Pick principale statistico: {top.selection} al {top.probability:.1%}. "
            f"Risultato esatto statistico stimato: {clean.exact_score}."
        )
    return clean


def render_manual_odds_inputs(prediction: MatchPrediction) -> dict[str, float]:
    match = prediction.match
    key_prefix = f"manual_odds_{match.id}".replace(" ", "_").replace("/", "_")
    manual: dict[str, float] = {}
    with st.expander("Inserisci quote bookmaker manuali"):
        st.caption("Opzionale: inserisci quote decimali reali 1X2 per calcolare value. Non vengono salvate.")
        col_home, col_draw, col_away = st.columns(3)
        home_odd = col_home.number_input(
            match.home_team,
            min_value=0.0,
            max_value=1000.0,
            value=0.0,
            step=0.01,
            key=f"{key_prefix}_home",
        )
        draw_odd = col_draw.number_input(
            "Pareggio",
            min_value=0.0,
            max_value=1000.0,
            value=0.0,
            step=0.01,
            key=f"{key_prefix}_draw",
        )
        away_odd = col_away.number_input(
            match.away_team,
            min_value=0.0,
            max_value=1000.0,
            value=0.0,
            step=0.01,
            key=f"{key_prefix}_away",
        )
    if home_odd > 1:
        manual[match.home_team] = home_odd
    if draw_odd > 1:
        manual["Pareggio"] = draw_odd
    if away_odd > 1:
        manual[match.away_team] = away_odd
    return manual


def render_market_table(picks: list[MarketPick], manual_odds: dict[str, float] | None = None) -> None:
    manual_odds = manual_odds or {}
    rows = [
        _market_row(pick, manual_odds)
        for pick in picks
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _market_row(pick: MarketPick, manual_odds: dict[str, float]) -> dict[str, object]:
    bookmaker_odd = pick.market_odd
    if pick.market == "1X2" and pick.selection in manual_odds:
        bookmaker_odd = manual_odds[pick.selection]

    average_probability = pick.average_probability
    computed_value = value_score(average_probability, bookmaker_odd)
    return {
        "Mercato": pick.market,
        "Selezione": pick.selection,
        "Probabilita statistica": f"{pick.probability:.1%}" if pick.probability else "-",
        "Probabilita modello": f"{pick.llm_probability:.1%}" if pick.llm_probability is not None else "-",
        "Media probabilita": f"{average_probability:.1%}" if average_probability else "-",
        "Quota media": _display_number(fair_odd(average_probability)),
        "Quota bookmaker": _display_number(bookmaker_odd),
        "Value": f"{computed_value:+.3f}" if computed_value is not None else "-",
        "Segnale medio": _model_signal(average_probability, pick.market),
        "Value betting": recommendation(average_probability, bookmaker_odd) if bookmaker_odd else "Quota mancante",
        "Conf.": pick.confidence,
    }


def _display_number(value: float | None) -> str:
    return f"{value:.2f}" if value else "-"


def _model_signal(probability: float, market: str) -> str:
    if probability <= 0:
        return "Dati insufficienti"
    if probability >= 0.70:
        return "Forte"
    if probability >= 0.56:
        return "Lean"
    if market == "1X2" and probability >= 0.50:
        return "Pick"
    return "Debole"


if __name__ == "__main__":
    main()
