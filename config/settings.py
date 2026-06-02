from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
LOCAL_TZ = ZoneInfo("Europe/Rome")


def _streamlit_secret(name: str) -> str | None:
    try:
        import streamlit as st

        value = st.secrets.get(name)
        return str(value) if value else None
    except Exception:
        return None


def _get_secret(name: str, default: str = "") -> str:
    return os.getenv(name) or _streamlit_secret(name) or default


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    gemini_model: str
    api_football_key: str
    api_football_free_mode: bool
    football_data_org_key: str
    the_odds_api_key: str
    odds_region: str
    supabase_url: str
    supabase_anon_key: str
    app_password: str
    sqlite_path: Path
    verify_ssl: bool
    request_timeout_seconds: int = 20
    local_timezone: ZoneInfo = LOCAL_TZ

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def has_api_football(self) -> bool:
        return bool(self.api_football_key)

    @property
    def has_football_data_org(self) -> bool:
        return bool(self.football_data_org_key)

    @property
    def has_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)


def load_settings() -> Settings:
    load_dotenv(ROOT_DIR / ".env", override=False)
    settings = Settings(
        gemini_api_key=_get_secret("GEMINI_API_KEY"),
        gemini_model=_get_secret("GEMINI_MODEL", "gemini-2.5-flash"),
        api_football_key=_get_secret("API_FOOTBALL_KEY"),
        api_football_free_mode=_as_bool(_get_secret("API_FOOTBALL_FREE_MODE", "true")),
        football_data_org_key=_get_secret("FOOTBALL_DATA_ORG_KEY"),
        the_odds_api_key=_get_secret("THE_ODDS_API_KEY"),
        odds_region=_get_secret("ODDS_REGION", "eu"),
        supabase_url=_get_secret("SUPABASE_URL"),
        supabase_anon_key=_get_secret("SUPABASE_ANON_KEY"),
        app_password=_get_secret("APP_PASSWORD"),
        sqlite_path=ROOT_DIR / "data" / "football_predictor.sqlite3",
        verify_ssl=not _as_bool(_get_secret("DISABLE_SSL_VERIFY", "false")),
    )
    if not settings.verify_ssl:
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
    return settings
