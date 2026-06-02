from __future__ import annotations

import json
from typing import Any

from config.settings import Settings
from schemas import MatchPrediction
from storage.llm_cache import llm_payload


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

    def load_llm_prediction(self, cache_key: str) -> dict[str, Any] | None:
        if not self.client:
            return None
        try:
            response = (
                self.client.table("llm_prediction_cache")
                .select("payload_json")
                .eq("cache_key", cache_key)
                .limit(1)
                .execute()
            )
        except Exception:
            return None
        rows = getattr(response, "data", None) or []
        if not rows:
            return None
        payload = rows[0].get("payload_json")
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError:
                return None
            return decoded if isinstance(decoded, dict) else None
        return None

    def upsert_llm_prediction(self, cache_key: str, prediction: MatchPrediction, model: str) -> bool:
        if not self.client:
            return False
        row = {
            "cache_key": cache_key,
            "match_id": prediction.match.id,
            "match_label": prediction.match.label,
            "match_date": prediction.match.match_date.isoformat(),
            "model": model,
            "generated_at": prediction.generated_at.isoformat(),
            "payload_json": llm_payload(prediction, model),
        }
        try:
            self.client.table("llm_prediction_cache").upsert(row, on_conflict="cache_key").execute()
        except Exception:
            return False
        return True
