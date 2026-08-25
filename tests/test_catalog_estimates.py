from fantasy.catalog_estimates import enrich_missing_analysis, recalibrate_injury_risk


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


def test_new_official_player_receives_complete_and_explicit_estimate() -> None:
    references = [
        _reference(f"Comparabile {index}", 8 + index, 35 + index * 5, 15 + index)
        for index in range(10)
    ]
    newcomer = {
        "id": "nuovo",
        "name": "Nuovo Estero",
        "team": "ROM",
        "role": "C",
        "quote": 14,
        "fvm": 65,
    }

    enrich_missing_analysis([*references, newcomer])

    assert newcomer["analysis_estimated"] is True
    assert newcomer["analysis_confidence"] == "media"
    assert len(newcomer["analysis_comparables"]) == 3
    assert newcomer["expected_fantasy_average"] == 6.8
    assert newcomer["starter_probability"] == 80
    assert newcomer["risk"] is not None
    assert newcomer["data_quality"] == "Stima automatica"


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
        "appearances_previous": 22,
        "expected_appearances": 32,
        "starter_probability": 90,
        "reliability": 82,
    }

    result = recalibrate_injury_risk(calhanoglu)

    assert result is not None and result >= 45
    assert calhanoglu["risk_base"] == 22
    assert calhanoglu["risk_availability_gap"] > 35


def test_few_appearances_do_not_over_penalize_a_reserve() -> None:
    reserve = {
        "risk": 20,
        "appearances_previous": 8,
        "expected_appearances": 10,
        "starter_probability": 20,
        "reliability": 70,
    }
    starter = {
        **reserve,
        "expected_appearances": 32,
        "starter_probability": 90,
    }

    reserve_risk = recalibrate_injury_risk(reserve)
    starter_risk = recalibrate_injury_risk(starter)

    assert reserve_risk is not None and starter_risk is not None
    assert reserve_risk < starter_risk
