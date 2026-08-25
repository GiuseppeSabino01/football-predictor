from datetime import date

from fantasy.decision_center import (
    OFFICIAL_FIXTURES_2026_27,
    build_roster_alerts,
    fixture_outlook,
    fixtures_for_team,
    injury_return_label,
    player_availability,
    recommend_lineup,
    season_next_matchday,
    simulate_purchase,
)


def player(index: int, role: str, team: str, *, starter: float = 90, risk: float = 10):
    return {
        "id": f"p{index}",
        "player_id": f"p{index}",
        "name": f"Player {index}",
        "role": role,
        "team": team,
        "quote": 10,
        "price": 10,
        "fantasy_score": 60 + index,
        "expected_fantasy_average": 6.1 + index / 100,
        "expected_goals": index / 5,
        "expected_assists": index / 8,
        "starter_probability": starter,
        "reliability": 85,
        "risk": risk,
    }


def complete_league():
    roles = ["P", *(["D"] * 5), *(["C"] * 5), *(["A"] * 4)]
    teams = ["INT", "JUV", "MIL", "ROM", "ATA", "NAP", "COM", "LAZ", "BOL", "FIO", "TOR", "PAR", "UDI", "GEN", "LEC"]
    catalog = [player(index, role, teams[index - 1]) for index, role in enumerate(roles, start=1)]
    league = {
        "id": "league",
        "initial_budget": 500,
        "roster_slots": {"P": 3, "D": 8, "C": 8, "A": 6},
        "purchases": [dict(row) for row in catalog],
        "watchlist": [],
    }
    return league, catalog


def test_fixture_alias_and_difficulty_are_available():
    fixtures = fixtures_for_team("INT", start_matchday=1, limit=38)
    assert len(fixtures) == 38
    assert fixtures[0]["opponent"] == "MONZA"
    assert fixtures[0]["venue"] == "C"
    assert fixtures[-1]["opponent"] == "SASSUOLO"
    outlook = fixture_outlook("INT", [player(1, "A", "INT"), player(2, "A", "MON")])
    assert 1 <= outlook[0]["difficulty"] <= 5


def test_official_calendar_contains_38_complete_matchdays():
    assert len(OFFICIAL_FIXTURES_2026_27) == 38
    for fixtures in OFFICIAL_FIXTURES_2026_27:
        teams = [team for fixture in fixtures for team in fixture]
        assert len(fixtures) == 10
        assert len(set(teams)) == 20


def test_next_matchday_uses_the_official_season_dates():
    assert season_next_matchday(date(2026, 8, 18)) == 1
    assert season_next_matchday(date(2027, 4, 12)) == 32
    assert season_next_matchday(date(2027, 6, 1)) == 38


def test_matchday_assistant_builds_a_valid_eleven():
    league, catalog = complete_league()
    result = recommend_lineup(league, catalog, matchday=1)
    assert result["complete"] is True
    assert result["formation"] in {"4-3-3", "4-4-2", "3-4-3", "3-5-2", "5-3-2"}
    assert len(result["players"]) == 11
    assert result["captain"] in result["players"]


def test_published_injury_excludes_player_until_announced_round():
    league, catalog = complete_league()
    injured = league["purchases"][1]
    injured["name"] = "Albarracin"
    catalog[1]["name"] = "Albarracin"
    news = [
        {
            "title": "Albarracin infortunato: stop fino alla 4a giornata",
            "summary": "Il difensore non sara disponibile.",
            "url": "https://www.fantacalcio.it/news/albarracin-stop.html",
            "source": "Fantacalcio.it",
            "verified": True,
            "status": "injured",
            "unavailable_until_matchday": 4,
        }
    ]
    result = recommend_lineup(
        league,
        catalog,
        matchday=3,
        news_items=news,
        next_matchday_number=3,
    )
    selected_ids = {row["player_id"] for row in result["players"]}
    assert injured["player_id"] not in selected_ids
    signal = next(
        row for row in result["all_players"] if row["player_id"] == injured["player_id"]
    )
    assert signal["availability_unavailable"] is True
    assert signal["appearance_probability"] <= 8
    assert signal["unavailable_until_matchday"] == 4


def test_injury_return_label_prefers_announced_matchday() -> None:
    assert injury_return_label({"return_matchday": 12}) == (
        "Rientro previsto alla 12ª giornata"
    )


def test_injury_return_label_uses_published_duration() -> None:
    candidate = player(70, "P", "NAP")
    candidate["name"] = "Meret"
    signal = player_availability(
        candidate,
        [{
            "title": "Meret infortunato",
            "body": "Meret ha rimediato un infortunio: stop di due mesi.",
            "url": "https://www.fantacalcio.it/news/meret-stop.html",
            "source": "Fantacalcio.it",
            "verified": True,
            "status": "injured",
            "published_at": "2026-08-20T12:00:00+00:00",
        }],
        matchday=2,
        next_matchday_number=2,
    )

    assert signal["estimated_return_date"] == "2026-10-19"
    assert injury_return_label(signal, today=date(2026, 8, 25)) == (
        "Rientro stimato tra circa 2 mesi (ottobre)"
    )


def test_probable_bench_changes_only_the_immediately_next_round():
    candidate = player(50, "C", "ROM", starter=90)
    candidate["name"] = "Perrone"
    news = [
        {
            "title": "Probabili formazioni: Perrone verso la panchina",
            "body": "Perrone verso la panchina nella prossima giornata.",
            "url": "https://www.fantacalcio.it/news/probabili-perrone.html",
            "source": "Fantacalcio.it",
            "verified": True,
        }
    ]
    next_signal = player_availability(
        candidate, news, matchday=5, next_matchday_number=5
    )
    future_signal = player_availability(
        candidate, news, matchday=6, next_matchday_number=5
    )
    assert next_signal["availability_status"] == "bench"
    assert next_signal["appearance_probability"] <= 58
    assert future_signal["availability_status"] == "model"
    assert future_signal["appearance_probability"] > next_signal["appearance_probability"]


def test_appearance_probability_is_individual_not_a_fixed_starter_band():
    first = player(50, "A", "ROM", starter=90, risk=8)
    first.update(
        {
            "expected_appearances": 35,
            "appearances_previous": 36,
            "reliability": 94,
        }
    )
    second = player(51, "A", "MIL", starter=90, risk=38)
    second.update(
        {
            "expected_appearances": 27,
            "appearances_previous": 18,
            "reliability": 72,
        }
    )

    first_signal = player_availability(first, [], matchday=1, next_matchday_number=1)
    second_signal = player_availability(second, [], matchday=1, next_matchday_number=1)

    assert first_signal["appearance_probability"] > second_signal["appearance_probability"]
    assert first_signal["appearance_probability"] != 94
    assert "presenze attese" in first_signal["availability_reason"]


def test_what_if_simulation_never_mutates_the_roster():
    league, _ = complete_league()
    league["purchases"] = league["purchases"][:2]
    original_count = len(league["purchases"])
    candidate = player(99, "C", "SAS")
    simulation = simulate_purchase(league, candidate, 15)
    assert simulation["valid"] is True
    assert simulation["after"]["remaining_budget"] == 465
    assert simulation["after"]["roster_size"] == 3
    assert len(league["purchases"]) == original_count


def test_alerts_are_personalized_to_roster_and_watchlist():
    league, catalog = complete_league()
    league["purchases"][0]["name"] = "Albarracin"
    catalog[0]["name"] = "Albarracin"
    alerts = build_roster_alerts(
        league,
        catalog,
        [
            {
                "title": "Albarracin si ferma: problema muscolare",
                "summary": "Il calciatore sara valutato nei prossimi giorni.",
                "url": "https://www.fantacalcio.it/news/serie-a/albarracin-stop.html",
                "source": "Fantacalcio.it",
                "verified": True,
            },
        ],
    )
    titles = " ".join(str(alert["title"]) for alert in alerts)
    assert "Disponibilita: Albarracin" in titles
    assert "Titolarita da monitorare" not in titles
    alert = alerts[0]
    assert alert["has_news"] is True
    assert alert["evidence_title"] == "Albarracin si ferma: problema muscolare"
    assert alert["source"] == "Fantacalcio.it"
    assert "problema muscolare" in alert["evidence_title"]


def test_statistical_risk_without_news_does_not_create_an_alert():
    league, catalog = complete_league()
    league["purchases"][0]["risk"] = 65
    league["purchases"][0]["starter_probability"] = 20
    alerts = build_roster_alerts(league, catalog, [])
    assert alerts == []


def test_unverified_news_is_ignored():
    league, catalog = complete_league()
    alerts = build_roster_alerts(
        league,
        catalog,
        [
            {
                "title": "Player 1 si ferma",
                "url": "https://example.com/player-1",
                "source": "Fonte sconosciuta",
                "verified": False,
            }
        ],
    )
    assert alerts == []
