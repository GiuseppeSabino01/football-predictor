from __future__ import annotations

from typing import Any

from config.settings import Settings


class SupabaseStorage:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = None
        if settings.has_supabase:
            try:
                from supabase import create_client

                self.client = create_client(settings.supabase_url, settings.supabase_anon_key)
            except Exception:
                self.client = None

    @property
    def available(self) -> bool:
        return self.client is not None

    def insert_rows(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not self.client or not rows:
            return
        self.client.table(table).insert(rows).execute()

