from app import streamlit_app


def test_fantasy_reload_refreshes_export_before_ui() -> None:
    delattr(streamlit_app.fantasy_export, "restore_listone_excel")

    refreshed_ui = streamlit_app.fresh_fantasy_ui()

    assert hasattr(streamlit_app.fantasy_export, "restore_listone_excel")
    assert hasattr(refreshed_ui, "restore_listone_excel")


def test_fantasy_reload_refreshes_decision_center_before_ui() -> None:
    delattr(streamlit_app.fantasy_decision_center, "injury_return_label")

    refreshed_ui = streamlit_app.fresh_fantasy_ui()

    assert hasattr(streamlit_app.fantasy_decision_center, "injury_return_label")
    assert hasattr(refreshed_ui, "injury_return_label")


def test_fantasy_reload_refreshes_injury_registry_before_ui() -> None:
    delattr(streamlit_app.fantasy_injuries, "fetch_injury_registry")

    streamlit_app.fresh_fantasy_ui()

    assert hasattr(streamlit_app.fantasy_injuries, "fetch_injury_registry")


def test_fantasy_reload_refreshes_catalog_before_ui() -> None:
    delattr(streamlit_app.fantasy_catalog, "catalog_dataframe")

    refreshed_ui = streamlit_app.fresh_fantasy_ui()

    assert hasattr(streamlit_app.fantasy_catalog, "catalog_dataframe")
    frame = streamlit_app.fantasy_catalog.catalog_dataframe(
        [{"id": "test", "name": "Test", "team": "INT", "role": "C"}]
    )
    assert "Origine dati" in frame.columns
    assert refreshed_ui.catalog_dataframe is streamlit_app.fantasy_catalog.catalog_dataframe


def test_fantasy_reload_refreshes_player_history_before_estimates() -> None:
    delattr(streamlit_app.fantasy_player_history, "attach_player_history")

    streamlit_app.fresh_fantasy_ui()

    assert hasattr(streamlit_app.fantasy_player_history, "attach_player_history")
    assert (
        streamlit_app.fantasy_catalog_estimates.attach_player_history
        is streamlit_app.fantasy_player_history.attach_player_history
    )
