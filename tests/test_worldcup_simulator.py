import random
from datetime import datetime, timezone

from schemas import Match, MatchPrediction, MarketPick
from services.worldcup_simulator import (
    NEXT_ROUNDS,
    ROUND_OF_32,
    SimulatedResult,
    _assign_thirds,
    _build_group_lookup,
    _fallback_score_from_probabilities,
    _group_standings,
    _normalize_knockout_result,
    _official_group_for_team,
    _rebalance_low_information_score,
    _slot_source_label,
    _third_rankings,
)


def test_worldcup_knockout_bracket_matches_fifa_official_slots():
    expected_round_of_32 = {
        73: (("group", "A", 2), ("group", "B", 2)),
        74: (("group", "E", 1), ("third", "ABCDF")),
        75: (("group", "F", 1), ("group", "C", 2)),
        76: (("group", "C", 1), ("group", "F", 2)),
        77: (("group", "I", 1), ("third", "CDFGH")),
        78: (("group", "E", 2), ("group", "I", 2)),
        79: (("group", "A", 1), ("third", "CEFHI")),
        80: (("group", "L", 1), ("third", "EHIJK")),
        81: (("group", "D", 1), ("third", "BEFIJ")),
        82: (("group", "G", 1), ("third", "AEHIJ")),
        83: (("group", "K", 2), ("group", "L", 2)),
        84: (("group", "H", 1), ("group", "J", 2)),
        85: (("group", "B", 1), ("third", "EFGIJ")),
        86: (("group", "J", 1), ("group", "H", 2)),
        87: (("group", "K", 1), ("third", "DEIJL")),
        88: (("group", "D", 2), ("group", "G", 2)),
    }
    expected_next_rounds = {
        89: (74, 77),
        90: (73, 75),
        91: (76, 78),
        92: (79, 80),
        93: (83, 84),
        94: (81, 82),
        95: (86, 88),
        96: (85, 87),
        97: (89, 90),
        98: (93, 94),
        99: (91, 92),
        100: (95, 96),
        101: (97, 98),
        102: (99, 100),
    }

    actual_round_of_32 = {int(slot["match_no"]): (slot["a"], slot["b"]) for slot in ROUND_OF_32}
    actual_next_rounds = {int(slot["match_no"]): (slot["a"], slot["b"]) for slot in NEXT_ROUNDS}

    assert actual_round_of_32 == expected_round_of_32
    assert actual_next_rounds == expected_next_rounds


def test_official_worldcup_groups_drive_spain_france_bracket_side():
    assert _official_group_for_team("Spagna") == "H"
    assert _official_group_for_team("Francia") == "I"

    france_match = next(slot for slot in ROUND_OF_32 if slot["a"] == ("group", "I", 1))
    spain_match = next(slot for slot in ROUND_OF_32 if slot["a"] == ("group", "H", 1))
    next_rounds = {slot["match_no"]: (slot["a"], slot["b"]) for slot in NEXT_ROUNDS}

    assert france_match["match_no"] == 77
    assert spain_match["match_no"] == 84
    assert next_rounds[89] == (74, 77)
    assert next_rounds[93] == (83, 84)
    assert next_rounds[97] == (89, 90)
    assert next_rounds[98] == (93, 94)
    assert next_rounds[101] == (97, 98)


def test_group_standings_orders_by_points_goal_difference_and_goals_for():
    matches = [
        {"home_team": "A", "away_team": "B", "home_goals": 2, "away_goals": 0},
        {"home_team": "C", "away_team": "D", "home_goals": 1, "away_goals": 1},
        {"home_team": "A", "away_team": "C", "home_goals": 1, "away_goals": 1},
        {"home_team": "B", "away_team": "D", "home_goals": 3, "away_goals": 0},
        {"home_team": "A", "away_team": "D", "home_goals": 0, "away_goals": 0},
        {"home_team": "B", "away_team": "C", "home_goals": 1, "away_goals": 0},
    ]

    table = _group_standings(matches, random.Random(7))

    assert [row["team"] for row in table] == ["B", "A", "C", "D"]
    assert table[0]["points"] == 6
    assert table[1]["goal_difference"] == 2
    assert table[2]["goals_for"] == 2


def test_third_rankings_use_requested_tiebreakers():
    groups = {
        "A": {"standings": [{"team": "A1"}, {"team": "A2"}, {"team": "A3", "points": 4, "goal_difference": 1, "goals_for": 5, "goals_against": 4}]},
        "B": {"standings": [{"team": "B1"}, {"team": "B2"}, {"team": "B3", "points": 4, "goal_difference": 2, "goals_for": 3, "goals_against": 1}]},
        "C": {"standings": [{"team": "C1"}, {"team": "C2"}, {"team": "C3", "points": 3, "goal_difference": 4, "goals_for": 8, "goals_against": 4}]},
    }

    thirds = _third_rankings(groups, random.Random(11))

    assert [row["team"] for row in thirds] == ["B3", "A3", "C3"]
    assert [row["third_rank"] for row in thirds] == [1, 2, 3]


def test_assign_thirds_uses_each_qualified_group_once():
    qualified = [
        {"group": group, "team": f"{group}3", "points": 4, "goal_difference": 0, "goals_for": 2, "goals_against": 2}
        for group in "ABCDEFIJ"
    ]

    assignments, warnings = _assign_thirds(qualified)

    assigned_groups = [row["group"] for row in assignments.values()]
    assert len(assigned_groups) == 8
    assert len(set(assigned_groups)) == 8
    assert not warnings


def test_normalize_knockout_result_adds_penalties_after_aet_draw():
    prediction = MatchPrediction(
        match=Match(
            id="m1",
            source="test",
            competition="FIFA World Cup 2026",
            season=2026,
            match_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
            home_team="Spagna",
            away_team="Italia",
        ),
        generated_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
        picks=[
            MarketPick("1X2", "Spagna", 0.42),
            MarketPick("1X2", "Pareggio", 0.31),
            MarketPick("1X2", "Italia", 0.27),
        ],
        exact_score="1-1",
        confidence="media",
        summary="test",
    )
    result = SimulatedResult(
        home_goals_90=1,
        away_goals_90=1,
        home_goals_aet=1,
        away_goals_aet=1,
        qualified_team="Spagna",
    )

    normalized = _normalize_knockout_result(prediction, result)

    assert normalized.resolution == "PEN"
    assert normalized.penalties_home == 5
    assert normalized.penalties_away == 4
    assert normalized.qualified_team == "Spagna"


def test_build_group_lookup_partitions_round_robin_components():
    matches = [
        _match("m1", "A", "B", "2026-06-11"),
        _match("m2", "C", "D", "2026-06-11"),
        _match("m3", "A", "C", "2026-06-16"),
        _match("m4", "B", "D", "2026-06-16"),
        _match("m5", "A", "D", "2026-06-22"),
        _match("m6", "B", "C", "2026-06-22"),
        _match("m7", "E", "F", "2026-06-12"),
        _match("m8", "G", "H", "2026-06-12"),
        _match("m9", "E", "G", "2026-06-17"),
        _match("m10", "F", "H", "2026-06-17"),
        _match("m11", "E", "H", "2026-06-23"),
        _match("m12", "F", "G", "2026-06-23"),
    ]

    lookup = _build_group_lookup(matches)

    assert {lookup[f"m{index}"] for index in range(1, 7)} == {"A"}
    assert {lookup[f"m{index}"] for index in range(7, 13)} == {"B"}


def test_fallback_score_uses_market_probabilities_instead_of_default_draw():
    prediction = MatchPrediction(
        match=Match(
            id="m2",
            source="test",
            competition="FIFA World Cup 2026",
            season=2026,
            match_date=datetime(2026, 6, 11, tzinfo=timezone.utc),
            home_team="Brasile",
            away_team="Haiti",
        ),
        generated_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
        picks=[
            MarketPick("1X2", "Brasile", 0.72),
            MarketPick("1X2", "Pareggio", 0.17),
            MarketPick("1X2", "Haiti", 0.11),
            MarketPick("Over/Under 2.5", "Over 2.5", 0.66),
            MarketPick("Goal/No Goal", "No Goal", 0.58),
        ],
        exact_score="1-1",
        confidence="media",
        summary="test",
    )

    home, away = _fallback_score_from_probabilities(prediction)

    assert home > away
    assert (home, away) != (1, 1)


def test_fallback_score_does_not_clone_low_goal_favorite_exact_score():
    prediction = MatchPrediction(
        match=Match(
            id="m-low-goal",
            source="test",
            competition="FIFA World Cup 2026",
            season=2026,
            match_date=datetime(2026, 7, 3, tzinfo=timezone.utc),
            home_team="Inghilterra",
            away_team="Capo Verde",
        ),
        generated_at=datetime(2026, 6, 8, tzinfo=timezone.utc),
        picks=[
            MarketPick("1X2", "Inghilterra", 0.56),
            MarketPick("1X2", "Pareggio", 0.25),
            MarketPick("1X2", "Capo Verde", 0.19),
            MarketPick("Over/Under 2.5", "Over 2.5", 0.54),
            MarketPick("Goal/No Goal", "Goal", 0.50),
        ],
        exact_score="1-0",
        confidence="media",
        summary="test",
    )

    home, away = _fallback_score_from_probabilities(prediction)

    assert home > away
    assert (home, away) != (1, 0)


def test_rebalance_low_information_score_adjusts_llm_low_goal_favorite_result():
    prediction = MatchPrediction(
        match=Match(
            id="m-llm-low-goal",
            source="test",
            competition="FIFA World Cup 2026",
            season=2026,
            match_date=datetime(2026, 7, 3, tzinfo=timezone.utc),
            home_team="Inghilterra",
            away_team="Capo Verde",
        ),
        generated_at=datetime(2026, 6, 8, tzinfo=timezone.utc),
        picks=[
            MarketPick("1X2", "Inghilterra", 0.56),
            MarketPick("1X2", "Pareggio", 0.25),
            MarketPick("1X2", "Capo Verde", 0.19),
            MarketPick("Over/Under 2.5", "Over 2.5", 0.54),
            MarketPick("Goal/No Goal", "Goal", 0.50),
        ],
        exact_score="1-0",
        confidence="media",
        summary="test",
    )
    result = SimulatedResult(home_goals_90=1, away_goals_90=0, reason="Gemini.")

    adjusted = _rebalance_low_information_score(prediction, result)

    assert adjusted.home_goals_90 > adjusted.away_goals_90
    assert (adjusted.home_goals_90, adjusted.away_goals_90) != (1, 0)
    assert "Ribilanciato" in adjusted.reason


def test_slot_source_labels_explain_bracket_origins():
    assert _slot_source_label(74) == "vincente M074"
    assert _slot_source_label(("group", "E", 1)) == "E1"
    assert _slot_source_label(("third", "ABCDF")) == "terza da ABCDF"


def _match(match_id: str, home: str, away: str, raw_date: str) -> Match:
    return Match(
        id=match_id,
        source="test",
        competition="FIFA World Cup 2026",
        season=2026,
        match_date=datetime.fromisoformat(f"{raw_date}T00:00:00+00:00"),
        home_team=home,
        away_team=away,
        raw={"group": {"groupName": "Gruppenphase 1", "groupOrderID": 1}},
    )
