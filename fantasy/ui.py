from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from html import escape
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from bs4 import BeautifulSoup
from st_aggrid import AgGrid, JsCode

from fantasy.analytics import (
    PERCENTILE_METRICS,
    number as analytics_number,
    optional_number as analytics_optional_number,
    pareto_frontier,
    player_derived_stats,
    role_percentiles,
)
from config.settings import Settings
from fantasy.catalog import catalog_dataframe, make_player, merge_catalog
from fantasy.decision_center import (
    FIXTURE_SOURCE_URL,
    best_rotation_pairs,
    build_roster_alerts,
    fixture_outlook,
    matchday_date,
    player_availability,
    recommend_lineup,
    season_next_matchday,
    simulate_purchase,
)
from fantasy.official_catalog import (
    OFFICIAL_CATALOG_URL,
    catalog_fingerprint,
    fetch_official_catalog,
    merge_catalog_updates,
)
from fantasy.service import (
    DEFAULT_ROSTER_SLOTS,
    FORMATIONS,
    GAME_MODE_AUCTION,
    GAME_MODE_LIST,
    ROLE_LABELS,
    add_purchase,
    add_purchases_batch,
    auction_manager_summary,
    auction_managers,
    auction_player_assignment,
    auction_player_tier,
    auction_price_board,
    auction_taken_player_ids,
    create_league,
    create_auction_tier,
    delete_auction_tier,
    delete_league,
    find_league,
    list_trade_analysis,
    record_auction_purchase,
    remove_auction_purchase,
    remove_purchase,
    reset_preferred_xi,
    role_balance_recommendation,
    rename_auction_manager,
    roster_summary,
    set_captain,
    set_preferred_xi,
    toggle_watchlist,
    top_xi_for_formation,
    top_xi_formation,
    top_xi_summary,
    touch_workspace,
    update_auction_assignments,
    update_list_assignments,
    utc_now,
    update_league_settings,
)
from fantasy.storage import FantasyWorkspaceStorage
from nlp.gemini_client import GeminiClient


WORKSPACE_SESSION_KEY = "fantasy_workspace"
SASA_ANALYSIS_VERSION = 2
AUCTION_TIER_PALETTE = {
    "red": ("Rosso", "🔴", "#ff5d73"),
    "orange": ("Arancione", "🟠", "#ff9f43"),
    "yellow": ("Giallo", "🟡", "#ffd166"),
    "green": ("Verde", "🟢", "#19e6b0"),
    "blue": ("Blu", "🔵", "#62d8ff"),
    "purple": ("Viola", "🟣", "#b895ff"),
    "gray": ("Grigio", "⚪", "#a7b0ad"),
}


def render_fantasy_page(settings: Settings) -> None:
    render_fantasy_styles()
    st.caption("Fantacalcio · Build 2026.08.20 v24.1 · Hotfix salvataggio")
    storage = FantasyWorkspaceStorage(settings)
    workspace = _load_workspace(storage)
    workspace = _sync_official_catalog(workspace, storage)

    if not workspace.get("leagues"):
        _render_empty_workspace(workspace, storage)
        return

    league = _render_league_switcher(workspace, storage)
    if not league:
        return

    summary = roster_summary(league)
    _render_league_hero(league, summary)
    list_mode = league.get("game_mode") == GAME_MODE_LIST
    preparation_tab, squad_tab, decision_tab = st.tabs([
        "Studia il listone" if list_mode else "Preparati all'asta",
        "La mia squadra",
        "Decision Center",
    ])
    with preparation_tab:
        _render_preparation(workspace, league, storage)
    with squad_tab:
        _render_my_squad(workspace, league, storage, settings)
    with decision_tab:
        _render_decision_center(workspace, league, storage)
    _render_sync_status(storage)


@st.cache_data(ttl=900, show_spinner=False)
def _cached_fantasy_news() -> list[dict[str, Any]]:
    try:
        response = requests.get(
            "https://www.fantacalcio.it/news",
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0 fantasy-decision-center/1.0"},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception:
        return []
    news: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in soup.select("a[href]"):
        title = " ".join(link.get_text(" ", strip=True).split())
        href = str(link.get("href") or "").strip()
        if len(title) < 18 or "/news/" not in href:
            continue
        if href.startswith("/"):
            href = f"https://www.fantacalcio.it{href}"
        if not href.startswith("http") or href in seen:
            continue
        summary = ""
        card = link.find_parent(["article", "li"])
        if card:
            paragraph = card.find("p")
            if paragraph:
                candidate = " ".join(paragraph.get_text(" ", strip=True).split())
                if candidate.casefold() != title.casefold():
                    summary = candidate[:280]
        seen.add(href)
        news.append(
            {
                "title": title[:180],
                "summary": summary,
                "url": href,
                "source": "Fantacalcio.it",
                "verified": True,
            }
        )
        if len(news) >= 40:
            break
    detail_keywords = (
        "probabili formazioni", "infortun", "indispon", "squal", "convocat",
        "stop", "recuper", "panchina", "ballottaggio",
    )
    detailed = [
        item for item in news
        if any(keyword in str(item.get("title") or "").casefold() for keyword in detail_keywords)
    ][:12]

    def load_article(item: dict[str, Any]) -> tuple[str, str, str]:
        url = str(item.get("url") or "")
        try:
            detail_response = requests.get(
                url,
                timeout=6,
                headers={"User-Agent": "Mozilla/5.0 fantasy-decision-center/1.0"},
            )
            detail_response.raise_for_status()
            detail_soup = BeautifulSoup(detail_response.text, "html.parser")
        except Exception:
            return url, "", ""
        article = detail_soup.select_one("article") or detail_soup.select_one("main")
        paragraphs = (article or detail_soup).select("p, li")
        body = " ".join(
            " ".join(paragraph.get_text(" ", strip=True).split())
            for paragraph in paragraphs
        )
        published = ""
        published_meta = detail_soup.select_one(
            'meta[property="article:published_time"], meta[name="date"]'
        )
        if published_meta:
            published = str(published_meta.get("content") or "")
        return url, body[:18000], published

    if detailed:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(load_article, item) for item in detailed]
            details = {url: (body, published) for url, body, published in (
                future.result() for future in as_completed(futures)
            )}
        for item in news:
            body, published = details.get(str(item.get("url") or ""), ("", ""))
            if body:
                item["body"] = body
            if published:
                item["published_at"] = published
    return news


def _load_workspace(storage: FantasyWorkspaceStorage) -> dict[str, Any]:
    if WORKSPACE_SESSION_KEY not in st.session_state:
        st.session_state[WORKSPACE_SESSION_KEY] = storage.load()
        st.session_state["fantasy_remote_synced"] = getattr(storage, "last_remote_save_ok", False)
    return st.session_state[WORKSPACE_SESSION_KEY]


def _cached_official_catalog() -> dict[str, Any]:
    key = "fantasy_official_catalog_session"
    if key not in st.session_state:
        st.session_state[key] = fetch_official_catalog()
    return st.session_state[key]


def _sync_official_catalog(
    workspace: dict[str, Any], storage: FantasyWorkspaceStorage
) -> dict[str, Any]:
    with st.spinner("Controllo il listone ufficiale piu recente..."):
        result = _cached_official_catalog()
    previous = workspace.get("catalog", [])
    merged = merge_catalog_updates(
        previous,
        result.get("players", []),
        authoritative=bool(result.get("remote_ok")),
    )
    purchases_repaired = _refresh_purchased_player_data(workspace, merged)
    meta = {
        "checked_at": result.get("checked_at"),
        "source": result.get("source", "Fantacalcio.it"),
        "source_url": result.get("source_url", OFFICIAL_CATALOG_URL),
        "remote_ok": bool(result.get("remote_ok")),
        "message": result.get("message", ""),
        "player_count": len(merged),
    }
    if (
        catalog_fingerprint(previous) != catalog_fingerprint(merged)
        or workspace.get("catalog_meta") != meta
        or purchases_repaired
    ):
        workspace["catalog"] = merged
        workspace["catalog_meta"] = meta
        touch_workspace(workspace)
        _save_workspace(workspace, storage)
    return workspace


def _refresh_purchased_player_data(
    workspace: dict[str, Any], catalog: list[dict[str, Any]]
) -> bool:
    by_id = {str(player.get("id")): player for player in catalog}
    changed = False
    fields = (
        "name",
        "team",
        "role",
        "quote",
        "fvm",
        "expected_goals",
        "expected_assists",
        "expected_fantasy_average",
        "starter_probability",
        "fantasy_score",
        "reliability",
        "risk",
        "tier",
        "profile",
    )
    for league in workspace.get("leagues", []):
        league_changed = False
        for purchase in league.get("purchases", []):
            player = by_id.get(str(purchase.get("player_id")))
            if not player:
                continue
            for field in fields:
                value = player.get(field)
                if value is not None and purchase.get(field) != value:
                    purchase[field] = value
                    changed = league_changed = True
        if league_changed:
            league["analysis"] = ""
            league["sasa_analysis"] = ""
            league["sasa_analysis_version"] = 0
            league["updated_at"] = utc_now()
    return changed


def _render_empty_workspace(workspace: dict[str, Any], storage: FantasyWorkspaceStorage) -> None:
    st.markdown(
        """
        <section class="fantasy-empty">
            <div class="fantasy-empty-icon">F</div>
            <p class="fantasy-eyebrow">FANTASY COMMAND CENTER</p>
            <h2>Crea il tuo primo fantacalcio</h2>
            <p>Ogni fanta avra budget, rosa, obiettivi e impostazioni indipendenti. Potrai crearne quanti vuoi e passare da uno all'altro.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    _render_create_form(workspace, storage, "empty")
    _render_sync_status(storage)


def _render_league_switcher(
    workspace: dict[str, Any], storage: FantasyWorkspaceStorage
) -> dict[str, Any] | None:
    leagues = workspace.get("leagues", [])
    league_ids = [league["id"] for league in leagues]
    current_id = workspace.get("active_league_id")
    current_index = league_ids.index(current_id) if current_id in league_ids else 0

    selected_id = st.selectbox(
        "Il mio fantacalcio",
        league_ids,
        index=current_index,
        format_func=lambda value: next(
            (league["name"] for league in leagues if league["id"] == value), value
        ),
        key="fantasy_league_selector",
    )
    if selected_id != workspace.get("active_league_id"):
        workspace["active_league_id"] = selected_id
        _save_workspace(workspace, storage)

    league = find_league(workspace, selected_id)
    if not league:
        return None

    create_column, settings_column, delete_column = st.columns(3)
    with create_column.popover("+ Nuovo", use_container_width=True):
        st.markdown("#### Nuovo fantacalcio")
        _render_create_form(workspace, storage, "popover")
    with settings_column.popover("Impostazioni", use_container_width=True):
        _render_manage_form(workspace, league, storage)
    with delete_column.popover("Elimina", use_container_width=True):
        _render_delete_league(workspace, league, storage)
    return league


def _render_delete_league(
    workspace: dict[str, Any], league: dict[str, Any], storage: FantasyWorkspaceStorage
) -> None:
    league_name = str(league.get("name") or "")
    st.markdown("#### Elimina fantacalcio")
    st.warning(
        "Verranno eliminati rosa, Top 11, preferenze e analisi di questo fantacalcio. "
        "Gli altri fanta non verranno modificati."
    )
    typed_name = st.text_input(
        f"Scrivi {league_name} per confermare",
        key=f"delete_name_{league['id']}",
    )
    if st.button(
        "Elimina definitivamente",
        disabled=typed_name.strip() != league_name,
        use_container_width=True,
        key=f"delete_league_{league['id']}",
    ):
        delete_league(workspace, league["id"])
        _save_workspace(workspace, storage)
        st.session_state.pop("fantasy_league_selector", None)
        st.rerun()


def _render_create_form(
    workspace: dict[str, Any], storage: FantasyWorkspaceStorage, key_suffix: str
) -> None:
    game_mode = st.radio(
        "Tipo di fantacalcio",
        [GAME_MODE_AUCTION, GAME_MODE_LIST],
        format_func=lambda value: "Asta" if value == GAME_MODE_AUCTION else "Listone",
        horizontal=True,
        key=f"create_mode_{key_suffix}",
    )
    st.caption(
        "Nell'asta registri i partecipanti e il prezzo battuto. "
        "Nel listone il costo e sempre la quotazione ufficiale."
    )
    with st.form(f"create_fantasy_league_{key_suffix}"):
        name = st.text_input("Nome", placeholder="Es. Fanta amici")
        budget = st.number_input(
            "Crediti iniziali per ogni partecipante"
            if game_mode == GAME_MODE_AUCTION else "Budget rosa",
            min_value=50,
            max_value=2000,
            value=500 if game_mode == GAME_MODE_AUCTION else 250,
            step=10,
        )
        participants = None
        if game_mode == GAME_MODE_AUCTION:
            participants = st.number_input(
                "Numero totale partecipanti (te compreso)",
                min_value=2,
                max_value=30,
                value=10,
            )
        season = st.text_input("Stagione", value="2026/27")
        st.markdown("**Composizione rosa**")
        slot_columns = st.columns(4)
        slots = {
            role: int(slot_columns[index].number_input(
                role,
                min_value=0,
                max_value=30,
                value=DEFAULT_ROSTER_SLOTS[role],
                key=f"create_slot_{key_suffix}_{role}",
                help=ROLE_LABELS[role],
            ))
            for index, role in enumerate(ROLE_LABELS)
        }
        modifier, captain = st.columns(2)
        modifier_enabled = modifier.toggle("Modificatore difesa", value=True)
        captain_enabled = captain.toggle("Capitano", value=False)
        submitted = st.form_submit_button("Crea fantacalcio", type="primary", use_container_width=True)
    if not submitted:
        return
    try:
        create_league(
            workspace,
            name,
            initial_budget=int(budget),
            participants=int(participants) if participants is not None else None,
            season=season,
            roster_slots=slots,
            modifier_enabled=modifier_enabled,
            captain_enabled=captain_enabled,
            game_mode=game_mode,
        )
    except ValueError as error:
        st.error(str(error))
        return
    _save_workspace(workspace, storage)
    st.rerun()


def _render_manage_form(
    workspace: dict[str, Any], league: dict[str, Any], storage: FantasyWorkspaceStorage
) -> None:
    st.markdown("#### Impostazioni")
    game_mode = st.radio(
        "Tipo di fantacalcio",
        [GAME_MODE_AUCTION, GAME_MODE_LIST],
        index=0 if league.get("game_mode") == GAME_MODE_AUCTION else 1,
        format_func=lambda value: "Asta" if value == GAME_MODE_AUCTION else "Listone",
        horizontal=True,
        key=f"manage_mode_{league['id']}",
    )
    with st.form(f"manage_league_{league['id']}"):
        name = st.text_input("Nome", value=league["name"])
        budget = st.number_input(
            "Crediti iniziali per ogni partecipante"
            if game_mode == GAME_MODE_AUCTION else "Budget rosa",
            min_value=1,
            max_value=5000,
            value=int(league.get("initial_budget", 250)),
        )
        participants = None
        if game_mode == GAME_MODE_AUCTION:
            participants = st.number_input(
                "Numero totale partecipanti (te compreso)",
                min_value=2,
                max_value=30,
                value=int(league.get("participants") or 10),
            )
        st.markdown("**Composizione rosa**")
        current_slots = league.get("roster_slots", DEFAULT_ROSTER_SLOTS)
        slot_columns = st.columns(4)
        slots = {
            role: int(slot_columns[index].number_input(
                role,
                min_value=0,
                max_value=30,
                value=int(current_slots.get(role, DEFAULT_ROSTER_SLOTS[role])),
                key=f"manage_slot_{league['id']}_{role}",
                help=ROLE_LABELS[role],
            ))
            for index, role in enumerate(ROLE_LABELS)
        }
        modifier_column, captain_column = st.columns(2)
        modifier = modifier_column.toggle(
            "Modificatore difesa", value=bool(league.get("modifier_enabled"))
        )
        captain = captain_column.toggle("Capitano", value=bool(league.get("captain_enabled")))
        save_settings = st.form_submit_button("Salva", type="primary", use_container_width=True)
    if save_settings:
        try:
            update_league_settings(
                league,
                name=name,
                initial_budget=int(budget),
                participants=int(participants) if participants is not None else None,
                game_mode=game_mode,
                modifier_enabled=modifier,
                captain_enabled=captain,
                roster_slots=slots,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            touch_workspace(workspace)
            _save_workspace(workspace, storage)
            st.rerun()

def _render_league_hero(league: dict[str, Any], summary: dict[str, Any]) -> None:
    completion = int(100 * summary["roster_size"] / max(summary["target_size"], 1))
    list_mode = league.get("game_mode") == GAME_MODE_LIST
    context = "LISTONE" if list_mode else f"{league.get('participants', 0)} PARTECIPANTI"
    chips = ["LISTONE" if list_mode else "ASTA"]
    if league.get("captain_enabled"):
        chips.append("CAP")
    chips_html = "".join(f'<span class="fantasy-mode-chip">{label}</span>' for label in chips)
    st.markdown(
        f"""
        <section class="fantasy-league-hero">
            <div>
                <p class="fantasy-eyebrow">{escape(str(league.get('season', '')))} · {context}</p>
                <h2>{escape(str(league.get('name', 'Fantacalcio')))}</h2>
                <p>Rosa {summary['roster_size']}/{summary['target_size']} · {summary['remaining_budget']:.0f} crediti disponibili</p>
            </div>
            <div class="fantasy-ring" style="--progress:{completion * 3.6}deg">
                <span>{completion}%</span>
            </div>
            <div class="fantasy-mode-stack">{chips_html}</div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_preparation(
    workspace: dict[str, Any], league: dict[str, Any], storage: FantasyWorkspaceStorage
) -> None:
    catalog = workspace.get("catalog", [])
    watchlist = set(league.get("watchlist", []))
    summary = roster_summary(league)
    list_mode = league.get("game_mode") == GAME_MODE_LIST
    if not list_mode:
        _render_auction_room(workspace, league, storage, catalog)
    purchased_ids = (
        {str(row.get("player_id")) for row in league.get("purchases", [])}
        if list_mode else auction_taken_player_ids(league)
    )
    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("Giocatori nel listone", len(catalog))
    metric_b.metric("Osservati", len(watchlist))
    metric_c.metric(
        "Gia acquistati" if list_mode else "Aggiudicati nell'asta",
        len(league.get("purchases", [])) if list_mode else len(purchased_ids),
    )

    meta = workspace.get("catalog_meta", {})
    source_status = "AGGIORNATO" if meta.get("remote_ok") else "BASE VERIFICATA"
    checked_at = str(meta.get("checked_at") or "").replace("T", " ")[:16]
    st.markdown(
        f"""
        <section class="fantasy-source-card">
            <div><span>{source_status}</span><strong>Listone automatico Fantacalcio.it</strong>
            <small>{escape(str(meta.get('message') or 'Controllo automatico attivo'))}</small></div>
            <div><b>{len(catalog)}</b><small>giocatori · controllo {escape(checked_at or 'in corso')}</small></div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    source_column, refresh_column = st.columns([2.4, 0.8])
    source_column.caption(
        "Fonte: [quotazioni ufficiali Fantacalcio.it]"
        f"({meta.get('source_url') or OFFICIAL_CATALOG_URL}). Nessun CSV da caricare."
    )
    if refresh_column.button("Aggiorna ora", use_container_width=True, key="refresh_official_catalog"):
        st.session_state.pop("fantasy_official_catalog_session", None)
        st.rerun()

    _render_top_players_visual_lab(catalog, league)

    if not catalog:
        st.info("Il listone e in aggiornamento. Riprova tra poco.")
        return

    st.markdown("### La tua rosa in costruzione")
    _render_budget_metrics(summary)
    progress = summary["roster_size"] / max(summary["target_size"], 1)
    st.progress(min(progress, 1.0), text=f"Rosa completata al {progress:.0%}")
    _render_role_plan(league, summary)
    advisor_catalog = (
        catalog if list_mode else [
            player for player in catalog if str(player.get("id")) not in purchased_ids
        ]
    )
    _render_role_advisors(workspace, league, storage, advisor_catalog)
    if list_mode:
        _render_auction_tier_manager(workspace, league, storage)

    search_column, role_column, team_column, sort_column = st.columns([1.5, 0.8, 1.1, 1.1])
    search = search_column.text_input("Cerca", placeholder="Nome giocatore")
    selected_roles = role_column.multiselect("Ruolo", list(ROLE_LABELS), default=list(ROLE_LABELS))
    teams = sorted({str(player.get("team", "")) for player in catalog if player.get("team")})
    selected_teams = team_column.multiselect("Squadra", teams)
    sort_options = ["Indice", "Quotazione", "FVM / 1000", "Quotazione prevista", "Gol attesi", "Assist attesi", "Titolarita %"]
    if not list_mode:
        sort_options = ["Spesa strategica", "Spesa aggiornata", "Spesa iniziale", *sort_options]
    sort_label = sort_column.selectbox(
        "Ordina per",
        sort_options,
    )

    frame = catalog_dataframe(catalog)
    if not list_mode:
        price_board = auction_price_board(league, catalog)
        frame["Spesa iniziale"] = frame["_id"].map(
            lambda player_id: price_board.get(str(player_id), {}).get("initial")
        )
        frame["Spesa aggiornata"] = frame["_id"].map(
            lambda player_id: price_board.get(str(player_id), {}).get("updated")
        )
        frame["Spesa strategica"] = frame["_id"].map(
            lambda player_id: price_board.get(str(player_id), {}).get("strategic")
        )
        frame["Comparabili"] = frame["_id"].map(
            lambda player_id: price_board.get(str(player_id), {}).get("comparables", 0)
        )
    if search:
        frame = frame[frame["Giocatore"].str.contains(search, case=False, na=False)]
    if selected_roles:
        frame = frame[frame["Ruolo"].isin(selected_roles)]
    if selected_teams:
        frame = frame[frame["Squadra"].isin(selected_teams)]
    if sort_label in frame.columns:
        frame = frame.sort_values(sort_label, ascending=False, na_position="last")

    st.markdown(
        '<div class="fantasy-table-heading"><div><strong>Player board</strong>'
        + (
            '<span>Assegna ogni giocatore, correggi il prezzo o scegli Non assegnato per rimuoverlo</span></div>'
            if not list_mode else
            '<span>Gestisci direttamente rosa e fascia personale; Apri mostra la scheda completa</span></div>'
        )
        + f'<b>{len(frame)}</b></div>',
        unsafe_allow_html=True,
    )
    version_key = f"catalog_board_version_{league['id']}"
    board_version = int(st.session_state.get(version_key, 0))
    if list_mode:
        selected_ids = _render_list_catalog_editor(
            frame,
            catalog,
            league,
            workspace,
            storage,
            key=f"catalog_board_{league['id']}_{board_version}",
            version_key=version_key,
            watchlist=watchlist,
        )
    else:
        selected_ids = _render_auction_catalog_editor(
            frame,
            catalog,
            league,
            workspace,
            storage,
            key=f"catalog_board_{league['id']}_{board_version}",
            version_key=version_key,
            watchlist=watchlist,
        )
    if selected_ids:
        st.session_state[f"fantasy_selected_player_{league['id']}"] = selected_ids[0]
    selected_id = st.session_state.get(f"fantasy_selected_player_{league['id']}")
    selected_player = next((player for player in catalog if player.get("id") == selected_id), None)
    if selected_player:
        _render_player_detail(selected_player, league, workspace, storage)
    else:
        st.info("Seleziona un giocatore dalla tabella per vedere tutte le statistiche e le proiezioni.")

    _render_what_if_simulator(league, catalog)

    watched_players = [player for player in catalog if player.get("id") in watchlist]
    if watched_players:
        with st.expander(f"Watchlist · {len(watched_players)} giocatori"):
            watch_frame = catalog_dataframe(watched_players)
            _render_catalog_table(
                watch_frame,
                key=f"watchlist_board_{league['id']}",
                height=260,
                purchased_ids=purchased_ids,
                watchlist=watchlist,
            )
    if league.get("game_mode") == GAME_MODE_AUCTION:
        _render_quick_purchase(workspace, league, storage)


def _render_auction_room(
    workspace: dict[str, Any],
    league: dict[str, Any],
    storage: FantasyWorkspaceStorage,
    catalog: list[dict[str, Any]],
) -> None:
    managers = auction_managers(league)
    summaries = {
        str(manager.get("id")): auction_manager_summary(league, str(manager.get("id")))
        for manager in managers
    }
    total_purchases = sum(summary["roster_size"] for summary in summaries.values())
    highest_opponent = max(
        (
            summary["remaining_budget"]
            for manager_id, summary in summaries.items()
            if not summary["manager"].get("is_user")
        ),
        default=0,
    )
    cards = []
    for manager in managers:
        manager_id = str(manager.get("id"))
        summary = summaries[manager_id]
        owner_class = " owner" if manager.get("is_user") else ""
        cards.append(
            f'<div class="fantasy-manager-card{owner_class}"><span>'
            f'{"TU" if manager.get("is_user") else "RIVALE"}</span>'
            f'<strong>{escape(str(manager.get("name") or ""))}</strong>'
            f'<small>{summary["roster_size"]}/{summary["target_size"]} giocatori</small>'
            f'<b>{summary["remaining_budget"]:.0f} CR</b></div>'
        )
    st.markdown(
        f'<section class="fantasy-auction-hero"><div><span>LIVE AUCTION ROOM</span>'
        f'<strong>Mercato adattivo</strong><small>{len(managers)} partecipanti · '
        f'{total_purchases} aggiudicazioni registrate</small></div>'
        f'<aside><small>PIU CREDITO TRA I RIVALI</small><b>{highest_opponent:.0f}</b></aside></section>'
        f'<div class="fantasy-manager-grid">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "La spesa aggiornata usa tutte le aggiudicazioni dello stesso reparto, senza distinguere le fasce. "
        "Il massimo strategico considera anche i crediti residui degli avversari e il budget da "
        "conservare per completare la tua rosa."
    )
    _render_auction_tier_manager(workspace, league, storage)
    with st.expander("Gestisci partecipanti e rose dell'asta"):
        st.markdown("##### Nomi delle squadre")
        with st.form(f"auction_manager_names_{league['id']}"):
            name_columns = st.columns(2)
            manager_names = {
                str(manager.get("id")): name_columns[index % 2].text_input(
                    "La mia squadra" if manager.get("is_user") else f"Partecipante {index + 1}",
                    value=str(manager.get("name") or ""),
                    key=f"auction_manager_name_{league['id']}_{manager.get('id')}",
                )
                for index, manager in enumerate(managers)
            }
            save_names = st.form_submit_button(
                "Salva nomi", type="primary", use_container_width=True
            )
        if save_names:
            clean_names = [name.strip() for name in manager_names.values()]
            if any(not name for name in clean_names):
                st.error("Inserisci un nome per ogni partecipante.")
            elif len({name.casefold() for name in clean_names}) != len(clean_names):
                st.error("I nomi dei partecipanti devono essere diversi.")
            else:
                for manager_id, name in manager_names.items():
                    rename_auction_manager(league, manager_id, name)
                touch_workspace(workspace)
                _save_workspace(workspace, storage)
                st.rerun()

        st.markdown("##### Rose registrate")
        selected_manager_id = st.selectbox(
            "Visualizza squadra",
            [str(manager.get("id")) for manager in managers],
            format_func=lambda value: next(
                str(manager.get("name")) for manager in managers if manager.get("id") == value
            ),
            key=f"auction_roster_manager_{league['id']}",
        )
        selected_summary = summaries[selected_manager_id]
        purchases = selected_summary["purchases"]
        budget_a, budget_b, budget_c = st.columns(3)
        budget_a.metric("Spesi", f"{selected_summary['spent']:.0f}")
        budget_b.metric("Crediti residui", f"{selected_summary['remaining_budget']:.0f}")
        budget_c.metric("Giocatori", f"{selected_summary['roster_size']}/{selected_summary['target_size']}")
        if purchases:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Ruolo": row.get("role"),
                            "Giocatore": row.get("name"),
                            "Squadra": row.get("team"),
                            "Prezzo": row.get("price"),
                            "Fascia": row.get("tier"),
                        }
                        for row in purchases
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
            correction_column, remove_column = st.columns([2.2, 0.8])
            correction_id = correction_column.selectbox(
                "Correggi un'aggiudicazione",
                [str(row.get("player_id")) for row in purchases],
                format_func=lambda value: next(
                    str(row.get("name")) for row in purchases
                    if str(row.get("player_id")) == value
                ),
                key=f"auction_remove_select_{league['id']}_{selected_manager_id}",
            )
            if remove_column.button(
                "Rimuovi",
                use_container_width=True,
                key=f"auction_remove_{league['id']}_{selected_manager_id}",
            ):
                remove_auction_purchase(league, selected_manager_id, correction_id)
                touch_workspace(workspace)
                _save_workspace(workspace, storage)
                st.rerun()
        else:
            st.info("Nessuna aggiudicazione registrata per questa squadra.")


def _render_auction_tier_manager(
    workspace: dict[str, Any], league: dict[str, Any], storage: FantasyWorkspaceStorage
) -> None:
    tiers = league.get("auction_tiers", [])
    with st.expander(f"Fasce personalizzate · {len(tiers)}"):
        st.caption(
            "Queste fasce e i relativi colori appartengono solo a questo fantacalcio. "
            "Dopo averle create potrai assegnarle direttamente dal Player Board."
        )
        if tiers:
            cards = []
            assignments = league.get("auction_player_tiers", {})
            for tier in tiers:
                color = str(tier.get("color") or "gray")
                marker = AUCTION_TIER_PALETTE.get(color, AUCTION_TIER_PALETTE["gray"])[1]
                hex_color = AUCTION_TIER_PALETTE.get(color, AUCTION_TIER_PALETTE["gray"])[2]
                count = sum(
                    1 for tier_id in assignments.values()
                    if str(tier_id) == str(tier.get("id"))
                )
                cards.append(
                    f'<div class="fantasy-custom-tier" style="--tier-color:{hex_color}">'
                    f'<span>{marker}</span><strong>{escape(str(tier.get("name") or ""))}</strong>'
                    f'<small>{count} giocatori</small></div>'
                )
            st.markdown(
                f'<div class="fantasy-custom-tier-grid">{"".join(cards)}</div>',
                unsafe_allow_html=True,
            )
        with st.form(f"create_auction_tier_{league['id']}"):
            name_column, color_column = st.columns([1.4, 0.8])
            tier_name = name_column.text_input("Nome fascia", placeholder="Es. Top assoluti")
            tier_color = color_column.selectbox(
                "Colore",
                list(AUCTION_TIER_PALETTE),
                format_func=lambda value: (
                    f"{AUCTION_TIER_PALETTE[value][1]} {AUCTION_TIER_PALETTE[value][0]}"
                ),
            )
            create_tier = st.form_submit_button(
                "Crea fascia", type="primary", use_container_width=True
            )
        if create_tier:
            try:
                create_auction_tier(league, tier_name, tier_color)
            except ValueError as error:
                st.error(str(error))
            else:
                touch_workspace(workspace)
                _save_workspace(workspace, storage)
                st.rerun()
        if tiers:
            tier_column, delete_column = st.columns([2.2, 0.8])
            delete_tier_id = tier_column.selectbox(
                "Elimina una fascia",
                [str(tier.get("id")) for tier in tiers],
                format_func=lambda value: next(
                    _tier_option_label(tier) for tier in tiers
                    if str(tier.get("id")) == value
                ),
                key=f"delete_auction_tier_select_{league['id']}",
            )
            if delete_column.button(
                "Elimina",
                use_container_width=True,
                key=f"delete_auction_tier_{league['id']}",
            ):
                delete_auction_tier(league, delete_tier_id)
                touch_workspace(workspace)
                _save_workspace(workspace, storage)
                st.rerun()


def _tier_option_label(tier: dict[str, Any]) -> str:
    color = str(tier.get("color") or "gray")
    marker = AUCTION_TIER_PALETTE.get(color, AUCTION_TIER_PALETTE["gray"])[1]
    return f"{marker} {str(tier.get('name') or 'Fascia')}"


def _auction_metric_style(color: str) -> JsCode:
    return JsCode(
        f"""function(params) {{
            const raw = Number(params.value);
            if (!Number.isFinite(raw)) return {{}};
            const value = Math.max(0, Math.min(100, raw));
            return {{
                backgroundImage: 'linear-gradient(90deg, {color} 0%, {color} ' + value + '%, rgba(255,255,255,.08) ' + value + '%, rgba(255,255,255,.08) 100%)',
                backgroundSize: 'calc(100% - 8px) 4px',
                backgroundPosition: 'center calc(100% - 4px)',
                backgroundRepeat: 'no-repeat',
                fontWeight: '800',
                textAlign: 'right',
                color: '#f4fbf7'
            }};
        }}"""
    )


def _auction_metric_formatter(suffix: str = "") -> JsCode:
    safe_suffix = json.dumps(suffix)
    return JsCode(
        f"""function(params) {{
            const value = Number(params.value);
            return Number.isFinite(value) ? Math.round(value) + {safe_suffix} : '—';
        }}"""
    )


def _render_list_catalog_editor(
    frame: pd.DataFrame,
    catalog: list[dict[str, Any]],
    league: dict[str, Any],
    workspace: dict[str, Any],
    storage: FantasyWorkspaceStorage,
    *,
    key: str,
    version_key: str,
    watchlist: set[str],
) -> list[str]:
    if frame.empty:
        st.warning("Nessun giocatore corrisponde ai filtri selezionati.")
        return []
    indexed = frame.reset_index(drop=True)
    purchased_ids = {
        str(row.get("player_id")) for row in league.get("purchases", [])
    }
    custom_tiers = league.get("auction_tiers", [])
    no_tier = "— Nessuna fascia —"
    tier_label_by_id = {
        str(tier.get("id")): _tier_option_label(tier) for tier in custom_tiers
    }
    tier_id_by_label = {
        label: tier_id for tier_id, label in tier_label_by_id.items()
    }
    player_tiers = {
        str(player_id): auction_player_tier(league, str(player_id))
        for player_id in indexed["_id"]
    }
    catalog_by_id = {str(player.get("id")): player for player in catalog}

    def player_metric(player_id: Any, field: str) -> float:
        value = _number_or_none(
            catalog_by_id.get(str(player_id), {}).get(field), 0.0
        ) or 0.0
        if 0 < value <= 1:
            value *= 100
        return round(max(0.0, min(100.0, value)), 1)

    display = pd.DataFrame(
        {
            "_player_id": indexed["_id"].astype(str),
            "Scheda": False,
            "In rosa": [
                str(player_id) in purchased_ids for player_id in indexed["_id"]
            ],
            "★": [
                "★" if str(player_id) in watchlist else ""
                for player_id in indexed["_id"]
            ],
            "Fascia personale": [
                tier_label_by_id.get(
                    str(player_tiers[str(player_id)].get("id")), no_tier
                )
                if player_tiers[str(player_id)] else no_tier
                for player_id in indexed["_id"]
            ],
            "Ruolo": indexed["Ruolo"].map(
                {"P": "🟨 P", "D": "🟩 D", "C": "🟦 C", "A": "🟥 A"}
            ).fillna(indexed["Ruolo"]),
            "Giocatore": indexed["Giocatore"],
            "Squadra": indexed["Squadra"],
            "Q": indexed["Quotazione"],
            "FM attesa": indexed["FM attesa"],
            "Gol attesi": indexed["Gol attesi"],
            "Assist attesi": indexed["Assist attesi"],
            "Bonus": [
                player_metric(player_id, "bonus") for player_id in indexed["_id"]
            ],
            "Titolarita": indexed["Titolarita %"],
            "Affidabilita": [
                player_metric(player_id, "reliability")
                for player_id in indexed["_id"]
            ],
            "Rischio infortuni": [
                player_metric(player_id, "risk") for player_id in indexed["_id"]
            ],
            "Potenziale": [
                player_metric(player_id, "potential")
                for player_id in indexed["_id"]
            ],
            "Indice": indexed["Indice"],
            "Fascia": indexed["Fascia"],
        }
    )
    first_id = str(indexed.iloc[0]["_id"])
    last_id = str(indexed.iloc[-1]["_id"])
    editor_version = int(st.session_state.get(version_key, 0))
    editor_key = f"{key}_{len(indexed)}_{first_id}_{last_id}_{editor_version}"
    tier_labels_by_color: dict[str, list[str]] = {}
    for tier in custom_tiers:
        color = str(tier.get("color") or "gray")
        tier_labels_by_color.setdefault(color, []).append(_tier_option_label(tier))
    row_class_rules: dict[str, Any] = {}
    tier_row_css: dict[str, dict[str, str]] = {}
    for color, labels in tier_labels_by_color.items():
        safe_color = color if color in AUCTION_TIER_PALETTE else "gray"
        hex_color = AUCTION_TIER_PALETTE[safe_color][2]
        class_name = f"fantasy-tier-{safe_color}"
        row_class_rules[class_name] = JsCode(
            f"""function(params) {{
                return params.data && {json.dumps(labels, ensure_ascii=False)}.includes(
                    params.data['Fascia personale']
                );
            }}"""
        )
        tier_row_css[f".{class_name}"] = {
            "background": (
                "linear-gradient(90deg, "
                f"color-mix(in srgb, {hex_color} 28%, #080b0a), "
                "#080b0a 82%) !important"
            ),
            "border-left": f"5px solid {hex_color} !important",
            "box-shadow": (
                f"inset 0 0 18px color-mix(in srgb, {hex_color} 10%, transparent)"
            ),
        }
    metric_columns = [
        ("Bonus", "Propensione bonus", 132, "#ffb020", ""),
        ("Titolarita", "Titolarità", 105, "#19e6b0", "%"),
        ("Affidabilita", "Affidabilità", 112, "#62d8ff", ""),
        ("Rischio infortuni", "Rischio infortuni", 125, "#f4538a", ""),
        ("Potenziale", "Potenziale", 105, "#b895ff", ""),
        ("Indice", "Indice", 90, "#19e6b0", ""),
    ]
    column_defs: list[dict[str, Any]] = [
        {"field": "_player_id", "hide": True},
        {
            "field": "Scheda",
            "headerName": "Apri",
            "editable": True,
            "cellRenderer": "agCheckboxCellRenderer",
            "cellEditor": "agCheckboxCellEditor",
            "width": 72,
            "pinned": "left",
        },
        {
            "field": "In rosa",
            "editable": True,
            "cellRenderer": "agCheckboxCellRenderer",
            "cellEditor": "agCheckboxCellEditor",
            "width": 88,
            "pinned": "left",
        },
        {"field": "★", "width": 55},
        {
            "field": "Fascia personale",
            "editable": True,
            "cellEditor": "agSelectCellEditor",
            "cellEditorParams": {"values": [no_tier, *tier_id_by_label]},
            "minWidth": 180,
        },
        {"field": "Ruolo", "width": 78},
        {
            "field": "Giocatore",
            "width": 180,
            "minWidth": 150,
            "pinned": "left",
            "lockPinned": True,
            "suppressMovable": True,
        },
        {"field": "Squadra", "width": 86},
        {"field": "Q", "width": 65, "type": "numericColumn"},
        {"field": "FM attesa", "width": 94, "type": "numericColumn"},
        {"field": "Gol attesi", "width": 92, "type": "numericColumn"},
        {"field": "Assist attesi", "width": 100, "type": "numericColumn"},
    ]
    column_defs.extend(
        {
            "field": field,
            "headerName": header,
            "width": width,
            "cellStyle": _auction_metric_style(color),
            "valueFormatter": _auction_metric_formatter(suffix),
        }
        for field, header, width, color, suffix in metric_columns
    )
    column_defs.append({"field": "Fascia", "width": 90})
    grid_response = AgGrid(
        display,
        gridOptions={
            "defaultColDef": {
                "sortable": True,
                "resizable": True,
                "filter": False,
                "editable": False,
                "suppressHeaderMenuButton": True,
            },
            "columnDefs": column_defs,
            "getRowId": JsCode(
                "function(params) { return params.data._player_id; }"
            ),
            "rowClassRules": row_class_rules,
            "singleClickEdit": True,
            "stopEditingWhenCellsLoseFocus": True,
            "suppressRowClickSelection": True,
            "rowHeight": 38,
            "headerHeight": 42,
            "animateRows": False,
        },
        height=min(620, 88 + max(len(display), 1) * 38),
        key=editor_key,
        data_return_mode="AS_INPUT",
        update_on=[("cellValueChanged", 250)],
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        theme="streamlit",
        show_toolbar=False,
        show_search=False,
        show_download_button=False,
        server_sync_strategy="client_wins",
        custom_css={
            ".ag-root-wrapper": {
                "border": "1px solid rgba(25,230,176,.22) !important",
                "border-radius": "10px !important",
                "overflow": "hidden !important",
            },
            ".ag-header": {
                "background": "#1a1f22 !important",
                "border-bottom": "1px solid rgba(244,251,247,.13) !important",
            },
            ".ag-pinned-left-header": {
                "border-right": "2px solid rgba(25,230,176,.32) !important",
            },
            ".ag-pinned-left-cols-container": {
                "border-right": "2px solid rgba(25,230,176,.32) !important",
                "box-shadow": "8px 0 18px rgba(0,0,0,.24) !important",
                "z-index": "2 !important",
            },
            ".ag-row": {
                "background": "#080b0a",
                "color": "#edf7f2",
                "border-bottom": "1px solid rgba(244,251,247,.08)",
            },
            ".ag-row-hover": {"background": "#10201b !important"},
            **tier_row_css,
        },
    )
    edited = grid_response.data
    if not isinstance(edited, pd.DataFrame):
        edited = pd.DataFrame(edited)
    changes: list[dict[str, Any]] = []
    for _, edited_row in edited.iterrows():
        player_id = str(edited_row.get("_player_id") or "")
        player = catalog_by_id.get(player_id)
        if not player:
            continue
        current_owned = player_id in purchased_ids
        edited_owned = bool(edited_row.get("In rosa"))
        current_tier = player_tiers.get(player_id)
        current_tier_label = (
            tier_label_by_id.get(str(current_tier.get("id")), no_tier)
            if current_tier else no_tier
        )
        edited_tier_label = str(edited_row.get("Fascia personale") or no_tier)
        if edited_owned == current_owned and edited_tier_label == current_tier_label:
            continue
        change: dict[str, Any] = {
            "player": player,
            "in_roster": edited_owned,
        }
        if edited_tier_label != current_tier_label:
            change["tier_id"] = (
                None if edited_tier_label == no_tier
                else tier_id_by_label[edited_tier_label]
            )
        changes.append(change)
    selected_ids = [
        str(row.get("_player_id"))
        for _, row in edited.iterrows()
        if bool(row.get("Scheda"))
    ]
    action_column, hint_column = st.columns([1.1, 2.2])
    if action_column.button(
        f"Salva modifiche ({len(changes)})",
        type="primary",
        use_container_width=True,
        disabled=not changes,
        key=f"save_list_grid_{editor_key}",
    ):
        try:
            update_list_assignments(league, changes)
        except ValueError as error:
            st.error(str(error))
        else:
            touch_workspace(workspace)
            _save_workspace(workspace, storage)
            st.session_state[version_key] = int(
                st.session_state.get(version_key, 0)
            ) + 1
            st.rerun()
    hint_column.caption(
        "Spunta In rosa per aggiungere o rimuovere più giocatori; scegli la fascia e salva una sola volta."
    )
    return selected_ids


def _render_auction_catalog_editor(
    frame: pd.DataFrame,
    catalog: list[dict[str, Any]],
    league: dict[str, Any],
    workspace: dict[str, Any],
    storage: FantasyWorkspaceStorage,
    *,
    key: str,
    version_key: str,
    watchlist: set[str],
) -> list[str]:
    if frame.empty:
        st.warning("Nessun giocatore corrisponde ai filtri selezionati.")
        return []
    indexed = frame.reset_index(drop=True)
    managers = auction_managers(league)
    manager_names = [str(manager.get("name") or "") for manager in managers]
    manager_id_by_name = {
        str(manager.get("name") or ""): str(manager.get("id")) for manager in managers
    }
    unassigned = "— Non assegnato —"
    no_tier = "— Nessuna fascia —"
    custom_tiers = league.get("auction_tiers", [])
    tier_label_by_id = {
        str(tier.get("id")): _tier_option_label(tier) for tier in custom_tiers
    }
    tier_id_by_label = {
        label: tier_id for tier_id, label in tier_label_by_id.items()
    }
    assignments = {
        str(player_id): auction_player_assignment(league, str(player_id))
        for player_id in indexed["_id"]
    }
    player_tiers = {
        str(player_id): auction_player_tier(league, str(player_id))
        for player_id in indexed["_id"]
    }
    catalog_by_id = {str(player.get("id")): player for player in catalog}

    def player_metric(player_id: Any, field: str) -> float:
        player = catalog_by_id.get(str(player_id), {})
        value = _number_or_none(player.get(field), 0.0) or 0.0
        if 0 < value <= 1:
            value *= 100
        return round(max(0.0, min(100.0, value)), 1)

    display = pd.DataFrame(
        {
            "_player_id": indexed["_id"].astype(str),
            "_assigned": [
                bool(assignments[str(player_id)]) for player_id in indexed["_id"]
            ],
            "Scheda": False,
            "In rosa": [
                "✓"
                if assignments[str(player_id)] and assignments[str(player_id)].get("is_user")
                else ""
                for player_id in indexed["_id"]
            ],
            "★": ["★" if str(player_id) in watchlist else "" for player_id in indexed["_id"]],
            "Partecipante": [
                assignments[str(player_id)]["manager_name"]
                if assignments[str(player_id)] else unassigned
                for player_id in indexed["_id"]
            ],
            "Prezzo asta": [
                float(assignments[str(player_id)]["purchase"].get("price") or 0)
                if assignments[str(player_id)] else 0.0
                for player_id in indexed["_id"]
            ],
            "Fascia personale": [
                tier_label_by_id.get(str(player_tiers[str(player_id)].get("id")), no_tier)
                if player_tiers[str(player_id)] else no_tier
                for player_id in indexed["_id"]
            ],
            "Ruolo": indexed["Ruolo"].map(
                {"P": "🟨 P", "D": "🟩 D", "C": "🟦 C", "A": "🟥 A"}
            ).fillna(indexed["Ruolo"]),
            "Giocatore": indexed["Giocatore"],
            "Squadra": indexed["Squadra"],
            "Q": indexed["Quotazione"],
            "Spesa iniziale": indexed["Spesa iniziale"],
            "Spesa aggiornata": indexed["Spesa aggiornata"],
            "Max strategico": indexed["Spesa strategica"],
            "FM attesa": indexed["FM attesa"],
            "Gol attesi": indexed["Gol attesi"],
            "Assist attesi": indexed["Assist attesi"],
            "Bonus": [player_metric(player_id, "bonus") for player_id in indexed["_id"]],
            "Titolarita": indexed["Titolarita %"],
            "Affidabilita": [
                player_metric(player_id, "reliability") for player_id in indexed["_id"]
            ],
            "Rischio infortuni": [
                player_metric(player_id, "risk") for player_id in indexed["_id"]
            ],
            "Potenziale": [
                player_metric(player_id, "potential") for player_id in indexed["_id"]
            ],
            "Indice": indexed["Indice"],
            "Fascia": indexed["Fascia"],
        }
    )
    first_id = str(indexed.iloc[0]["_id"])
    last_id = str(indexed.iloc[-1]["_id"])
    editor_version = int(st.session_state.get(version_key, 0))
    editor_key = f"{key}_{len(indexed)}_{first_id}_{last_id}_{editor_version}"
    tier_labels_by_color: dict[str, list[str]] = {}
    for tier in custom_tiers:
        color = str(tier.get("color") or "gray")
        tier_labels_by_color.setdefault(color, []).append(_tier_option_label(tier))
    row_class_rules: dict[str, Any] = {
        "fantasy-player-assigned": "data._assigned === true",
    }
    tier_row_css: dict[str, dict[str, str]] = {}
    for color, labels in tier_labels_by_color.items():
        safe_color = color if color in AUCTION_TIER_PALETTE else "gray"
        hex_color = AUCTION_TIER_PALETTE[safe_color][2]
        class_name = f"fantasy-tier-{safe_color}"
        encoded_labels = json.dumps(labels, ensure_ascii=False)
        row_class_rules[class_name] = JsCode(
            f"""function(params) {{
                return params.data && params.data._assigned !== true
                    && {encoded_labels}.includes(params.data['Fascia personale']);
            }}"""
        )
        tier_row_css[f".{class_name}"] = {
            "background": (
                "linear-gradient(90deg, "
                f"color-mix(in srgb, {hex_color} 28%, #080b0a), "
                "#080b0a 82%) !important"
            ),
            "border-left": f"5px solid {hex_color} !important",
            "box-shadow": f"inset 0 0 18px color-mix(in srgb, {hex_color} 10%, transparent)",
        }
    grid_options = {
        "defaultColDef": {
            "sortable": True,
            "resizable": True,
            "filter": False,
            "editable": False,
            "suppressHeaderMenuButton": True,
        },
        "columnDefs": [
            {"field": "_player_id", "hide": True},
            {"field": "_assigned", "hide": True},
            {
                "field": "Scheda",
                "headerName": "Apri",
                "editable": True,
                "cellRenderer": "agCheckboxCellRenderer",
                "cellEditor": "agCheckboxCellEditor",
                "width": 72,
                "pinned": "left",
            },
            {"field": "In rosa", "width": 82, "pinned": "left"},
            {"field": "★", "width": 55},
            {
                "field": "Partecipante",
                "headerName": "Fantallenatore",
                "editable": True,
                "cellEditor": "agSelectCellEditor",
                "cellEditorParams": {"values": [unassigned, *manager_names]},
                "minWidth": 190,
            },
            {
                "field": "Prezzo asta",
                "headerName": "Prezzo",
                "editable": True,
                "cellDataType": "number",
                "valueParser": JsCode(
                    """function(params) {
                        const value = Number(params.newValue);
                        return Number.isFinite(value) && value >= 0 ? value : params.oldValue;
                    }"""
                ),
                "width": 88,
            },
            {
                "field": "Fascia personale",
                "editable": True,
                "cellEditor": "agSelectCellEditor",
                "cellEditorParams": {"values": [no_tier, *tier_id_by_label]},
                "minWidth": 180,
            },
            {"field": "Ruolo", "width": 78},
            {
                "field": "Giocatore",
                "headerName": "Giocatore",
                "width": 180,
                "minWidth": 150,
                "pinned": "left",
                "lockPinned": True,
                "suppressMovable": True,
            },
            {"field": "Squadra", "width": 86},
            {"field": "Q", "width": 65, "type": "numericColumn"},
            {"field": "Spesa iniziale", "width": 112, "type": "numericColumn"},
            {"field": "Spesa aggiornata", "width": 125, "type": "numericColumn"},
            {"field": "Max strategico", "width": 118, "type": "numericColumn"},
            {"field": "FM attesa", "width": 94, "type": "numericColumn"},
            {"field": "Gol attesi", "width": 92, "type": "numericColumn"},
            {"field": "Assist attesi", "width": 100, "type": "numericColumn"},
            {
                "field": "Bonus",
                "headerName": "Propensione bonus",
                "width": 132,
                "cellStyle": _auction_metric_style("#ffb020"),
                "valueFormatter": _auction_metric_formatter(),
            },
            {
                "field": "Titolarita",
                "headerName": "Titolarità",
                "width": 105,
                "cellStyle": _auction_metric_style("#19e6b0"),
                "valueFormatter": _auction_metric_formatter("%"),
            },
            {
                "field": "Affidabilita",
                "headerName": "Affidabilità",
                "width": 112,
                "cellStyle": _auction_metric_style("#62d8ff"),
                "valueFormatter": _auction_metric_formatter(),
            },
            {
                "field": "Rischio infortuni",
                "width": 125,
                "cellStyle": _auction_metric_style("#f4538a"),
                "valueFormatter": _auction_metric_formatter(),
            },
            {
                "field": "Potenziale",
                "width": 105,
                "cellStyle": _auction_metric_style("#b895ff"),
                "valueFormatter": _auction_metric_formatter(),
            },
            {
                "field": "Indice",
                "width": 90,
                "cellStyle": _auction_metric_style("#19e6b0"),
                "valueFormatter": _auction_metric_formatter(),
            },
            {"field": "Fascia", "width": 90},
        ],
        "getRowId": JsCode("function(params) { return params.data._player_id; }"),
        "rowClassRules": row_class_rules,
        "singleClickEdit": True,
        "stopEditingWhenCellsLoseFocus": True,
        "suppressRowClickSelection": True,
        "rowHeight": 38,
        "headerHeight": 42,
        "animateRows": False,
    }
    grid_response = AgGrid(
        display,
        gridOptions=grid_options,
        height=min(620, 88 + max(len(display), 1) * 38),
        key=editor_key,
        data_return_mode="AS_INPUT",
        update_on=[("cellValueChanged", 250)],
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        theme="streamlit",
        show_toolbar=False,
        show_search=False,
        show_download_button=False,
        server_sync_strategy="client_wins",
        custom_css={
            ".ag-root-wrapper": {
                "border": "1px solid rgba(25,230,176,.22) !important",
                "border-radius": "10px !important",
                "overflow": "hidden !important",
            },
            ".ag-header": {
                "background": "#1a1f22 !important",
                "border-bottom": "1px solid rgba(244,251,247,.13) !important",
            },
            ".ag-pinned-left-header": {
                "border-right": "2px solid rgba(25,230,176,.32) !important",
                "box-shadow": "8px 0 18px rgba(0,0,0,.24) !important",
            },
            ".ag-pinned-left-cols-container": {
                "border-right": "2px solid rgba(25,230,176,.32) !important",
                "box-shadow": "8px 0 18px rgba(0,0,0,.24) !important",
                "z-index": "2 !important",
            },
            ".ag-row": {
                "background": "#080b0a",
                "color": "#edf7f2",
                "border-bottom": "1px solid rgba(244,251,247,.08)",
            },
            ".ag-row-hover": {
                "background": "#10201b !important",
            },
            **tier_row_css,
            ".fantasy-player-assigned": {
                "background": "#111514 !important",
                "color": "#5b6661 !important",
                "opacity": "0.48 !important",
                "border-left": "5px solid #78827e !important",
                "filter": "grayscale(1) !important",
            },
            ".fantasy-player-assigned .ag-cell": {
                "color": "#5b6661 !important",
            },
        },
    )
    edited = grid_response.data
    if not isinstance(edited, pd.DataFrame):
        edited = pd.DataFrame(edited)
    changes: list[dict[str, Any]] = []
    by_id = catalog_by_id
    for _, edited_row in edited.iterrows():
        clean_id = str(edited_row.get("_player_id") or "")
        if clean_id not in assignments:
            continue
        current = assignments[clean_id]
        current_name = current["manager_name"] if current else unassigned
        edited_name = str(edited_row.get("Partecipante") or unassigned)
        raw_price = edited_row.get("Prezzo asta")
        edited_price = float(raw_price) if pd.notna(raw_price) else 0.0
        current_price = (
            float(current["purchase"].get("price") or 0) if current else 0.0
        )
        current_tier = player_tiers[clean_id]
        current_tier_label = (
            tier_label_by_id.get(str(current_tier.get("id")), no_tier)
            if current_tier else no_tier
        )
        edited_tier_label = str(edited_row.get("Fascia personale") or no_tier)
        owner_changed = edited_name != current_name
        price_changed = current is not None and abs(edited_price - current_price) > 0.001
        tier_changed = edited_tier_label != current_tier_label
        if not owner_changed and not price_changed and not tier_changed:
            continue
        player = by_id.get(clean_id)
        if not player:
            continue
        change = {
            "player": player,
            "manager_id": None if edited_name == unassigned else manager_id_by_name[edited_name],
            "price": edited_price,
            "update_assignment": owner_changed or price_changed,
        }
        if tier_changed:
            change["tier_id"] = (
                None if edited_tier_label == no_tier
                else tier_id_by_label[edited_tier_label]
            )
        changes.append(change)

    selected_ids = [
        str(row.get("_player_id"))
        for _, row in edited.iterrows()
        if bool(row.get("Scheda"))
    ]
    action_column, hint_column = st.columns([1.1, 2.2])
    if action_column.button(
        f"Salva modifiche ({len(changes)})",
        type="primary",
        use_container_width=True,
        disabled=not changes,
        key=f"save_auction_grid_{editor_key}",
    ):
        try:
            update_auction_assignments(league, changes)
        except ValueError as error:
            st.error(str(error))
        else:
            touch_workspace(workspace)
            _save_workspace(workspace, storage)
            st.session_state[version_key] = int(st.session_state.get(version_key, 0)) + 1
            st.rerun()
    hint_column.caption(
        "Prezzo resta 0 finché il giocatore è libero. Puoi aggiornare proprietario, prezzo e fascia su più righe insieme."
    )
    return selected_ids


def _render_catalog_table(
    frame: pd.DataFrame,
    *,
    key: str,
    height: int = 560,
    selection_mode: str = "single-row",
    purchased_ids: set[str] | None = None,
    watchlist: set[str] | None = None,
) -> list[str]:
    if frame.empty:
        st.warning("Nessun giocatore corrisponde ai filtri selezionati.")
        return []
    indexed = frame.reset_index(drop=True)
    compact_columns = [
        "Ruolo",
        "Giocatore",
        "Squadra",
        "Quotazione",
        "FM attesa",
        "Gol attesi",
        "Assist attesi",
        "Titolarita %",
        "Indice",
        "Fascia",
    ]
    auction_columns = [
        column
        for column in ("Spesa iniziale", "Spesa aggiornata", "Spesa strategica", "Comparabili")
        if column in indexed.columns
    ]
    compact_columns = compact_columns[:4] + auction_columns + compact_columns[4:]
    display = indexed[compact_columns].copy()
    display.insert(
        0,
        "Rosa",
        indexed["_id"].map(lambda player_id: "✓" if player_id in (purchased_ids or set()) else ""),
    )
    display.insert(
        1,
        "Watch",
        indexed["_id"].map(lambda player_id: "★" if player_id in (watchlist or set()) else ""),
    )
    display["Ruolo"] = display["Ruolo"].map(
        {"P": "🟨 P", "D": "🟩 D", "C": "🟦 C", "A": "🟥 A"}
    ).fillna(display["Ruolo"])
    event = st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
        height=min(height, 88 + max(len(display), 1) * 38),
        row_height=38,
        on_select="rerun",
        selection_mode=selection_mode,
        key=key,
        column_config={
            "Rosa": st.column_config.TextColumn("In rosa", width="small"),
            "Watch": st.column_config.TextColumn("★", width="small"),
            "Ruolo": st.column_config.TextColumn(width="small"),
            "Giocatore": st.column_config.TextColumn(width="large"),
            "Squadra": st.column_config.TextColumn(width="small"),
            "Quotazione": st.column_config.NumberColumn("Q", format="%.0f", width="small"),
            "Spesa iniziale": st.column_config.NumberColumn(
                "Spesa iniziale", format="%.0f", width="small"
            ),
            "Spesa aggiornata": st.column_config.NumberColumn(
                "Spesa aggiornata", format="%.0f", width="small"
            ),
            "Spesa strategica": st.column_config.NumberColumn(
                "Max strategico", format="%.0f", width="small"
            ),
            "Comparabili": st.column_config.NumberColumn(
                "Confronti", format="%d", width="small"
            ),
            "FM attesa": st.column_config.NumberColumn(format="%.2f", width="small"),
            "Gol attesi": st.column_config.NumberColumn(format="%.1f", width="small"),
            "Assist attesi": st.column_config.NumberColumn(format="%.1f", width="small"),
            "Titolarita %": st.column_config.ProgressColumn(
                "Titolarita", min_value=0, max_value=100, format="%.0f%%", width="medium"
            ),
            "Indice": st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.0f", width="medium"
            ),
            "Fascia": st.column_config.TextColumn(width="small"),
        },
    )
    rows = _selected_dataframe_rows(event)
    return [
        str(indexed.iloc[position]["_id"])
        for position in rows
        if 0 <= position < len(indexed)
    ]


def _selected_dataframe_rows(event: Any) -> list[int]:
    try:
        return list(event.selection.rows)
    except AttributeError:
        if isinstance(event, dict):
            return list(event.get("selection", {}).get("rows", []))
    return []


def _render_board_actions(
    selected_ids: list[str],
    catalog: list[dict[str, Any]],
    league: dict[str, Any],
    workspace: dict[str, Any],
    storage: FantasyWorkspaceStorage,
    *,
    version_key: str,
) -> None:
    if not selected_ids:
        st.caption("Seleziona un giocatore dalla tabella per registrare l'aggiudicazione.")
        return
    by_id = {str(player.get("id")): player for player in catalog}
    list_mode = league.get("game_mode") == GAME_MODE_LIST
    purchased_ids = (
        {str(row.get("player_id")) for row in league.get("purchases", [])}
        if list_mode else auction_taken_player_ids(league)
    )
    selected_players = [
        by_id[player_id]
        for player_id in selected_ids
        if player_id in by_id and player_id not in purchased_ids
    ]
    already_owned = len(selected_ids) - len(selected_players)
    total_quote = sum(_number_or_none(player.get("quote"), 0) or 0 for player in selected_players)
    names = ", ".join(str(player.get("name")) for player in selected_players[:3])
    if len(selected_players) > 3:
        names += f" e altri {len(selected_players) - 3}"
    st.markdown(
        f'<div class="fantasy-selection-bar"><div><strong>{len(selected_players)} selezionati</strong>'
        f'<span>{escape(names or "Solo giocatori gia in rosa")}</span></div>'
        f'<b>{total_quote:.0f} crediti</b></div>',
        unsafe_allow_html=True,
    )
    if already_owned:
        st.caption(f"{already_owned} giocatori selezionati sono gia presenti nella rosa e verranno ignorati.")

    price = None
    manager_id = None
    if not list_mode and len(selected_players) == 1:
        player = selected_players[0]
        managers = auction_managers(league)
        price_board = auction_price_board(league, catalog)
        estimate = price_board.get(str(player.get("id")), {})
        manager_column, price_column = st.columns([1.45, 0.75])
        manager_id = manager_column.selectbox(
            "Squadra che ha acquistato",
            [str(manager.get("id")) for manager in managers],
            format_func=lambda value: next(
                str(manager.get("name")) for manager in managers if manager.get("id") == value
            ),
            key=f"board_manager_{league['id']}_{player.get('id')}",
        )
        manager_summary = auction_manager_summary(league, manager_id)
        default_price = min(
            float(estimate.get("strategic") or estimate.get("updated") or 1),
            float(manager_summary["remaining_budget"]),
        )
        price = price_column.number_input(
            "Prezzo asta",
            min_value=0.0,
            max_value=float(max(manager_summary["remaining_budget"], 1)),
            value=default_price,
            step=1.0,
            key=f"board_price_{league['id']}_{player.get('id')}",
        )
        st.caption(
            f"Base {estimate.get('initial', 0):.0f} · aggiornata {estimate.get('updated', 0):.0f} · "
            f"massimo strategico {estimate.get('strategic', 0):.0f} · "
            f"{estimate.get('comparables', 0)} acquisti comparabili"
        )
    elif not list_mode and len(selected_players) > 1:
        st.info("In modalita asta seleziona un solo giocatore alla volta per indicare il prezzo battuto.")

    add_column, watch_column, clear_column = st.columns([1.25, 1, 0.65])
    add_disabled = not selected_players or (not list_mode and len(selected_players) != 1)
    add_label = (
        f"Aggiungi {len(selected_players)} alla rosa"
        if list_mode else "Registra acquisto"
    )
    if add_column.button(
        add_label,
        type="primary",
        use_container_width=True,
        disabled=add_disabled,
        key=f"board_add_{league['id']}",
    ):
        try:
            if list_mode:
                add_purchases_batch(league, selected_players)
            else:
                record_auction_purchase(
                    league,
                    str(manager_id),
                    selected_players[0],
                    float(price or 0),
                )
        except ValueError as error:
            st.error(str(error))
        else:
            touch_workspace(workspace)
            _save_workspace(workspace, storage)
            st.session_state[version_key] = int(st.session_state.get(version_key, 0)) + 1
            st.rerun()

    missing_watchlist = [
        player for player in selected_players if str(player.get("id")) not in league.get("watchlist", [])
    ]
    if watch_column.button(
        f"Osserva selezionati ({len(missing_watchlist)})",
        use_container_width=True,
        disabled=not missing_watchlist,
        key=f"board_watch_{league['id']}",
    ):
        for player in missing_watchlist:
            toggle_watchlist(league, str(player.get("id")))
        touch_workspace(workspace)
        _save_workspace(workspace, storage)
        st.session_state[version_key] = int(st.session_state.get(version_key, 0)) + 1
        st.rerun()
    if clear_column.button(
        "Deseleziona",
        use_container_width=True,
        key=f"board_clear_{league['id']}",
    ):
        st.session_state[version_key] = int(st.session_state.get(version_key, 0)) + 1
        st.rerun()


def _render_role_advisors(
    workspace: dict[str, Any],
    league: dict[str, Any],
    storage: FantasyWorkspaceStorage,
    catalog: list[dict[str, Any]],
) -> None:
    advices = [
        advice
        for role in ROLE_LABELS
        if (advice := role_balance_recommendation(league, catalog, role)) is not None
    ]
    if not advices:
        st.caption("I consigli di completamento si attivano quando raggiungi almeno meta degli slot di un ruolo.")
        return

    st.markdown(
        '<div class="fantasy-advisor-heading"><span>SCOUT INTELLIGENTE</span>'
        '<strong>Cosa manca alla tua rosa</strong></div>',
        unsafe_allow_html=True,
    )
    tabs = st.tabs([
        f"{advice['role']} · {advice['count']}/{advice['target']}"
        for advice in advices
    ])
    for tab, advice in zip(tabs, advices):
        with tab:
            st.markdown(f"#### {advice['title']}")
            st.write(advice["reason"])
            candidates = advice.get("candidates", [])
            if not candidates:
                st.info("Nessun giocatore compatibile con ruolo e budget rimasto.")
                continue
            candidate_rows = [
                {
                    "Giocatore": player.get("name"),
                    "Squadra": player.get("team"),
                    "Q": player.get("quote"),
                    "FM attesa": player.get("expected_fantasy_average"),
                    "Gol attesi": player.get("expected_goals"),
                    "Assist attesi": player.get("expected_assists"),
                    "Titolarita %": player.get("starter_probability"),
                }
                for player in candidates
            ]
            st.dataframe(
                pd.DataFrame(candidate_rows),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Q": st.column_config.NumberColumn(format="%.0f"),
                    "FM attesa": st.column_config.NumberColumn(format="%.2f"),
                    "Gol attesi": st.column_config.NumberColumn(format="%.1f"),
                    "Assist attesi": st.column_config.NumberColumn(format="%.1f"),
                    "Titolarita %": st.column_config.ProgressColumn(
                        min_value=0, max_value=100, format="%.0f%%"
                    ),
                },
            )
            by_id = {str(player.get("id")): player for player in candidates}
            select_column, price_column, action_column = st.columns([1.7, 0.7, 0.75])
            candidate_id = select_column.selectbox(
                "Scegli un profilo consigliato",
                list(by_id),
                format_func=lambda value: (
                    f"{by_id[value].get('name')} · {by_id[value].get('team')} · "
                    f"Q {float(by_id[value].get('quote') or 0):.0f}"
                ),
                key=f"advisor_candidate_{league['id']}_{advice['role']}",
            )
            candidate = by_id[candidate_id]
            if league.get("game_mode") == GAME_MODE_LIST:
                price_column.metric("Costo", f"{float(candidate.get('quote') or 0):.0f}")
                price = float(candidate.get("quote") or 0)
            else:
                summary = roster_summary(league)
                price = price_column.number_input(
                    "Prezzo",
                    min_value=0.0,
                    max_value=float(max(summary["remaining_budget"], 1)),
                    value=min(float(candidate.get("quote") or 1), float(summary["remaining_budget"])),
                    key=f"advisor_price_{league['id']}_{advice['role']}_{candidate_id}",
                )
            if action_column.button(
                "Aggiungi alla rosa" if league.get("game_mode") == GAME_MODE_LIST else "Acquista",
                type="primary",
                use_container_width=True,
                key=f"advisor_add_{league['id']}_{advice['role']}",
            ):
                try:
                    add_purchase(league, candidate, price)
                except ValueError as error:
                    st.error(str(error))
                else:
                    touch_workspace(workspace)
                    _save_workspace(workspace, storage)
                    version_key = f"catalog_board_version_{league['id']}"
                    st.session_state[version_key] = int(st.session_state.get(version_key, 0)) + 1
                    st.rerun()


ROLE_CHART_COLORS = {
    "P": "#ffb020",
    "D": "#19e6b0",
    "C": "#62d8ff",
    "A": "#f4538a",
}

PLAYER_RANKING_METRICS = {
    "Fanta Score": "fantasy_score",
    "Fantamedia attesa": "expected_fantasy_average",
    "Gol attesi": "expected_goals",
    "Assist attesi": "expected_assists",
    "Propensione bonus": "bonus",
    "Titolarita": "starter_probability",
    "Affidabilita": "reliability",
    "Potenziale": "potential",
    "Valore": "value",
}

PLOTLY_CONFIG = {
    "displayModeBar": False,
    "responsive": True,
    "scrollZoom": False,
}


def _render_top_players_visual_lab(
    catalog: list[dict[str, Any]], league: dict[str, Any]
) -> None:
    if not catalog:
        return
    with st.expander("✦ Player Intelligence Lab · esplora i migliori", expanded=False):
        st.caption(
            "Tre letture avanzate del listone: costellazione dei bonus, frontiera qualita/prezzo "
            "e impronta multidimensionale. Passa sul grafico per leggere tutti i valori."
        )
        role_column, metric_column, starter_column = st.columns([0.8, 1.2, 1])
        role_filter = role_column.selectbox(
            "Reparto",
            ["Tutti", "P", "D", "C", "A"],
            format_func=lambda value: "Tutti i ruoli" if value == "Tutti" else ROLE_LABELS[value],
            key=f"visual_lab_role_{league['id']}",
        )
        metric_label = metric_column.selectbox(
            "Evidenzia i top per",
            list(PLAYER_RANKING_METRICS),
            key=f"visual_lab_metric_{league['id']}",
        )
        minimum_starter = starter_column.slider(
            "Titolarita minima",
            0,
            100,
            40,
            step=5,
            key=f"visual_lab_starter_{league['id']}",
        )

        filtered = [
            player
            for player in catalog
            if (role_filter == "Tutti" or str(player.get("role")) == role_filter)
            and analytics_number(player.get("starter_probability")) >= minimum_starter
        ]
        if not filtered:
            st.info("Nessun giocatore corrisponde ai filtri scelti.")
            return
        metric_field = PLAYER_RANKING_METRICS[metric_label]
        top_players = sorted(
            filtered,
            key=lambda player: analytics_number(player.get(metric_field), -1),
            reverse=True,
        )[:18]
        frame = _players_analytics_frame(filtered)
        top_ids = {str(player.get("id")) for player in top_players}
        frame["Top selezionato"] = frame["_id"].isin(top_ids)

        constellation_tab, frontier_tab, fingerprint_tab = st.tabs(
            ["Costellazione bonus", "Frontiera del valore", "Impronta top player"]
        )
        with constellation_tab:
            _render_bonus_constellation(
                frame,
                metric_label,
                metric_field,
                top_ids,
                key=f"constellation_{league['id']}",
            )
        with frontier_tab:
            _render_value_frontier(
                filtered,
                frame,
                metric_label,
                top_ids,
                key=f"frontier_{league['id']}",
            )
        with fingerprint_tab:
            _render_parallel_fingerprint(
                top_players,
                metric_label,
                metric_field,
                key=f"fingerprint_{league['id']}",
            )


def _players_analytics_frame(players: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for player in players:
        derived = player_derived_stats(player)
        rows.append(
            {
                "_id": str(player.get("id") or ""),
                "Giocatore": str(player.get("name") or ""),
                "Squadra": str(player.get("team") or ""),
                "Ruolo": str(player.get("role") or ""),
                "Quotazione": analytics_number(player.get("quote")),
                "FM attesa": analytics_number(player.get("expected_fantasy_average")),
                "Gol attesi": analytics_number(player.get("expected_goals")),
                "Assist attesi": analytics_number(player.get("expected_assists")),
                "Bonus attesi": analytics_number(derived.get("expected_bonus_points")),
                "Bonus per presenza": analytics_number(derived.get("expected_bonus_per_appearance")),
                "Propensione bonus": analytics_number(player.get("bonus")),
                "Titolarita": analytics_number(player.get("starter_probability")),
                "Affidabilita": analytics_number(player.get("reliability")),
                "Potenziale": analytics_number(player.get("potential")),
                "Rischio": analytics_number(player.get("risk")),
                "Valore": analytics_number(player.get("value")),
                "Fanta Score": analytics_number(player.get("fantasy_score")),
                "Presenze attese": max(analytics_number(player.get("expected_appearances")), 3),
            }
        )
    return pd.DataFrame(rows)


def _plotly_base_layout(*, height: int = 560) -> dict[str, Any]:
    return {
        "height": height,
        "margin": {"l": 34, "r": 26, "t": 48, "b": 42},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(8,10,11,.3)",
        "font": {"family": "Inter, system-ui, sans-serif", "color": "#dce8e3"},
        "hoverlabel": {"bgcolor": "#111718", "font_color": "#f4fbf7", "bordercolor": "#19e6b0"},
        "legend": {"orientation": "h", "y": 1.08, "x": 0},
    }


def _render_bonus_constellation(
    frame: pd.DataFrame,
    metric_label: str,
    metric_field: str,
    top_ids: set[str],
    *,
    key: str,
) -> None:
    display_metric = {
        "fantasy_score": "Fanta Score",
        "expected_fantasy_average": "FM attesa",
        "expected_goals": "Gol attesi",
        "expected_assists": "Assist attesi",
        "bonus": "Propensione bonus",
        "starter_probability": "Titolarita",
        "reliability": "Affidabilita",
        "potential": "Potenziale",
        "value": "Valore",
    }[metric_field]
    chart = frame.copy()
    chart["Metrica selezionata"] = chart[display_metric]
    chart["Etichetta"] = chart.apply(
        lambda row: row["Giocatore"] if row["_id"] in top_ids else "", axis=1
    )
    figure = px.scatter(
        chart,
        x="Gol attesi",
        y="Assist attesi",
        size="Presenze attese",
        color="Metrica selezionata",
        color_continuous_scale=["#19322d", "#19e6b0", "#ffb020", "#f4538a"],
        text="Etichetta",
        hover_name="Giocatore",
        hover_data={
            "Squadra": True,
            "Ruolo": True,
            "FM attesa": ":.2f",
            "Bonus attesi": ":.1f",
            "Titolarita": ":.0f",
            "Affidabilita": ":.0f",
            "Metrica selezionata": ":.2f",
            "Presenze attese": False,
            "Etichetta": False,
            "_id": False,
        },
        labels={"Metrica selezionata": metric_label},
        size_max=30,
    )
    figure.update_traces(
        marker={"line": {"width": 1, "color": "rgba(244,251,247,.45)"}, "opacity": 0.8},
        textposition="top center",
        textfont={"size": 10, "color": "#f4fbf7"},
    )
    figure.add_vline(
        x=float(chart["Gol attesi"].median()),
        line_dash="dot",
        line_color="rgba(244,251,247,.24)",
    )
    figure.add_hline(
        y=float(chart["Assist attesi"].median()),
        line_dash="dot",
        line_color="rgba(244,251,247,.24)",
    )
    figure.update_layout(
        **_plotly_base_layout(),
        title={"text": f"<b>Costellazione dei top · {metric_label}</b><br><sup>In alto a destra vivono i profili piu completi nei bonus</sup>", "x": 0.01},
        coloraxis_colorbar={"title": metric_label, "thickness": 10},
    )
    figure.update_xaxes(gridcolor="rgba(244,251,247,.08)", zeroline=False)
    figure.update_yaxes(gridcolor="rgba(244,251,247,.08)", zeroline=False)
    st.plotly_chart(figure, use_container_width=True, theme=None, config=PLOTLY_CONFIG, key=key)


def _render_value_frontier(
    players: list[dict[str, Any]],
    frame: pd.DataFrame,
    metric_label: str,
    top_ids: set[str],
    *,
    key: str,
) -> None:
    chart = frame[frame["Quotazione"] > 0].copy()
    chart["Etichetta"] = chart.apply(
        lambda row: row["Giocatore"] if row["_id"] in top_ids else "", axis=1
    )
    figure = px.scatter(
        chart,
        x="Quotazione",
        y="FM attesa",
        size="Bonus attesi",
        color="Ruolo",
        color_discrete_map=ROLE_CHART_COLORS,
        text="Etichetta",
        hover_name="Giocatore",
        hover_data={
            "Squadra": True,
            "Bonus attesi": ":.1f",
            "Gol attesi": ":.1f",
            "Assist attesi": ":.1f",
            "Titolarita": ":.0f",
            "Affidabilita": ":.0f",
            "Etichetta": False,
            "_id": False,
        },
        size_max=32,
    )
    frontier = pareto_frontier(players)
    if frontier:
        figure.add_trace(
            go.Scatter(
                x=[analytics_number(player.get("quote")) for player in frontier],
                y=[analytics_number(player.get("expected_fantasy_average")) for player in frontier],
                mode="lines+markers",
                name="Frontiera efficiente",
                line={"color": "#ffb020", "width": 3, "shape": "spline"},
                marker={"size": 8, "symbol": "diamond", "color": "#ffb020"},
                customdata=[[str(player.get("name") or "")] for player in frontier],
                hovertemplate="%{customdata[0]}<br>Q %{x:.0f}<br>FM %{y:.2f}<extra>Frontiera</extra>",
            )
        )
    figure.update_traces(
        marker={"line": {"width": 1, "color": "rgba(244,251,247,.38)"}, "opacity": 0.78},
        textposition="top center",
        selector={"mode": "markers+text"},
    )
    figure.update_layout(
        **_plotly_base_layout(),
        title={"text": f"<b>Frontiera qualita/prezzo</b><br><sup>La linea ambra evidenzia chi offre piu FM senza pagare crediti inutili · top per {metric_label}</sup>", "x": 0.01},
    )
    figure.update_xaxes(gridcolor="rgba(244,251,247,.08)", zeroline=False)
    figure.update_yaxes(gridcolor="rgba(244,251,247,.08)", zeroline=False)
    st.plotly_chart(figure, use_container_width=True, theme=None, config=PLOTLY_CONFIG, key=key)


def _render_parallel_fingerprint(
    players: list[dict[str, Any]],
    metric_label: str,
    metric_field: str,
    *,
    key: str,
) -> None:
    if not players:
        st.info("Non ci sono giocatori sufficienti per il confronto multidimensionale.")
        return
    names = [str(player.get("name") or "") for player in players]
    values = [analytics_number(player.get(metric_field)) for player in players]
    dimensions = [
        dict(range=[0, max(9, max(analytics_number(p.get("expected_fantasy_average")) for p in players))], label="FM", values=[analytics_number(p.get("expected_fantasy_average")) for p in players]),
        dict(range=[0, max(1, max(analytics_number(p.get("expected_goals")) for p in players))], label="Gol", values=[analytics_number(p.get("expected_goals")) for p in players]),
        dict(range=[0, max(1, max(analytics_number(p.get("expected_assists")) for p in players))], label="Assist", values=[analytics_number(p.get("expected_assists")) for p in players]),
        dict(range=[0, 100], label="Titolarita", values=[analytics_number(p.get("starter_probability")) for p in players]),
        dict(range=[0, 100], label="Affidabilita", values=[analytics_number(p.get("reliability")) for p in players]),
        dict(range=[0, 100], label="Potenziale", values=[analytics_number(p.get("potential")) for p in players]),
        dict(range=[0, 100], label="Integrita", values=[100 - analytics_number(p.get("risk")) for p in players]),
        dict(range=[0, 100], label="Valore", values=[analytics_number(p.get("value")) for p in players]),
    ]
    figure = go.Figure(
        data=go.Parcoords(
            line={
                "color": values,
                "colorscale": [[0, "#19322d"], [0.5, "#19e6b0"], [0.8, "#ffb020"], [1, "#f4538a"]],
                "showscale": True,
                "colorbar": {"title": metric_label, "thickness": 10},
            },
            dimensions=dimensions,
            labelfont={"color": "#f4fbf7", "size": 12},
            tickfont={"color": "#9dafaa", "size": 10},
            rangefont={"color": "#9dafaa", "size": 9},
        )
    )
    figure.update_layout(
        **_plotly_base_layout(height=590),
        title={"text": f"<b>Impronta dei migliori {len(players)}</b><br><sup>Ogni linea e un giocatore: segui il profilo sulle otto dimensioni</sup>", "x": 0.01},
    )
    st.caption("Giocatori inclusi: " + " · ".join(names))
    st.plotly_chart(figure, use_container_width=True, theme=None, config=PLOTLY_CONFIG, key=key)


def _render_player_detail(
    player: dict[str, Any],
    league: dict[str, Any],
    workspace: dict[str, Any],
    storage: FantasyWorkspaceStorage,
) -> None:
    role = str(player.get("role", ""))
    catalog = workspace.get("catalog", [])
    derived = player_derived_stats(player)
    role_names = {"P": "Portiere", "D": "Difensore", "C": "Centrocampista", "A": "Attaccante"}
    st.markdown(
        f"""
        <section class="fantasy-player-hero role-{role.lower()}">
            <div class="fantasy-player-role">{escape(role)}</div>
            <div class="fantasy-player-title">
                <span>{escape(role_names.get(role, 'Calciatore'))} · {escape(str(player.get('team') or 'Svincolato'))}</span>
                <h3>{escape(str(player.get('name') or ''))}</h3>
                <p>{escape(str(player.get('status') or 'Stato non disponibile'))} · {escape(str(player.get('profile') or 'Profilo in analisi'))}</p>
            </div>
            <div class="fantasy-player-score"><small>FANTA SCORE</small><strong>{_format_stat(player.get('fantasy_score'), 0)}</strong><span>{escape(str(player.get('tier') or '—'))}</span></div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    quote, fvm, expected_fm, starter = st.columns(4)
    quote.metric("Quotazione", _format_stat(player.get("quote"), 0))
    fvm.metric("FVM / 1000", _format_stat(player.get("fvm"), 0))
    expected_fm.metric("Fantamedia attesa", _format_stat(player.get("expected_fantasy_average"), 2))
    starter.metric("Titolarita", _format_stat(player.get("starter_probability"), 0, "%"))

    watchlist = set(league.get("watchlist", []))
    is_watched = player.get("id") in watchlist
    if st.button(
        "Rimuovi dalla watchlist" if is_watched else "+ Aggiungi alla watchlist",
        key=f"detail_watch_{league['id']}_{player.get('id')}",
        type="secondary",
    ):
        toggle_watchlist(league, str(player.get("id")))
        touch_workspace(workspace)
        _save_workspace(workspace, storage)
        st.rerun()

    if league.get("game_mode") == GAME_MODE_AUCTION:
        _render_player_assignment_editor(player, league, workspace, storage)

    visual_tab, projection_tab, season_tab, advanced_tab, profile_tab = st.tabs(
        [
            "Identikit visuale",
            "Proiezione 26/27",
            "Stagione 25/26",
            "Dati avanzati",
            "Profilo & asta",
        ]
    )
    with visual_tab:
        _render_player_visuals(player, catalog)
    with projection_tab:
        _render_stat_grid([
            ("Presenze attese", player.get("expected_appearances"), 0),
            ("Disponibilita attesa", derived.get("expected_availability"), 0, "%"),
            ("Gol attesi", player.get("expected_goals"), 1),
            ("Assist attesi", player.get("expected_assists"), 1),
            ("Partecipazioni gol", derived.get("expected_goal_involvements"), 1),
            ("Punti bonus attesi", derived.get("expected_bonus_points"), 1),
            ("Gol attesi / presenza", derived.get("expected_goals_per_appearance"), 2),
            ("Assist attesi / presenza", derived.get("expected_assists_per_appearance"), 2),
            ("Bonus attesi / presenza", derived.get("expected_bonus_per_appearance"), 2),
            ("Fantamedia attesa", player.get("expected_fantasy_average"), 2),
            ("Variazione FM", derived.get("fantasy_average_delta"), 2),
            ("Titolarita", player.get("starter_probability"), 0, "%"),
            ("Affidabilita", player.get("reliability"), 0),
            ("Propensione bonus", player.get("bonus"), 0),
            ("Potenziale", player.get("potential"), 0),
            ("Rischio infortuni", player.get("risk"), 0),
            ("Valore", player.get("value"), 0),
            ("Fanta Score", player.get("fantasy_score"), 0),
        ])
    with season_tab:
        _render_stat_grid([
            ("Presenze", player.get("appearances_previous"), 0),
            ("Media voto", player.get("average_rating_previous"), 2),
            ("Fantamedia", player.get("fantasy_average_previous"), 2),
            ("Gol", player.get("goals_previous"), 0),
            ("Assist", player.get("assists_previous"), 0),
            ("Partecipazioni gol", derived.get("previous_goal_involvements"), 0),
            ("Punti bonus", derived.get("previous_bonus_points"), 0),
            ("Gol / presenza", derived.get("goals_per_appearance"), 2),
            ("Assist / presenza", derived.get("assists_per_appearance"), 2),
            ("Bonus / presenza", derived.get("bonus_points_per_appearance"), 2),
            ("Rigori segnati", player.get("penalties_scored"), 0),
            ("Rigori tirati", player.get("penalties_taken"), 0),
            ("Conversione rigori", derived.get("penalty_conversion"), 0, "%"),
            ("Ammonizioni", player.get("yellow_cards"), 0),
            ("Espulsioni", player.get("red_cards"), 0),
            ("Cartellini / presenza", derived.get("cards_per_appearance"), 2),
            ("Gol subiti", player.get("goals_conceded"), 0),
            ("Gol subiti / presenza", derived.get("goals_conceded_per_appearance"), 2),
            ("Rigori parati", player.get("penalties_saved"), 0),
            ("Goal prevented", player.get("goals_prevented"), 2),
        ])
    with advanced_tab:
        goals_minus_xg = player.get("goals_minus_xg")
        if goals_minus_xg is None and player.get("xg_previous") is not None:
            goals_minus_xg = _number_or_none(player.get("goals_previous"), 0) - _number_or_none(player.get("xg_previous"), 0)
        assists_minus_xa = player.get("assists_minus_xa")
        if assists_minus_xa is None and player.get("xa_previous") is not None:
            assists_minus_xa = _number_or_none(player.get("assists_previous"), 0) - _number_or_none(player.get("xa_previous"), 0)
        _render_stat_grid([
            ("xG", player.get("xg_previous"), 2),
            ("xA", player.get("xa_previous"), 2),
            ("xGI · xG + xA", derived.get("xgi_previous"), 2),
            ("xG / presenza", derived.get("xg_per_appearance"), 2),
            ("xA / presenza", derived.get("xa_per_appearance"), 2),
            ("Gol - xG", goals_minus_xg, 2),
            ("Assist - xA", assists_minus_xa, 2),
            ("Goal prevented", player.get("goals_prevented"), 2),
            ("Copertura dati", derived.get("data_coverage"), 0, "%"),
        ])
        _render_role_percentile_strip(player, catalog)
        st.caption(
            "xG, xA e Goal prevented provengono dall'analisi [FotMob](https://www.fotmob.com/leagues/55/overview/serie-a). I tracking fisici "
            "(km percorsi, sprint e velocita) sono mostrabili solo quando una fonte pubblica dati uniformi e verificabili: "
            "non vengono stimati artificialmente."
        )
    with profile_tab:
        penalty_labels = {1: "Prima scelta", 2: "Seconda scelta"}
        _render_stat_grid([
            ("Ruolo Classic", player.get("role"), None),
            ("Ruolo Mantra", player.get("mantra_role"), None),
            ("Quotazione iniziale", player.get("initial_quote"), 0),
            ("Quotazione attuale", player.get("quote"), 0),
            ("Variazione quotazione", derived.get("current_quote_delta"), 0),
            ("Quotazione prevista", player.get("predicted_quote"), 0),
            ("Delta quotazione prevista", derived.get("predicted_quote_delta"), 0),
            ("FVM / 1000", player.get("fvm"), 0),
            ("FVM / credito", derived.get("fvm_per_credit"), 2),
            ("FM attesa / credito", derived.get("fantasy_average_per_credit"), 3),
            ("Bonus attesi / credito", derived.get("expected_bonus_per_credit"), 2),
            ("Score / credito", derived.get("score_per_credit"), 2),
            ("Rigorista", penalty_labels.get(_int_or_none(player.get("penalty_taker")), "No"), None),
            ("Piazzati", penalty_labels.get(_int_or_none(player.get("set_pieces")), "No"), None),
            ("Stato 26/27", player.get("status"), None),
            ("Qualita dati", player.get("data_quality"), None),
            ("Fascia", player.get("tier"), None),
            ("Profilo", player.get("profile"), None),
            ("Fonte", player.get("source"), None),
        ])


def _render_player_assignment_editor(
    player: dict[str, Any],
    league: dict[str, Any],
    workspace: dict[str, Any],
    storage: FantasyWorkspaceStorage,
) -> None:
    player_id = str(player.get("id") or "")
    assignment = auction_player_assignment(league, player_id)
    managers = auction_managers(league)
    manager_by_id = {str(manager.get("id")): manager for manager in managers}
    current_manager_id = str(assignment.get("manager_id")) if assignment else ""
    current_price = (
        float(assignment["purchase"].get("price") or 0) if assignment else 0.0
    )
    tiers = league.get("auction_tiers", [])
    tier_by_id = {str(tier.get("id")): tier for tier in tiers}
    current_tier = auction_player_tier(league, player_id)
    current_tier_id = str(current_tier.get("id")) if current_tier else ""

    with st.expander("Gestisci acquisto · fantallenatore, prezzo e fascia", expanded=False):
        st.caption(
            "Puoi correggere in qualsiasi momento chi ha comprato il giocatore, "
            "il prezzo pagato e la fascia personale."
        )
        owner_column, price_column, tier_column = st.columns([1.25, 0.7, 1.15])
        manager_options = ["", *manager_by_id]
        selected_manager_id = owner_column.selectbox(
            "Fantallenatore",
            manager_options,
            index=(
                manager_options.index(current_manager_id)
                if current_manager_id in manager_options else 0
            ),
            format_func=lambda value: (
                "— Non assegnato —"
                if not value else str(manager_by_id[value].get("name") or "")
            ),
            key=f"detail_owner_{league['id']}_{player_id}",
        )
        edited_price = price_column.number_input(
            "Crediti pagati",
            min_value=0.0,
            max_value=float(max(int(league.get("initial_budget") or 0), 1)),
            value=current_price,
            step=1.0,
            disabled=not selected_manager_id,
            key=f"detail_price_{league['id']}_{player_id}",
        )
        tier_options = ["", *tier_by_id]
        selected_tier_id = tier_column.selectbox(
            "Fascia personale",
            tier_options,
            index=(tier_options.index(current_tier_id) if current_tier_id in tier_options else 0),
            format_func=lambda value: (
                "— Nessuna fascia —" if not value else _tier_option_label(tier_by_id[value])
            ),
            key=f"detail_tier_{league['id']}_{player_id}",
        )
        effective_price = float(edited_price) if selected_manager_id else 0.0
        changed = (
            selected_manager_id != current_manager_id
            or abs(effective_price - current_price) > 0.001
            or selected_tier_id != current_tier_id
        )
        if st.button(
            "Salva assegnazione",
            type="primary",
            use_container_width=True,
            disabled=not changed,
            key=f"detail_assignment_save_{league['id']}_{player_id}",
        ):
            change: dict[str, Any] = {
                "player": player,
                "manager_id": selected_manager_id or None,
                "price": effective_price,
                "update_assignment": (
                    selected_manager_id != current_manager_id
                    or abs(effective_price - current_price) > 0.001
                ),
            }
            if selected_tier_id != current_tier_id:
                change["tier_id"] = selected_tier_id or None
            try:
                update_auction_assignments(league, [change])
            except ValueError as error:
                st.error(str(error))
            else:
                touch_workspace(workspace)
                _save_workspace(workspace, storage)
                st.rerun()

def _render_player_visuals(player: dict[str, Any], catalog: list[dict[str, Any]]) -> None:
    player_id = str(player.get("id") or player.get("name") or "player")
    radar_tab, peers_tab, evolution_tab = st.tabs(
        ["DNA nel ruolo", "Mappa dei concorrenti", "Storico → proiezione"]
    )
    with radar_tab:
        _render_player_radar(player, catalog, key=f"player_radar_{player_id}")
    with peers_tab:
        _render_player_peer_map(player, catalog, key=f"player_peers_{player_id}")
    with evolution_tab:
        _render_player_dumbbell(player, key=f"player_evolution_{player_id}")


def _render_player_radar(
    player: dict[str, Any], catalog: list[dict[str, Any]], *, key: str
) -> None:
    percentiles = role_percentiles(player, catalog)
    labels = [label for _, label, _ in PERCENTILE_METRICS]
    values = [analytics_number(percentiles.get(field)) for field, _, _ in PERCENTILE_METRICS]
    labels_closed = [*labels, labels[0]]
    values_closed = [*values, values[0]]
    figure = go.Figure()
    figure.add_trace(
        go.Scatterpolar(
            r=[50] * len(labels_closed),
            theta=labels_closed,
            mode="lines",
            line={"color": "rgba(244,251,247,.22)", "dash": "dot", "width": 1},
            name="Mediana ruolo",
            hoverinfo="skip",
        )
    )
    figure.add_trace(
        go.Scatterpolar(
            r=values_closed,
            theta=labels_closed,
            mode="lines+markers",
            fill="toself",
            fillcolor="rgba(25,230,176,.18)",
            line={"color": "#19e6b0", "width": 3},
            marker={"size": 8, "color": "#f4fbf7", "line": {"color": "#19e6b0", "width": 2}},
            name=str(player.get("name") or "Giocatore"),
            hovertemplate="%{theta}: percentile %{r:.0f}<extra></extra>",
        )
    )
    figure.update_layout(
        **_plotly_base_layout(height=540),
        title={"text": f"<b>DNA di {escape(str(player.get('name') or ''))}</b><br><sup>Percentile rispetto agli altri {ROLE_LABELS.get(str(player.get('role')), 'giocatori')}</sup>", "x": 0.01},
        polar={
            "bgcolor": "rgba(8,10,11,.24)",
            "radialaxis": {"range": [0, 100], "tickvals": [25, 50, 75, 100], "gridcolor": "rgba(244,251,247,.12)", "showline": False},
            "angularaxis": {"gridcolor": "rgba(244,251,247,.10)"},
        },
        showlegend=False,
    )
    st.plotly_chart(figure, use_container_width=True, theme=None, config=PLOTLY_CONFIG, key=key)
    st.caption("Un valore 80 significa che il giocatore supera l'80% dei pari ruolo. Integrita e il rischio infortuni invertito.")


def _render_player_peer_map(
    player: dict[str, Any], catalog: list[dict[str, Any]], *, key: str
) -> None:
    role = str(player.get("role") or "")
    peers = [row for row in catalog if str(row.get("role") or "") == role]
    frame = _players_analytics_frame(peers)
    if frame.empty:
        st.info("Non ci sono confronti disponibili per questo ruolo.")
        return
    frame["Selezionato"] = frame["_id"].eq(str(player.get("id") or ""))
    frame["Etichetta"] = frame.apply(
        lambda row: row["Giocatore"]
        if row["Selezionato"] or row["Fanta Score"] >= frame["Fanta Score"].quantile(.92)
        else "",
        axis=1,
    )
    figure = px.scatter(
        frame,
        x="Bonus per presenza",
        y="FM attesa",
        size="Presenze attese",
        color="Affidabilita",
        color_continuous_scale=["#f4538a", "#ffb020", "#19e6b0"],
        text="Etichetta",
        hover_name="Giocatore",
        hover_data={
            "Squadra": True,
            "Gol attesi": ":.1f",
            "Assist attesi": ":.1f",
            "Titolarita": ":.0f",
            "Rischio": ":.0f",
            "Etichetta": False,
            "Selezionato": False,
            "_id": False,
        },
        size_max=26,
    )
    selected = frame[frame["Selezionato"]]
    if not selected.empty:
        figure.add_trace(
            go.Scatter(
                x=selected["Bonus per presenza"],
                y=selected["FM attesa"],
                mode="markers+text",
                text=selected["Giocatore"],
                textposition="bottom center",
                marker={"size": 25, "symbol": "star", "color": "#f4fbf7", "line": {"color": "#f4538a", "width": 3}},
                name="Giocatore selezionato",
                hoverinfo="skip",
            )
        )
    figure.add_vline(x=float(frame["Bonus per presenza"].median()), line_dash="dot", line_color="rgba(244,251,247,.22)")
    figure.add_hline(y=float(frame["FM attesa"].median()), line_dash="dot", line_color="rgba(244,251,247,.22)")
    figure.update_traces(textposition="top center", selector={"mode": "markers+text"})
    figure.update_layout(
        **_plotly_base_layout(),
        title={"text": "<b>Mappa dei concorrenti diretti</b><br><sup>La stella e il giocatore selezionato; in alto a destra bonus e rendimento si incontrano</sup>", "x": 0.01},
        coloraxis_colorbar={"title": "Affidabilita", "thickness": 10},
    )
    figure.update_xaxes(gridcolor="rgba(244,251,247,.08)", zeroline=False)
    figure.update_yaxes(gridcolor="rgba(244,251,247,.08)", zeroline=False)
    st.plotly_chart(figure, use_container_width=True, theme=None, config=PLOTLY_CONFIG, key=key)


def _render_player_dumbbell(player: dict[str, Any], *, key: str) -> None:
    metrics = [
        ("Presenze", player.get("appearances_previous"), player.get("expected_appearances")),
        ("Gol", player.get("goals_previous"), player.get("expected_goals")),
        ("Assist", player.get("assists_previous"), player.get("expected_assists")),
        ("Fantamedia", player.get("fantasy_average_previous"), player.get("expected_fantasy_average")),
    ]
    available = [
        (label, analytics_optional_number(previous), analytics_optional_number(expected))
        for label, previous, expected in metrics
        if analytics_optional_number(previous) is not None and analytics_optional_number(expected) is not None
    ]
    if not available:
        st.info("Non ci sono dati storici e previsionali sufficienti per questa evoluzione.")
        return
    figure = go.Figure()
    for index, (label, previous, expected) in enumerate(available):
        figure.add_trace(
            go.Scatter(
                x=[previous, expected],
                y=[label, label],
                mode="lines",
                line={"color": "rgba(244,251,247,.24)", "width": 5},
                showlegend=False,
                hoverinfo="skip",
            )
        )
    figure.add_trace(
        go.Scatter(
            x=[previous for _, previous, _ in available],
            y=[label for label, _, _ in available],
            mode="markers+text",
            text=[f"{previous:.1f}" for _, previous, _ in available],
            textposition="middle left",
            marker={"size": 15, "color": "#8e9b96"},
            name="2025/26",
            hovertemplate="%{y}: %{x:.2f}<extra>2025/26</extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[expected for _, _, expected in available],
            y=[label for label, _, _ in available],
            mode="markers+text",
            text=[f"{expected:.1f}" for _, _, expected in available],
            textposition="middle right",
            marker={"size": 17, "color": "#19e6b0", "line": {"width": 2, "color": "#f4fbf7"}},
            name="Proiezione 26/27",
            hovertemplate="%{y}: %{x:.2f}<extra>Proiezione 26/27</extra>",
        )
    )
    figure.update_layout(
        **_plotly_base_layout(height=470),
        title={"text": "<b>Traiettoria attesa</b><br><sup>Il collegamento mostra la distanza tra ultima stagione e proiezione</sup>", "x": 0.01},
        xaxis={"gridcolor": "rgba(244,251,247,.08)", "zeroline": False},
        yaxis={"gridcolor": "rgba(244,251,247,.06)", "categoryorder": "array", "categoryarray": [label for label, _, _ in reversed(available)]},
    )
    st.plotly_chart(figure, use_container_width=True, theme=None, config=PLOTLY_CONFIG, key=key)


def _render_role_percentile_strip(player: dict[str, Any], catalog: list[dict[str, Any]]) -> None:
    percentiles = role_percentiles(player, catalog)
    cards = []
    for field, label, _ in PERCENTILE_METRICS:
        value = percentiles.get(field)
        if value is None:
            continue
        tone = "elite" if value >= 80 else "good" if value >= 60 else "average" if value >= 40 else "weak"
        cards.append(
            f'<div class="fantasy-percentile {tone}"><span>{escape(label)}</span>'
            f'<strong>P{value:.0f}</strong><i style="--value:{max(0, min(value, 100)):.0f}%"></i></div>'
        )
    if cards:
        st.markdown("#### Percentili nel ruolo")
        st.markdown(f'<div class="fantasy-percentile-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def _render_stat_grid(items: list[tuple]) -> None:
    cards = []
    for item in items:
        label, value, decimals = item[:3]
        suffix = item[3] if len(item) > 3 else ""
        display = (
            escape(str("—" if value is None or value == "" else value))
            if decimals is None else _format_stat(value, decimals, suffix)
        )
        cards.append(
            f'<div class="fantasy-stat-card"><span>{escape(label)}</span><strong>{display}</strong></div>'
        )
    st.markdown(f'<div class="fantasy-stat-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def _format_stat(value: Any, decimals: int, suffix: str = "") -> str:
    number = _number_or_none(value)
    return "—" if number is None else f"{number:.{decimals}f}{suffix}"


def _number_or_none(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_or_none(value: Any) -> int | None:
    number = _number_or_none(value)
    return int(number) if number is not None else None


def _render_manual_player_form(
    workspace: dict[str, Any], storage: FantasyWorkspaceStorage
) -> None:
    with st.popover("Aggiungi giocatore manualmente"):
        with st.form("manual_catalog_player"):
            name = st.text_input("Nome giocatore")
            team = st.text_input("Squadra")
            role = st.selectbox("Ruolo", list(ROLE_LABELS), format_func=lambda value: ROLE_LABELS[value])
            quote = st.number_input("Quotazione", min_value=0.0, max_value=1000.0, value=1.0)
            predicted_quote = st.number_input("Quotazione prevista", min_value=0.0, max_value=1000.0, value=1.0)
            col_goals, col_assists = st.columns(2)
            expected_goals = col_goals.number_input("Gol attesi", min_value=0.0, max_value=100.0, value=0.0)
            expected_assists = col_assists.number_input("Assist attesi", min_value=0.0, max_value=100.0, value=0.0)
            starter = st.slider("Probabilita titolare", 0, 100, 70)
            add_player = st.form_submit_button("Aggiungi", type="primary", use_container_width=True)
        if add_player:
            try:
                player = make_player(
                    name=name,
                    team=team,
                    role=role,
                    quote=quote,
                    predicted_quote=predicted_quote,
                    expected_goals=expected_goals,
                    expected_assists=expected_assists,
                    starter_probability=starter,
                )
            except ValueError as error:
                st.error(str(error))
            else:
                workspace["catalog"] = merge_catalog(workspace.get("catalog", []), [player])
                touch_workspace(workspace)
                _save_workspace(workspace, storage)
                st.rerun()


def _render_watchlist_control(
    catalog: list[dict[str, Any]],
    visible_ids: list[str],
    league: dict[str, Any],
    workspace: dict[str, Any],
    storage: FantasyWorkspaceStorage,
) -> None:
    if not visible_ids:
        return
    by_id = {player["id"]: player for player in catalog}
    selector, action = st.columns([2.4, 0.8])
    player_id = selector.selectbox(
        "Seleziona giocatore",
        visible_ids,
        format_func=lambda value: f"{by_id[value]['name']} · {by_id[value].get('team', '-')} · {by_id[value]['role']}",
        key="watchlist_player",
    )
    in_watchlist = player_id in league.get("watchlist", [])
    if action.button(
        "Rimuovi" if in_watchlist else "+ Osserva",
        use_container_width=True,
        key="toggle_watchlist",
    ):
        toggle_watchlist(league, player_id)
        touch_workspace(workspace)
        _save_workspace(workspace, storage)
        st.rerun()


def _render_auction(
    workspace: dict[str, Any], league: dict[str, Any], storage: FantasyWorkspaceStorage
) -> None:
    list_mode = league.get("game_mode") == GAME_MODE_LIST
    summary = roster_summary(league)
    _render_budget_metrics(summary)
    progress = summary["roster_size"] / max(summary["target_size"], 1)
    st.progress(min(progress, 1.0), text=f"Rosa completata al {progress:.0%}")
    _render_role_plan(league, summary)

    catalog = workspace.get("catalog", [])
    purchased_ids = {row.get("player_id") for row in league.get("purchases", [])}
    available = [player for player in catalog if player.get("id") not in purchased_ids]
    if available:
        st.markdown("#### Aggiungi dal listone" if list_mode else "#### Registra un acquisto")
        by_id = {player["id"]: player for player in available}
        player_column, price_column, button_column = st.columns([2.2, 0.75, 0.7])
        selected_id = player_column.selectbox(
            "Giocatore",
            list(by_id),
            format_func=lambda value: f"{by_id[value]['role']} · {by_id[value]['name']} · {by_id[value].get('team', '-')}",
            key=f"auction_player_{league['id']}",
        )
        selected_player = by_id[selected_id]
        default_price = max(float(selected_player.get("quote") or 1), 0.0)
        if list_mode:
            price_column.metric("Costo", f"{default_price:.0f}")
            price = default_price
        else:
            price = price_column.number_input(
                "Prezzo asta",
                min_value=0.0,
                max_value=float(max(summary["remaining_budget"], default_price, 1)),
                value=min(default_price, float(max(summary["remaining_budget"], 0))),
                step=1.0,
                key=f"auction_price_{league['id']}_{selected_id}",
            )
        if button_column.button(
            "Aggiungi" if list_mode else "Acquista", type="primary", use_container_width=True
        ):
            try:
                add_purchase(league, selected_player, price)
            except ValueError as error:
                st.error(str(error))
            else:
                touch_workspace(workspace)
                _save_workspace(workspace, storage)
                st.rerun()
    else:
        st.info("Non ci sono altri giocatori disponibili nel listone.")

    if not list_mode:
        _render_quick_purchase(workspace, league, storage)
    _render_roster_table(workspace, league, storage)


def _render_budget_metrics(summary: dict[str, Any]) -> None:
    spent, remaining, average, slots = st.columns(4)
    spent.metric("Spesi", f"{summary['spent']:.0f}")
    remaining.metric("Rimasti", f"{summary['remaining_budget']:.0f}")
    average.metric("Crediti per slot", f"{summary['credits_per_slot']:.1f}")
    slots.metric("Slot liberi", summary["remaining_slots"])


def _render_role_plan(league: dict[str, Any], summary: dict[str, Any]) -> None:
    cards = []
    slots = league.get("roster_slots", DEFAULT_ROSTER_SLOTS)
    for role, label in ROLE_LABELS.items():
        count = summary["role_counts"][role]
        target = int(slots.get(role, 0))
        status = "complete" if count >= target else "open"
        cards.append(
            f'<div class="fantasy-role-card {status}"><span>{role}</span>'
            f'<strong>{count}/{target}</strong><small>{escape(label)}</small></div>'
        )
    st.markdown(f'<div class="fantasy-role-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def _render_quick_purchase(
    workspace: dict[str, Any], league: dict[str, Any], storage: FantasyWorkspaceStorage
) -> None:
    with st.expander("Acquisto rapido di un giocatore non presente nel listone"):
        with st.form(f"quick_purchase_{league['id']}"):
            col_name, col_team, col_role, col_price = st.columns([1.5, 1, 0.65, 0.7])
            name = col_name.text_input("Nome")
            team = col_team.text_input("Squadra")
            role = col_role.selectbox("Ruolo", list(ROLE_LABELS))
            price = col_price.number_input("Prezzo", min_value=0.0, max_value=1000.0, value=1.0)
            submit = st.form_submit_button("Aggiungi alla rosa")
        if submit:
            try:
                player = make_player(name=name, team=team, role=role, quote=price)
                workspace["catalog"] = merge_catalog(workspace.get("catalog", []), [player])
                add_purchase(league, player, price)
            except ValueError as error:
                st.error(str(error))
            else:
                touch_workspace(workspace)
                _save_workspace(workspace, storage)
                st.rerun()


def _render_roster_table(
    workspace: dict[str, Any], league: dict[str, Any], storage: FantasyWorkspaceStorage
) -> None:
    catalog_by_id = {
        str(player.get("id")): player for player in workspace.get("catalog", [])
    }
    purchases = sorted(
        (
            {
                **catalog_by_id.get(str(row.get("player_id")), {}),
                **row,
            }
            for row in league.get("purchases", [])
        ),
        key=lambda row: ("PDCA".find(str(row.get("role", ""))), str(row.get("name", ""))),
    )
    if not purchases:
        return
    list_mode = league.get("game_mode") == GAME_MODE_LIST
    st.markdown("#### Rosa dal listone" if list_mode else "#### Acquisti")
    price_label = "Costo listone" if list_mode else "Prezzo asta"
    upcoming_matchday = season_next_matchday()
    news_items = _cached_fantasy_news()
    rows = [
        {
            "Ruolo": row.get("role"),
            "Giocatore": row.get("name"),
            "Squadra": row.get("team"),
            price_label: row.get("price"),
            "FM attesa": row.get("expected_fantasy_average"),
            "Gol attesi": row.get("expected_goals"),
            "Assist attesi": row.get("expected_assists"),
            f"Impiego G{upcoming_matchday}": player_availability(
                row,
                news_items,
                matchday=upcoming_matchday,
                next_matchday_number=upcoming_matchday,
            ).get("appearance_probability"),
        }
        for row in purchases
    ]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            f"Impiego G{upcoming_matchday}": st.column_config.ProgressColumn(
                "Prob. impiego",
                min_value=0,
                max_value=100,
                format="%.0f%%",
            )
        },
    )
    remove_column, action_column = st.columns([2.3, 0.7])
    selected_id = remove_column.selectbox(
        "Correggi un acquisto",
        [row["player_id"] for row in purchases],
        format_func=lambda value: next(row["name"] for row in purchases if row["player_id"] == value),
        key=f"remove_purchase_select_{league['id']}",
    )
    if action_column.button("Rimuovi", use_container_width=True, key=f"remove_purchase_{league['id']}"):
        remove_purchase(league, selected_id)
        touch_workspace(workspace)
        _save_workspace(workspace, storage)
        st.rerun()


def _render_what_if_simulator(
    league: dict[str, Any], catalog: list[dict[str, Any]]
) -> None:
    list_mode = league.get("game_mode") == GAME_MODE_LIST
    unavailable_ids = (
        {str(row.get("player_id")) for row in league.get("purchases", [])}
        if list_mode else auction_taken_player_ids(league)
    )
    available = sorted(
        (player for player in catalog if str(player.get("id")) not in unavailable_ids),
        key=lambda player: (
            _number_or_none(player.get("fantasy_score"), 0),
            _number_or_none(player.get("quote"), 0),
        ),
        reverse=True,
    )
    with st.expander("E se lo compro? · Simulatore senza rischi"):
        st.caption(
            "Prova un acquisto prima di salvarlo: budget, completezza e bonus attesi "
            "vengono ricalcolati, ma la rosa non cambia."
        )
        if not available:
            st.info("Non risultano giocatori disponibili da simulare.")
            return
        by_id = {str(player.get("id")): player for player in available}
        selector_column, price_column = st.columns([2.15, 0.85])
        selected_id = selector_column.selectbox(
            "Giocatore da simulare",
            list(by_id),
            format_func=lambda player_id: (
                f"{by_id[player_id].get('role')} · {by_id[player_id].get('name')} · "
                f"{by_id[player_id].get('team')}"
            ),
            key=f"what_if_player_{league['id']}",
        )
        player = by_id[selected_id]
        if list_mode:
            suggested_price = float(_number_or_none(player.get("quote"), 0) or 0)
        else:
            price_board = auction_price_board(league, catalog)
            suggested_price = float(
                price_board.get(selected_id, {}).get("strategic")
                or price_board.get(selected_id, {}).get("updated")
                or player.get("quote")
                or 1
            )
        price = price_column.number_input(
            "Costo ipotizzato",
            min_value=0.0,
            max_value=float(max(int(league.get("initial_budget") or 1), 1)),
            value=min(suggested_price, float(max(int(league.get("initial_budget") or 1), 1))),
            step=1.0,
            disabled=list_mode,
            key=f"what_if_price_{league['id']}_{selected_id}",
        )
        simulation = simulate_purchase(league, player, float(price))
        before, after = simulation["before"], simulation["after"]
        budget, size, goals, assists, fantasy_average = st.columns(5)
        budget.metric(
            "Crediti dopo",
            f"{after['remaining_budget']:.0f}",
            f"-{simulation['price']:.0f}",
            delta_color="inverse",
        )
        size.metric("Rosa", f"{after['roster_size']}", f"+{after['roster_size'] - before['roster_size']}")
        goals.metric("Gol attesi rosa", f"{after['goals']:.1f}", f"+{after['goals'] - before['goals']:.1f}")
        assists.metric("Assist attesi rosa", f"{after['assists']:.1f}", f"+{after['assists'] - before['assists']:.1f}")
        fantasy_average.metric(
            "Somma FM attese",
            f"{after['fantasy_average_sum']:.2f}",
            f"+{after['fantasy_average_sum'] - before['fantasy_average_sum']:.2f}",
        )
        tone = "ok" if simulation["valid"] and "positivo" in simulation["verdict"].lower() else "warn"
        details = (
            f"Valore stimato {simulation['value_score']:.2f} punti indice per credito."
            if simulation["valid"] else " · ".join(simulation["errors"])
        )
        st.markdown(
            f'<div class="fantasy-sim-verdict {tone}"><span>VERDETTO</span>'
            f'<strong>{escape(str(simulation["verdict"]))}</strong><small>{escape(details)}</small></div>',
            unsafe_allow_html=True,
        )


def _render_decision_center(
    workspace: dict[str, Any],
    league: dict[str, Any],
    storage: FantasyWorkspaceStorage,
) -> None:
    catalog = workspace.get("catalog", [])
    news_items = _cached_fantasy_news()
    alerts = build_roster_alerts(league, catalog, news_items)
    read_ids = {str(alert_id) for alert_id in league.get("read_alert_ids", [])}
    unread_count = sum(str(alert.get("id")) not in read_ids for alert in alerts)
    st.markdown(
        f'<section class="fantasy-decision-hero"><div><span>SaSa · MATCH INTELLIGENCE</span>'
        f'<strong>Decision Center</strong><small>Formazione, calendario, simulazioni e segnali della tua rosa in un unico posto.</small>'
        f'</div><aside><small>DA LEGGERE</small><b>{unread_count}</b></aside></section>',
        unsafe_allow_html=True,
    )
    if not league.get("purchases"):
        st.info("Aggiungi almeno un giocatore alla rosa per attivare il Decision Center.")
        return
    lineup_tab, calendar_tab, alert_tab = st.tabs(
        ["Assistente di giornata", "Calendario strategico", f"Avvisi · {unread_count}"]
    )
    with lineup_tab:
        _render_matchday_assistant(workspace, league, storage, catalog, news_items)
    with calendar_tab:
        _render_strategic_calendar(league, catalog)
    with alert_tab:
        _render_alert_center(workspace, league, storage, alerts, read_ids)


def _render_matchday_assistant(
    workspace: dict[str, Any],
    league: dict[str, Any],
    storage: FantasyWorkspaceStorage,
    catalog: list[dict[str, Any]],
    news_items: list[dict[str, Any]],
) -> None:
    upcoming_matchday = season_next_matchday()
    matchday = st.select_slider(
        "Giornata da preparare",
        options=list(range(1, 39)),
        value=upcoming_matchday,
        format_func=lambda value: (
            f"{value}ª giornata · {matchday_date(value).strftime('%d/%m/%Y')}"
            if matchday_date(value) else f"{value}ª giornata"
        ),
        key=f"decision_matchday_v22_{league['id']}",
    )
    recommendation = recommend_lineup(
        league,
        catalog,
        matchday=int(matchday),
        news_items=news_items,
        next_matchday_number=upcoming_matchday,
    )
    players = recommendation.get("players", [])
    if not players:
        st.info("La rosa non contiene ancora giocatori sufficienti per una proposta.")
        return
    goals_total = sum(float(_number_or_none(player.get("expected_goals"), 0) or 0) for player in players)
    assists_total = sum(float(_number_or_none(player.get("expected_assists"), 0) or 0) for player in players)
    fantasy_average_sum = sum(
        float(_number_or_none(player.get("expected_fantasy_average"), 0) or 0)
        for player in players
    )
    captain = recommendation.get("captain")
    formation_label = recommendation.get("formation") or "In costruzione"
    formation_metric, captain_metric, goals_metric, fm_metric = st.columns(4)
    formation_metric.metric("Modulo consigliato", formation_label)
    captain_metric.metric("Uomo bonus", str((captain or {}).get("name") or "—"))
    goals_metric.metric("Gol + assist attesi", f"{goals_total + assists_total:.1f}")
    fm_metric.metric("Somma FM attese", f"{fantasy_average_sum:.2f}")
    if not recommendation.get("complete"):
        st.warning(
            "La rosa non consente ancora un undici regolamentare: SaSa mostra i migliori "
            "giocatori disponibili e si aggiornera automaticamente."
        )
    st.markdown(
        f'<div class="fantasy-matchday-label"><span>XI CONSIGLIATO</span>'
        f'<strong>{escape(str(formation_label))} · Giornata {int(matchday)}</strong></div>',
        unsafe_allow_html=True,
    )
    role_labels = {"A": "Attacco", "C": "Centrocampo", "D": "Difesa", "P": "Porta"}
    role_rows = []
    captain_id = str((captain or {}).get("player_id") or "")
    for role in ("A", "C", "D", "P"):
        cards = []
        for player in (row for row in players if row.get("role") == role):
            fixture = player.get("decision_fixture") or {}
            difficulty = _number_or_none(fixture.get("difficulty"))
            tone = _fixture_tone(difficulty)
            venue = "vs" if fixture.get("venue") == "C" else "@"
            opponent = fixture.get("opponent") or "calendario n/d"
            crown = "<i>★ BONUS</i>" if str(player.get("player_id")) == captain_id else ""
            appearance_probability = int(
                _number_or_none(player.get("appearance_probability"), 0) or 0
            )
            availability_status = str(player.get("availability_status") or "model")
            availability_html = ""
            if int(matchday) == upcoming_matchday or player.get("availability_unavailable"):
                availability_html = (
                    f'<em class="availability {escape(availability_status)}">'
                    f'{escape(str(player.get("availability_label") or "Stima impiego"))} · '
                    f'{appearance_probability}%</em>'
                )
            cards.append(
                f'<div class="fantasy-decision-player role-{role.lower()} {tone}">'
                f'<span>{escape(role)} · {float(_number_or_none(player.get("decision_score"), 0) or 0):.0f}</span>'
                f'<strong>{escape(str(player.get("name") or ""))}</strong>'
                f'<small>{escape(str(player.get("team") or ""))} {venue} {escape(str(opponent))}'
                f'{" · D " + f"{difficulty:.1f}" if difficulty is not None else ""}</small>'
                f'{availability_html}{crown}</div>'
            )
        if cards:
            role_rows.append(
                f'<div class="fantasy-decision-line"><b>{role_labels[role]}</b>'
                f'<div>{"".join(cards)}</div></div>'
            )
    st.markdown(
        f'<section class="fantasy-decision-pitch">{"".join(role_rows)}</section>',
        unsafe_allow_html=True,
    )
    unavailable_players = [
        player for player in recommendation.get("all_players", [])
        if player.get("availability_unavailable")
    ]
    if unavailable_players:
        st.markdown("##### Indisponibili per questa giornata")
        for player in unavailable_players:
            unavailable_until = player.get("unavailable_until_matchday")
            duration = (
                f"fino alla G{int(unavailable_until)}"
                if unavailable_until else "rientro non ancora comunicato"
            )
            source = str(player.get("availability_source") or "Fonte pubblicata")
            url = str(player.get("availability_url") or "")
            source_markdown = f"[{source}]({url})" if url.startswith("http") else source
            st.warning(
                f"**{player.get('name')}** · {player.get('availability_label')} · "
                f"{duration} · {source_markdown}"
            )
    if int(matchday) == upcoming_matchday:
        st.markdown("##### Probabilità di impiego · tutta la rosa")
        st.caption(
            "Disponibile solo per la prossima giornata. SaSa combina titolarità, "
            "possibilità di subentro e notizie/probabili formazioni pubblicate."
        )
        availability_cards = []
        role_order = {"P": 0, "D": 1, "C": 2, "A": 3}
        all_players = sorted(
            recommendation.get("all_players", []),
            key=lambda player: (
                role_order.get(str(player.get("role") or ""), 9),
                -float(_number_or_none(player.get("appearance_probability"), 0) or 0),
                str(player.get("name") or ""),
            ),
        )
        for player in all_players:
            probability = int(_number_or_none(player.get("appearance_probability"), 0) or 0)
            if player.get("availability_unavailable"):
                tone = "out"
            elif probability >= 80:
                tone = "ready"
            elif probability >= 55:
                tone = "watch"
            else:
                tone = "low"
            source = escape(str(player.get("availability_source") or "Modello SaSa"))
            url = str(player.get("availability_url") or "")
            if player.get("availability_has_news") and url.startswith("http"):
                source = (
                    f'<a href="{escape(url, quote=True)}" target="_blank">{source} ↗</a>'
                )
            reason = escape(str(player.get("availability_reason") or ""))
            availability_cards.append(
                f'<article class="fantasy-appearance-card {tone}">'
                f'<header><span>{escape(str(player.get("role") or ""))} · '
                f'{escape(str(player.get("team") or ""))}</span><b>{probability}%</b></header>'
                f'<strong>{escape(str(player.get("name") or ""))}</strong>'
                f'<div><i style="width:{probability}%"></i></div>'
                f'<small>{escape(str(player.get("availability_label") or "Stima impiego"))} · '
                f'{source}</small><p>{reason}</p></article>'
            )
        st.markdown(
            f'<section class="fantasy-appearance-grid">{"".join(availability_cards)}</section>',
            unsafe_allow_html=True,
        )
    else:
        st.info(
            f"Le probabilità individuali sono mostrate solo sulla prossima giornata "
            f"(G{upcoming_matchday}), perché oltre quel turno non sarebbero attendibili."
        )
    bench = recommendation.get("bench", [])[:5]
    bench_column, reason_column = st.columns([1, 1.25])
    with bench_column:
        st.markdown("##### Prime alternative")
        if bench:
            for index, player in enumerate(bench, start=1):
                fixture = player.get("decision_fixture") or {}
                probability_text = ""
                if int(matchday) == upcoming_matchday:
                    probability_text = (
                        f" · {int(_number_or_none(player.get('appearance_probability'), 0) or 0)}% impiego"
                    )
                st.caption(
                    f"{index}. {player.get('name')} · {player.get('role')} · "
                    f"{fixture.get('venue', '–')} {fixture.get('opponent', 'calendario n/d')}"
                    f"{probability_text}"
                )
        else:
            st.caption("Nessuna alternativa disponibile.")
    with reason_column:
        st.markdown("##### Perche questa formazione")
        favorable = sorted(
            (
                player for player in players
                if (player.get("decision_fixture") or {}).get("difficulty") is not None
            ),
            key=lambda player: float((player.get("decision_fixture") or {}).get("difficulty") or 5),
        )[:3]
        st.caption(
            "SaSa combina fantamedia attesa, titolarita, bonus, affidabilita, "
            "difficolta dell'avversario e segnali pubblicati sulla disponibilita."
        )
        if favorable:
            st.caption(
                "Calendario favorevole: "
                + " · ".join(str(player.get("name")) for player in favorable)
            )
    if recommendation.get("complete") and recommendation.get("formation"):
        if st.button(
            "Usa questo undici come Top 11",
            type="primary",
            use_container_width=True,
            key=f"use_decision_xi_{league['id']}_{matchday}",
        ):
            try:
                set_preferred_xi(
                    league,
                    [str(player.get("player_id")) for player in players],
                    formation=str(recommendation["formation"]),
                )
            except ValueError as error:
                st.error(str(error))
            else:
                touch_workspace(workspace)
                _save_workspace(workspace, storage)
                st.rerun()


def _fixture_tone(difficulty: float | None) -> str:
    if difficulty is None:
        return "neutral"
    if difficulty <= 2.3:
        return "easy"
    if difficulty <= 3.6:
        return "medium"
    return "hard"


def _render_strategic_calendar(
    league: dict[str, Any], catalog: list[dict[str, Any]]
) -> None:
    upcoming_matchday = season_next_matchday()
    start_matchday = st.selectbox(
        "Parti dalla giornata",
        list(range(1, 39)),
        index=upcoming_matchday - 1,
        format_func=lambda value: (
            f"{value}ª giornata · {matchday_date(value).strftime('%d/%m/%Y')}"
            if matchday_date(value) else f"{value}ª giornata"
        ),
        key=f"calendar_start_v22_{league['id']}",
    )
    st.caption(
        "Verde = partita favorevole · ambra = equilibrata · rosso = impegnativa. "
        "La difficolta e calcolata sulla forza del listone e sul fattore casa/trasferta."
    )
    grouped: dict[str, list[str]] = {}
    for player in league.get("purchases", []):
        grouped.setdefault(str(player.get("team") or ""), []).append(str(player.get("name") or ""))
    rows = []
    for team, names in sorted(grouped.items()):
        outlook = fixture_outlook(team, catalog, start_matchday=int(start_matchday), limit=5)
        chips = []
        for fixture in outlook:
            difficulty = float(fixture.get("difficulty") or 3)
            tone = _fixture_tone(difficulty)
            venue = "vs" if fixture.get("venue") == "C" else "@"
            chips.append(
                f'<span class="{tone}"><small>G{fixture.get("matchday")}</small>'
                f'<strong>{venue} {escape(str(fixture.get("opponent") or ""))}</strong>'
                f'<b>{difficulty:.1f}</b></span>'
            )
        rows.append(
            f'<div class="fantasy-calendar-row"><div><strong>{escape(team)}</strong>'
            f'<small>{escape(" · ".join(names))}</small></div><section>{"".join(chips) or "<em>Calendario non disponibile</em>"}</section></div>'
        )
    st.markdown(
        f'<div class="fantasy-calendar-board">{"".join(rows)}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Fonte: [calendario ufficiale Lega Serie A · 38 giornate]({FIXTURE_SOURCE_URL}). "
        "La vista mostra la giornata selezionata e le quattro successive."
    )
    rotations = best_rotation_pairs(
        league, catalog, start_matchday=int(start_matchday), limit=5
    )
    if rotations:
        st.markdown("##### Rotazioni intelligenti")
        rotation_columns = st.columns(min(3, len(rotations)))
        for index, pair in enumerate(rotations[:3]):
            with rotation_columns[index % len(rotation_columns)]:
                st.markdown(
                    f'<div class="fantasy-rotation-card"><span>{escape(str(pair["role"]))} · COPPIA</span>'
                    f'<strong>{escape(str(pair["first"].get("name")))} + {escape(str(pair["second"].get("name")))}</strong>'
                    f'<small>Difficolta media della scelta migliore: {pair["average_difficulty"]:.2f}/5</small></div>',
                    unsafe_allow_html=True,
                )


def _render_alert_center(
    workspace: dict[str, Any],
    league: dict[str, Any],
    storage: FantasyWorkspaceStorage,
    alerts: list[dict[str, Any]],
    read_ids: set[str],
) -> None:
    unread = [alert for alert in alerts if str(alert.get("id")) not in read_ids]
    filter_column, action_column = st.columns([1.6, 0.8])
    only_unread = filter_column.toggle(
        "Mostra solo da leggere",
        value=True,
        key=f"only_unread_alerts_{league['id']}",
    )
    if action_column.button(
        "Segna tutto come letto",
        use_container_width=True,
        disabled=not unread,
        key=f"read_all_alerts_{league['id']}",
    ):
        league["read_alert_ids"] = [str(alert.get("id")) for alert in alerts]
        league["updated_at"] = utc_now()
        touch_workspace(workspace)
        _save_workspace(workspace, storage)
        st.rerun()
    visible = unread if only_unread else alerts
    if not visible:
        st.success("Nessuna nuova notizia pubblicata sulla tua rosa o watchlist.")
        return
    for alert in visible:
        alert_id = str(alert.get("id"))
        unread_class = " unread" if alert_id not in read_ids else ""
        severity = str(alert.get("severity") or "low")
        url = str(alert.get("url") or "")
        source_html = escape(str(alert.get("source") or "Analisi rosa"))
        if url.startswith("http"):
            source_html = f'<a href="{escape(url, quote=True)}" target="_blank">{source_html} ↗</a>'
        evidence_title = str(alert.get("evidence_title") or "").strip()
        evidence_html = (
            f'<div class="fantasy-alert-evidence"><em>NOTIZIA COLLEGATA</em>'
            f'<b>{escape(evidence_title)}</b></div>'
            if evidence_title else
            '<div class="fantasy-alert-evidence no-news"><em>NESSUNA NOTIZIA VERIFICATA</em>'
            '<b>Segnale generato dagli indicatori statistici, non da una news.</b></div>'
            if severity in {"high", "medium"} and "Rischio fisico" in str(alert.get("title"))
            else ""
        )
        st.markdown(
            f'<article class="fantasy-alert-card {severity}{unread_class}"><span></span><div>'
            f'<small>{"NUOVO · " if unread_class else ""}{source_html}</small>'
            f'<strong>{escape(str(alert.get("title") or ""))}</strong>'
            f'{evidence_html}<p><b>MOTIVO</b>{escape(str(alert.get("message") or ""))}</p>'
            f'</div></article>',
            unsafe_allow_html=True,
        )
    st.caption(
        "Il Centro notifiche non genera avvisi da indici statistici: mostra esclusivamente "
        "notizie realmente pubblicate e collegate alla rosa o alla watchlist. "
        "Aggiornamento ogni 15 minuti."
    )


def _render_my_squad(
    workspace: dict[str, Any],
    league: dict[str, Any],
    storage: FantasyWorkspaceStorage,
    settings: Settings,
) -> None:
    summary = roster_summary(league)
    if not league.get("purchases"):
        st.info("Aggiungi i giocatori da Studia il listone: qui compariranno rosa, analisi e formazione.")
        return

    _render_top_xi_editor(workspace, league, storage)
    xi_summary = top_xi_summary(league)
    goals, assists, fantasy_average = st.columns(3)
    goals.metric(
        "Gol totali attesi · Top 11",
        _format_stat(xi_summary["expected_goals_total"], 1),
    )
    assists.metric(
        "Assist totali attesi · Top 11",
        _format_stat(xi_summary["expected_assists_total"], 1),
    )
    fantasy_average.metric(
        "Somma FM attese · Top 11",
        _format_stat(xi_summary["expected_fantasy_average_sum"], 2),
    )
    if league.get("captain_enabled"):
        _render_captain_control(workspace, league, storage)
    with st.expander(f"Rosa completa · {len(league.get('purchases', []))} giocatori"):
        _render_roster_table(workspace, league, storage)
    if league.get("game_mode") == GAME_MODE_LIST and summary["complete"]:
        _render_swap_lab(league, workspace.get("catalog", []))
    _render_sasa_analysis(workspace, league, storage, settings, summary, xi_summary)


def _render_top_xi_editor(
    workspace: dict[str, Any],
    league: dict[str, Any],
    storage: FantasyWorkspaceStorage,
) -> None:
    catalog_by_id = {
        str(player.get("id")): player for player in workspace.get("catalog", [])
    }
    purchases = [
        {
            **catalog_by_id.get(str(row.get("player_id")), {}),
            **row,
        }
        for row in league.get("purchases", [])
    ]
    by_id = {str(row.get("player_id")): row for row in purchases}
    upcoming_matchday = season_next_matchday()
    news_items = _cached_fantasy_news()
    availability_by_id = {
        str(row.get("player_id")): player_availability(
            row,
            news_items,
            matchday=upcoming_matchday,
            next_matchday_number=upcoming_matchday,
        )
        for row in purchases
    }
    current = top_xi_summary(league)
    mode = "personalizzata" if league.get("preferred_xi_customized") else "automatica"
    st.markdown(
        f'<section class="fantasy-xi-hero"><div><span>TOP 11 · {mode.upper()}</span>'
        f'<strong>Disegna la tua formazione sul campo</strong>'
        f'<small>Scegli il modulo e ogni posizione. Di default inserisco i giocatori piu costosi compatibili.</small>'
        f'</div><b>{current["count"]}/11</b></section>',
        unsafe_allow_html=True,
    )
    formation_options = list(FORMATIONS)
    default_formation = top_xi_formation(league)
    formation = st.selectbox(
        "Modulo",
        formation_options,
        index=formation_options.index(default_formation),
        key=f"preferred_formation_{league['id']}",
    )
    st.caption(
        f"Probabilità di impiego G{upcoming_matchday}: stima individuale da titolarità, "
        "presenze attese e precedenti, affidabilità, rischio, ruolo e notizie ufficiali."
    )
    saved_formation = str(league.get("preferred_formation") or default_formation)
    if league.get("preferred_xi_customized") and formation == saved_formation:
        default_players = current["players"]
    else:
        default_players = top_xi_for_formation(league, formation)
    defaults_by_role = {
        role: [str(row.get("player_id")) for row in default_players if row.get("role") == role]
        for role in ROLE_LABELS
    }
    available_by_role = {
        role: sorted(
            (str(row.get("player_id")) for row in purchases if row.get("role") == role),
            key=lambda player_id: (
                float(by_id[player_id].get("price") or 0),
                float(by_id[player_id].get("fantasy_score") or 0),
            ),
            reverse=True,
        )
        for role in ROLE_LABELS
    }
    selected_ids: list[str] = []
    pitch_version = (
        f"{len(purchases)}_{int(bool(league.get('preferred_xi_customized')))}_{formation}"
    )
    role_titles = {"A": "ATTACCO", "C": "CENTROCAMPO", "D": "DIFESA", "P": "PORTA"}
    with st.container(key="top_xi_pitch"):
        st.markdown(
            f'<div class="fantasy-pitch-title"><div><span>STARTING XI</span>'
            f'<small>{escape(str(league.get("name", "")))}</small></div>'
            f'<strong>{escape(formation)}</strong></div>',
            unsafe_allow_html=True,
        )
        for role in ("A", "C", "D", "P"):
            required = int(FORMATIONS[formation].get(role, 0))
            st.markdown(
                f'<div class="fantasy-pitch-role role-{role.lower()}">{role_titles[role]}</div>',
                unsafe_allow_html=True,
            )
            slot_columns = _pitch_slot_columns(required)
            for slot_index, column in enumerate(slot_columns):
                with column:
                    default_id = (
                        defaults_by_role[role][slot_index]
                        if slot_index < len(defaults_by_role[role]) else None
                    )
                    options = [
                        None,
                        *[
                            player_id
                            for player_id in available_by_role[role]
                            if player_id not in selected_ids
                        ],
                    ]
                    if default_id not in options:
                        default_id = None
                    selected_id = st.selectbox(
                        f"{role}{slot_index + 1}",
                        options,
                        index=options.index(default_id),
                        format_func=lambda player_id, slot=f"{role}{slot_index + 1}": (
                            f"Scegli {slot}" if player_id is None else
                            f"{by_id[player_id].get('name')} · {by_id[player_id].get('team')}"
                        ),
                        label_visibility="collapsed",
                        key=(
                            f"pitch_player_{league['id']}_{pitch_version}_"
                            f"{role}_{slot_index}"
                        ),
                    )
                    if selected_id is not None:
                        selected_ids.append(selected_id)
                        st.markdown(
                            _lineup_player_card(
                                by_id[selected_id],
                                f"{role}{slot_index + 1}",
                                availability=availability_by_id.get(selected_id),
                                matchday=upcoming_matchday,
                            ),
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f'<div class="fantasy-lineup-card empty role-{role.lower()}">'
                            f'<span>{role}{slot_index + 1}</span><strong>POSTO LIBERO</strong></div>',
                            unsafe_allow_html=True,
                        )
        selected_cost = sum(float(by_id[player_id].get("price") or 0) for player_id in selected_ids)
        st.markdown(
            f'<div class="fantasy-pitch-footer"><span>XI LAB · {len(selected_ids)}/11</span>'
            f'<strong>{selected_cost:.0f} CREDITI IN CAMPO</strong></div>',
            unsafe_allow_html=True,
        )
    save_column, reset_column = st.columns([1.35, 0.85])
    selection_complete = len(selected_ids) == 11 and len(set(selected_ids)) == 11
    if save_column.button(
        "Salva la mia Top 11",
        type="primary",
        use_container_width=True,
        disabled=not selection_complete,
        key=f"save_preferred_xi_{league['id']}",
    ):
        try:
            set_preferred_xi(league, selected_ids, formation=formation)
        except ValueError as error:
            st.error(str(error))
        else:
            touch_workspace(workspace)
            _save_workspace(workspace, storage)
            st.rerun()
    if reset_column.button(
        "Ripristina i piu costosi",
        use_container_width=True,
        disabled=not league.get("preferred_xi_customized"),
        key=f"reset_preferred_xi_{league['id']}",
    ):
        reset_preferred_xi(league, formation=formation)
        touch_workspace(workspace)
        _save_workspace(workspace, storage)
        st.rerun()
    if not selection_complete:
        missing = 11 - len(set(selected_ids))
        st.warning(f"Completa il campo: mancano {missing} giocatori alla Top 11.")


def _lineup_player_card(
    player: dict[str, Any],
    position: str,
    *,
    availability: dict[str, Any] | None = None,
    matchday: int | None = None,
) -> str:
    name = str(player.get("name") or "Giocatore")
    parts = [part for part in name.replace(".", " ").split() if part]
    initials = "".join(part[0] for part in parts[:2]).upper() or "XI"
    role = str(player.get("role") or "").lower()
    fantasy_average = _format_stat(player.get("expected_fantasy_average"), 2)
    appearance = int(
        _number_or_none((availability or {}).get("appearance_probability"), 0) or 0
    )
    tone = (
        "out" if (availability or {}).get("availability_unavailable")
        else "ready" if appearance >= 80
        else "watch" if appearance >= 55
        else "low"
    )
    reason = escape(
        str((availability or {}).get("availability_reason") or ""), quote=True
    )
    appearance_badge = (
        f'<span class="fantasy-xi-appearance {tone}" title="{reason}">'
        f'G{int(matchday or 0)} · {appearance}%</span>'
        if availability else ""
    )
    return (
        f'<div class="fantasy-lineup-card role-{role}">'
        f'<div class="fantasy-lineup-shirt"><i>{escape(initials)}</i><span>{escape(position)}</span></div>'
        f'<div class="fantasy-lineup-copy"><small>{escape(str(player.get("team") or "—"))}</small>'
        f'<strong>{escape(name)}</strong><div><span>Q {float(player.get("price") or 0):.0f}</span>'
        f'<span>FM {fantasy_average}</span>{appearance_badge}</div></div></div>'
    )


def _pitch_slot_columns(count: int) -> list[Any]:
    side_space = {1: 2.2, 2: 1.15, 3: 0.58, 4: 0.24, 5: 0.08}.get(count, 0.08)
    columns = st.columns([side_space, *([1.0] * count), side_space], gap="small")
    return list(columns[1:-1])


def _render_top_xi_table(summary: dict[str, Any]) -> None:
    players = summary.get("players", [])
    if not players:
        return
    rows = [
        {
            "#": index,
            "Ruolo": row.get("role"),
            "Giocatore": row.get("name"),
            "Squadra": row.get("team"),
            "Costo": row.get("price"),
            "Gol attesi": row.get("expected_goals"),
            "Assist attesi": row.get("expected_assists"),
            "FM attesa": row.get("expected_fantasy_average"),
        }
        for index, row in enumerate(players, start=1)
    ]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "#": st.column_config.NumberColumn(width="small"),
            "Ruolo": st.column_config.TextColumn(width="small"),
            "Giocatore": st.column_config.TextColumn(width="large"),
            "Squadra": st.column_config.TextColumn(width="small"),
            "Costo": st.column_config.NumberColumn(format="%.0f", width="small"),
            "Gol attesi": st.column_config.NumberColumn(format="%.2f", width="small"),
            "Assist attesi": st.column_config.NumberColumn(format="%.2f", width="small"),
            "FM attesa": st.column_config.NumberColumn(format="%.2f", width="small"),
        },
    )


def _render_squad_insights(league: dict[str, Any], summary: dict[str, Any]) -> None:
    missing_labels = [
        f"{count} {ROLE_LABELS[role].lower()}" for role, count in summary["missing"].items() if count
    ]
    items = []
    if summary["complete"]:
        items.append(("ok", "Rosa completa", "Hai coperto tutti gli slot previsti."))
    else:
        items.append(("warn", "Copertura da completare", ", ".join(missing_labels)))
    if league.get("modifier_enabled"):
        if summary["modifier_ready"]:
            items.append(("ok", "Modificatore attivabile", "Hai almeno un portiere e quattro difensori."))
        else:
            items.append(("warn", "Modificatore non pronto", "Servono un portiere e almeno quattro difensori."))
    if summary["remaining_slots"]:
        items.append(
            (
                "info",
                "Margine d'asta",
                f"Puoi spendere in media {summary['credits_per_slot']:.1f} crediti per ogni slot rimasto.",
            )
        )
    cards = [
        f'<div class="fantasy-insight {kind}"><strong>{escape(title)}</strong><span>{escape(text)}</span></div>'
        for kind, title, text in items
    ]
    st.markdown(f'<div class="fantasy-insights">{"".join(cards)}</div>', unsafe_allow_html=True)


def _render_captain_control(
    workspace: dict[str, Any], league: dict[str, Any], storage: FantasyWorkspaceStorage
) -> None:
    purchases = league.get("purchases", [])
    ids = [row["player_id"] for row in purchases]
    current = league.get("captain_player_id")
    index = ids.index(current) + 1 if current in ids else 0
    selector, action = st.columns([2.4, 0.8])
    selected = selector.selectbox(
        "Capitano",
        [None, *ids],
        index=index,
        format_func=lambda value: "Non assegnato" if value is None else next(
            row["name"] for row in purchases if row["player_id"] == value
        ),
        key=f"captain_{league['id']}",
    )
    if action.button("Salva capitano", use_container_width=True, key=f"save_captain_{league['id']}"):
        try:
            set_captain(league, selected)
        except ValueError as error:
            st.error(str(error))
        else:
            touch_workspace(workspace)
            _save_workspace(workspace, storage)
            st.rerun()


def _render_lineup(lineup: dict[str, Any], captain_player_id: str | None = None) -> None:
    st.markdown(f"#### Formazione consigliata · {lineup['formation']}")
    role_lines = []
    for role in ("A", "C", "D", "P"):
        names = " · ".join(
            escape(str(player.get("name", ""))) + (" ©" if player.get("player_id") == captain_player_id else "")
            for player in lineup["players"][role]
        )
        role_lines.append(
            f'<div class="fantasy-line"><span>{role}</span><div>{names}</div></div>'
        )
    st.markdown(f'<div class="fantasy-pitch">{"".join(role_lines)}</div>', unsafe_allow_html=True)


def _render_swap_lab(league: dict[str, Any], catalog: list[dict[str, Any]]) -> None:
    analysis = list_trade_analysis(league, catalog, limit=5)
    weak_names = " · ".join(
        str(row.get("name") or "") for row in analysis.get("weakest", [])
    )
    st.markdown(
        f'<section class="fantasy-swap-hero"><div><span>SASA · SWAP LAB</span>'
        f'<strong>Upgrade a somma zero</strong><small>Ho analizzato tutti i '
        f'{analysis.get("evaluated_players", 0)} giocatori della rosa e il listone completo.</small></div>'
        f'<b>{len(analysis.get("trades", []))}</b></section>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Ogni proposta mantiene gli stessi ruoli, crediti in uscita = crediti in entrata "
        f"e spesa totale entro {analysis.get('budget', 0):.0f}. "
        + (f"Profili piu migliorabili: {weak_names}." if weak_names else "")
    )
    trades = analysis.get("trades", [])
    if not trades:
        st.info(str(analysis.get("reason") or "Nessun cambio migliorativo trovato."))
        return
    for index, trade in enumerate(trades, start=1):
        outgoing = "".join(_swap_player_chip(row, "out") for row in trade["outgoing"])
        incoming = "".join(_swap_player_chip(row, "in") for row in trade["incoming"])
        deltas = trade["deltas"]
        st.markdown(
            f'<article class="fantasy-swap-card"><header><span>PROPOSTA {index}</span>'
            f'<b>+{trade["improvement"]:.1f} UPGRADE SCORE</b></header>'
            f'<div class="fantasy-swap-flow"><section><small>FUORI</small>{outgoing}</section>'
            f'<div class="fantasy-swap-arrow"><strong>→</strong>'
            f'<span>{trade["outgoing_total"]:.0f} = {trade["incoming_total"]:.0f} CR</span></div>'
            f'<section><small>DENTRO</small>{incoming}</section></div>'
            f'<div class="fantasy-swap-deltas">'
            f'<span>Gol {deltas["goals"]:+.1f}</span>'
            f'<span>Assist {deltas["assists"]:+.1f}</span>'
            f'<span>Somma FM {deltas["fantasy_average"]:+.2f}</span>'
            f'<span>Rosa {trade["projected_spent"]:.0f}/{analysis["budget"]:.0f} CR</span></div>'
            f'<p>{escape(str(trade["motivation"]))}</p></article>',
            unsafe_allow_html=True,
        )


def _swap_player_chip(player: dict[str, Any], direction: str) -> str:
    role = escape(str(player.get("role") or ""))
    name = escape(str(player.get("name") or ""))
    team = escape(str(player.get("team") or ""))
    quote = player.get("price") if direction == "out" else player.get("quote")
    return (
        f'<div class="fantasy-swap-player {direction}"><span>{role}</span>'
        f'<div><strong>{name}</strong><small>{team} · Q {float(quote or 0):.0f}</small></div></div>'
    )


def _render_sasa_analysis(
    workspace: dict[str, Any],
    league: dict[str, Any],
    storage: FantasyWorkspaceStorage,
    settings: Settings,
    summary: dict[str, Any],
    xi_summary: dict[str, Any],
) -> None:
    st.markdown("#### SaSa · Il tuo analista di fantacalcio")
    st.caption(
        "SaSa analizza ogni giocatore della rosa e usa la Top 11 come riferimento tattico."
    )
    if st.button(
        "Chiedi l'analisi a SaSa",
        type="primary",
        disabled=not settings.has_gemini,
        key=f"sasa_ai_{league['id']}",
    ):
        prompt = _sasa_analysis_prompt(league, summary, xi_summary)
        try:
            with st.spinner("SaSa sta studiando tutti i giocatori della rosa..."):
                analysis = GeminiClient(settings).generate_text(prompt).strip()
        except Exception as error:
            st.error(f"Analisi non disponibile: {error}")
        else:
            if analysis:
                league["sasa_analysis"] = analysis
                league["sasa_analysis_version"] = SASA_ANALYSIS_VERSION
                league["updated_at"] = utc_now()
                touch_workspace(workspace)
                _save_workspace(workspace, storage)
                st.rerun()
    if not settings.has_gemini:
        st.info("Configura GEMINI_API_KEY per attivare SaSa.")
    analysis_is_current = (
        league.get("sasa_analysis")
        and int(league.get("sasa_analysis_version") or 0) == SASA_ANALYSIS_VERSION
    )
    if league.get("sasa_analysis") and not analysis_is_current:
        st.info("SaSa e stato aggiornato: avvia una nuova analisi per includere tutta la rosa.")
    if analysis_is_current:
        with st.container(border=True):
            st.markdown(league["sasa_analysis"])


def _sasa_analysis_prompt(
    league: dict[str, Any],
    summary: dict[str, Any],
    xi_summary: dict[str, Any],
) -> str:
    top_xi_ids = set(xi_summary.get("player_ids", []))
    roster_lines = []
    for row in league.get("purchases", []):
        status = "TOP 11" if str(row.get("player_id")) in top_xi_ids else "PANCHINA"
        roster_lines.append(
            " | ".join(
                [
                    status,
                    str(row.get("role", "")),
                    str(row.get("name", "")),
                    str(row.get("team", "")),
                    f"costo {row.get('price', 0)}",
                    f"gol attesi {row.get('expected_goals')}",
                    f"assist attesi {row.get('expected_assists')}",
                    f"fantamedia attesa {row.get('expected_fantasy_average')}",
                    f"titolarita {row.get('starter_probability')}",
                ]
            )
        )
    top_xi_lines = []
    for row in xi_summary.get("players", []):
        top_xi_lines.append(
            " | ".join(
                [
                    str(row.get("role", "")),
                    str(row.get("name", "")),
                    str(row.get("team", "")),
                    f"costo {row.get('price', 0)}",
                    f"gol attesi {row.get('expected_goals')}",
                    f"assist attesi {row.get('expected_assists')}",
                    f"fantamedia attesa {row.get('expected_fantasy_average')}",
                ]
            )
        )
    list_mode = league.get("game_mode") == GAME_MODE_LIST
    participants = "non previsto (modalita listone)" if list_mode else league.get("participants")
    captain_id = league.get("captain_player_id")
    captain_name = next(
        (row.get("name") for row in league.get("purchases", []) if row.get("player_id") == captain_id),
        "non assegnato",
    )
    return f"""
Ti chiami SaSa. Sei un assistente IA specializzato esclusivamente nel fantacalcio Classic italiano.
Analizza in italiano questa squadra senza inventare dati mancanti e distingui sempre la Top 11 dal resto della rosa.
Fanta: {league.get('name')} - stagione {league.get('season')} - modalita {'listone' if list_mode else 'asta'} - partecipanti {participants}.
Budget iniziale: {league.get('initial_budget')}; spesi: {summary['spent']}; rimasti: {summary['remaining_budget']}.
Capitano: {'regola attiva, ' + str(captain_name) if league.get('captain_enabled') else 'regola non attiva'}.
Composizione rosa prevista: {league.get('roster_slots')}.
Slot mancanti: {summary['missing']}.
Top 11 selezionata ({xi_summary.get('count', 0)}/11):
{chr(10).join(top_xi_lines) or 'non ancora disponibile'}
Totali Top 11: gol attesi {xi_summary.get('expected_goals_total')}; assist attesi {xi_summary.get('expected_assists_total')}; somma fantamedie attese {xi_summary.get('expected_fantasy_average_sum')}.

Rosa completa ({len(league.get('purchases', []))} giocatori; TOP 11 o PANCHINA indicato per ogni riga):
{chr(10).join(roster_lines)}

ISTRUZIONE OBBLIGATORIA: l'oggetto principale e l'intera rosa, non soltanto la Top 11. Considera e cita tutti i {len(league.get('purchases', []))} giocatori senza ometterne nessuno. Usa la Top 11 come riferimento per gerarchie, equilibrio e possibili sostituzioni.

Rispondi con queste sezioni:
1. Voto della rosa completa su 10.
2. Analisi giocatore per giocatore: una tabella con una riga per ogni calciatore, stato TOP 11/PANCHINA, giudizio sintetico e utilita prevista.
3. Analisi della Top 11: bonus attesi, equilibrio e punti deboli.
4. Panchina e profondita: coperture, rischi di titolarita e alternative alla Top 11.
5. Cambi consigliati nella Top 11 e priorita per i prossimi acquisti.
Sii concreto, non inventare dati e verifica prima di concludere che ogni nome della rosa sia stato citato almeno una volta.
""".strip()


def _save_workspace(workspace: dict[str, Any], storage: FantasyWorkspaceStorage) -> None:
    st.session_state[WORKSPACE_SESSION_KEY] = workspace
    st.session_state["fantasy_remote_save_attempted"] = storage.remote_available
    st.session_state["fantasy_remote_synced"] = storage.save(workspace)
    st.session_state["fantasy_remote_error"] = getattr(storage, "last_remote_error", "")


def _render_sync_status(storage: FantasyWorkspaceStorage) -> None:
    if storage.remote_available:
        synced = st.session_state.get("fantasy_remote_synced", False)
        attempted = st.session_state.get("fantasy_remote_save_attempted", False)
        if synced:
            st.caption("● Dati sincronizzati su Supabase")
        elif attempted:
            remote_error = str(
                st.session_state.get("fantasy_remote_error")
                or getattr(storage, "last_remote_error", "")
                or ""
            )
            detail = f" Motivo: {remote_error}" if remote_error else ""
            st.warning(
                "Salvataggio cloud non riuscito: i dati potrebbero andare persi al riavvio."
                + detail
            )
        else:
            st.caption("● Supabase collegato · salvataggio al primo aggiornamento")
    else:
        st.warning(
            "Persistenza cloud non configurata: su Streamlit i dati locali possono sparire dopo "
            "un riavvio. Configura SUPABASE_URL e SUPABASE_ANON_KEY nei secrets dell'app."
        )

def render_fantasy_styles() -> None:
    st.markdown(
        """
        <style>
        .fantasy-eyebrow { margin:0 0 .4rem; color:#19e6b0; font-size:.74rem; font-weight:900; letter-spacing:.1em; }
        .fantasy-empty { padding:2.2rem; border:1px solid rgba(25,230,176,.28); border-radius:14px; background:radial-gradient(circle at 85% 20%,rgba(25,230,176,.18),transparent 28%),linear-gradient(135deg,rgba(18,27,27,.98),rgba(8,10,11,.96)); text-align:center; }
        .fantasy-empty h2,.fantasy-league-hero h2 { margin:.1rem 0 .35rem; color:#f4fbf7; }
        .fantasy-empty p { max-width:650px; margin:.35rem auto; color:#aebbb6; }
        .fantasy-empty-icon { width:56px; height:56px; margin:0 auto .8rem; display:grid; place-items:center; border:1px solid #19e6b0; border-radius:16px; color:#08110e; background:#19e6b0; font-size:1.5rem; font-weight:950; box-shadow:0 0 35px rgba(25,230,176,.25); }
        .fantasy-league-hero { position:relative; display:grid; grid-template-columns:1fr auto auto; gap:1rem; align-items:center; margin:.65rem 0 1rem; padding:1rem 1.15rem; overflow:hidden; border:1px solid rgba(25,230,176,.28); border-radius:12px; background:linear-gradient(125deg,rgba(25,230,176,.12),rgba(255,176,32,.05) 55%,rgba(244,83,138,.09)),#0d1112; }
        .fantasy-league-hero p { margin:0; color:#9caaa5; }
        .fantasy-ring { --progress:0deg; width:62px; aspect-ratio:1; display:grid; place-items:center; border-radius:50%; background:conic-gradient(#19e6b0 var(--progress),rgba(255,255,255,.08) 0); position:relative; }
        .fantasy-ring:after { content:""; position:absolute; inset:6px; border-radius:50%; background:#0c1111; }
        .fantasy-ring span { position:relative; z-index:1; color:#f4fbf7; font-size:.78rem; font-weight:900; }
        .fantasy-mode-stack { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:.35rem; }
        .fantasy-mode-chip { padding:.55rem .7rem; border:1px solid rgba(255,176,32,.4); border-radius:8px; color:#ffe0a0; background:rgba(255,176,32,.1); font-size:.75rem; font-weight:900; }
        .fantasy-source-card { display:grid; grid-template-columns:1fr auto; gap:1rem; align-items:center; margin:.85rem 0 .25rem; padding:.85rem 1rem; border:1px solid rgba(25,230,176,.28); border-radius:10px; background:linear-gradient(120deg,rgba(25,230,176,.1),rgba(244,251,247,.025)); }
        .fantasy-source-card>div { display:flex; flex-direction:column; gap:.15rem; }
        .fantasy-source-card>div:last-child { text-align:right; }
        .fantasy-source-card span { width:fit-content; color:#07100d; background:#19e6b0; border-radius:999px; padding:.15rem .45rem; font-size:.62rem; font-weight:950; }
        .fantasy-source-card strong,.fantasy-source-card b { color:#f4fbf7; }
        .fantasy-source-card b { font-size:1.35rem; }
        .fantasy-source-card small { color:#95a39e; }
        .fantasy-table-heading { display:flex; justify-content:space-between; align-items:center; margin:1rem 0 .45rem; padding:.75rem .9rem; border:1px solid rgba(244,251,247,.1); border-radius:10px 10px 4px 4px; background:linear-gradient(110deg,rgba(25,230,176,.09),rgba(255,176,32,.035)); }
        .fantasy-table-heading>div { display:flex; flex-direction:column; gap:.15rem; }
        .fantasy-table-heading strong { color:#f4fbf7; font-size:1rem; }
        .fantasy-table-heading span { color:#899791; font-size:.78rem; }
        .fantasy-table-heading b { min-width:42px; text-align:center; color:#07100d; background:#19e6b0; border-radius:999px; padding:.32rem .55rem; }
        .fantasy-selection-bar { display:flex; justify-content:space-between; align-items:center; gap:1rem; margin:.55rem 0; padding:.75rem .9rem; border:1px solid rgba(25,230,176,.3); border-radius:10px; background:linear-gradient(110deg,rgba(25,230,176,.12),rgba(98,216,255,.05)); }
        .fantasy-selection-bar>div { display:flex; flex-direction:column; gap:.1rem; }
        .fantasy-selection-bar strong,.fantasy-selection-bar b { color:#f4fbf7; }
        .fantasy-selection-bar span { color:#95a39e; font-size:.78rem; }
        .fantasy-advisor-heading { display:flex; flex-direction:column; gap:.15rem; margin:1rem 0 .55rem; padding:.8rem .95rem; border-left:3px solid #ffb020; border-radius:0 10px 10px 0; background:linear-gradient(90deg,rgba(255,176,32,.12),transparent); }
        .fantasy-advisor-heading span { color:#ffcf72; font-size:.62rem; font-weight:950; letter-spacing:.1em; }
        .fantasy-advisor-heading strong { color:#f4fbf7; font-size:1.05rem; }
        .fantasy-xi-hero { display:flex; justify-content:space-between; align-items:center; gap:1rem; margin:.25rem 0 .8rem; padding:1rem 1.1rem; border:1px solid rgba(98,216,255,.28); border-radius:13px; background:radial-gradient(circle at 92% 15%,rgba(98,216,255,.18),transparent 30%),linear-gradient(120deg,rgba(25,230,176,.1),rgba(8,10,11,.78)); }
        .fantasy-xi-hero>div { display:flex; flex-direction:column; gap:.18rem; }
        .fantasy-xi-hero span { color:#62d8ff; font-size:.65rem; font-weight:950; letter-spacing:.1em; }
        .fantasy-xi-hero strong { color:#f4fbf7; font-size:1.12rem; }
        .fantasy-xi-hero small { color:#95a39e; }
        .fantasy-xi-hero b { min-width:66px; height:66px; display:grid; place-items:center; border:1px solid rgba(98,216,255,.55); border-radius:50%; color:#07100d; background:#62d8ff; font-size:1.08rem; box-shadow:0 0 30px rgba(98,216,255,.18); }
        .st-key-top_xi_pitch { position:relative; isolation:isolate; overflow:hidden; margin:.75rem 0 1rem; padding:1rem 1.1rem 1.35rem; border:1px solid rgba(94,255,178,.45); border-radius:18px; background:radial-gradient(circle at 50% 50%,transparent 0 66px,rgba(225,255,240,.2) 67px 69px,transparent 70px),linear-gradient(to bottom,transparent 49.7%,rgba(225,255,240,.22) 49.8% 50.2%,transparent 50.3%),repeating-linear-gradient(90deg,rgba(10,74,53,.94) 0 12.5%,rgba(12,88,62,.94) 12.5% 25%),linear-gradient(145deg,#07533a,#092f26); box-shadow:inset 0 0 70px rgba(0,0,0,.34),0 18px 45px rgba(0,0,0,.22); }
        .st-key-top_xi_pitch:before { content:""; position:absolute; z-index:-1; inset:1.2rem; border:2px solid rgba(225,255,240,.2); border-radius:4px; pointer-events:none; }
        .st-key-top_xi_pitch:after { content:""; position:absolute; z-index:-1; left:36%; right:36%; bottom:1.2rem; height:13%; border:2px solid rgba(225,255,240,.18); border-bottom:0; pointer-events:none; }
        .fantasy-pitch-title { display:flex; justify-content:space-between; align-items:center; margin-bottom:.35rem; padding:.35rem .5rem; border-radius:8px; background:rgba(3,25,18,.48); }
        .fantasy-pitch-title span { color:#a8c6ba; font-size:.62rem; font-weight:950; letter-spacing:.12em; }
        .fantasy-pitch-title strong { color:#f4fbf7; font-size:1rem; }
        .fantasy-pitch-role { width:fit-content; margin:.55rem auto .12rem; padding:.15rem .48rem; border-radius:999px; color:#07100d; background:#19e6b0; font-size:.58rem; font-weight:950; letter-spacing:.08em; box-shadow:0 4px 16px rgba(0,0,0,.18); }
        .fantasy-pitch-role.role-a { background:#f4538a; }
        .fantasy-pitch-role.role-c { background:#62d8ff; }
        .fantasy-pitch-role.role-d { background:#19e6b0; }
        .fantasy-pitch-role.role-p { background:#ffb020; }
        .st-key-top_xi_pitch div[data-testid="stCaptionContainer"] { text-align:center; }
        .st-key-top_xi_pitch div[data-testid="stCaptionContainer"] p { color:#d9eee5; font-size:.62rem; font-weight:900; }
        .st-key-top_xi_pitch [data-baseweb="select"]>div { min-height:42px; border-color:rgba(224,255,241,.28); background:rgba(3,22,16,.84); box-shadow:0 8px 18px rgba(0,0,0,.2); }
        .st-key-top_xi_pitch [data-baseweb="select"] span { color:#f4fbf7; font-size:.72rem; font-weight:750; }
        div[data-testid="stDataFrame"] { overflow:hidden; border:1px solid rgba(25,230,176,.2); border-radius:4px 4px 12px 12px; box-shadow:0 14px 36px rgba(0,0,0,.18); }
        .fantasy-player-hero { --role:#19e6b0; display:grid; grid-template-columns:auto 1fr auto; gap:.9rem; align-items:center; margin:1.15rem 0 .75rem; padding:1rem; border:1px solid color-mix(in srgb,var(--role) 42%,transparent); border-radius:13px; background:radial-gradient(circle at 88% 12%,color-mix(in srgb,var(--role) 18%,transparent),transparent 32%),linear-gradient(125deg,rgba(244,251,247,.055),rgba(8,10,11,.92)); }
        .fantasy-player-hero.role-p { --role:#ffb020; }
        .fantasy-player-hero.role-d { --role:#19e6b0; }
        .fantasy-player-hero.role-c { --role:#62d8ff; }
        .fantasy-player-hero.role-a { --role:#f4538a; }
        .fantasy-player-role { width:52px; height:52px; display:grid; place-items:center; border-radius:15px; color:#07100d; background:var(--role); font-size:1.25rem; font-weight:950; box-shadow:0 0 30px color-mix(in srgb,var(--role) 28%,transparent); }
        .fantasy-player-title span { color:var(--role); font-size:.7rem; font-weight:900; letter-spacing:.08em; text-transform:uppercase; }
        .fantasy-player-title h3 { margin:.12rem 0; color:#f4fbf7; font-size:1.45rem; }
        .fantasy-player-title p { margin:0; color:#94a19c; font-size:.8rem; }
        .fantasy-player-score { min-width:88px; display:flex; flex-direction:column; align-items:flex-end; }
        .fantasy-player-score small { color:#899791; font-size:.58rem; font-weight:900; letter-spacing:.08em; }
        .fantasy-player-score strong { color:var(--role); font-size:1.75rem; line-height:1; }
        .fantasy-player-score span { color:#f4fbf7; font-size:.72rem; }
        .fantasy-stat-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.55rem; margin:.7rem 0 1rem; }
        .fantasy-stat-card { min-height:72px; display:flex; flex-direction:column; justify-content:center; gap:.25rem; padding:.65rem .75rem; border:1px solid rgba(244,251,247,.1); border-radius:9px; background:linear-gradient(140deg,rgba(244,251,247,.045),rgba(8,10,11,.35)); }
        .fantasy-stat-card span { color:#899791; font-size:.72rem; }
        .fantasy-stat-card strong { color:#f4fbf7; font-size:1.05rem; overflow-wrap:anywhere; }
        .fantasy-percentile-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.55rem; margin:.55rem 0 1rem; }
        .fantasy-percentile { position:relative; overflow:hidden; min-height:74px; display:grid; grid-template-columns:1fr auto; align-items:start; gap:.5rem; padding:.72rem .8rem 1rem; border:1px solid rgba(244,251,247,.1); border-radius:10px; background:rgba(14,18,19,.82); }
        .fantasy-percentile span { color:#9ba9a4; font-size:.72rem; }
        .fantasy-percentile strong { color:#f4fbf7; font-size:1.05rem; }
        .fantasy-percentile i { position:absolute; left:0; bottom:0; width:var(--value); height:4px; background:#62d8ff; box-shadow:0 0 16px currentColor; }
        .fantasy-percentile.elite i { background:#19e6b0; }
        .fantasy-percentile.good i { background:#62d8ff; }
        .fantasy-percentile.average i { background:#ffb020; }
        .fantasy-percentile.weak i { background:#f4538a; }
        .fantasy-role-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.55rem; margin:.8rem 0 1.15rem; }
        .fantasy-role-card { display:grid; grid-template-columns:auto 1fr; gap:.1rem .6rem; align-items:center; padding:.7rem; border:1px solid rgba(244,251,247,.12); border-radius:9px; background:rgba(244,251,247,.035); }
        .fantasy-role-card>span { grid-row:1/3; width:35px; height:35px; display:grid; place-items:center; border-radius:50%; color:#08100e; background:#19e6b0; font-weight:950; }
        .fantasy-role-card strong { color:#f4fbf7; font-size:1.05rem; }
        .fantasy-role-card small { color:#899791; }
        .fantasy-role-card.complete { border-color:rgba(25,230,176,.35); }
        .fantasy-insights { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.6rem; margin:.85rem 0 1.2rem; }
        .fantasy-insight { display:flex; flex-direction:column; gap:.3rem; min-height:82px; padding:.75rem; border-radius:9px; border:1px solid rgba(244,251,247,.12); background:rgba(244,251,247,.035); }
        .fantasy-insight strong { color:#f4fbf7; }
        .fantasy-insight span { color:#95a39e; font-size:.82rem; line-height:1.35; }
        .fantasy-insight.ok { border-color:rgba(25,230,176,.3); }
        .fantasy-insight.warn { border-color:rgba(255,176,32,.35); }
        .fantasy-pitch { display:grid; gap:.65rem; padding:1.1rem; margin-bottom:1.1rem; border:1px solid rgba(25,230,176,.28); border-radius:12px; background:linear-gradient(90deg,transparent 49.7%,rgba(255,255,255,.1) 49.7% 50.3%,transparent 50.3%),repeating-linear-gradient(90deg,rgba(25,230,176,.06) 0 10%,rgba(25,230,176,.1) 10% 20%),#0b1512; }
        .fantasy-line { display:grid; grid-template-columns:32px 1fr; align-items:center; gap:.5rem; }
        .fantasy-line>span { width:30px; height:30px; display:grid; place-items:center; border-radius:50%; background:#19e6b0; color:#07100d; font-weight:950; }
        .fantasy-line>div { padding:.55rem .7rem; border-radius:8px; color:#f4fbf7; text-align:center; background:rgba(8,10,11,.72); border:1px solid rgba(255,255,255,.12); font-weight:750; }
        .st-key-top_xi_pitch { padding:1rem 1.2rem 1.25rem; border:1px solid rgba(104,255,190,.52); border-radius:24px; background:radial-gradient(ellipse at 8% 0,rgba(132,255,218,.23),transparent 18%),radial-gradient(ellipse at 92% 0,rgba(132,255,218,.23),transparent 18%),radial-gradient(circle at 50% 50%,transparent 0 65px,rgba(237,255,246,.22) 66px 68px,transparent 69px),linear-gradient(to bottom,transparent 49.7%,rgba(237,255,246,.24) 49.8% 50.2%,transparent 50.3%),repeating-linear-gradient(90deg,rgba(7,69,49,.97) 0 12.5%,rgba(10,91,62,.97) 12.5% 25%); box-shadow:inset 0 0 100px rgba(0,0,0,.38),inset 0 14px 24px rgba(151,255,221,.08),0 28px 70px rgba(0,0,0,.36),0 0 0 7px rgba(5,15,13,.7); }
        .st-key-top_xi_pitch:before { inset:1.1rem; border:2px solid rgba(237,255,246,.27); border-radius:7px; box-shadow:inset 0 0 0 1px rgba(0,0,0,.12); }
        .st-key-top_xi_pitch:after { left:35%; right:35%; bottom:1.1rem; height:14%; border-color:rgba(237,255,246,.24); }
        .fantasy-pitch-title { margin:0 0 .25rem; padding:.55rem .7rem; border:1px solid rgba(255,255,255,.1); background:linear-gradient(100deg,rgba(2,20,14,.86),rgba(8,44,31,.68)); box-shadow:0 10px 24px rgba(0,0,0,.2); }
        .fantasy-pitch-title>div { display:flex; flex-direction:column; gap:.05rem; }
        .fantasy-pitch-title small { color:#88a99c; font-size:.62rem; }
        .fantasy-pitch-title strong { padding:.24rem .55rem; border:1px solid rgba(98,216,255,.35); border-radius:7px; color:#b8efff; background:rgba(98,216,255,.1); letter-spacing:.08em; }
        .fantasy-pitch-role { margin:.42rem auto .05rem; border:1px solid rgba(255,255,255,.28); box-shadow:0 6px 18px rgba(0,0,0,.24); }
        .st-key-top_xi_pitch [data-baseweb="select"]>div { min-height:34px; border-color:rgba(224,255,241,.2); border-radius:7px; background:rgba(3,18,14,.82); box-shadow:none; }
        .st-key-top_xi_pitch [data-baseweb="select"] span { font-size:.62rem; }
        .fantasy-lineup-card { --accent:#19e6b0; min-height:82px; display:grid; grid-template-columns:43px minmax(0,1fr); gap:.42rem; align-items:center; margin:.22rem 0 .06rem; padding:.44rem; overflow:hidden; border:1px solid color-mix(in srgb,var(--accent) 52%,transparent); border-radius:12px; background:linear-gradient(145deg,rgba(4,19,15,.96),rgba(7,35,25,.86)); box-shadow:0 12px 26px rgba(0,0,0,.3),inset 0 1px rgba(255,255,255,.06); backdrop-filter:blur(7px); }
        .fantasy-lineup-card.role-p { --accent:#ffb020; }
        .fantasy-lineup-card.role-d { --accent:#19e6b0; }
        .fantasy-lineup-card.role-c { --accent:#62d8ff; }
        .fantasy-lineup-card.role-a { --accent:#f4538a; }
        .fantasy-lineup-shirt { position:relative; width:40px; height:48px; display:grid; place-items:center; clip-path:polygon(18% 0,36% 8%,64% 8%,82% 0,100% 24%,85% 38%,80% 100%,20% 100%,15% 38%,0 24%); color:#07100d; background:linear-gradient(145deg,#fff,var(--accent) 52%,color-mix(in srgb,var(--accent) 74%,#000)); filter:drop-shadow(0 5px 6px rgba(0,0,0,.32)); }
        .fantasy-lineup-shirt i { font-style:normal; font-size:.69rem; font-weight:950; }
        .fantasy-lineup-shirt span { position:absolute; bottom:4px; color:rgba(7,16,13,.78); font-size:.47rem; font-weight:950; }
        .fantasy-lineup-copy { min-width:0; display:flex; flex-direction:column; gap:.02rem; }
        .fantasy-lineup-copy>small { color:var(--accent); font-size:.52rem; font-weight:950; letter-spacing:.07em; }
        .fantasy-lineup-copy>strong { overflow:hidden; color:#f7fffb; font-size:.72rem; line-height:1.08; text-overflow:ellipsis; white-space:nowrap; }
        .fantasy-lineup-copy>div { display:flex; flex-wrap:wrap; gap:.2rem; margin-top:.18rem; }
        .fantasy-lineup-copy>div span { padding:.09rem .22rem; border-radius:4px; color:#c9ddd5; background:rgba(255,255,255,.07); font-size:.48rem; font-weight:800; }
        .fantasy-lineup-copy>div .fantasy-xi-appearance { border:1px solid rgba(98,216,255,.34); color:#a9ecff; background:rgba(98,216,255,.12); box-shadow:0 0 12px rgba(98,216,255,.08); }
        .fantasy-lineup-copy>div .fantasy-xi-appearance.ready { border-color:rgba(25,230,176,.4); color:#83f4d4; background:rgba(25,230,176,.13); }
        .fantasy-lineup-copy>div .fantasy-xi-appearance.watch { border-color:rgba(255,176,32,.42); color:#ffd17b; background:rgba(255,176,32,.13); }
        .fantasy-lineup-copy>div .fantasy-xi-appearance.low,.fantasy-lineup-copy>div .fantasy-xi-appearance.out { border-color:rgba(244,83,138,.44); color:#ff9abd; background:rgba(244,83,138,.14); }
        .fantasy-lineup-card.empty { display:flex; flex-direction:column; justify-content:center; gap:.12rem; border-style:dashed; opacity:.7; text-align:center; }
        .fantasy-lineup-card.empty span { color:var(--accent); font-size:.58rem; font-weight:950; }
        .fantasy-lineup-card.empty strong { color:#c7d6d0; font-size:.59rem; letter-spacing:.05em; }
        .fantasy-pitch-footer { display:flex; justify-content:space-between; align-items:center; margin-top:.55rem; padding:.42rem .65rem; border:1px solid rgba(255,255,255,.1); border-radius:8px; color:#a8c6ba; background:rgba(2,20,14,.76); font-size:.58rem; font-weight:900; letter-spacing:.07em; }
        .fantasy-pitch-footer strong { color:#f4fbf7; }
        .fantasy-swap-hero { display:flex; justify-content:space-between; align-items:center; gap:1rem; margin:1.25rem 0 .35rem; padding:1rem 1.05rem; border:1px solid rgba(174,112,255,.42); border-radius:14px; background:radial-gradient(circle at 88% 0,rgba(174,112,255,.2),transparent 34%),linear-gradient(120deg,rgba(98,216,255,.08),rgba(8,10,11,.92)); }
        .fantasy-swap-hero>div { display:flex; flex-direction:column; gap:.14rem; }
        .fantasy-swap-hero span { color:#c9a7ff; font-size:.65rem; font-weight:950; letter-spacing:.1em; }
        .fantasy-swap-hero strong { color:#f4fbf7; font-size:1.12rem; }
        .fantasy-swap-hero small { color:#95a39e; }
        .fantasy-swap-hero>b { min-width:55px; height:55px; display:grid; place-items:center; border-radius:16px; color:#0b0711; background:linear-gradient(145deg,#d6bdff,#9b65ee); font-size:1.2rem; box-shadow:0 0 28px rgba(174,112,255,.24); }
        .fantasy-swap-card { margin:.7rem 0; padding:.8rem; border:1px solid rgba(244,251,247,.12); border-radius:13px; background:linear-gradient(145deg,rgba(244,251,247,.045),rgba(8,10,11,.78)); box-shadow:0 14px 34px rgba(0,0,0,.16); }
        .fantasy-swap-card>header { display:flex; justify-content:space-between; align-items:center; gap:.6rem; margin-bottom:.65rem; }
        .fantasy-swap-card>header span { color:#899791; font-size:.6rem; font-weight:950; letter-spacing:.1em; }
        .fantasy-swap-card>header b { padding:.25rem .45rem; border-radius:6px; color:#c9a7ff; background:rgba(174,112,255,.12); font-size:.62rem; }
        .fantasy-swap-flow { display:grid; grid-template-columns:1fr auto 1fr; gap:.7rem; align-items:center; }
        .fantasy-swap-flow>section { display:flex; flex-direction:column; gap:.35rem; }
        .fantasy-swap-flow>section>small { color:#899791; font-size:.56rem; font-weight:950; letter-spacing:.1em; }
        .fantasy-swap-player { display:grid; grid-template-columns:31px 1fr; gap:.45rem; align-items:center; padding:.42rem .5rem; border-radius:8px; background:rgba(255,255,255,.035); }
        .fantasy-swap-player>span { width:29px; height:29px; display:grid; place-items:center; border-radius:8px; color:#f4fbf7; background:rgba(244,83,138,.18); font-weight:950; }
        .fantasy-swap-player.in>span { color:#07100d; background:#19e6b0; }
        .fantasy-swap-player>div { min-width:0; display:flex; flex-direction:column; }
        .fantasy-swap-player strong { overflow:hidden; color:#f4fbf7; font-size:.8rem; text-overflow:ellipsis; white-space:nowrap; }
        .fantasy-swap-player small { color:#899791; font-size:.62rem; }
        .fantasy-swap-arrow { display:flex; flex-direction:column; align-items:center; gap:.15rem; color:#c9a7ff; }
        .fantasy-swap-arrow strong { font-size:1.5rem; }
        .fantasy-swap-arrow span { padding:.15rem .3rem; border-radius:5px; color:#d8c4f8; background:rgba(174,112,255,.12); font-size:.55rem; font-weight:900; }
        .fantasy-swap-deltas { display:flex; flex-wrap:wrap; gap:.35rem; margin:.65rem 0 .45rem; }
        .fantasy-swap-deltas span { padding:.22rem .4rem; border:1px solid rgba(25,230,176,.22); border-radius:999px; color:#bceee0; background:rgba(25,230,176,.07); font-size:.62rem; font-weight:850; }
        .fantasy-swap-card>p { margin:.2rem 0 0; color:#a8b5b0; font-size:.76rem; line-height:1.45; }
        .fantasy-auction-hero { display:flex; justify-content:space-between; align-items:center; gap:1rem; margin:.25rem 0 .65rem; padding:1rem 1.05rem; overflow:hidden; border:1px solid rgba(255,176,32,.38); border-radius:14px; background:radial-gradient(circle at 90% 0,rgba(255,176,32,.2),transparent 35%),linear-gradient(120deg,rgba(244,83,138,.08),rgba(8,10,11,.92)); }
        .fantasy-auction-hero>div { display:flex; flex-direction:column; gap:.12rem; }
        .fantasy-auction-hero span { color:#ffbe45; font-size:.64rem; font-weight:950; letter-spacing:.11em; }
        .fantasy-auction-hero strong { color:#f4fbf7; font-size:1.16rem; }
        .fantasy-auction-hero small { color:#95a39e; }
        .fantasy-auction-hero aside { min-width:120px; display:flex; flex-direction:column; align-items:flex-end; }
        .fantasy-auction-hero aside small { font-size:.5rem; font-weight:900; letter-spacing:.08em; }
        .fantasy-auction-hero aside b { color:#ffbe45; font-size:1.75rem; line-height:1; }
        .fantasy-manager-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:.48rem; margin-bottom:.55rem; }
        .fantasy-manager-card { display:grid; grid-template-columns:1fr auto; gap:.05rem .4rem; align-items:center; padding:.62rem .7rem; border:1px solid rgba(244,251,247,.1); border-radius:10px; background:linear-gradient(140deg,rgba(244,251,247,.04),rgba(8,10,11,.58)); }
        .fantasy-manager-card.owner { border-color:rgba(25,230,176,.36); background:linear-gradient(140deg,rgba(25,230,176,.1),rgba(8,10,11,.58)); }
        .fantasy-manager-card>span { grid-column:1/3; color:#899791; font-size:.48rem; font-weight:950; letter-spacing:.1em; }
        .fantasy-manager-card.owner>span { color:#19e6b0; }
        .fantasy-manager-card>strong { overflow:hidden; color:#f4fbf7; font-size:.76rem; text-overflow:ellipsis; white-space:nowrap; }
        .fantasy-manager-card>small { grid-column:1; color:#899791; font-size:.58rem; }
        .fantasy-manager-card>b { grid-column:2; grid-row:2/4; color:#ffbe45; font-size:1.05rem; }
        .fantasy-custom-tier-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:.48rem; margin:.35rem 0 .75rem; }
        .fantasy-custom-tier { display:grid; grid-template-columns:auto 1fr; gap:.05rem .45rem; align-items:center; padding:.58rem .65rem; border:1px solid color-mix(in srgb,var(--tier-color) 38%,transparent); border-left:4px solid var(--tier-color); border-radius:10px; background:linear-gradient(135deg,color-mix(in srgb,var(--tier-color) 10%,transparent),rgba(8,10,11,.62)); }
        .fantasy-custom-tier>span { grid-row:1/3; font-size:1.05rem; filter:drop-shadow(0 0 8px var(--tier-color)); }
        .fantasy-custom-tier>strong { color:#f4fbf7; font-size:.76rem; }
        .fantasy-custom-tier>small { color:#899791; font-size:.58rem; }
        .fantasy-sim-verdict { display:flex; flex-direction:column; gap:.15rem; margin:.65rem 0 .2rem; padding:.8rem .9rem; border:1px solid rgba(255,176,32,.35); border-left:4px solid #ffb020; border-radius:10px; background:linear-gradient(110deg,rgba(255,176,32,.1),rgba(8,10,11,.62)); }
        .fantasy-sim-verdict.ok { border-color:rgba(25,230,176,.35); border-left-color:#19e6b0; background:linear-gradient(110deg,rgba(25,230,176,.1),rgba(8,10,11,.62)); }
        .fantasy-sim-verdict span { color:#8f9d98; font-size:.55rem; font-weight:950; letter-spacing:.11em; }
        .fantasy-sim-verdict strong { color:#f4fbf7; font-size:1rem; }
        .fantasy-sim-verdict small { color:#9eaca7; }
        .fantasy-decision-hero { position:relative; overflow:hidden; display:grid; grid-template-columns:1fr auto; gap:1rem; align-items:center; margin:.25rem 0 1rem; padding:1.15rem 1.2rem; border:1px solid rgba(98,216,255,.34); border-radius:16px; background:radial-gradient(circle at 88% -20%,rgba(98,216,255,.27),transparent 38%),radial-gradient(circle at 8% 120%,rgba(25,230,176,.18),transparent 32%),linear-gradient(125deg,#0d1716,#0b1013 58%,#15101b); box-shadow:0 18px 48px rgba(0,0,0,.22); }
        .fantasy-decision-hero>div { display:flex; flex-direction:column; gap:.16rem; }
        .fantasy-decision-hero span { color:#62d8ff; font-size:.62rem; font-weight:950; letter-spacing:.12em; }
        .fantasy-decision-hero strong { color:#f7fffb; font-size:1.5rem; }
        .fantasy-decision-hero small { color:#9eaca7; }
        .fantasy-decision-hero aside { min-width:72px; height:72px; display:flex; flex-direction:column; align-items:center; justify-content:center; border:1px solid rgba(98,216,255,.45); border-radius:20px; background:rgba(98,216,255,.09); box-shadow:inset 0 0 24px rgba(98,216,255,.08); }
        .fantasy-decision-hero aside small { color:#8ca39f; font-size:.48rem; font-weight:950; letter-spacing:.08em; }
        .fantasy-decision-hero aside b { color:#62d8ff; font-size:1.55rem; line-height:1; }
        .fantasy-matchday-label { display:flex; align-items:center; justify-content:space-between; gap:1rem; margin:.8rem 0 .4rem; padding:.55rem .75rem; border-radius:9px; background:linear-gradient(90deg,rgba(25,230,176,.12),rgba(98,216,255,.05)); }
        .fantasy-matchday-label span { color:#19e6b0; font-size:.58rem; font-weight:950; letter-spacing:.1em; }
        .fantasy-matchday-label strong { color:#f4fbf7; }
        .fantasy-decision-pitch { position:relative; overflow:hidden; display:flex; flex-direction:column; gap:.65rem; padding:1rem; border:1px solid rgba(104,255,190,.42); border-radius:18px; background:radial-gradient(circle at 50% 50%,transparent 0 58px,rgba(237,255,246,.18) 59px 61px,transparent 62px),linear-gradient(to bottom,transparent 49.7%,rgba(237,255,246,.2) 49.8% 50.2%,transparent 50.3%),repeating-linear-gradient(90deg,rgba(7,69,49,.94) 0 12.5%,rgba(10,91,62,.94) 12.5% 25%); box-shadow:inset 0 0 80px rgba(0,0,0,.36),0 20px 48px rgba(0,0,0,.22); }
        .fantasy-decision-line { display:grid; grid-template-columns:92px 1fr; gap:.7rem; align-items:center; }
        .fantasy-decision-line>b { color:rgba(237,255,246,.68); font-size:.62rem; text-transform:uppercase; letter-spacing:.08em; }
        .fantasy-decision-line>div { display:grid; grid-template-columns:repeat(auto-fit,minmax(135px,1fr)); gap:.45rem; }
        .fantasy-decision-player { --accent:#19e6b0; position:relative; display:flex; flex-direction:column; min-width:0; padding:.58rem .62rem; border:1px solid color-mix(in srgb,var(--accent) 42%,transparent); border-radius:11px; background:linear-gradient(145deg,rgba(3,20,15,.94),rgba(6,35,24,.86)); box-shadow:0 10px 20px rgba(0,0,0,.22); }
        .fantasy-decision-player.role-a { --accent:#f4538a; }
        .fantasy-decision-player.role-c { --accent:#62d8ff; }
        .fantasy-decision-player.role-p { --accent:#ffb020; }
        .fantasy-decision-player>span { color:var(--accent); font-size:.5rem; font-weight:950; letter-spacing:.08em; }
        .fantasy-decision-player>strong { overflow:hidden; color:#f7fffb; font-size:.8rem; text-overflow:ellipsis; white-space:nowrap; }
        .fantasy-decision-player>small { color:#9fb1aa; font-size:.58rem; }
        .fantasy-decision-player>em.availability { width:fit-content; margin-top:.3rem; padding:.13rem .32rem; border:1px solid rgba(98,216,255,.25); border-radius:999px; color:#9fe8ff; background:rgba(98,216,255,.08); font-size:.46rem; font-style:normal; font-weight:900; letter-spacing:.04em; }
        .fantasy-decision-player>em.availability.bench { border-color:rgba(255,176,32,.35); color:#ffcf72; background:rgba(255,176,32,.09); }
        .fantasy-decision-player>em.availability.injured,.fantasy-decision-player>em.availability.suspended { border-color:rgba(244,83,138,.38); color:#ff8db4; background:rgba(244,83,138,.1); }
        .fantasy-decision-player>i { position:absolute; top:.45rem; right:.45rem; color:#ffdf72; font-size:.44rem; font-style:normal; font-weight:950; }
        .fantasy-decision-player.easy { box-shadow:0 0 0 1px rgba(25,230,176,.16),0 10px 22px rgba(0,0,0,.24); }
        .fantasy-decision-player.medium { box-shadow:inset 3px 0 #ffb020,0 10px 22px rgba(0,0,0,.24); }
        .fantasy-decision-player.hard { box-shadow:inset 3px 0 #f4538a,0 10px 22px rgba(0,0,0,.24); }
        .fantasy-appearance-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:.5rem; margin:.55rem 0 1rem; }
        .fantasy-appearance-card { --signal:#62d8ff; display:flex; flex-direction:column; gap:.18rem; min-width:0; padding:.65rem .7rem; border:1px solid color-mix(in srgb,var(--signal) 28%,transparent); border-radius:11px; background:linear-gradient(145deg,color-mix(in srgb,var(--signal) 7%,transparent),rgba(8,10,11,.7)); }
        .fantasy-appearance-card.ready { --signal:#19e6b0; }
        .fantasy-appearance-card.watch { --signal:#ffb020; }
        .fantasy-appearance-card.low,.fantasy-appearance-card.out { --signal:#f4538a; }
        .fantasy-appearance-card header { display:flex; justify-content:space-between; align-items:center; gap:.5rem; }
        .fantasy-appearance-card header span { color:var(--signal); font-size:.5rem; font-weight:950; letter-spacing:.08em; }
        .fantasy-appearance-card header b { color:var(--signal); font-size:1rem; }
        .fantasy-appearance-card>strong { overflow:hidden; color:#f7fffb; font-size:.82rem; text-overflow:ellipsis; white-space:nowrap; }
        .fantasy-appearance-card>div { height:5px; overflow:hidden; border-radius:999px; background:rgba(255,255,255,.08); }
        .fantasy-appearance-card>div>i { display:block; height:100%; border-radius:inherit; background:var(--signal); box-shadow:0 0 14px color-mix(in srgb,var(--signal) 62%,transparent); }
        .fantasy-appearance-card>small,.fantasy-appearance-card>small a { color:#97aaa3; font-size:.52rem; text-decoration:none; }
        .fantasy-appearance-card>p { display:-webkit-box; overflow:hidden; margin:.12rem 0 0; color:#788680; font-size:.55rem; line-height:1.35; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
        .fantasy-calendar-board { display:flex; flex-direction:column; gap:.45rem; margin:.7rem 0; }
        .fantasy-calendar-row { display:grid; grid-template-columns:minmax(150px,.72fr) 2fr; gap:.65rem; align-items:center; padding:.62rem; border:1px solid rgba(244,251,247,.1); border-radius:11px; background:linear-gradient(120deg,rgba(244,251,247,.045),rgba(8,10,11,.5)); }
        .fantasy-calendar-row>div { min-width:0; display:flex; flex-direction:column; }
        .fantasy-calendar-row>div strong { color:#f4fbf7; }
        .fantasy-calendar-row>div small { overflow:hidden; color:#899791; font-size:.6rem; text-overflow:ellipsis; white-space:nowrap; }
        .fantasy-calendar-row>section { display:grid; grid-template-columns:repeat(5,minmax(88px,1fr)); gap:.35rem; }
        .fantasy-calendar-row>section>span { display:grid; grid-template-columns:auto 1fr auto; gap:.3rem; align-items:center; padding:.4rem .45rem; border:1px solid rgba(244,251,247,.1); border-radius:7px; background:rgba(244,251,247,.035); }
        .fantasy-calendar-row>section>span.easy { border-color:rgba(25,230,176,.32); background:rgba(25,230,176,.08); }
        .fantasy-calendar-row>section>span.medium { border-color:rgba(255,176,32,.32); background:rgba(255,176,32,.08); }
        .fantasy-calendar-row>section>span.hard { border-color:rgba(244,83,138,.32); background:rgba(244,83,138,.08); }
        .fantasy-calendar-row span small { color:#899791; font-size:.48rem; }
        .fantasy-calendar-row span strong { overflow:hidden; color:#f4fbf7; font-size:.58rem; text-overflow:ellipsis; white-space:nowrap; }
        .fantasy-calendar-row span b { color:#c8d6d1; font-size:.62rem; }
        .fantasy-rotation-card { min-height:86px; display:flex; flex-direction:column; gap:.2rem; padding:.72rem; border:1px solid rgba(98,216,255,.25); border-radius:10px; background:linear-gradient(145deg,rgba(98,216,255,.08),rgba(8,10,11,.54)); }
        .fantasy-rotation-card span { color:#62d8ff; font-size:.52rem; font-weight:950; letter-spacing:.09em; }
        .fantasy-rotation-card strong { color:#f4fbf7; }
        .fantasy-rotation-card small { color:#94a29d; }
        .fantasy-alert-card { position:relative; display:grid; grid-template-columns:5px 1fr; gap:.75rem; margin:.5rem 0; padding:.72rem .8rem .72rem .45rem; border:1px solid rgba(244,251,247,.1); border-radius:11px; background:linear-gradient(115deg,rgba(244,251,247,.045),rgba(8,10,11,.6)); }
        .fantasy-alert-card>span { width:5px; height:100%; border-radius:999px; background:#62d8ff; }
        .fantasy-alert-card.high>span { background:#f4538a; box-shadow:0 0 18px rgba(244,83,138,.45); }
        .fantasy-alert-card.medium>span { background:#ffb020; }
        .fantasy-alert-card.news>span { background:#62d8ff; }
        .fantasy-alert-card.unread { border-color:rgba(98,216,255,.26); background:linear-gradient(115deg,rgba(98,216,255,.08),rgba(8,10,11,.64)); }
        .fantasy-alert-card>div { display:flex; flex-direction:column; gap:.12rem; }
        .fantasy-alert-card small,.fantasy-alert-card small a { color:#62d8ff; font-size:.52rem; font-weight:900; letter-spacing:.07em; text-decoration:none; }
        .fantasy-alert-card strong { color:#f4fbf7; }
        .fantasy-alert-card p { display:flex; flex-direction:column; gap:.14rem; margin:.28rem 0 0; color:#b3c0bb; font-size:.76rem; line-height:1.42; }
        .fantasy-alert-card p>b { color:#ffcf72; font-size:.5rem; letter-spacing:.1em; }
        .fantasy-alert-evidence { display:flex; flex-direction:column; gap:.18rem; margin:.32rem 0 .08rem; padding:.62rem .7rem; border:1px solid rgba(244,83,138,.34); border-left:4px solid #f4538a; border-radius:8px; background:linear-gradient(110deg,rgba(244,83,138,.13),rgba(8,10,11,.42)); }
        .fantasy-alert-evidence em { color:#ff8db4; font-size:.5rem; font-style:normal; font-weight:950; letter-spacing:.1em; }
        .fantasy-alert-evidence b { color:#f9fffc; font-size:.8rem; line-height:1.35; }
        .fantasy-alert-evidence.no-news { border-color:rgba(255,176,32,.26); border-left-color:#ffb020; background:linear-gradient(110deg,rgba(255,176,32,.08),rgba(8,10,11,.42)); }
        .fantasy-alert-evidence.no-news em { color:#ffcf72; }
        .fantasy-alert-evidence.no-news b { color:#a8b5b0; font-size:.7rem; font-weight:700; }
        @media (max-width:720px) {
            .fantasy-league-hero { grid-template-columns:1fr auto; }
            .fantasy-mode-stack { grid-column:1/3; justify-content:flex-start; }
            .fantasy-source-card { grid-template-columns:1fr; }
            .fantasy-source-card>div:last-child { text-align:left; }
            .fantasy-player-hero { grid-template-columns:auto 1fr; }
            .fantasy-player-score { grid-column:1/3; flex-direction:row; align-items:center; gap:.5rem; }
            .fantasy-player-score strong { font-size:1.35rem; }
            .fantasy-stat-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .fantasy-percentile-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .fantasy-table-heading span { display:none; }
            .fantasy-selection-bar { align-items:flex-start; }
            .fantasy-selection-bar span { display:none; }
            .fantasy-xi-hero { align-items:flex-start; padding:.85rem; }
            .fantasy-xi-hero small { font-size:.72rem; }
            .fantasy-xi-hero b { min-width:54px; height:54px; }
            .st-key-top_xi_pitch { padding:.7rem .35rem 1rem; border-radius:12px; }
            .st-key-top_xi_pitch:before { inset:.75rem .45rem; }
            .st-key-top_xi_pitch [data-baseweb="select"] span { font-size:.58rem; }
            .st-key-top_xi_pitch [data-baseweb="select"]>div { min-height:38px; padding-left:.25rem; padding-right:.15rem; }
            .fantasy-lineup-card { min-height:68px; grid-template-columns:31px minmax(0,1fr); gap:.25rem; padding:.3rem; border-radius:9px; }
            .fantasy-lineup-shirt { width:30px; height:38px; }
            .fantasy-lineup-shirt i { font-size:.55rem; }
            .fantasy-lineup-copy>strong { font-size:.58rem; }
            .fantasy-lineup-copy>small,.fantasy-lineup-copy>div span { font-size:.43rem; }
            .fantasy-pitch-footer { font-size:.48rem; }
            .fantasy-swap-flow { grid-template-columns:1fr; }
            .fantasy-swap-arrow { flex-direction:row; justify-content:center; }
            .fantasy-swap-arrow strong { transform:rotate(90deg); }
            .fantasy-auction-hero { align-items:flex-start; }
            .fantasy-auction-hero aside { min-width:75px; }
            .fantasy-manager-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .fantasy-custom-tier-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .fantasy-role-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .fantasy-insights { grid-template-columns:1fr; }
            .fantasy-empty { padding:1.25rem .8rem; }
            .fantasy-line { grid-template-columns:28px 1fr; }
            .fantasy-line>div { font-size:.78rem; padding:.48rem; overflow-wrap:anywhere; }
            .fantasy-decision-hero { padding:.9rem; }
            .fantasy-decision-hero strong { font-size:1.2rem; }
            .fantasy-decision-hero small { font-size:.68rem; }
            .fantasy-decision-hero aside { min-width:58px; height:58px; }
            .fantasy-decision-line { grid-template-columns:1fr; gap:.25rem; }
            .fantasy-decision-line>b { text-align:center; }
            .fantasy-decision-line>div { grid-template-columns:repeat(3,minmax(0,1fr)); gap:.28rem; }
            .fantasy-decision-player { padding:.42rem; border-radius:8px; }
            .fantasy-decision-player>strong { font-size:.63rem; }
            .fantasy-decision-player>small { font-size:.48rem; }
            .fantasy-decision-player>i { display:none; }
            .fantasy-appearance-grid { grid-template-columns:repeat(2,minmax(0,1fr)); gap:.38rem; }
            .fantasy-appearance-card { padding:.5rem; }
            .fantasy-calendar-row { grid-template-columns:1fr; }
            .fantasy-calendar-row>section { display:flex; overflow-x:auto; padding-bottom:.2rem; }
            .fantasy-calendar-row>section>span { min-width:104px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
