from io import BytesIO

from openpyxl import load_workbook

from fantasy.catalog import make_player
from fantasy.export import build_listone_excel
from fantasy.service import (
    auction_managers,
    create_league,
    new_workspace,
    record_auction_purchase,
    update_list_assignments,
)


def test_listone_excel_contains_personal_tiers_and_roster_data() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Export listone",
        initial_budget=250,
        participants=None,
        game_mode="list",
        roster_slots={"P": 0, "D": 1, "C": 0, "A": 0},
    )
    player = make_player(name="Dimarco", team="INT", role="D", quote=32)
    player.update({"bonus": 0.72, "potential": 81, "profile": "Esterno offensivo"})
    tier = next(item for item in league["auction_tiers"] if item["name"] == "Semi-top")
    update_list_assignments(
        league,
        [{"player": player, "in_roster": True, "tier_id": tier["id"]}],
    )

    workbook = load_workbook(BytesIO(build_listone_excel([player], league)))
    sheet = workbook["Listone"]
    headers = [cell.value for cell in sheet[1]]
    values = dict(zip(headers, [cell.value for cell in sheet[2]]))

    assert workbook.sheetnames == ["Listone", "Fasce personali"]
    assert values["Giocatore"] == "Dimarco"
    assert values["Fascia personale"] == "Semi-top"
    assert values["In rosa"] == "Sì"
    assert values["Crediti"] == 32
    assert values["Propensione bonus"] == 72
    assert values["Potenziale"] == 81
    assert values["Profilo"] == "Esterno offensivo"
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == sheet.dimensions


def test_auction_excel_contains_manager_and_paid_credits() -> None:
    workspace = new_workspace()
    league = create_league(
        workspace,
        "Export asta",
        initial_budget=500,
        participants=2,
        roster_slots={"P": 1, "D": 0, "C": 0, "A": 0},
    )
    player = make_player(name="Sommer", team="INT", role="P", quote=18)
    rival = auction_managers(league)[1]
    record_auction_purchase(league, str(rival["id"]), player, 27)

    workbook = load_workbook(BytesIO(build_listone_excel([player], league)))
    sheet = workbook["Listone"]
    headers = [cell.value for cell in sheet[1]]
    values = dict(zip(headers, [cell.value for cell in sheet[2]]))

    assert values["Fantaallenatore"] == rival["name"]
    assert values["Crediti"] == 27
    assert values["In rosa"] == "No"
