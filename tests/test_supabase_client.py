from __future__ import annotations

from storage.supabase_client import _retrying_session, _safe_error


def test_supabase_rest_session_retries_connect_and_post() -> None:
    session = _retrying_session()
    adapter = session.get_adapter("https://")
    retry = adapter.max_retries

    assert retry.connect == 3
    assert retry.total == 3
    assert "GET" in retry.allowed_methods
    assert "POST" in retry.allowed_methods
    assert 503 in retry.status_forcelist


def test_dns_error_is_reported_as_temporary_and_mentions_browser_backup() -> None:
    message = _safe_error(
        RuntimeError(
            "NameResolutionError: Failed to resolve 'example.supabase.co'"
        )
    )

    assert "temporaneamente" in message
    assert "DNS" in message
    assert "backup browser" in message
