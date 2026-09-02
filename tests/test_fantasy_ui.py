from fantasy.ui import (
    _auction_assigned_row_class_rule,
    _auction_player_column,
    _auction_trade_gain_gap,
    _auction_updated_price_column,
    _strategic_calendar_groups,
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


def test_trade_gain_gap_supports_proposals_cached_by_older_builds() -> None:
    assert _auction_trade_gain_gap(
        {"user_improvement": 8.0, "opponent_improvement": 5.5}
    ) == 2.5
    assert _auction_trade_gain_gap(
        {
            "gain_gap": 1.25,
            "user_improvement": 8.0,
            "opponent_improvement": 5.5,
        }
    ) == 1.25


def test_strategic_calendar_contains_all_teams_without_players() -> None:
    groups = _strategic_calendar_groups({"purchases": []})

    assert len(groups) == 20
    assert all(names == [] for names in groups.values())


def test_strategic_calendar_adds_owned_players_without_hiding_other_teams() -> None:
    groups = _strategic_calendar_groups(
        {"purchases": [{"name": "Lautaro", "team": "INT"}]}
    )

    assert len(groups) == 20
    assert groups["INTER"] == ["Lautaro"]
