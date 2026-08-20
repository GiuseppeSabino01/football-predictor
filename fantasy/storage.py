from __future__ import annotations

from copy import deepcopy
from typing import Any

from config.settings import Settings
from fantasy.service import new_workspace, normalize_workspace
from storage.sqlite_client import SQLiteStorage
from storage.supabase_client import SupabaseStorage


FANTASY_STATE_KEY = "app-state:fantacalcio:v2"
LEGACY_FANTASY_STATE_KEY = "app-state:fantacalcio:v1"


class FantasyWorkspaceStorage:
    """Persist the single-user workspace locally and, when configured, remotely."""

    def __init__(self, settings: Settings):
        self.local = SQLiteStorage(settings.sqlite_path)
        self.remote = SupabaseStorage(settings)
        self.last_remote_save_ok = False
        self.last_remote_error = ""

    @property
    def remote_available(self) -> bool:
        return self.remote.available

    def load(self) -> dict[str, Any]:
        local_payload = self.local.load_json_state(FANTASY_STATE_KEY)
        if not local_payload:
            local_payload = self.local.load_json_state(LEGACY_FANTASY_STATE_KEY)
        local_workspace = normalize_workspace(local_payload or new_workspace())
        if self.remote_available:
            remote_payload = self.remote.load_json_state(FANTASY_STATE_KEY)
            loaded_legacy = False
            if not remote_payload:
                remote_payload = self.remote.load_json_state(LEGACY_FANTASY_STATE_KEY)
                loaded_legacy = bool(remote_payload)
            if remote_payload:
                self.last_remote_save_ok = True
                workspace = _restore_catalog_from_local(remote_payload, local_workspace)
                self.local.upsert_json_state(FANTASY_STATE_KEY, "Fantacalcio workspace", workspace)
                if loaded_legacy:
                    self.save(workspace)
                return workspace
            self.last_remote_error = getattr(self.remote, "last_error", "")
            if local_workspace.get("leagues"):
                self.save(local_workspace)
        return local_workspace

    def save(self, workspace: dict[str, Any]) -> bool:
        normalized = normalize_workspace(workspace)
        self.local.upsert_json_state(FANTASY_STATE_KEY, "Fantacalcio workspace", normalized)
        if not self.remote_available:
            self.last_remote_save_ok = False
            self.last_remote_error = getattr(self.remote, "last_error", "")
            return False
        self.last_remote_save_ok = self.remote.upsert_json_state(
            FANTASY_STATE_KEY,
            "Fantacalcio workspace",
            _remote_workspace_payload(normalized),
        )
        self.last_remote_error = getattr(self.remote, "last_error", "")
        return self.last_remote_save_ok


def _remote_workspace_payload(workspace: dict[str, Any]) -> dict[str, Any]:
    """Keep user-owned fantasy data in the cloud without the replaceable catalog."""
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
    remote_payload: dict[str, Any], local_workspace: dict[str, Any]
) -> dict[str, Any]:
    """Remote leagues are authoritative; the local catalog is only a warm cache."""
    workspace = normalize_workspace(remote_payload)
    if not workspace.get("catalog") and local_workspace.get("catalog"):
        workspace["catalog"] = deepcopy(local_workspace["catalog"])
        workspace["catalog_meta"] = deepcopy(local_workspace.get("catalog_meta", {}))
    return workspace
