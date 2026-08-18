from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from config.settings import Settings
from fantasy.catalog import catalog_dataframe, make_player, merge_catalog
from fantasy.official_catalog import (
    OFFICIAL_CATALOG_URL,
    catalog_fingerprint,
    fetch_official_catalog,
    merge_catalog_updates,
)
from fantasy.service import (
    DEFAULT_ROSTER_SLOTS,
    GAME_MODE_AUCTION,
    GAME_MODE_LIST,
    ROLE_LABELS,
    add_purchase,
    create_league,
    delete_league,
    find_league,
    remove_purchase,
    roster_summary,
    set_captain,
    suggest_lineup,
    toggle_watchlist,
    touch_workspace,
    utc_now,
    update_league_settings,
)
from fantasy.storage import FantasyWorkspaceStorage
from nlp.gemini_client import GeminiClient


WORKSPACE_SESSION_KEY = "fantasy_workspace"


def render_fantasy_page(settings: Settings) -> None:
    render_fantasy_styles()
    st.caption("Fantacalcio · Player Board v2 · build 2026.08.18")
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
    preparation_tab, auction_tab, squad_tab = st.tabs([
        "Studia il listone" if list_mode else "Preparati all'asta",
        "Componi rosa" if list_mode else "Asta",
        "La mia squadra",
    ])
    with preparation_tab:
        _render_preparation(workspace, league, storage)
    with auction_tab:
        _render_auction(workspace, league, storage)
    with squad_tab:
        _render_my_squad(workspace, league, storage, settings)
    _render_sync_status(storage)


def _load_workspace(storage: FantasyWorkspaceStorage) -> dict[str, Any]:
    if WORKSPACE_SESSION_KEY not in st.session_state:
        st.session_state[WORKSPACE_SESSION_KEY] = storage.load()
        st.session_state["fantasy_remote_synced"] = storage.last_remote_save_ok
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

    selector, create_column, settings_column = st.columns([2.35, 0.75, 0.75])
    selected_id = selector.selectbox(
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

    with create_column.popover("+ Nuovo", use_container_width=True):
        st.markdown("#### Nuovo fantacalcio")
        _render_create_form(workspace, storage, "popover")

    league = find_league(workspace, selected_id)
    if not league:
        return None
    with settings_column.popover("Gestisci", use_container_width=True):
        _render_manage_form(workspace, league, storage)
    return league


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
        budget = st.number_input("Budget", min_value=50, max_value=2000, value=250, step=10)
        participants = None
        if game_mode == GAME_MODE_AUCTION:
            participants = st.number_input("Partecipanti", min_value=2, max_value=30, value=10)
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
            "Budget iniziale",
            min_value=1,
            max_value=5000,
            value=int(league.get("initial_budget", 250)),
        )
        participants = None
        if game_mode == GAME_MODE_AUCTION:
            participants = st.number_input(
                "Partecipanti",
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

    st.divider()
    confirm_delete = st.checkbox("Confermo l'eliminazione", key=f"confirm_delete_{league['id']}")
    if st.button(
        "Elimina questo fanta",
        disabled=not confirm_delete,
        use_container_width=True,
        key=f"delete_league_{league['id']}",
    ):
        delete_league(workspace, league["id"])
        _save_workspace(workspace, storage)
        st.session_state.pop("fantasy_league_selector", None)
        st.rerun()


def _render_league_hero(league: dict[str, Any], summary: dict[str, Any]) -> None:
    completion = int(100 * summary["roster_size"] / max(summary["target_size"], 1))
    list_mode = league.get("game_mode") == GAME_MODE_LIST
    context = "LISTONE" if list_mode else f"{league.get('participants', 0)} PARTECIPANTI"
    chips = ["LISTONE" if list_mode else "ASTA"]
    if league.get("modifier_enabled"):
        chips.append("MOD")
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
    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("Giocatori nel listone", len(catalog))
    metric_b.metric("Osservati", len(watchlist))
    metric_c.metric("Gia acquistati", len(league.get("purchases", [])))

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

    if not catalog:
        st.info("Il listone e in aggiornamento. Riprova tra poco.")
        return

    search_column, role_column, team_column, sort_column = st.columns([1.5, 0.8, 1.1, 1.1])
    search = search_column.text_input("Cerca", placeholder="Nome giocatore")
    selected_roles = role_column.multiselect("Ruolo", list(ROLE_LABELS), default=list(ROLE_LABELS))
    teams = sorted({str(player.get("team", "")) for player in catalog if player.get("team")})
    selected_teams = team_column.multiselect("Squadra", teams)
    sort_label = sort_column.selectbox(
        "Ordina per",
        ["Indice", "Quotazione", "FVM / 1000", "Quotazione prevista", "Gol attesi", "Assist attesi", "Titolarita %"],
    )

    frame = catalog_dataframe(catalog)
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
        '<span>Confronta i profili e clicca una riga per aprire la scheda completa</span></div>'
        f'<b>{len(frame)}</b></div>',
        unsafe_allow_html=True,
    )
    selected_id = _render_catalog_table(frame, key=f"catalog_board_{league['id']}")
    if selected_id:
        st.session_state[f"fantasy_selected_player_{league['id']}"] = selected_id

    selected_id = st.session_state.get(f"fantasy_selected_player_{league['id']}")
    selected_player = next((player for player in catalog if player.get("id") == selected_id), None)
    if selected_player:
        _render_player_detail(selected_player, league, workspace, storage)
    else:
        st.info("Seleziona un giocatore dalla tabella per vedere tutte le statistiche e le proiezioni.")

    watched_players = [player for player in catalog if player.get("id") in watchlist]
    if watched_players:
        with st.expander(f"Watchlist · {len(watched_players)} giocatori"):
            watch_frame = catalog_dataframe(watched_players)
            _render_catalog_table(watch_frame, key=f"watchlist_board_{league['id']}", height=260)


def _render_catalog_table(frame: pd.DataFrame, *, key: str, height: int = 560) -> str | None:
    if frame.empty:
        st.warning("Nessun giocatore corrisponde ai filtri selezionati.")
        return None
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
    display = indexed[compact_columns].copy()
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
        selection_mode="single-row",
        key=key,
        column_config={
            "Ruolo": st.column_config.TextColumn(width="small"),
            "Giocatore": st.column_config.TextColumn(width="large"),
            "Squadra": st.column_config.TextColumn(width="small"),
            "Quotazione": st.column_config.NumberColumn("Q", format="%.0f", width="small"),
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
    if not rows:
        return None
    position = rows[0]
    return str(indexed.iloc[position]["_id"]) if 0 <= position < len(indexed) else None


def _selected_dataframe_rows(event: Any) -> list[int]:
    try:
        return list(event.selection.rows)
    except AttributeError:
        if isinstance(event, dict):
            return list(event.get("selection", {}).get("rows", []))
    return []


def _render_player_detail(
    player: dict[str, Any],
    league: dict[str, Any],
    workspace: dict[str, Any],
    storage: FantasyWorkspaceStorage,
) -> None:
    role = str(player.get("role", ""))
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

    projection_tab, season_tab, advanced_tab, profile_tab = st.tabs(
        ["Proiezione 26/27", "Stagione 25/26", "Dati avanzati", "Profilo & listone"]
    )
    with projection_tab:
        _render_stat_grid([
            ("Presenze attese", player.get("expected_appearances"), 0),
            ("Gol attesi", player.get("expected_goals"), 1),
            ("Assist attesi", player.get("expected_assists"), 1),
            ("Fantamedia attesa", player.get("expected_fantasy_average"), 2),
            ("Affidabilita", player.get("reliability"), 0),
            ("Bonus", player.get("bonus"), 0),
            ("Potenziale", player.get("potential"), 0),
            ("Rischio", player.get("risk"), 0),
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
            ("Rigori segnati", player.get("penalties_scored"), 0),
            ("Rigori tirati", player.get("penalties_taken"), 0),
            ("Ammonizioni", player.get("yellow_cards"), 0),
            ("Espulsioni", player.get("red_cards"), 0),
            ("Gol subiti", player.get("goals_conceded"), 0),
            ("Rigori parati", player.get("penalties_saved"), 0),
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
            ("Gol - xG", goals_minus_xg, 2),
            ("Assist - xA", assists_minus_xa, 2),
            ("Goal prevented", player.get("goals_prevented"), 2),
        ])
        st.caption(
            "xG, xA e Goal prevented provengono dall'analisi [FotMob](https://www.fotmob.com/leagues/55/overview/serie-a). I tracking fisici "
            "(km percorsi, sprint e velocita) non sono pubblicati in modo completo e uniforme per tutti i giocatori."
        )
    with profile_tab:
        penalty_labels = {1: "Prima scelta", 2: "Seconda scelta"}
        _render_stat_grid([
            ("Ruolo Classic", player.get("role"), None),
            ("Ruolo Mantra", player.get("mantra_role"), None),
            ("Quotazione iniziale", player.get("initial_quote"), 0),
            ("Quotazione attuale", player.get("quote"), 0),
            ("FVM / 1000", player.get("fvm"), 0),
            ("Rigorista", penalty_labels.get(_int_or_none(player.get("penalty_taker")), "No"), None),
            ("Piazzati", penalty_labels.get(_int_or_none(player.get("set_pieces")), "No"), None),
            ("Stato 26/27", player.get("status"), None),
            ("Qualita dati", player.get("data_quality"), None),
            ("Fascia", player.get("tier"), None),
            ("Profilo", player.get("profile"), None),
            ("Fonte", player.get("source"), None),
        ])


def _render_stat_grid(items: list[tuple[str, Any, int | None]]) -> None:
    cards = []
    for label, value, decimals in items:
        display = (
            escape(str("—" if value is None or value == "" else value))
            if decimals is None else _format_stat(value, decimals)
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
            f"""
            <div class="fantasy-role-card {status}">
                <span>{role}</span><strong>{count}/{target}</strong><small>{label}</small>
            </div>
            """
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
    purchases = sorted(
        league.get("purchases", []),
        key=lambda row: ("PDCA".find(str(row.get("role", ""))), str(row.get("name", ""))),
    )
    if not purchases:
        return
    list_mode = league.get("game_mode") == GAME_MODE_LIST
    st.markdown("#### Rosa dal listone" if list_mode else "#### Acquisti")
    price_label = "Costo listone" if list_mode else "Prezzo asta"
    rows = [
        {
            "Ruolo": row.get("role"),
            "Giocatore": row.get("name"),
            "Squadra": row.get("team"),
            price_label: row.get("price"),
            "FM attesa": row.get("expected_fantasy_average"),
            "Gol attesi": row.get("expected_goals"),
            "Assist attesi": row.get("expected_assists"),
        }
        for row in purchases
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
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


def _render_my_squad(
    workspace: dict[str, Any],
    league: dict[str, Any],
    storage: FantasyWorkspaceStorage,
    settings: Settings,
) -> None:
    summary = roster_summary(league)
    if not league.get("purchases"):
        destination = "Componi rosa" if league.get("game_mode") == GAME_MODE_LIST else "Asta"
        st.info(f"Aggiungi i giocatori nella sezione {destination}: qui compariranno analisi e formazione.")
        return

    goals, assists, modifier, coverage = st.columns(4)
    goals.metric("Gol attesi", f"{summary['expected_goals']:.1f}")
    assists.metric("Assist attesi", f"{summary['expected_assists']:.1f}")
    modifier.metric(
        "Modificatore",
        ("Pronto" if summary["modifier_ready"] else "Da completare")
        if league.get("modifier_enabled") else "Non attivo",
    )
    coverage.metric("Copertura", f"{summary['roster_size']}/{summary['target_size']}")

    _render_squad_insights(league, summary)
    if league.get("captain_enabled"):
        _render_captain_control(workspace, league, storage)
    lineup = suggest_lineup(league)
    if lineup:
        _render_lineup(lineup, league.get("captain_player_id"))
    else:
        st.warning("Non ci sono ancora abbastanza giocatori per costruire un undici valido.")
    _render_ai_analysis(workspace, league, storage, settings, summary)


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


def _render_ai_analysis(
    workspace: dict[str, Any],
    league: dict[str, Any],
    storage: FantasyWorkspaceStorage,
    settings: Settings,
    summary: dict[str, Any],
) -> None:
    st.markdown("#### GiGi · Analisi della rosa")
    st.caption("L'IA usa rosa, prezzi, statistiche attese e regolamento di questo fanta.")
    if st.button(
        "Analizza la mia squadra",
        type="primary",
        disabled=not settings.has_gemini,
        key=f"fantasy_ai_{league['id']}",
    ):
        prompt = _fantasy_analysis_prompt(league, summary)
        try:
            with st.spinner("GiGi sta studiando la rosa..."):
                analysis = GeminiClient(settings).generate_text(prompt).strip()
        except Exception as error:
            st.error(f"Analisi non disponibile: {error}")
        else:
            if analysis:
                league["analysis"] = analysis
                league["updated_at"] = utc_now()
                touch_workspace(workspace)
                _save_workspace(workspace, storage)
                st.rerun()
    if not settings.has_gemini:
        st.info("Configura GEMINI_API_KEY per attivare l'analisi IA.")
    if league.get("analysis"):
        with st.container(border=True):
            st.markdown(league["analysis"])


def _fantasy_analysis_prompt(league: dict[str, Any], summary: dict[str, Any]) -> str:
    roster_lines = []
    for row in league.get("purchases", []):
        roster_lines.append(
            " | ".join(
                [
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
    list_mode = league.get("game_mode") == GAME_MODE_LIST
    participants = "non previsto (modalita listone)" if list_mode else league.get("participants")
    captain_id = league.get("captain_player_id")
    captain_name = next(
        (row.get("name") for row in league.get("purchases", []) if row.get("player_id") == captain_id),
        "non assegnato",
    )
    return f"""
Sei un analista esperto di fantacalcio Classic italiano. Analizza in italiano questa rosa senza inventare dati mancanti.
Fanta: {league.get('name')} - stagione {league.get('season')} - modalita {'listone' if list_mode else 'asta'} - partecipanti {participants}.
Budget iniziale: {league.get('initial_budget')}; spesi: {summary['spent']}; rimasti: {summary['remaining_budget']}.
Modificatore difesa: {'attivo' if league.get('modifier_enabled') else 'non attivo'}.
Capitano: {'regola attiva, ' + str(captain_name) if league.get('captain_enabled') else 'regola non attiva'}.
Composizione rosa prevista: {league.get('roster_slots')}.
Slot mancanti: {summary['missing']}.
Rosa:
{chr(10).join(roster_lines)}

Rispondi con queste sezioni brevi: Voto attuale su 10, Punti di forza, Rischi, Priorita per i prossimi acquisti, Strategia modificatore. Sii concreto e conciso.
""".strip()


def _save_workspace(workspace: dict[str, Any], storage: FantasyWorkspaceStorage) -> None:
    st.session_state[WORKSPACE_SESSION_KEY] = workspace
    st.session_state["fantasy_remote_save_attempted"] = storage.remote_available
    st.session_state["fantasy_remote_synced"] = storage.save(workspace)


def _render_sync_status(storage: FantasyWorkspaceStorage) -> None:
    if storage.remote_available:
        synced = st.session_state.get("fantasy_remote_synced", False)
        attempted = st.session_state.get("fantasy_remote_save_attempted", False)
        if synced:
            st.caption("● Dati sincronizzati su Supabase")
        elif attempted:
            st.warning("Salvataggio Supabase non riuscito. I dati restano disponibili solo in locale.")
        else:
            st.caption("● Supabase collegato · salvataggio al primo aggiornamento")
    else:
        st.warning(
            "I dati sono salvati solo sul dispositivo. Configura Supabase per ritrovare le squadre anche da telefono."
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
        @media (max-width:720px) {
            .fantasy-league-hero { grid-template-columns:1fr auto; }
            .fantasy-mode-stack { grid-column:1/3; justify-content:flex-start; }
            .fantasy-source-card { grid-template-columns:1fr; }
            .fantasy-source-card>div:last-child { text-align:left; }
            .fantasy-player-hero { grid-template-columns:auto 1fr; }
            .fantasy-player-score { grid-column:1/3; flex-direction:row; align-items:center; gap:.5rem; }
            .fantasy-player-score strong { font-size:1.35rem; }
            .fantasy-stat-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .fantasy-table-heading span { display:none; }
            .fantasy-role-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .fantasy-insights { grid-template-columns:1fr; }
            .fantasy-empty { padding:1.25rem .8rem; }
            .fantasy-line { grid-template-columns:28px 1fr; }
            .fantasy-line>div { font-size:.78rem; padding:.48rem; overflow-wrap:anywhere; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
