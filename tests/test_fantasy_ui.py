from bs4 import BeautifulSoup
from streamlit.testing.v1 import AppTest

from fantasy.decision_center import serie_a_teams
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


def _calendar_test_app(with_roster: bool = False) -> None:
    from fantasy.decision_center import serie_a_teams
    from fantasy.ui import _render_strategic_calendar

    catalog = [
        {"team": team, "fantasy_score": index + 1}
        for index, team in enumerate(serie_a_teams())
    ]
    purchases = (
        [
            {"name": "Difensore Inter", "team": "INT", "role": "D"},
            {"name": "Difensore Milan", "team": "MIL", "role": "D"},
        ]
        if with_roster else []
    )
    _render_strategic_calendar({"id": "calendar-test", "purchases": purchases}, catalog)


def _calendar_rows(app: AppTest, matchdays: list[int]) -> dict[str, list[float]]:
    assert not app.exception
    board = next(
        element.value for element in app.markdown
        if 'class="fantasy-calendar-board"' in element.value
    )
    rows = BeautifulSoup(board, "html.parser").select(".fantasy-calendar-row")
    assert len(rows) == 20
    difficulties_by_team = {}
    averages = []
    for row in rows:
        team = row.select_one("div > strong").get_text()
        assert [
            chip.get_text() for chip in row.select("section > span > small")
        ] == [f"G{matchday}" for matchday in matchdays]
        difficulties = [
            float(chip.get_text()) for chip in row.select("section > span > b")
        ]
        average = sum(difficulties) / len(difficulties)
        assert row.select_one("div > small").get_text() == f"Difficoltà media: {average:.1f}"
        difficulties_by_team[team] = difficulties
        averages.append(average)
    assert set(difficulties_by_team) == set(serie_a_teams())
    assert all(left <= right + 1e-12 for left, right in zip(averages, averages[1:]))
    return difficulties_by_team


def test_calendar_filter_updates_fixtures_averages_and_order_without_roster() -> None:
    app = AppTest.from_function(_calendar_test_app).run()
    horizon = app.selectbox(key="calendar_limit_calendar-test")
    options = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25, 30, 35, 38]
    assert horizon.options == [str(value) for value in options]
    assert horizon.value == 5
    app.selectbox(key="calendar_start_v22_calendar-test").set_value(1)
    orders = {}
    for limit in options:
        app.selectbox(key="calendar_limit_calendar-test").set_value(limit).run()
        rows = _calendar_rows(app, list(range(1, limit + 1)))
        orders[limit] = list(rows)
    assert orders[1] != orders[38]


def test_calendar_rotations_use_visible_matches_at_end_of_season() -> None:
    app = AppTest.from_function(_calendar_test_app, args=(True,)).run()
    app.selectbox(key="calendar_start_v22_calendar-test").set_value(36)
    for limit, matchdays in [(1, [36]), (38, [36, 37, 38])]:
        app.selectbox(key="calendar_limit_calendar-test").set_value(limit).run()
        difficulties = _calendar_rows(app, matchdays)
        best_each_week = [
            min(inter, milan)
            for inter, milan in zip(difficulties["INTER"], difficulties["MILAN"])
        ]
        expected_rotation = sum(best_each_week) / len(matchdays)
        rotation = next(
            element.value for element in app.markdown
            if 'class="fantasy-rotation-card"' in element.value
        )
        assert f"scelta migliore: {expected_rotation:.2f}/5" in rotation
    assert any("G36–G38 · 3 giornate" in caption.value for caption in app.caption)
    app.selectbox(key="calendar_start_v22_calendar-test").set_value(38).run()
    _calendar_rows(app, [38])
    assert any("G38 · 1 giornata" in caption.value for caption in app.caption)
