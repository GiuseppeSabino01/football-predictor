from fantasy.ui import _auction_assigned_row_class_rule, _auction_credit_column


def test_assigned_row_rule_follows_the_live_participant_cell() -> None:
    rule = _auction_assigned_row_class_rule("— Non assegnato —")

    assert "params.data['Partecipante']" in rule.js_code
    assert "!== \"— Non assegnato —\"" in rule.js_code
    assert "_assigned" not in rule.js_code


def test_auction_credits_stay_pinned_and_editable() -> None:
    column = _auction_credit_column()

    assert column["field"] == "Prezzo asta"
    assert column["headerName"] == "Crediti"
    assert column["pinned"] == "left"
    assert column["lockPinned"] is True
    assert column["editable"] is True
