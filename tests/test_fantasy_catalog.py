import pandas as pd

from fantasy.catalog import make_player, merge_catalog, normalize_catalog_dataframe


def test_normalizes_italian_catalog_columns() -> None:
    frame = pd.DataFrame(
        [
            {
                "Nome": "Lautaro Martinez",
                "R": "A",
                "Squadra": "Inter",
                "Qt. A": 35,
                "Gol attesi 26/27": 20,
                "Assist attesi": 5,
                "Titolarita": 92,
            }
        ]
    )

    players = normalize_catalog_dataframe(frame)

    assert len(players) == 1
    assert players[0]["name"] == "Lautaro Martinez"
    assert players[0]["role"] == "A"
    assert players[0]["quote"] == 35
    assert players[0]["expected_goals"] == 20
    assert players[0]["starter_probability"] == 92


def test_merge_catalog_updates_same_player() -> None:
    original = make_player(name="Giocatore", team="Roma", role="C", quote=7)
    updated = make_player(name="Giocatore", team="Roma", role="C", quote=9)

    merged = merge_catalog([original], [updated])

    assert len(merged) == 1
    assert merged[0]["quote"] == 9
