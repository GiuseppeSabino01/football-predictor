from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import inspect
import json
from html import escape
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from config.competitions import DEFAULT_COMPETITIONS, SUPPORTED_COMPETITIONS
from config.settings import load_settings
from features.market_features import fair_odd, recommendation, value_score
from features.team_strength import canonical_team_name
from nlp.gemini_client import GeminiClient
from nlp.jarvis_assistant import JarvisAssistant
from services.predictor import PredictionService
from schemas import MatchPrediction, MarketPick


st.set_page_config(page_title="Football Betting Predictor", layout="wide")
SESSION_SCHEMA_VERSION = "gigi-v9"
APP_ACCENT_COLORS = ["#19e6b0", "#ffb020", "#f4538a"]
VIEW_OPTIONS = ["Home", "GiGi", "Predict manuale", "Config"]
WORLD_CUP_START = date(2026, 6, 11)


def settings():
    return load_settings()


def require_login() -> bool:
    app_password = settings().app_password
    if not app_password:
        st.warning("APP_PASSWORD non configurata. Aggiungila nel file .env o nei secrets Streamlit.")
        return True
    if st.session_state.get("logged_in"):
        return True

    render_login_header()
    password = st.text_input("Password", type="password")
    if st.button("Entra", type="primary"):
        if password == app_password:
            st.session_state["logged_in"] = True
            st.rerun()
        st.error("Password non corretta.")
    return False


@st.cache_data(ttl=900, show_spinner=False)
def load_predictions(target_date: date, competition_keys: tuple[str, ...]) -> tuple[list[MatchPrediction], list[str]]:
    service = PredictionService(settings())
    signature = inspect.signature(service.predictions_for_date)
    if "competition_keys" in signature.parameters:
        return service.predictions_for_date(target_date, competition_keys=competition_keys)
    return service.predictions_for_date(target_date, worldcup_only="worldcup" in competition_keys)


def main() -> None:
    render_global_styles()
    if not require_login():
        return
    init_session_state()
    apply_pending_navigation()

    with st.sidebar:
        st.markdown('<div class="side-title">Filtro</div>', unsafe_allow_html=True)
        page = st.radio(
            "Schermata",
            VIEW_OPTIONS,
            index=_view_index(st.session_state.get("control_page", "Home")),
            key="control_page",
        )

    render_app_header(page)
    if page == "Config":
        render_config()
    elif page == "GiGi":
        render_jarvis_page()
    elif page == "Predict manuale":
        render_manual_prediction()
    else:
        target_date, competition_keys = render_control_panel()
        render_predictions(target_date, competition_keys)


def apply_pending_navigation() -> None:
    next_page = st.session_state.pop("pending_control_page", None)
    if next_page in VIEW_OPTIONS:
        st.session_state["control_page"] = next_page
    current_page = st.session_state.get("control_page", "Home")
    if current_page in {"Jarvis", "GIGI"}:
        current_page = "GiGi"
    if current_page not in VIEW_OPTIONS:
        current_page = "Home"
    st.session_state["control_page"] = current_page


def render_global_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg: #080a0b;
            --panel: rgba(16, 20, 22, 0.86);
            --panel-strong: rgba(22, 28, 30, 0.94);
            --line: rgba(25, 230, 176, 0.24);
            --line-soft: rgba(244, 251, 247, 0.10);
            --text: #f4fbf7;
            --muted: #8e9b96;
            --teal: #19e6b0;
            --amber: #ffb020;
            --rose: #f4538a;
            --cyan: #62d8ff;
            --radius: 8px;
        }

        html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
            background: var(--bg);
            color: var(--text);
        }

        [data-testid="stAppViewContainer"]::before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            background:
                linear-gradient(90deg, rgba(25,230,176,0.06) 1px, transparent 1px),
                linear-gradient(180deg, rgba(255,176,32,0.045) 1px, transparent 1px),
                linear-gradient(135deg, rgba(25,230,176,0.16), transparent 32%),
                linear-gradient(225deg, rgba(244,83,138,0.12), transparent 36%),
                #080a0b;
            background-size: 44px 44px, 44px 44px, 100% 100%, 100% 100%, 100% 100%;
            z-index: -1;
        }

        .stApp {
            background: transparent;
        }

        .main .block-container {
            max-width: 1180px;
            padding-top: 1.35rem;
            padding-bottom: 4rem;
        }

        [data-testid="stSidebar"] {
            background:
                linear-gradient(180deg, rgba(16,20,22,0.98), rgba(8,10,11,0.98)),
                #101416;
            border-right: 1px solid rgba(25,230,176,0.22);
        }

        [data-testid="stSidebar"] * {
            color: var(--text);
        }

        .side-title {
            color: var(--teal);
            font-size: 0.92rem;
            font-weight: 800;
            margin: 0.8rem 0 0.65rem;
        }

        h1, h2, h3, p, label, span {
            letter-spacing: 0;
        }

        .app-hero {
            position: relative;
            overflow: hidden;
            border-radius: var(--radius);
            border: 1px solid rgba(25,230,176,0.28);
            background:
                linear-gradient(135deg, rgba(25,230,176,0.18), rgba(255,176,32,0.075) 45%, rgba(244,83,138,0.12)),
                rgba(13, 17, 18, 0.92);
            box-shadow: 0 18px 50px rgba(0,0,0,0.34), inset 0 1px 0 rgba(255,255,255,0.08);
            padding: 0.95rem 1.1rem;
            margin-bottom: 0.8rem;
        }

        .app-hero::after {
            content: "";
            position: absolute;
            inset: 0;
            pointer-events: none;
            background:
                repeating-linear-gradient(135deg, transparent 0 18px, rgba(244,251,247,0.045) 18px 19px);
            opacity: 0.8;
        }

        .app-hero-inner {
            position: relative;
            z-index: 1;
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 1rem;
            align-items: center;
        }

        .app-title {
            margin: 0;
            color: var(--text);
            font-size: 1.85rem;
            line-height: 1.05;
            font-weight: 900;
        }

        .app-kicker {
            margin: 0 0 0.45rem;
            color: var(--teal);
            font-size: 0.82rem;
            font-weight: 800;
        }

        .app-subtitle {
            margin: 0.45rem 0 0;
            max-width: 720px;
            color: #c8d6d1;
            font-size: 0.98rem;
        }

        .hero-chip {
            border-radius: var(--radius);
            border: 1px solid rgba(255,176,32,0.34);
            background: rgba(255,176,32,0.10);
            color: #ffe5ad;
            padding: 0.72rem 0.9rem;
            font-weight: 800;
            white-space: nowrap;
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            background:
                linear-gradient(180deg, rgba(18,24,25,0.94), rgba(10,13,14,0.92)),
                var(--panel);
            border: 1px solid rgba(25,230,176,0.23);
            border-radius: var(--radius);
            box-shadow: 0 16px 42px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.055);
        }

        .match-hero {
            display: grid;
            grid-template-columns: minmax(0, 1.55fr) minmax(260px, 0.95fr);
            gap: 1rem;
            align-items: start;
            padding: 0.15rem 0 0.35rem;
        }

        .match-meta {
            color: var(--muted);
            font-size: 0.83rem;
            margin-bottom: 0.45rem;
        }

        .match-title {
            color: var(--text);
            font-size: 1.62rem;
            line-height: 1.16;
            margin: 0;
            font-weight: 900;
            overflow-wrap: anywhere;
        }

        .match-summary {
            color: #c9d7d1;
            margin: 0.85rem 0 0;
            font-size: 0.98rem;
            line-height: 1.55;
        }

        .metric-stack {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.55rem;
        }

        .neo-metric {
            min-height: 86px;
            border-radius: var(--radius);
            border: 1px solid var(--line-soft);
            background:
                linear-gradient(180deg, rgba(244,251,247,0.07), rgba(244,251,247,0.025));
            padding: 0.72rem;
        }

        .neo-metric-label {
            color: var(--muted);
            font-size: 0.75rem;
            margin-bottom: 0.35rem;
        }

        .neo-metric-value {
            color: var(--text);
            font-size: 1.45rem;
            line-height: 1.12;
            font-weight: 900;
            overflow-wrap: anywhere;
        }

        .neo-metric-value.accent {
            color: var(--teal);
        }

        .prob-strip {
            margin-top: 0.8rem;
        }

        .prob-track {
            display: flex;
            height: 10px;
            overflow: hidden;
            border-radius: 999px;
            background: rgba(244,251,247,0.08);
            border: 1px solid rgba(244,251,247,0.08);
        }

        .prob-segment {
            height: 100%;
        }

        .prob-legend {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.45rem;
            margin-top: 0.45rem;
        }

        .prob-item {
            color: #cbd8d4;
            font-size: 0.78rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .viz-grid {
            display: grid;
            grid-template-columns: minmax(190px, 0.75fr) minmax(260px, 1.25fr) minmax(230px, 1fr);
            gap: 0.65rem;
            margin: 0.8rem 0 0.8rem;
        }

        .viz-card {
            border-radius: var(--radius);
            border: 1px solid rgba(244,251,247,0.12);
            background:
                linear-gradient(180deg, rgba(244,251,247,0.065), rgba(244,251,247,0.025));
            padding: 0.78rem;
            min-height: 142px;
        }

        .viz-title {
            color: var(--muted);
            font-size: 0.75rem;
            font-weight: 800;
            margin-bottom: 0.7rem;
        }

        .gauge-wrap {
            display: grid;
            grid-template-columns: 94px minmax(0, 1fr);
            gap: 0.72rem;
            align-items: center;
        }

        .gauge {
            width: 92px;
            aspect-ratio: 1;
            border-radius: 999px;
            display: grid;
            place-items: center;
            box-shadow: inset 0 0 0 1px rgba(244,251,247,0.10), 0 12px 28px rgba(0,0,0,0.22);
        }

        .gauge-core {
            width: 66px;
            aspect-ratio: 1;
            border-radius: 999px;
            background: #0b1011;
            display: grid;
            place-items: center;
            color: var(--text);
            font-weight: 900;
            font-size: 0.92rem;
            border: 1px solid rgba(244,251,247,0.09);
        }

        .gauge-pick {
            color: var(--text);
            font-size: 1.02rem;
            font-weight: 900;
            overflow-wrap: anywhere;
            line-height: 1.16;
        }

        .gauge-note {
            color: var(--muted);
            font-size: 0.76rem;
            margin-top: 0.35rem;
        }

        .market-bars {
            display: grid;
            gap: 0.48rem;
        }

        .bar-row {
            display: grid;
            grid-template-columns: minmax(72px, 0.82fr) minmax(130px, 1.55fr) 44px;
            gap: 0.5rem;
            align-items: center;
        }

        .bar-label {
            color: #d9e7e2;
            font-size: 0.84rem;
            font-weight: 850;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .bar-track {
            height: 8px;
            overflow: hidden;
            border-radius: 999px;
            background: rgba(244,251,247,0.08);
            border: 1px solid rgba(244,251,247,0.06);
        }

        .bar-fill {
            height: 100%;
            border-radius: 999px;
            box-shadow: 0 0 18px rgba(25,230,176,0.24);
        }

        .bar-value {
            color: var(--text);
            font-size: 0.76rem;
            font-weight: 800;
            text-align: right;
        }

        .form-board {
            display: grid;
            gap: 0.56rem;
        }

        .form-team {
            display: grid;
            grid-template-columns: minmax(80px, 0.9fr) minmax(0, 1.8fr);
            gap: 0.55rem;
            align-items: center;
        }

        .form-name {
            color: #d9e7e2;
            font-size: 0.78rem;
            font-weight: 800;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .form-chips {
            display: flex;
            gap: 0.28rem;
            flex-wrap: wrap;
        }

        .form-chip {
            width: 22px;
            height: 22px;
            border-radius: 999px;
            display: inline-grid;
            place-items: center;
            font-size: 0.68rem;
            font-weight: 900;
            border: 1px solid rgba(244,251,247,0.12);
        }

        .form-chip.win {
            color: #06100d;
            background: var(--teal);
        }

        .form-chip.draw {
            color: #1a1000;
            background: var(--amber);
        }

        .form-chip.loss {
            color: #fff2f7;
            background: var(--rose);
        }

        .form-empty {
            color: var(--muted);
            font-size: 0.78rem;
        }

        .dot {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 999px;
            margin-right: 0.32rem;
            vertical-align: 1px;
        }

        div.stButton > button {
            min-height: 2.55rem;
            border-radius: var(--radius);
            border: 1px solid rgba(25,230,176,0.38);
            background:
                linear-gradient(135deg, rgba(25,230,176,0.95), rgba(98,216,255,0.78));
            color: #06100d;
            font-weight: 900;
            box-shadow: 0 8px 24px rgba(25,230,176,0.18);
        }

        div.stButton > button:hover {
            border-color: rgba(255,176,32,0.68);
            color: #06100d;
            box-shadow: 0 10px 30px rgba(255,176,32,0.16);
        }

        [data-baseweb="input"] {
            border-radius: var(--radius);
            border: 1px solid rgba(244,251,247,0.13);
            background: rgba(244,251,247,0.055);
        }

        [data-baseweb="input"] input {
            color: var(--text);
        }

        [data-baseweb="radio"] {
            border-radius: var(--radius);
            padding: 0.18rem 0.25rem;
        }

        [data-baseweb="radio"] div[aria-checked="true"] {
            border-color: var(--teal);
        }

        [data-testid="stExpander"] {
            border: 1px solid rgba(244,251,247,0.12);
            border-radius: var(--radius);
            background: rgba(244,251,247,0.035);
        }

        [data-testid="stAlert"] {
            border-radius: var(--radius);
            border: 1px solid rgba(25,230,176,0.22);
            background: rgba(25,230,176,0.08);
            color: var(--text);
        }

        [data-testid="stDataFrame"] {
            border-radius: var(--radius);
            overflow: hidden;
            border: 1px solid rgba(244,251,247,0.12);
        }

        .section-heading {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin: 1.1rem 0 0.85rem;
        }

        .section-heading h2 {
            margin: 0;
            color: var(--text);
            font-size: 1.45rem;
            font-weight: 900;
        }

        .section-pill {
            border: 1px solid rgba(244,83,138,0.34);
            background: rgba(244,83,138,0.10);
            color: #ffd3df;
            border-radius: var(--radius);
            padding: 0.42rem 0.62rem;
            font-size: 0.78rem;
            font-weight: 800;
        }

        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 0.7rem;
            margin: 0.8rem 0 1rem;
        }

        .status-card {
            border-radius: var(--radius);
            border: 1px solid rgba(244,251,247,0.12);
            background: rgba(244,251,247,0.045);
            padding: 0.85rem;
        }

        .status-name {
            color: var(--muted);
            font-size: 0.78rem;
            margin-bottom: 0.35rem;
        }

        .status-ok {
            color: var(--teal);
            font-weight: 900;
        }

        .status-missing {
            color: var(--amber);
            font-weight: 900;
        }

        .gigi-message {
            border-radius: var(--radius);
            border: 1px solid rgba(244,251,247,0.10);
            background: rgba(244,251,247,0.045);
            padding: 0.7rem;
            margin: 0.45rem 0;
            color: #d9e7e2;
            font-size: 0.88rem;
            line-height: 1.45;
        }

        .gigi-message.gigi-user {
            border-color: rgba(25,230,176,0.26);
            background: rgba(25,230,176,0.075);
        }

        .gigi-message.gigi-assistant {
            border-color: rgba(98,216,255,0.24);
            background: rgba(98,216,255,0.065);
        }

        .gigi-role {
            color: var(--teal);
            font-size: 0.72rem;
            font-weight: 900;
            margin-bottom: 0.22rem;
        }

        .control-panel-title {
            color: var(--teal);
            font-size: 0.78rem;
            font-weight: 900;
            margin: 0.1rem 0 0.7rem;
        }

        .control-panel-caption {
            color: var(--muted);
            font-size: 0.78rem;
            margin-top: -0.2rem;
            margin-bottom: 0.55rem;
        }

        .desktop-control-card [data-testid="stVerticalBlockBorderWrapper"] {
            padding-top: 0;
            padding-bottom: 0;
        }

        .desktop-control-card .control-panel-title,
        .desktop-control-card .control-panel-caption {
            display: none;
        }

        @media (max-width: 760px) {
            .main .block-container {
                padding-left: 0.75rem;
                padding-right: 0.75rem;
                padding-top: 1rem;
            }

            .desktop-control-card .control-panel-title,
            .desktop-control-card .control-panel-caption {
                display: block;
            }

            .app-hero-inner,
            .match-hero {
                grid-template-columns: 1fr;
            }

            .app-title {
                font-size: 1.7rem;
            }

            .metric-stack {
                grid-template-columns: 1fr;
            }

            .prob-legend {
                grid-template-columns: 1fr;
            }

            .viz-grid {
                grid-template-columns: 1fr;
            }

            .hero-chip {
                width: fit-content;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_login_header() -> None:
    st.markdown(
        """
        <div class="app-hero">
            <div class="app-hero-inner">
                <div>
                    <p class="app-kicker">Private model console</p>
                    <h1 class="app-title">Football Betting Predictor</h1>
                    <p class="app-subtitle">Accesso protetto</p>
                </div>
                <div class="hero-chip">LOCKED</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_app_header(page: str) -> None:
    st.markdown(
        f"""
        <div class="app-hero">
            <div class="app-hero-inner">
                <div>
                    <p class="app-kicker">{escape(page)}</p>
                    <h1 class="app-title">Football Betting Predictor</h1>
                    <p class="app-subtitle">Probabilita, value e segnali partita in un cockpit personale.</p>
                </div>
                <div class="hero-chip">MODEL READY</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def init_session_state() -> None:
    if st.session_state.get("session_schema_version") == SESSION_SCHEMA_VERSION:
        return
    load_predictions.clear()
    st.session_state["session_schema_version"] = SESSION_SCHEMA_VERSION
    st.session_state.setdefault("control_page", "Home")
    st.session_state.setdefault("control_date", date.today())
    st.session_state.setdefault("selected_competitions", ["worldcup"])
    st.session_state.pop("llm_predictions", None)
    st.session_state.pop("llm_requested_predictions", None)
    st.session_state.pop("manual_prediction", None)


def render_control_panel() -> tuple[date, tuple[str, ...]]:
    st.markdown('<div class="desktop-control-card">', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(
            """
            <div class="control-panel-title">Home</div>
            <div class="control-panel-caption">Inserisci data e campionati da analizzare.</div>
            """,
            unsafe_allow_html=True,
        )
        col_date, col_competitions = st.columns([0.85, 1.8])
        selected_date = col_date.date_input(
            "Data",
            key="control_date",
            min_value=date(2024, 1, 1),
            max_value=date(2035, 12, 31),
        )
        selected_competitions = col_competitions.multiselect(
            "Campionati",
            list(SUPPORTED_COMPETITIONS.keys()),
            key="selected_competitions",
            format_func=_competition_label,
            placeholder="Scegli uno o piu campionati",
        )

        target_date = selected_date if isinstance(selected_date, date) else date.today()
        if "worldcup" in selected_competitions and target_date < WORLD_CUP_START:
            target_date = WORLD_CUP_START
            st.info("Per i Mondiali uso la prima data disponibile: 2026-06-11.")

    st.markdown("</div>", unsafe_allow_html=True)
    return target_date, tuple(selected_competitions)


def _view_index(page: str) -> int:
    return VIEW_OPTIONS.index(page) if page in VIEW_OPTIONS else 0


def _competition_label(key: str) -> str:
    competition = SUPPORTED_COMPETITIONS.get(key)
    return competition.name if competition else key


def _selected_competitions_label(keys: tuple[str, ...]) -> str:
    if len(keys) == len(DEFAULT_COMPETITIONS):
        return "Tutti"
    if len(keys) <= 2:
        return ", ".join(_competition_label(key) for key in keys)
    return f"{len(keys)} campionati"


def render_config() -> None:
    cfg = settings()
    rows = [
        ("Gemini", cfg.has_gemini),
        ("API-Football", cfg.has_api_football),
        ("football-data.org", cfg.has_football_data_org),
        ("Supabase", cfg.has_supabase),
        ("Password app", bool(cfg.app_password)),
    ]
    render_section_heading("Stato configurazione", "runtime")
    status_cards = []
    for name, ok in rows:
        class_name = "status-ok" if ok else "status-missing"
        label = "OK" if ok else "mancante"
        status_cards.append(
            f"""
            <div class="status-card">
                <div class="status-name">{escape(name)}</div>
                <div class="{class_name}">{label}</div>
            </div>
            """
        )
    st.markdown(f'<div class="status-grid">{"".join(status_cards)}</div>', unsafe_allow_html=True)
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


def render_jarvis_page() -> None:
    prediction = st.session_state.get("jarvis_prediction")
    prediction_key = st.session_state.get("jarvis_prediction_key", "")
    if not prediction:
        render_section_heading("GiGi", "nessuna partita")
        st.info("Apri GiGi dal pulsante dentro una scheda partita.")
        return

    messages = st.session_state.setdefault("jarvis_messages", [])
    last_answer = next(
        (
            message["content"]
            for message in reversed(messages)
            if message["role"] == "assistant" and not message["content"].startswith("Warning:")
        ),
        "",
    )

    visual_col, chat_col = st.columns([2.1, 0.95], gap="medium")
    with visual_col:
        render_jarvis_console(prediction, last_answer)

    with chat_col:
        render_gigi_side_panel(prediction, messages)


def render_gigi_side_panel(prediction: MatchPrediction, messages: list[dict[str, str]]) -> None:
    with st.container(border=True):
        st.markdown("### GiGi")
        st.caption(f"Contesto: {prediction.match.label}")
        if st.button("Torna alle partite", key="jarvis_back_home"):
            st.session_state["pending_control_page"] = "Home"
            st.rerun()

        st.markdown("**Conversazione**")
        if not messages:
            st.caption("Registra una domanda oppure scrivila qui sotto.")
        for message in messages[-10:]:
            role = "Tu" if message["role"] == "user" else "GiGi"
            css_class = "gigi-user" if message["role"] == "user" else "gigi-assistant"
            st.markdown(
                f"""
                <div class="gigi-message {css_class}">
                    <div class="gigi-role">{escape(role)}</div>
                    <div>{escape(message["content"])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        render_gigi_audio_input(prediction)

        with st.form("gigi_text_form", clear_on_submit=True):
            question = st.text_area("Scrivi", placeholder="Es. chi pensi che vincera?", height=92)
            submitted = st.form_submit_button("Invia a GiGi")
        if submitted and question.strip():
            ask_jarvis_text(prediction, question)


def render_gigi_audio_input(prediction: MatchPrediction) -> None:
    if not hasattr(st, "audio_input"):
        st.caption("Input vocale non disponibile: usa il campo scritto.")
        return

    st.markdown("**Voce**")
    audio_key = f"gigi_audio_{prediction.match.id}_{len(st.session_state.get('jarvis_messages', []))}"
    audio_value = st.audio_input("Parla con GiGi", key=audio_key, label_visibility="collapsed")
    if audio_value is None:
        st.caption("Premi il microfono, parla, poi termina: GiGi riceve l'audio automaticamente.")
        return

    audio_bytes = audio_value.getvalue()
    if not audio_bytes:
        return
    audio_hash = hashlib.sha1(audio_bytes).hexdigest()
    processed_key = f"gigi_audio_processed_{prediction.match.id}"
    if st.session_state.get(processed_key) == audio_hash:
        st.caption("Audio gia inviato.")
        return
    st.session_state[processed_key] = audio_hash
    ask_jarvis_audio(prediction, audio_bytes, getattr(audio_value, "type", None) or "audio/wav")


def render_jarvis_open_button(prediction: MatchPrediction, prediction_key: str) -> None:
    col_button, col_hint = st.columns([1.1, 3])
    if col_button.button("Parla con GiGi", key=f"jarvis_open_{prediction_key}"):
        if st.session_state.get("jarvis_prediction_key") != prediction_key:
            st.session_state["jarvis_messages"] = []
            st.session_state["jarvis_speech_nonce"] = 0
        st.session_state["jarvis_prediction"] = deepcopy(prediction)
        st.session_state["jarvis_prediction_key"] = prediction_key
        st.session_state["pending_control_page"] = "GiGi"
        st.rerun()
    col_hint.caption("Chatta con GiGi usando le statistiche di questa partita.")


def ask_jarvis_text(prediction: MatchPrediction, question: str) -> None:
    messages = st.session_state.setdefault("jarvis_messages", [])
    messages.append({"role": "user", "content": question})
    assistant = JarvisAssistant(GeminiClient(settings()))
    with st.spinner("GiGi sta analizzando la partita..."):
        reply = assistant.answer_text(prediction, question)
    messages.append({"role": "assistant", "content": reply.answer})
    for warning in reply.warnings:
        messages.append({"role": "assistant", "content": f"Warning: {warning}"})
    st.session_state["jarvis_speech_nonce"] = st.session_state.get("jarvis_speech_nonce", 0) + 1
    st.rerun()


def ask_jarvis_audio(prediction: MatchPrediction, audio_bytes: bytes, mime_type: str) -> None:
    messages = st.session_state.setdefault("jarvis_messages", [])
    messages.append({"role": "user", "content": "Domanda vocale registrata."})
    assistant = JarvisAssistant(GeminiClient(settings()))
    with st.spinner("GiGi sta ascoltando e analizzando..."):
        reply = assistant.answer_audio(prediction, audio_bytes, mime_type)
    messages.append({"role": "assistant", "content": reply.answer})
    for warning in reply.warnings:
        messages.append({"role": "assistant", "content": f"Warning: {warning}"})
    st.session_state["jarvis_speech_nonce"] = st.session_state.get("jarvis_speech_nonce", 0) + 1
    st.rerun()


def render_jarvis_console(prediction: MatchPrediction, last_answer: str) -> None:
    match = escape(prediction.match.label)
    competition = escape(prediction.match.competition)
    spoken_text = _jarvis_speech_text(last_answer)
    speech_json = json.dumps(spoken_text)
    nonce = int(st.session_state.get("jarvis_speech_nonce", 0))
    components.html(
        f"""
        <div class="jarvis-stage">
            <div class="hud-panel top-left">
                <div class="hud-title">MATCH DATA</div>
                <div>{match}</div>
                <small>{competition}</small>
            </div>
            <div class="hud-panel top-right">
                <div class="hud-title">GiGi OS</div>
                <div>voice synthesis: online</div>
                <div>speech input: browser</div>
            </div>
            <div class="jarvis-core" id="jarvis-core">
                <div class="ring r1"></div>
                <div class="ring r2"></div>
                <div class="triangle"></div>
                <div class="pulse"></div>
            </div>
            <button class="voice-unlock" id="voice-unlock" onclick="enableGigiVoice()">Attiva voce GiGi</button>
            <div class="voice-status" id="voice-status">microfono nel pannello GiGi</div>
            <div class="wave-row">
                <span></span><span></span><span></span><span></span><span></span><span></span>
                <span></span><span></span><span></span><span></span><span></span><span></span>
            </div>
        </div>
        <style>
            .jarvis-stage {{
                position: relative;
                height: 690px;
                min-height: 68vh;
                overflow: hidden;
                border-radius: 8px;
                border: 1px solid rgba(98,216,255,.35);
                background:
                    radial-gradient(circle at center, rgba(98,216,255,.20), transparent 28%),
                    linear-gradient(135deg, rgba(25,230,176,.10), rgba(8,10,11,.96) 42%, rgba(244,83,138,.10)),
                    repeating-linear-gradient(90deg, rgba(98,216,255,.10) 0 1px, transparent 1px 42px),
                    #05090b;
                color: #dff9ff;
                font-family: Inter, system-ui, sans-serif;
                box-shadow: inset 0 0 60px rgba(98,216,255,.12), 0 18px 50px rgba(0,0,0,.35);
            }}
            .hud-panel {{
                position: absolute;
                z-index: 3;
                border: 1px solid rgba(98,216,255,.25);
                background: rgba(6,14,18,.72);
                padding: 10px 12px;
                border-radius: 8px;
                font-size: 12px;
                line-height: 1.45;
                box-shadow: 0 0 24px rgba(98,216,255,.10);
            }}
            .hud-panel small {{ color: rgba(223,249,255,.62); }}
            .hud-title {{ color: #19e6b0; font-weight: 900; font-size: 11px; margin-bottom: 4px; }}
            .top-left {{ top: 16px; left: 16px; max-width: 38%; }}
            .top-right {{ top: 16px; right: 16px; }}
            .jarvis-core {{
                position: absolute;
                inset: 0;
                margin: auto;
                width: min(34vw, 260px);
                height: min(34vw, 260px);
                min-width: 190px;
                min-height: 190px;
                border-radius: 50%;
                display: grid;
                place-items: center;
                filter: drop-shadow(0 0 28px rgba(98,216,255,.65));
            }}
            .ring {{
                position: absolute;
                inset: 0;
                border-radius: 50%;
                border: 2px solid rgba(98,216,255,.82);
                box-shadow: inset 0 0 28px rgba(98,216,255,.22), 0 0 24px rgba(98,216,255,.28);
            }}
            .r1 {{ border-style: dashed; }}
            .r2 {{ inset: 22px; border-color: rgba(25,230,176,.78); }}
            .triangle {{
                width: 76px;
                height: 76px;
                background: linear-gradient(180deg, rgba(98,216,255,.95), rgba(25,230,176,.25));
                clip-path: polygon(50% 5%, 95% 92%, 5% 92%);
                box-shadow: 0 0 35px rgba(98,216,255,.8);
            }}
            .pulse {{
                position: absolute;
                width: 118px;
                height: 118px;
                border-radius: 50%;
                border: 1px solid rgba(255,255,255,.3);
                opacity: .32;
            }}
            .jarvis-core.speaking .r1 {{ animation: spin 8s linear infinite; }}
            .jarvis-core.speaking .r2 {{ animation: spinReverse 5.5s linear infinite; }}
            .jarvis-core.speaking .triangle {{ animation: talk 280ms ease-in-out infinite; }}
            .jarvis-core.speaking .pulse {{ animation: pulse 520ms ease-out infinite; }}
            .voice-status {{
                position: absolute;
                left: 50%;
                bottom: 42px;
                transform: translateX(-50%);
                color: rgba(223,249,255,.72);
                font-size: 12px;
                font-weight: 800;
                letter-spacing: 0;
                text-align: center;
            }}
            .voice-unlock {{
                position: absolute;
                left: 50%;
                bottom: 72px;
                transform: translateX(-50%);
                border: 1px solid rgba(25,230,176,.5);
                border-radius: 8px;
                background: linear-gradient(135deg, rgba(25,230,176,.95), rgba(98,216,255,.78));
                color: #04100e;
                font-weight: 900;
                padding: 10px 14px;
                cursor: pointer;
            }}
            .voice-unlock.enabled {{
                background: rgba(25,230,176,.10);
                color: #19e6b0;
                border-color: rgba(25,230,176,.25);
            }}
            .wave-row {{
                position: absolute;
                left: 24px;
                right: 24px;
                bottom: 122px;
                display: flex;
                gap: 7px;
                justify-content: center;
                opacity: .82;
            }}
            .wave-row span {{
                width: 5px;
                height: 18px;
                border-radius: 999px;
                background: #62d8ff;
                transform: scaleY(.45);
            }}
            .wave-row span:nth-child(2n) {{ animation-delay: .12s; background: #19e6b0; }}
            .wave-row span:nth-child(3n) {{ animation-delay: .22s; height: 26px; }}
            .jarvis-stage.speaking .wave-row span {{ animation: wave 1.05s ease-in-out infinite; }}
            @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
            @keyframes spinReverse {{ to {{ transform: rotate(-360deg); }} }}
            @keyframes breathe {{ 0%,100% {{ transform: scale(.96); }} 50% {{ transform: scale(1.04); }} }}
            @keyframes talk {{ 0%,100% {{ transform: scale(.88); filter: brightness(1); }} 50% {{ transform: scale(1.16); filter: brightness(1.45); }} }}
            @keyframes pulse {{ from {{ transform: scale(.72); opacity: .82; }} to {{ transform: scale(1.8); opacity: 0; }} }}
            @keyframes wave {{ 0%,100% {{ transform: scaleY(.45); }} 50% {{ transform: scaleY(1.55); }} }}
        </style>
        <script>
            const jarvisText = {speech_json};
            const jarvisNonce = {nonce};
            const stage = document.querySelector(".jarvis-stage");
            const core = document.getElementById("jarvis-core");
            const voiceStatus = document.getElementById("voice-status");
            const voiceUnlock = document.getElementById("voice-unlock");
            const voiceEnabledKey = "gigi_voice_enabled";
            function pickItalianVoice() {{
                const voices = window.speechSynthesis.getVoices() || [];
                return voices.find(v => v.lang === "it-IT" && /Microsoft|Google|Elsa|Isabella|Diego/i.test(v.name))
                    || voices.find(v => v.lang === "it-IT")
                    || voices.find(v => v.lang && v.lang.startsWith("it"))
                    || null;
            }}
            function speakJarvis() {{
                if (!jarvisText || !("speechSynthesis" in window)) return;
                window.speechSynthesis.cancel();
                const utterance = new SpeechSynthesisUtterance(jarvisText);
                utterance.lang = "it-IT";
                utterance.rate = 1.16;
                utterance.pitch = .96;
                utterance.volume = 1;
                const voice = pickItalianVoice();
                if (voice) utterance.voice = voice;
                utterance.onstart = () => {{
                    core.classList.add("speaking");
                    stage.classList.add("speaking");
                    voiceStatus.textContent = "GiGi sta parlando";
                }};
                const stopSpeaking = () => {{
                    core.classList.remove("speaking");
                    stage.classList.remove("speaking");
                    voiceStatus.textContent = window.localStorage.getItem(voiceEnabledKey) === "1"
                        ? "voce attiva: microfono nel pannello GiGi"
                        : "premi Attiva voce GiGi";
                }};
                utterance.onend = stopSpeaking;
                utterance.onerror = (event) => {{
                    stopSpeaking();
                    voiceStatus.textContent = "audio bloccato: premi Attiva voce GiGi";
                    voiceUnlock.classList.remove("enabled");
                    voiceUnlock.textContent = "Attiva voce GiGi";
                    window.localStorage.removeItem(voiceEnabledKey);
                }};
                window.speechSynthesis.speak(utterance);
            }}
            function markVoiceEnabled() {{
                window.localStorage.setItem(voiceEnabledKey, "1");
                voiceUnlock.classList.add("enabled");
                voiceUnlock.textContent = "Voce attiva";
                voiceStatus.textContent = "voce attiva: le risposte partiranno da sole";
            }}
            function enableGigiVoice() {{
                if (!("speechSynthesis" in window)) {{
                    voiceStatus.textContent = "sintesi vocale non supportata dal browser";
                    return;
                }}
                markVoiceEnabled();
                if (jarvisText) {{
                    speakJarvis();
                    return;
                }}
                const unlock = new SpeechSynthesisUtterance("Voce attiva.");
                unlock.lang = "it-IT";
                unlock.rate = 1.16;
                unlock.pitch = .96;
                const voice = pickItalianVoice();
                if (voice) unlock.voice = voice;
                window.speechSynthesis.cancel();
                window.speechSynthesis.speak(unlock);
            }}
            if (window.localStorage.getItem(voiceEnabledKey) === "1") {{
                markVoiceEnabled();
            }}
            const autoKey = "jarvis_spoken_" + jarvisNonce;
            if (jarvisText && jarvisNonce && window.localStorage.getItem(voiceEnabledKey) === "1" && !window.sessionStorage.getItem(autoKey)) {{
                window.sessionStorage.setItem(autoKey, "1");
                if (window.speechSynthesis.getVoices().length) {{
                    setTimeout(speakJarvis, 250);
                }} else {{
                    window.speechSynthesis.onvoiceschanged = () => setTimeout(speakJarvis, 250);
                    setTimeout(speakJarvis, 900);
                }}
            }}
        </script>
        """,
        height=720,
        scrolling=False,
    )


def _jarvis_speech_text(answer: str) -> str:
    cleaned = " ".join(answer.replace("Warning:", "").split())
    return cleaned[:900]


def render_predictions(target_date: date, competition_keys: tuple[str, ...]) -> None:
    if not competition_keys:
        st.info("Seleziona almeno un campionato nella Home.")
        return
    with st.spinner("Carico partite, quote, news e pronostici..."):
        try:
            predictions, errors = load_predictions(target_date, competition_keys)
        except TypeError as exc:
            st.error("Errore di compatibilita nel servizio predizioni. Riavvia l'app Streamlit dopo il deploy.")
            st.code(str(exc))
            return

    if errors:
        with st.expander("Warning fonti dati", expanded=False):
            for error in errors:
                st.warning(error)

    if not predictions:
        st.info("Nessuna partita trovata per questa data nelle competizioni configurate.")
        if "worldcup" in competition_keys:
            st.caption("Per i Mondiali prova dall'11 giugno 2026 in avanti.")
        return

    competition_label = _selected_competitions_label(competition_keys)
    render_section_heading(f"Pronostici del {target_date.isoformat()}", f"{len(predictions)} match | {competition_label}")
    for prediction in predictions:
        render_prediction_card(prediction)


def render_prediction_card(prediction: MatchPrediction) -> None:
    base_prediction = _without_gemini_output(prediction)
    prediction_key = _prediction_cache_key(base_prediction)
    cached_prediction = load_saved_gemini_prediction(base_prediction, prediction_key)
    if cached_prediction:
        prediction = cached_prediction
    else:
        prediction = base_prediction

    match = prediction.match
    with st.container(border=True):
        top = max((pick for pick in prediction.picks if pick.market == "1X2"), key=lambda p: p.average_probability)
        render_match_header(prediction, top)
        render_gemini_probability_button(base_prediction, prediction, prediction_key)
        render_jarvis_open_button(prediction, prediction_key)
        render_match_visuals(prediction, top)
        manual_odds = render_manual_odds_inputs(prediction)
        if not any(pick.market_odd for pick in prediction.picks) and not manual_odds:
            st.info(
                "Quote bookmaker non disponibili da fonti gratuite per questa partita. "
                "La tabella mostra quote medie; value betting sospeso senza quote reali."
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
                    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        if prediction.warnings:
            with st.expander("Warning"):
                for warning in prediction.warnings:
                    st.warning(warning)


def render_section_heading(title: str, pill: str) -> None:
    st.markdown(
        f"""
        <div class="section-heading">
            <h2>{escape(title)}</h2>
            <div class="section-pill">{escape(pill)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_match_header(prediction: MatchPrediction, top: MarketPick) -> None:
    match = prediction.match
    one_x_two = [pick for pick in prediction.picks if pick.market == "1X2"]
    probability_strip = render_probability_strip(one_x_two)
    summary = escape(prediction.summary)
    stage = escape(match.stage or "fase non specificata")
    competition = escape(match.competition)
    title = escape(match.label)
    pick = escape(top.selection)
    confidence = escape(prediction.confidence)
    probability = f"{top.average_probability:.1%}"
    st.markdown(
        f"""
        <div class="match-hero">
            <div>
                <div class="match-meta">{competition} | {stage}</div>
                <h2 class="match-title">{title}</h2>
                <p class="match-summary">{summary}</p>
                {probability_strip}
            </div>
            <div class="metric-stack">
                <div class="neo-metric">
                    <div class="neo-metric-label">Pick</div>
                    <div class="neo-metric-value accent">{pick}</div>
                </div>
                <div class="neo-metric">
                    <div class="neo-metric-label">Prob. media</div>
                    <div class="neo-metric-value">{probability}</div>
                </div>
                <div class="neo-metric">
                    <div class="neo-metric-label">Confidenza</div>
                    <div class="neo-metric-value">{confidence}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_probability_strip(picks: list[MarketPick]) -> str:
    if len(picks) < 3:
        return ""
    segments = []
    labels = []
    total = sum(max(0.0, pick.average_probability) for pick in picks) or 1
    for index, pick in enumerate(picks[:3]):
        color = APP_ACCENT_COLORS[index % len(APP_ACCENT_COLORS)]
        width = max(4.0, min(100.0, pick.average_probability / total * 100))
        label = escape(pick.selection)
        probability = f"{pick.average_probability:.1%}"
        segments.append(
            f'<div class="prob-segment" style="width:{width:.2f}%; background:{color};"></div>'
        )
        labels.append(
            f'<div class="prob-item"><span class="dot" style="background:{color};"></span>{label} {probability}</div>'
        )
    return (
        '<div class="prob-strip">'
        f'<div class="prob-track">{"".join(segments)}</div>'
        f'<div class="prob-legend">{"".join(labels)}</div>'
        '</div>'
    )


def render_match_visuals(prediction: MatchPrediction, top: MarketPick) -> None:
    html = (
        '<div class="viz-grid">'
        f"{render_pick_gauge(top)}"
        f"{render_market_bars(prediction.picks)}"
        f"{render_form_board(prediction)}"
        "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def render_pick_gauge(top: MarketPick) -> str:
    probability = max(0.0, min(1.0, top.average_probability))
    degrees = probability * 360
    color = _probability_color(probability)
    return (
        '<div class="viz-card">'
        '<div class="viz-title">Pick Pulse</div>'
        '<div class="gauge-wrap">'
        f'<div class="gauge" style="background: conic-gradient({color} 0deg {degrees:.1f}deg, rgba(244,251,247,0.08) {degrees:.1f}deg 360deg);">'
        f'<div class="gauge-core">{probability:.0%}</div>'
        "</div>"
        "<div>"
        f'<div class="gauge-pick">{escape(top.selection)}</div>'
        f'<div class="gauge-note">{escape(top.market)} | {escape(top.confidence)}</div>'
        "</div>"
        "</div>"
        "</div>"
    )


def render_market_bars(picks: list[MarketPick]) -> str:
    preferred_markets = ["1X2", "Over/Under 2.5", "Goal/No Goal"]
    selected: list[MarketPick] = []
    for market in preferred_markets:
        selected.extend([pick for pick in picks if pick.market == market])
    if not selected:
        return _empty_viz_card("Mercati chiave", "Dati mercato non disponibili")

    rows = []
    for index, pick in enumerate(selected[:7]):
        probability = max(0.0, min(1.0, pick.average_probability))
        width = max(3.0, probability * 100)
        color = APP_ACCENT_COLORS[index % len(APP_ACCENT_COLORS)]
        label = _market_bar_label(pick)
        rows.append(
            '<div class="bar-row">'
            f'<div class="bar-label">{escape(label)}</div>'
            '<div class="bar-track">'
            f'<div class="bar-fill" style="width:{width:.1f}%; background:{color};"></div>'
            "</div>"
            f'<div class="bar-value">{probability:.0%}</div>'
            "</div>"
        )
    return (
        '<div class="viz-card">'
        '<div class="viz-title">Mercati chiave</div>'
        f'<div class="market-bars">{"".join(rows)}</div>'
        "</div>"
    )


def _market_bar_label(pick: MarketPick) -> str:
    if pick.market == "Over/Under 2.5":
        if pick.selection.lower().startswith("over"):
            return "Over"
        if pick.selection.lower().startswith("under"):
            return "Under"
    return pick.selection


def render_form_board(prediction: MatchPrediction) -> str:
    rows = []
    for title, table_rows in prediction.stats_tables.items():
        if not title.startswith("Ultime partite") or not table_rows:
            continue
        team_name = title.replace("Ultime partite", "").strip()
        rows.append(_form_row(team_name, table_rows[:10]))
        if len(rows) == 2:
            break
    if not rows:
        return _empty_viz_card("Forma recente", "Storico recente non disponibile")
    return (
        '<div class="viz-card">'
        '<div class="viz-title">Forma recente</div>'
        f'<div class="form-board">{"".join(rows)}</div>'
        "</div>"
    )


def _form_row(team_name: str, rows: list[dict[str, str]]) -> str:
    chips = []
    for row in rows:
        winner = str(row.get("Vincitore", "")).strip()
        if winner == "Pareggio":
            class_name, label = "draw", "N"
        elif canonical_team_name(winner) == canonical_team_name(team_name):
            class_name, label = "win", "V"
        elif winner:
            class_name, label = "loss", "P"
        else:
            class_name, label = "draw", "-"
        chips.append(f'<span class="form-chip {class_name}">{label}</span>')
    return (
        '<div class="form-team">'
        f'<div class="form-name">{escape(team_name)}</div>'
        f'<div class="form-chips">{"".join(chips)}</div>'
        "</div>"
    )


def _empty_viz_card(title: str, text: str) -> str:
    return (
        '<div class="viz-card">'
        f'<div class="viz-title">{escape(title)}</div>'
        f'<div class="form-empty">{escape(text)}</div>'
        "</div>"
    )


def _probability_color(probability: float) -> str:
    if probability >= 0.58:
        return "#19e6b0"
    if probability >= 0.45:
        return "#ffb020"
    return "#f4538a"


def render_gemini_probability_button(
    base_prediction: MatchPrediction,
    displayed_prediction: MatchPrediction,
    prediction_key: str,
) -> None:
    has_model_probability = any(pick.llm_probability is not None for pick in displayed_prediction.picks)
    button_label = "Ricalcola probabilita" if has_model_probability else "Calcola probabilita"
    col_button, col_hint = st.columns([1.1, 3])
    if col_button.button(button_label, key=f"gemini_{prediction_key}"):
        service = PredictionService(settings())
        prediction_to_enrich = deepcopy(base_prediction)
        with st.spinner(f"Calcolo probabilita per {prediction_to_enrich.match.label}..."):
            enriched_prediction = service.enrich_prediction_with_gemini(prediction_to_enrich)
        if not service.save_cached_gemini_prediction(prediction_key, enriched_prediction) and any(
            pick.llm_probability is not None for pick in enriched_prediction.picks
        ):
            enriched_prediction.warnings.append("Analisi Gemini calcolata ma non salvata.")
        st.session_state.setdefault("llm_predictions", {})[prediction_key] = enriched_prediction
        st.rerun()
    if has_model_probability:
        col_hint.caption("Analisi salvata.")
    else:
        col_hint.caption("Probabilita non calcolata.")


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


def load_saved_gemini_prediction(base_prediction: MatchPrediction, prediction_key: str) -> MatchPrediction | None:
    cached_prediction = st.session_state.get("llm_predictions", {}).get(prediction_key)
    if cached_prediction:
        return cached_prediction

    service = PredictionService(settings())
    saved_prediction = service.load_cached_gemini_prediction(prediction_key, base_prediction)
    if saved_prediction:
        st.session_state.setdefault("llm_predictions", {})[prediction_key] = saved_prediction
    return saved_prediction


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
        st.caption("Quote decimali reali 1X2. Non vengono salvate.")
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
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


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
