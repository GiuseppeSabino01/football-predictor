from fantasy.catalog import make_player
from fantasy.decision_center import injury_return_label, player_availability
from fantasy.injuries import INJURY_REGISTRY_URL, parse_injury_registry_html


def test_registry_keeps_long_term_injury_and_return_period() -> None:
    raw = """
    <div class="card team-card" id="team-6">
      <span class="team-name">Fiorentina</span>
      <ul>
        <li>
          <strong class="item-name">Parisi</strong>
          <div class="item-description"><p>
            sta recuperando dall'infortunio al legamento crociato,
            punta a tornare convocabile da novembre.
          </p></div>
        </li>
      </ul>
    </div>
    """

    items = parse_injury_registry_html(raw)
    parisi = make_player(name="Fabiano Parisi", team="FIO", role="D")
    signal = player_availability(
        parisi,
        items,
        matchday=2,
        next_matchday_number=2,
    )

    assert len(items) == 1
    assert items[0]["player_name"] == "Parisi"
    assert items[0]["url"] == f"{INJURY_REGISTRY_URL}#team-6"
    assert signal["availability_status"] == "injured"
    assert signal["return_month"] == "novembre"
    assert injury_return_label(signal) == "Ipotesi rientro: novembre"


def test_registry_ignores_teams_without_injured_players() -> None:
    raw = """
    <div class="card team-card" id="team-1">
      <span class="team-name">Atalanta</span>
      <ul><li><strong class="item-name">Nessuno</strong></li></ul>
    </div>
    """

    assert parse_injury_registry_html(raw) == []


def test_registry_initial_disambiguates_players_with_same_surname() -> None:
    items = [{
        "title": "Sulemana K.: lesione al ginocchio",
        "summary": "Lesione al ginocchio, recuperabile da inizio ottobre.",
        "url": INJURY_REGISTRY_URL,
        "source": "Fantacalcio.it · Infortunati Serie A",
        "verified": True,
        "status": "injured",
        "player_name": "Sulemana K.",
        "team": "Atalanta",
    }]
    correct_player = make_player(name="Sulemana K.", team="ATA", role="A")
    namesake = make_player(name="Sulemana I.", team="ATA", role="A")

    correct_signal = player_availability(
        correct_player, items, matchday=2, next_matchday_number=2
    )
    namesake_signal = player_availability(
        namesake, items, matchday=2, next_matchday_number=2
    )

    assert correct_signal["availability_status"] == "injured"
    assert namesake_signal["availability_status"] == "model"
