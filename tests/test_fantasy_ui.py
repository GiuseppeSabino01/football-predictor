from fantasy.ui import (
    _auction_assigned_row_class_rule,
    _auction_player_column,
    _auction_updated_price_column,
)


def test_assigned_row_rule_follows_the_live_participant_cell() -> None:
    rule = _auction_assigned_row_class_rule("— Non assegnato —")

    assert "params.data['Partecipante']" in rule.js_code
    assert "!== \"— Non assegnato —\"" in rule.js_code
    assert "_assigned" not in rule.js_code


def test_live_auction_price_stays_pinned() -> None:
    column = _auction_updated_price_column()

    assert column["field"] == "Spesa aggiornata"
    assert column["headerName"] == "Prezzo aggiornato"
    assert column["pinned"] == "left"
    assert column["lockPinned"] is True
    assert "editable" not in column


def test_auction_player_column_is_compact_and_pinned() -> None:
    column = _auction_player_column()

    assert column["field"] == "Giocatore"
    assert column["width"] == 155
    assert column["minWidth"] == 135
    assert column["pinned"] == "left"
