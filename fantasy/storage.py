from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from typing import Any

from config.settings import Settings
from fantasy.service import new_workspace, normalize_workspace
from storage.sqlite_client import SQLiteStorage
from storage.supabase_client import SupabaseStorage


FANTASY_STATE_KEY = "app-state:fantacalcio:v2"
LEGACY_FANTASY_STATE_KEY = "app-state:fantacalcio:v1"
BROWSER_FANTASY_STATE_KEY = "football-predictor:fantacalcio:v2"


class BrowserWorkspaceStorage:
    """Durable per-browser backup used when the Streamlit container is recycled."""

    def __init__(self) -> None:
        self.client = None
        self.last_error = ""
        try:
            from streamlit.runtime.scriptrunner import get_script_run_ctx

            if get_script_run_ctx() is None:
                self.last_error = "Browser storage disponibile solo durante una sessione Streamlit."
                return
            from streamlit_local_storage import LocalStorage

            # A stable component key lets the package hydrate its cached browser values
            # before the app continues rendering after a fresh Streamlit session.
            self.client = LocalStorage(key="fantasy_browser_storage_init")
        except Exception as error:
            self.last_error = _safe_error(error)
            self.client = None

    @property
    def available(self) -> bool:
        return self.client is not None

    def load_json_state(self, state_key: str) -> dict[str, Any] | None:
        if not self.client:
            return None
        try:
            raw = self.client.getItem(state_key)
            self.last_error = ""
        except Exception as error:
            self.last_error = _safe_error(error)
            return None
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str) or not raw:
            return None
        try:
            decoded = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            self.last_error = _safe_error(error)
            return None
        return decoded if isinstance(decoded, dict) else None

    def upsert_json_state(self, state_key: str, payload: dict[str, Any]) -> bool:
        if not self.client:
            return False
        try:
            encoded = json.dumps(
                _browser_json_safe(payload),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            self.client.setItem(
                state_key,
                encoded,
                key="fantasy_browser_storage_set",
            )
        except Exception as error:
            self.last_error = _safe_error(error)
            return False
        self.last_error = ""
        return True


class FantasyWorkspaceStorage:
    """Persist the workspace locally, in the browser, and remotely when configured."""

    def __init__(self, settings: Settings):
        self.local = SQLiteStorage(settings.sqlite_path)
        self.browser = BrowserWorkspaceStorage()
        self.remote = SupabaseStorage(settings)
        self.last_remote_save_ok = False
        self.last_remote_error = ""
        self.last_browser_save_ok = False
        self.last_browser_error = ""

    @property
    def remote_available(self) -> bool:
        return self.remote.available

    @property
    def browser_available(self) -> bool:
        return self.browser.available

    def load(self) -> dict[str, Any]:
        local_payload = self.local.load_json_state(FANTASY_STATE_KEY)
        if not local_payload:
            local_payload = self.local.load_json_state(LEGACY_FANTASY_STATE_KEY)
        local_workspace = normalize_workspace(local_payload) if local_payload else None

        browser_payload = self.browser.load_json_state(BROWSER_FANTASY_STATE_KEY)
        if not browser_payload:
            browser_payload = self.browser.load_json_state(FANTASY_STATE_KEY)
        browser_workspace = normalize_workspace(browser_payload) if browser_payload else None
        self.last_browser_error = getattr(self.browser, "last_error", "")

        remote_payload: dict[str, Any] | None = None
        loaded_remote_legacy = False
        if self.remote_available:
            remote_payload = self.remote.load_json_state(FANTASY_STATE_KEY)
            if not remote_payload:
                remote_payload = self.remote.load_json_state(LEGACY_FANTASY_STATE_KEY)
                loaded_remote_legacy = bool(remote_payload)
            self.last_remote_error = getattr(self.remote, "last_error", "")
            self.last_remote_save_ok = bool(remote_payload) and not self.last_remote_error
        remote_workspace = normalize_workspace(remote_payload) if remote_payload else None

        candidates: list[tuple[str, dict[str, Any]]] = []
        if local_workspace:
            candidates.append(("local", local_workspace))
        if browser_workspace:
            candidates.append(("browser", browser_workspace))
        if remote_workspace:
            candidates.append(("remote", remote_workspace))

        if not candidates:
            return new_workspace()

        source, workspace = max(
            candidates,
            key=lambda item: _workspace_sort_key(item[1], item[0]),
        )
        workspace = _restore_catalog_from_local(
            workspace,
            local_workspace or normalize_workspace(new_workspace()),
        )
        self.local.upsert_json_state(FANTASY_STATE_KEY, "Fantacalcio workspace", workspace)

        # Reconcile all durable copies from the newest snapshot. This is what makes
        # an outage recover automatically once Supabase becomes reachable again.
        browser_snapshot = _remote_workspace_payload(workspace)
        if source != "browser" or loaded_remote_legacy:
            self.last_browser_save_ok = self.browser.upsert_json_state(
                BROWSER_FANTASY_STATE_KEY,
                browser_snapshot,
            )
            self.last_browser_error = getattr(self.browser, "last_error", "")
        else:
            self.last_browser_save_ok = True

        if self.remote_available and (source != "remote" or loaded_remote_legacy):
            self.last_remote_save_ok = self.remote.upsert_json_state(
                FANTASY_STATE_KEY,
                "Fantacalcio workspace",
                browser_snapshot,
            )
            self.last_remote_error = getattr(self.remote, "last_error", "")

        return workspace

    def save(self, workspace: dict[str, Any]) -> bool:
        normalized = normalize_workspace(workspace)
        self.local.upsert_json_state(FANTASY_STATE_KEY, "Fantacalcio workspace", normalized)

        durable_payload = _remote_workspace_payload(normalized)
        self.last_browser_save_ok = self.browser.upsert_json_state(
            BROWSER_FANTASY_STATE_KEY,
            durable_payload,
        )
        self.last_browser_error = getattr(self.browser, "last_error", "")

        if not self.remote_available:
            self.last_remote_save_ok = False
            self.last_remote_error = getattr(self.remote, "last_error", "")
            return False
        self.last_remote_save_ok = self.remote.upsert_json_state(
            FANTASY_STATE_KEY,
            "Fantacalcio workspace",
            durable_payload,
        )
        self.last_remote_error = getattr(self.remote, "last_error", "")
        return self.last_remote_save_ok


def _remote_workspace_payload(workspace: dict[str, Any]) -> dict[str, Any]:
    """Keep user-owned fantasy data in durable storage without the replaceable catalog."""
    normalized = normalize_workspace(workspace)
    return {
        "version": max(int(normalized.get("version") or 1), 2),
        "updated_at": normalized.get("updated_at"),
        "active_league_id": normalized.get("active_league_id"),
        "catalog": [],
        "catalog_meta": {},
        "leagues": deepcopy(normalized.get("leagues", [])),
    }


def _restore_catalog_from_local(
    durable_payload: dict[str, Any], local_workspace: dict[str, Any]
) -> dict[str, Any]:
    """Durable leagues are authoritative; the local catalog is only a warm cache."""
    workspace = normalize_workspace(durable_payload)
    if not workspace.get("catalog") and local_workspace.get("catalog"):
        workspace["catalog"] = deepcopy(local_workspace["catalog"])
        workspace["catalog_meta"] = deepcopy(local_workspace.get("catalog_meta", {}))
    return workspace


def _workspace_sort_key(workspace: dict[str, Any], source: str) -> tuple[float, int]:
    """Choose the newest snapshot; prefer cloud/browser over local on exact ties."""
    raw = str(workspace.get("updated_at") or "").strip()
    timestamp = 0.0
    if raw:
        try:
            timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            timestamp = 0.0
    source_priority = {"local": 0, "browser": 1, "remote": 2}.get(source, 0)
    return timestamp, source_priority


def _browser_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _browser_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_browser_json_safe(item) for item in value]
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            return None
    return value


def _safe_error(error: Exception) -> str:
    message = " ".join(str(error).split())
    return message[:280] or error.__class__.__name__
