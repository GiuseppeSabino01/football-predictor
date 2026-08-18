from __future__ import annotations

from typing import Any

from config.settings import Settings
from fantasy.service import new_workspace, normalize_workspace
from storage.sqlite_client import SQLiteStorage
from storage.supabase_client import SupabaseStorage


FANTASY_STATE_KEY = "app-state:fantacalcio:v1"


class FantasyWorkspaceStorage:
    """Persist the single-user workspace locally and, when configured, remotely."""

    def __init__(self, settings: Settings):
        self.local = SQLiteStorage(settings.sqlite_path)
        self.remote = SupabaseStorage(settings)
        self.last_remote_save_ok = False

    @property
    def remote_available(self) -> bool:
        return self.remote.available

    def load(self) -> dict[str, Any]:
        if self.remote_available:
            remote_payload = self.remote.load_json_state(FANTASY_STATE_KEY)
            if remote_payload:
                self.last_remote_save_ok = True
                workspace = normalize_workspace(remote_payload)
                self.local.upsert_json_state(FANTASY_STATE_KEY, "Fantacalcio workspace", workspace)
                return workspace
        local_payload = self.local.load_json_state(FANTASY_STATE_KEY)
        return normalize_workspace(local_payload or new_workspace())

    def save(self, workspace: dict[str, Any]) -> bool:
        normalized = normalize_workspace(workspace)
        self.local.upsert_json_state(FANTASY_STATE_KEY, "Fantacalcio workspace", normalized)
        self.last_remote_save_ok = self.remote.upsert_json_state(
            FANTASY_STATE_KEY,
            "Fantacalcio workspace",
            normalized,
        )
        return self.last_remote_save_ok
