from fantasy.ui import _auction_assigned_row_class_rule


def test_assigned_row_rule_follows_the_live_participant_cell() -> None:
    rule = _auction_assigned_row_class_rule("— Non assegnato —")

    assert "params.data['Partecipante']" in rule.js_code
    assert "!== \"— Non assegnato —\"" in rule.js_code
    assert "_assigned" not in rule.js_code
