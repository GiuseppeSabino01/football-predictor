from app import streamlit_app


def test_fantasy_reload_refreshes_export_before_ui() -> None:
    delattr(streamlit_app.fantasy_export, "restore_listone_excel")

    refreshed_ui = streamlit_app.fresh_fantasy_ui()

    assert hasattr(streamlit_app.fantasy_export, "restore_listone_excel")
    assert hasattr(refreshed_ui, "restore_listone_excel")
