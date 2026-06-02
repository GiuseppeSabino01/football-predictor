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
            },
            {
                "date": date(2025, 1, 1),
                "home_team": "Italy",
                "away_team": "Germany",
                "home_score": 2,
                "away_score": 2,
            },
            {
                "date": date(2024, 1, 1),
                "home_team": "Italy",
                "away_team": "France",
                "home_score": 1,
                "away_score": 0,
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
    assert list(h2h_rows[0].keys()) == ["Data", "Partita", "Risultato", "Vincitore", "Esito"]
