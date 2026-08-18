from fantasy.decision_center import (
    build_roster_alerts,
    fixture_outlook,
    fixtures_for_team,
    recommend_lineup,
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
    fixtures = fixtures_for_team("INT", start_matchday=1, limit=5)
    assert len(fixtures) == 5
    assert fixtures[0]["opponent"] == "MONZA"
    assert fixtures[0]["venue"] == "C"
    outlook = fixture_outlook("INT", [player(1, "A", "INT"), player(2, "A", "MON")])
    assert 1 <= outlook[0]["difficulty"] <= 5


def test_matchday_assistant_builds_a_valid_eleven():
    league, catalog = complete_league()
    result = recommend_lineup(league, catalog, matchday=1)
    assert result["complete"] is True
    assert result["formation"] in {"4-3-3", "4-4-2", "3-4-3", "3-5-2", "5-3-2"}
    assert len(result["players"]) == 11
    assert result["captain"] in result["players"]


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
    league["purchases"][0]["risk"] = 70
    league["purchases"][1]["starter_probability"] = 30
    alerts = build_roster_alerts(
        league,
        catalog,
        [
            {
                "title": "Player 1 si ferma: problema muscolare",
                "summary": "Il calciatore sara valutato nei prossimi giorni.",
                "url": "https://example.com/1",
                "source": "Test News",
            },
            {"title": "Player 3 cambia gerarchia", "url": "https://example.com/3"},
        ],
    )
    titles = " ".join(str(alert["title"]) for alert in alerts)
    assert "Rischio fisico" in titles
    assert "Titolarita da monitorare" in titles
    risk_alert = next(alert for alert in alerts if alert["title"].startswith("Rischio fisico"))
    assert risk_alert["has_news"] is True
    assert risk_alert["evidence_title"] == "Player 1 si ferma: problema muscolare"
    assert risk_alert["source"] == "Test News"
    assert "problema muscolare" in risk_alert["evidence_title"]


def test_physical_risk_without_news_explains_that_it_is_statistical():
    league, catalog = complete_league()
    league["purchases"][0]["risk"] = 65
    alerts = build_roster_alerts(league, catalog, [])
    risk_alert = next(alert for alert in alerts if alert["title"].startswith("Rischio fisico"))
    assert risk_alert["has_news"] is False
    assert "Non risulta una notizia recente verificata" in risk_alert["message"]
