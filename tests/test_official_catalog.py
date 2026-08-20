from fantasy.official_catalog import (
    catalog_fingerprint,
    load_seed_catalog,
    merge_catalog_updates,
    parse_official_html,
)


def test_bundled_analysis_contains_full_classic_list() -> None:
    players = load_seed_catalog()
    role_counts = {
        role: sum(player["role"] == role for player in players)
        for role in ("P", "D", "C", "A")
    }

    assert len(players) == 494
    assert role_counts == {"P": 60, "D": 177, "C": 172, "A": 85}


def test_official_html_updates_quote_and_uses_last_number_as_fvm() -> None:
    seed = [{"id": "lautaro", "name": "Lautaro Martinez", "team": "INTER", "role": "A"}]
    html = """
    <table><thead><tr><th>Nome</th><th>Squadra</th><th>Qt.I</th><th>Qt.A</th><th>Diff.</th><th>FVM</th></tr></thead>
    <tbody><tr class="role-a"><td><a href="/serie-a/squadre/inter/lautaro">Lautaro Martinez</a></td>
    <td>INTER</td><td>34</td><td>35</td><td>1</td><td>93</td></tr></tbody></table>
    """

    players = parse_official_html(html, seed)

    assert players[0]["quote"] == 35
    assert players[0]["fvm"] == 93


def test_generic_role_player_class_does_not_turn_everyone_into_goalkeeper() -> None:
    seed = [{"id": "defender", "name": "Difensore Test", "team": "ROM", "role": "D"}]
    html = """
    <table><thead><tr><th>Nome</th><th>Squadra</th><th>Qt.I</th><th>Qt.A</th><th>FVM</th></tr></thead>
    <tbody><tr class="role-player"><td><a href="/serie-a/squadre/roma/test">Difensore Test</a></td>
    <td>ROM</td><td>8</td><td>9</td><td>30</td></tr></tbody></table>
    """

    players = parse_official_html(html, seed)

    assert players[0]["role"] == "D"


def test_new_player_uses_official_classic_role_metadata() -> None:
    html = """
    <table><thead><tr><th>Nome</th><th>Squadra</th><th>Qt.I</th><th>Qt.A</th><th>FVM</th></tr></thead>
    <tbody><tr class="player-row" data-filter-role-classic="d">
    <th class="player-role player-role-classic"><span class="role" data-value="d"></span></th>
    <th class="player-role player-role-mantra"><span class="role role-mantra" data-value="e" title="Esterno"></span></th>
    <th><a href="/serie-a/squadre/roma/molina-n/4998">Molina N.</a></th>
    <td>ROM</td><td>18</td><td>18</td><td>87</td></tr></tbody></table>
    """

    players = parse_official_html(
        html,
        [{"id": "seed", "name": "Seed", "team": "ROM", "role": "D"}],
    )

    assert len(players) == 1
    assert players[0]["name"] == "Molina N."
    assert players[0]["role"] == "D"
    assert players[0]["quote"] == 18


def test_official_update_preserves_analysis_fields() -> None:
    seed_player = load_seed_catalog()[0]
    current = [{**seed_player, "expected_goals": 7.5, "profile": "profilo personalizzato"}]
    official = [{
        "id": seed_player["id"],
        "name": seed_player["name"],
        "team": seed_player["team"],
        "role": seed_player["role"],
        "quote": 42,
        "fvm": 88,
    }]

    merged = merge_catalog_updates(current, official)
    updated = next(player for player in merged if player["id"] == seed_player["id"])

    assert updated["quote"] == 42
    assert updated["fvm"] == 88
    assert updated["expected_goals"] == 7.5
    assert updated["profile"] == "profilo personalizzato"


def test_authoritative_catalog_removes_players_no_longer_official() -> None:
    seed_player = load_seed_catalog()[0]
    official = [{
        "id": seed_player["id"],
        "name": seed_player["name"],
        "team": seed_player["team"],
        "role": seed_player["role"],
        "quote": 11,
        "fvm": 22,
    }]

    merged = merge_catalog_updates([], official, authoritative=True)

    assert len(merged) == 1
    assert merged[0]["expected_goals"] == seed_player["expected_goals"]


def test_saved_corrupted_roles_are_repaired_from_analyzed_seed() -> None:
    seed = load_seed_catalog()
    corrupted = [{**player, "role": "P"} for player in seed]

    repaired = merge_catalog_updates(corrupted, [])
    counts = {role: sum(player["role"] == role for player in repaired) for role in "PDCA"}

    assert counts == {"P": 60, "D": 177, "C": 172, "A": 85}
    assert catalog_fingerprint(seed) != catalog_fingerprint(corrupted)
