from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import Settings
from schemas import MatchPrediction
from storage.llm_cache import llm_payload


class SupabaseStorage:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = None
        self.last_error = ""
        self.http = _retrying_session()
        if settings.has_supabase:
            try:
                from supabase import create_client

                self.client = create_client(settings.supabase_url, settings.supabase_anon_key)
            except Exception as error:
                self.last_error = _safe_error(error)
                self.client = None
        else:
            self.last_error = "SUPABASE_URL o SUPABASE_ANON_KEY non configurati."

    @property
    def available(self) -> bool:
        return bool(self.settings.has_supabase)

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

    def load_json_state(self, state_key: str) -> dict[str, Any] | None:
        if not self.available:
            return None
        rows: list[dict[str, Any]] = []
        if self.client:
            try:
                response = (
                    self.client.table("llm_prediction_cache")
                    .select("payload_json")
                    .eq("cache_key", state_key)
                    .limit(1)
                    .execute()
                )
                rows = getattr(response, "data", None) or []
                self.last_error = ""
            except Exception as error:
                self.last_error = _safe_error(error)
        if not rows:
            rows = self._rest_load_json_state(state_key)
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

    def upsert_json_state(self, state_key: str, label: str, payload: dict[str, Any]) -> bool:
        if not self.available:
            return False
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "cache_key": state_key,
            "match_id": "app-state",
            "match_label": label,
            "match_date": now[:10],
            "model": "app-state-v1",
            "generated_at": now,
            "payload_json": _json_safe(payload),
        }
        if self.client:
            try:
                self.client.table("llm_prediction_cache").upsert(
                    row, on_conflict="cache_key"
                ).execute()
                self.last_error = ""
                return True
            except Exception as error:
                self.last_error = _safe_error(error)
        return self._rest_upsert_json_state(row)

    def _rest_load_json_state(self, state_key: str) -> list[dict[str, Any]]:
        try:
            response = self.http.get(
                self._rest_table_url(),
                headers=self._rest_headers(),
                params={
                    "select": "payload_json",
                    "cache_key": f"eq.{state_key}",
                    "limit": "1",
                },
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                self.last_error = ""
                return [row for row in payload if isinstance(row, dict)]
        except Exception as error:
            self.last_error = _safe_error(error)
        return []

    def _rest_upsert_json_state(self, row: dict[str, Any]) -> bool:
        headers = self._rest_headers()
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
        try:
            response = self.http.post(
                self._rest_table_url(),
                headers=headers,
                params={"on_conflict": "cache_key"},
                json=row,
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
        except Exception as error:
            self.last_error = _safe_error(error)
            return False
        self.last_error = ""
        return True

    def _rest_table_url(self) -> str:
        return f"{self.settings.supabase_url.rstrip('/')}/rest/v1/llm_prediction_cache"

    def _rest_headers(self) -> dict[str, str]:
        return {
            "apikey": self.settings.supabase_anon_key,
            "Authorization": f"Bearer {self.settings.supabase_anon_key}",
            "Content-Type": "application/json",
        }

    def insert_worldcup_simulation(self, run_id: str, generated_at: str, label: str, model: str, payload: dict) -> bool:
        if not self.client:
            return False
        row = {
            "run_id": run_id,
            "generated_at": generated_at,
            "label": label,
            "model": model,
            "payload_json": payload,
        }
        try:
            self.client.table("worldcup_simulation_runs").insert(row).execute()
        except Exception:
            return False
        return True

    def list_worldcup_simulations(self, limit: int = 8) -> list[dict[str, Any]]:
        if not self.client:
            return []
        try:
            response = (
                self.client.table("worldcup_simulation_runs")
                .select("run_id, generated_at, label, model, payload_json")
                .order("generated_at", desc=True)
                .limit(limit)
                .execute()
            )
        except Exception:
            return []
        rows = getattr(response, "data", None) or []
        simulations: list[dict[str, Any]] = []
        for row in rows:
            payload = row.get("payload_json")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = None
            if isinstance(payload, dict):
                simulations.append(
                    {
                        "run_id": row.get("run_id", ""),
                        "generated_at": row.get("generated_at", ""),
                        "label": row.get("label", ""),
                        "model": row.get("model", ""),
                        "payload": payload,
                    }
                )
        return simulations


def _retrying_session() -> requests.Session:
    """Retry transient Supabase network/DNS failures without duplicating app state."""
    retry = Retry(
        total=3,
        connect=3,
        read=0,
        status=2,
        backoff_factor=0.4,
        status_forcelist=(502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _json_safe(value: Any) -> Any:
    """Return a Postgres-jsonb-safe copy, replacing NaN and infinities."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _safe_error(error: Exception) -> str:
    message = " ".join(str(error).split())
    lowered = message.casefold()
    if "nameresolutionerror" in lowered or "failed to resolve" in lowered:
        return (
            "Supabase temporaneamente non raggiungibile per un errore DNS. "
            "Il salvataggio verra ritentato automaticamente; il backup browser resta disponibile."
        )
    if "connectionerror" in lowered or "max retries exceeded" in lowered:
        return (
            "Connessione a Supabase temporaneamente non disponibile. "
            "Il salvataggio verra ritentato automaticamente; il backup browser resta disponibile."
        )
    return message[:280] or error.__class__.__name__
