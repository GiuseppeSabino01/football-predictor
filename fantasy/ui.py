from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from config.settings import Settings
from fantasy.catalog import catalog_dataframe, make_player, merge_catalog, read_catalog_file
from fantasy.service import (
    DEFAULT_ROSTER_SLOTS,
    ROLE_LABELS,
    add_purchase,
    create_league,
    delete_league,
    find_league,
    remove_purchase,
    roster_summary,
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
    storage = FantasyWorkspaceStorage(settings)
    workspace = _load_workspace(storage)

    if not workspace.get("leagues"):
        _render_empty_workspace(workspace, storage)
        return

    league = _render_league_switcher(workspace, storage)
    if not league:
        return

    summary = roster_summary(league)
    _render_league_hero(league, summary)
    preparation_tab, auction_tab, squad_tab = st.tabs(
        ["Preparati all'asta", "Asta", "La mia squadra"]
    )
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
    with st.form(f"create_fantasy_league_{key_suffix}"):
        name = st.text_input("Nome", placeholder="Es. Fanta amici")
        col_budget, col_players = st.columns(2)
        budget = col_budget.number_input("Budget", min_value=50, max_value=2000, value=250, step=10)
        participants = col_players.number_input("Partecipanti", min_value=2, max_value=30, value=10)
        season = st.text_input("Stagione", value="2026/27")
        modifier = st.toggle("Modificatore difesa", value=True)
        submitted = st.form_submit_button("Crea fantacalcio", type="primary", use_container_width=True)
    if not submitted:
        return
    try:
        create_league(
            workspace,
            name,
            initial_budget=int(budget),
            participants=int(participants),
            season=season,
            roster_slots=DEFAULT_ROSTER_SLOTS,
            modifier_enabled=modifier,
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
    with st.form(f"manage_league_{league['id']}"):
        name = st.text_input("Nome", value=league["name"])
        budget = st.number_input(
            "Budget iniziale",
            min_value=1,
            max_value=5000,
            value=int(league.get("initial_budget", 250)),
        )
        participants = st.number_input(
            "Partecipanti",
            min_value=2,
            max_value=30,
            value=int(league.get("participants", 10)),
        )
        modifier = st.toggle("Modificatore difesa", value=bool(league.get("modifier_enabled")))
        save_settings = st.form_submit_button("Salva", type="primary", use_container_width=True)
    if save_settings:
        try:
            update_league_settings(
                league,
                name=name,
                initial_budget=int(budget),
                participants=int(participants),
                modifier_enabled=modifier,
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
    modifier_label = "MOD ON" if league.get("modifier_enabled") else "CLASSIC"
    st.markdown(
        f"""
        <section class="fantasy-league-hero">
            <div>
                <p class="fantasy-eyebrow">{escape(str(league.get('season', '')))} · {league.get('participants', 0)} PARTECIPANTI</p>
                <h2>{escape(str(league.get('name', 'Fantacalcio')))}</h2>
                <p>Rosa {summary['roster_size']}/{summary['target_size']} · {summary['remaining_budget']:.0f} crediti disponibili</p>
            </div>
            <div class="fantasy-ring" style="--progress:{completion * 3.6}deg">
                <span>{completion}%</span>
            </div>
            <div class="fantasy-mode-chip">{modifier_label}</div>
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

    with st.expander("Importa o aggiorna il listone", expanded=not catalog):
        st.caption("Carica CSV o Excel. Riconosco automaticamente le principali colonne del listone Classic.")
        uploaded = st.file_uploader(
            "Listone Fantacalcio",
            type=["csv", "xlsx"],
            key="fantasy_catalog_upload",
        )
        if st.button("Importa listone", disabled=uploaded is None, type="primary"):
            try:
                incoming = read_catalog_file(uploaded, uploaded.name)
            except (ValueError, ImportError) as error:
                st.error(str(error))
            else:
                workspace["catalog"] = merge_catalog(catalog, incoming)
                touch_workspace(workspace)
                _save_workspace(workspace, storage)
                st.success(f"Importati {len(incoming)} giocatori.")
                st.rerun()
        _render_manual_player_form(workspace, storage)

    if not catalog:
        st.info("Importa il listone oppure aggiungi il primo giocatore manualmente per iniziare l'analisi.")
        return

    search_column, role_column, team_column, sort_column = st.columns([1.5, 0.8, 1.1, 1.1])
    search = search_column.text_input("Cerca", placeholder="Nome giocatore")
    selected_roles = role_column.multiselect("Ruolo", list(ROLE_LABELS), default=list(ROLE_LABELS))
    teams = sorted({str(player.get("team", "")) for player in catalog if player.get("team")})
    selected_teams = team_column.multiselect("Squadra", teams)
    sort_label = sort_column.selectbox(
        "Ordina per",
        ["Indice", "Quotazione", "Quotazione prevista", "Gol attesi", "Assist attesi", "Titolarita %"],
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

    visible_ids = frame["_id"].tolist()
    _render_watchlist_control(catalog, visible_ids, league, workspace, storage)
    display = frame.drop(columns=["_id"])
    st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
        height=min(620, 92 + max(len(display), 1) * 35),
        column_config={
            "Quotazione": st.column_config.NumberColumn(format="%.0f"),
            "Quotazione prevista": st.column_config.NumberColumn(format="%.0f"),
            "Indice": st.column_config.NumberColumn(format="%.1f"),
            "Titolarita %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
        },
    )

    watched_players = [player for player in catalog if player.get("id") in watchlist]
    if watched_players:
        st.markdown("#### La tua watchlist")
        st.dataframe(
            catalog_dataframe(watched_players).drop(columns=["_id"]),
            hide_index=True,
            use_container_width=True,
        )


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
    summary = roster_summary(league)
    _render_budget_metrics(summary)
    progress = summary["roster_size"] / max(summary["target_size"], 1)
    st.progress(min(progress, 1.0), text=f"Rosa completata al {progress:.0%}")
    _render_role_plan(league, summary)

    catalog = workspace.get("catalog", [])
    purchased_ids = {row.get("player_id") for row in league.get("purchases", [])}
    available = [player for player in catalog if player.get("id") not in purchased_ids]
    if available:
        st.markdown("#### Registra un acquisto")
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
        price = price_column.number_input(
            "Prezzo",
            min_value=0.0,
            max_value=float(max(summary["remaining_budget"], default_price, 1)),
            value=min(default_price, float(max(summary["remaining_budget"], 0))),
            step=1.0,
            key=f"auction_price_{league['id']}_{selected_id}",
        )
        if button_column.button("Acquista", type="primary", use_container_width=True):
            try:
                add_purchase(league, selected_player, price)
            except ValueError as error:
                st.error(str(error))
            else:
                touch_workspace(workspace)
                _save_workspace(workspace, storage)
                st.rerun()
    else:
        st.info("Importa il listone in 'Preparati all'asta' per registrare rapidamente gli acquisti.")

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
    st.markdown("#### Acquisti")
    rows = [
        {
            "Ruolo": row.get("role"),
            "Giocatore": row.get("name"),
            "Squadra": row.get("team"),
            "Prezzo": row.get("price"),
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
        st.info("Registra gli acquisti nella sezione Asta: qui compariranno analisi, formazione e modificatore.")
        return

    goals, assists, modifier, coverage = st.columns(4)
    goals.metric("Gol attesi", f"{summary['expected_goals']:.1f}")
    assists.metric("Assist attesi", f"{summary['expected_assists']:.1f}")
    modifier.metric("Modificatore", "Pronto" if summary["modifier_ready"] else "Da completare")
    coverage.metric("Copertura", f"{summary['roster_size']}/{summary['target_size']}")

    _render_squad_insights(league, summary)
    lineup = suggest_lineup(league)
    if lineup:
        _render_lineup(lineup)
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


def _render_lineup(lineup: dict[str, Any]) -> None:
    st.markdown(f"#### Formazione consigliata · {lineup['formation']}")
    role_lines = []
    for role in ("A", "C", "D", "P"):
        names = " · ".join(escape(str(player.get("name", ""))) for player in lineup["players"][role])
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
                    f"titolarita {row.get('starter_probability')}",
                ]
            )
        )
    return f"""
Sei un analista esperto di fantacalcio Classic italiano. Analizza in italiano questa rosa senza inventare dati mancanti.
Fanta: {league.get('name')} - stagione {league.get('season')} - {league.get('participants')} partecipanti.
Budget iniziale: {league.get('initial_budget')}; spesi: {summary['spent']}; rimasti: {summary['remaining_budget']}.
Modificatore difesa: {'attivo' if league.get('modifier_enabled') else 'non attivo'}.
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
        .fantasy-mode-chip { padding:.55rem .7rem; border:1px solid rgba(255,176,32,.4); border-radius:8px; color:#ffe0a0; background:rgba(255,176,32,.1); font-size:.75rem; font-weight:900; }
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
            .fantasy-mode-chip { grid-column:1/3; width:fit-content; }
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
