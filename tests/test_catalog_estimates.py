from fantasy.catalog_estimates import enrich_missing_analysis, recalibrate_injury_risk
from fantasy.player_history import attach_player_history


def _reference(name: str, quote: float, fvm: float, risk: float = 20) -> dict:
    return {
        "id": name.lower(),
        "name": name,
        "team": "INT",
        "role": "C",
        "quote": quote,
        "fvm": fvm,
        "starter_probability": 80,
        "expected_appearances": 30,
        "expected_goals": 5,
        "expected_assists": 5,
        "expected_fantasy_average": 6.8,
        "reliability": 78,
        "potential": 75,
        "risk": risk,
        "value": 70,
        "tier": "Buono",
    }


def test_new_official_player_receives_real_historical_analysis() -> None:
    newcomer = {
        "id": "nuovo",
        "name": "Nuovo Estero",
        "team": "ROM",
        "role": "C",
        "quote": 14,
        "fvm": 65,
        "age": 27,
        "history_source": "ESPN",
        "history_5y": [
            {
                "year": 2025,
                "appearances": 30,
                "starts": 24,
                "goals": 5,
                "assists": 4,
                "yellow_cards": 3,
                "red_cards": 0,
                "league": "esp.1",
                "league_matches": 38,
            },
            {
                "year": 2024,
                "appearances": 32,
                "starts": 27,
                "goals": 4,
                "assists": 5,
                "yellow_cards": 4,
                "red_cards": 0,
                "league": "esp.1",
                "league_matches": 38,
            },
        ],
    }

    enrich_missing_analysis([newcomer])
    recalibrate_injury_risk(newcomer)

    assert newcomer["analysis_estimated"] is False
    assert newcomer["analysis_historical"] is True
    assert newcomer["analysis_confidence"] == "media"
    assert "analysis_comparables" not in newcomer
    assert newcomer["expected_fantasy_average"] > 6
    assert newcomer["starter_probability"] > 75
    assert newcomer["risk"] is not None
    assert newcomer["data_quality"] == "Storico reale · 2 stagioni"
    assert "ESPN" in newcomer["analysis_source"]


def test_market_values_do_not_change_historical_analysis() -> None:
    history = [
        {
            "year": 2025,
            "appearances": 30,
            "starts": 20,
            "goals": 6,
            "assists": 3,
            "league": "eng.1",
            "league_matches": 38,
        }
    ]
    cheap = {
        "id": "cheap",
        "name": "Storico",
        "role": "A",
        "quote": 1,
        "fvm": 1,
        "history_5y": history,
    }
    expensive = {**cheap, "id": "expensive", "quote": 40, "fvm": 400}

    enrich_missing_analysis([cheap, expensive])

    fields = (
        "expected_appearances",
        "expected_goals",
        "expected_assists",
        "expected_fantasy_average",
        "starter_probability",
    )
    assert {field: cheap[field] for field in fields} == {
        field: expensive[field] for field in fields
    }


def test_estimator_never_overwrites_existing_analysis() -> None:
    references = [_reference(f"Riferimento {index}", 10, 50) for index in range(6)]
    analysed = _reference("Analizzato", 10, 50)
    analysed["expected_fantasy_average"] = 7.77

    enrich_missing_analysis([*references, analysed])

    assert analysed["expected_fantasy_average"] == 7.77
    assert not analysed.get("analysis_estimated")


def test_injury_risk_penalizes_low_availability_for_a_regular_starter() -> None:
    calhanoglu = {
        "risk": 22,
        "history_5y": [
            {"appearances": 22, "starts": 20, "league_matches": 38},
            {"appearances": 29, "starts": 26, "league_matches": 38},
            {"appearances": 32, "starts": 30, "league_matches": 38},
            {"appearances": 33, "starts": 28, "league_matches": 38},
            {"appearances": 34, "starts": 33, "league_matches": 38},
        ],
    }

    result = recalibrate_injury_risk(calhanoglu)

    assert result is not None and result >= 45
    assert calhanoglu["risk_base"] == 22
    assert calhanoglu["risk_availability_gap"] > 20
    assert calhanoglu["risk_history_seasons"] == 5
    assert "5 stagioni" in calhanoglu["risk_source"]


def test_few_appearances_do_not_over_penalize_a_reserve() -> None:
    reserve = {
        "risk": 20,
        "history_5y": [
            {"appearances": 8, "starts": 2, "league_matches": 38},
            {"appearances": 6, "starts": 1, "league_matches": 38},
        ],
    }
    starter = {
        "risk": 20,
        "history_5y": [
            {"appearances": 18, "starts": 17, "league_matches": 38},
            {"appearances": 20, "starts": 18, "league_matches": 38},
        ],
    }

    reserve_risk = recalibrate_injury_risk(reserve)
    starter_risk = recalibrate_injury_risk(starter)

    assert reserve_risk is not None and starter_risk is not None
    assert reserve_risk < starter_risk


def test_single_meaningful_season_uses_low_sample_risk() -> None:
    newcomer = {
        "history_5y": [
            {"appearances": 20, "starts": 18, "league_matches": 38},
            {"appearances": 4, "starts": 1, "league_matches": 38},
        ]
    }

    result = recalibrate_injury_risk(newcomer)

    assert result is not None and 25 <= result <= 35
    assert newcomer["risk_history_seasons"] == 1
    assert "campione ridotto" in newcomer["risk_source"]


def test_previous_real_season_is_used_when_five_year_history_is_unavailable() -> None:
    player = {
        "id": "fallback",
        "name": "Storico ridotto",
        "team": "INT",
        "role": "C",
        "source": "Fantacalcio.it",
        "appearances_previous": 28,
        "goals_previous": 4,
        "assists_previous": 3,
    }

    attach_player_history([player])

    assert player["history_seasons"] == 1
    assert player["history_5y"][0]["appearances"] == 28
    assert player["history_source"] == "Fantacalcio.it"
