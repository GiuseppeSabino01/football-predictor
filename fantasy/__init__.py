"""Fantacalcio workspace, catalog and Streamlit UI."""

from __future__ import annotations

import inspect
from typing import Any


def _auction_assignment_signature(workspace: dict[str, Any] | None) -> tuple:
    """Return only the auction data that changes managers' remaining credits."""
    if not isinstance(workspace, dict):
        return ()
    signature: list[tuple] = []
    for league in workspace.get("leagues", []):
        if not isinstance(league, dict) or league.get("game_mode") != "auction":
            continue
        league_id = str(league.get("id") or "")
        user_rows = tuple(
            sorted(
                (
                    str(row.get("player_id") or ""),
                    float(row.get("price") or 0),
                )
                for row in league.get("purchases", [])
                if isinstance(row, dict)
            )
        )
        rival_rows: list[tuple[str, tuple]] = []
        for manager in league.get("auction_managers", []):
            if not isinstance(manager, dict) or manager.get("is_user"):
                continue
            purchases = tuple(
                sorted(
                    (
                        str(row.get("player_id") or ""),
                        float(row.get("price") or 0),
                    )
                    for row in manager.get("purchases", [])
                    if isinstance(row, dict)
                )
            )
            rival_rows.append((str(manager.get("id") or ""), purchases))
        signature.append((league_id, user_rows, tuple(sorted(rival_rows))))
    return tuple(sorted(signature))


def _install_immediate_auction_credit_refresh() -> None:
    """Refresh Streamlit after an inline auction assignment is durably saved.

    The Auction Room is rendered before the editable player board. Without this
    extra rerun, its credit cards show the state from the beginning of the run
    and therefore appear one assignment late.
    """
    try:
        import streamlit as st

        from fantasy.storage import FANTASY_STATE_KEY, FantasyWorkspaceStorage
    except Exception:
        return

    original_save = FantasyWorkspaceStorage.save
    if getattr(original_save, "_fantasy_immediate_credit_refresh", False):
        return

    def save_with_immediate_credit_refresh(
        self: FantasyWorkspaceStorage, workspace: dict[str, Any]
    ) -> bool:
        inline_auction_edit = any(
            frame.function == "_render_auction_catalog_editor"
            for frame in inspect.stack(context=0)[:10]
        )
        previous_signature: tuple = ()
        if inline_auction_edit:
            try:
                previous = self.local.load_json_state(FANTASY_STATE_KEY)
                previous_signature = _auction_assignment_signature(previous)
            except Exception:
                previous_signature = ()

        current_signature = _auction_assignment_signature(workspace)
        result = original_save(self, workspace)

        # Only owner/price edits need the immediate second render. Notes and
        # personal tiers keep their normal debounced autosave behaviour.
        if inline_auction_edit and current_signature != previous_signature:
            st.rerun()
        return result

    save_with_immediate_credit_refresh._fantasy_immediate_credit_refresh = True  # type: ignore[attr-defined]
    FantasyWorkspaceStorage.save = save_with_immediate_credit_refresh


_install_immediate_auction_credit_refresh()
