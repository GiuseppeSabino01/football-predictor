from datetime import date

import pandas as pd

from data_sources.openligadb import _team_name
from features.historical_stats import HistoricalStatsBuilder
from features.team_strength import canonical_team_name, national_elo_for, rating_based_1x2


def test_canonical_team_names():
    assert canonical_team_name("Italia") == "Italy"
    assert canonical_team_name("Paesi Bassi") == "Netherlands"
    assert canonical_team_name("Turchia") == "Turkey"
    assert canonical_team_name("Repubblica Ceca") == "Czech Republic"
    assert canonical_team_name("Bosnia ed Erzegovina") == "Bosnia and Herzegovina"
    assert canonical_team_name("Corea del Sud") == "South Korea"
    assert canonical_team_name("Kanada") == "Canada"
    assert canonical_team_name("Tunisia") == "Tunisia"
    assert canonical_team_name("Svezia") == "Sweden"
    assert canonical_team_name("Egitto") == "Egypt"
    assert canonical_team_name("RD Congo") == "DR Congo"
    assert canonical_team_name("Nuova Zelanda") == "New Zealand"
    assert canonical_team_name("Capo Verde") == "Cape Verde"


def test_openligadb_worldcup_names_are_translated():
    expected = {
        "Algerien": "Algeria",
        "Argentinien": "Argentina",
        "Australien": "Australia",
        "Belgien": "Belgio",
        "Bosnien und Herzegowina": "Bosnia ed Erzegovina",
        "Brasilien": "Brasile",
        "Cura\u00e7ao": "Cura\u00e7ao",
        "DR Kongo": "RD Congo",
        "Deutschland": "Germania",
        "Ecuador": "Ecuador",
        "Elfenbeink\u00fcste": "Costa d'Avorio",
        "England": "Inghilterra",
        "Frankreich": "Francia",
        "Ghana": "Ghana",
        "Haiti": "Haiti",
        "Irak": "Iraq",
        "Iran": "Iran",
        "Japan": "Giappone",
        "Jordanien": "Giordania",
        "Kanada": "Canada",
        "Kap Verde": "Capo Verde",
        "Katar": "Qatar",
        "Kolumbien": "Colombia",
        "Kroatien": "Croazia",
        "Marokko": "Marocco",
        "Mexiko": "Messico",
        "Neuseeland": "Nuova Zelanda",
        "Niederlande": "Paesi Bassi",
        "Norwegen": "Norvegia",
        "Panama": "Panama",
        "Paraguay": "Paraguay",
        "Portugal": "Portogallo",
        "Saudi Arabien": "Arabia Saudita",
        "Schottland": "Scozia",
        "Schweden": "Svezia",
        "Schweiz": "Svizzera",
        "Senegal": "Senegal",
        "Serbien": "Serbia",
        "Spanien": "Spagna",
        "S\u00fcdafrika": "Sudafrica",
        "S\u00fcdkorea": "Corea del Sud",
        "Tschechien": "Repubblica Ceca",
        "Tunesien": "Tunisia",
        "T\u00fcrkei": "Turchia",
        "USA": "USA",
        "Uruguay": "Uruguay",
        "Usbekistan": "Uzbekistan",
        "\u00c4gypten": "Egitto",
        "\u00d6sterreich": "Austria",
    }

    for source_name, display_name in expected.items():
        assert _team_name(source_name) == display_name
        assert national_elo_for(display_name) is not None


def test_rating_based_probabilities_vary_by_team_strength():
    probabilities = rating_based_1x2("Qatar", "Svizzera")
    assert probabilities is not None
    assert probabilities["away"] > probabilities["home"]


def test_historical_stats_builder():
    frame = pd.DataFrame(
        [
            {
                "date": date(2026, 1, 1),
                "home_team": "Germany",
                "away_team": "Italy",
                "home_score": 2,
                "away_score": 2,
                "home_shots": 14,
                "away_shots": 11,
                "home_corners": 6,
                "away_corners": 5,
            },
            {
                "date": date(2025, 1, 1),
                "home_team": "Italy",
                "away_team": "Germany",
                "home_score": 2,
                "away_score": 2,
                "home_shots": 10,
                "away_shots": 13,
                "home_corners": 4,
                "away_corners": 7,
            },
            {
                "date": date(2024, 1, 1),
                "home_team": "Italy",
                "away_team": "France",
                "home_score": 1,
                "away_score": 0,
                "home_shots": 9,
                "away_shots": 8,
                "home_corners": 3,
                "away_corners": 2,
            },
        ]
    )
    stats = HistoricalStatsBuilder(frame).build("Germany", "Italy")
    assert stats.h2h.matches == 2
    assert stats.h2h.most_common_score == ((2, 2), 1.0)
    assert stats.home_recent.scored_rate == 1.0
    assert stats.away_recent.scored_rate == 1.0
    assert "vinte" in stats.notes[0]
    assert "Gol fatti" in stats.notes[0]
    assert "H2H" in stats.notes[2]
    h2h_rows = stats.result_tables("Germany", "Italy")["Scontri diretti"]
    assert h2h_rows[0]["Tiri casa"] == "14"
    assert h2h_rows[0]["Tiri trasferta"] == "11"
    assert h2h_rows[0]["Angoli casa"] == "6"
    assert h2h_rows[0]["Angoli trasferta"] == "5"


def test_historical_stats_missing_shots_and_corners_are_explicit():
    frame = pd.DataFrame(
        [
            {
                "date": date(2026, 1, 1),
                "home_team": "Mexico",
                "away_team": "South Africa",
                "home_score": 1,
                "away_score": 1,
            }
        ]
    )
    stats = HistoricalStatsBuilder(frame).build("Mexico", "South Africa")
    row = stats.result_tables("Mexico", "South Africa")["Scontri diretti"][0]
    assert row["Tiri casa"] == "-"
    assert row["Tiri trasferta"] == "-"
    assert row["Angoli casa"] == "-"
    assert row["Angoli trasferta"] == "-"
    assert any("Tiri e angoli storici non disponibili" in note for note in stats.notes)
