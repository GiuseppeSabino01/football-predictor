from __future__ import annotations

import math
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo

from fantasy.catalog import catalog_dataframe
from fantasy.service import (
    GAME_MODE_AUCTION,
    auction_player_assignment,
    auction_player_tier,
)

TIER_FILLS = {
    "red": "F4CCCC",
    "orange": "FCE5CD",
    "yellow": "FFF2CC",
    "green": "D9EAD3",
    "blue": "CFE2F3",
    "purple": "D9D2E9",
    "gray": "D9D9D9",
}


def build_listone_excel(catalog: list[dict[str, Any]], league: dict[str, Any]) -> bytes:
    """Export the current player board with personal tiers and ownership data."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Listone"

    base_frame = catalog_dataframe(catalog)
    base_headers = [column for column in base_frame.columns if column != "_id"]
    extra_headers = ["Propensione bonus", "Potenziale", "Profilo"]
    headers = [
        "Giocatore",
        "Squadra",
        "Ruolo",
        "Fascia personale",
        "In rosa",
        "Fantaallenatore",
        "Crediti",
        *[
            header
            for header in base_headers
            if header not in {"Giocatore", "Squadra", "Ruolo"}
        ],
        *extra_headers,
    ]
    sheet.append(headers)

    roster_ids = {
        str(purchase.get("player_id")) for purchase in league.get("purchases", [])
    }
    tier_color_by_name = {
        str(tier.get("name") or ""): str(tier.get("color") or "gray")
        for tier in league.get("auction_tiers", [])
    }
    tier_counts = {name: 0 for name in tier_color_by_name}
    for player, (_, base_row) in zip(catalog, base_frame.iterrows()):
        player_id = str(player.get("id") or "")
        personal_tier = auction_player_tier(league, player_id)
        personal_tier_name = (
            str(personal_tier.get("name") or "") if personal_tier else ""
        )
        if personal_tier_name:
            tier_counts[personal_tier_name] = tier_counts.get(personal_tier_name, 0) + 1

        assignment = (
            auction_player_assignment(league, player_id)
            if league.get("game_mode") == GAME_MODE_AUCTION
            else None
        )
        if assignment:
            in_roster = "Sì" if assignment.get("is_user") else "No"
            manager_name = str(assignment.get("manager_name") or "")
            credits = assignment.get("purchase", {}).get("price")
        else:
            in_roster = "Sì" if player_id in roster_ids else "No"
            manager_name = "La mia squadra" if player_id in roster_ids else ""
            credits = next(
                (
                    purchase.get("price")
                    for purchase in league.get("purchases", [])
                    if str(purchase.get("player_id")) == player_id
                ),
                None,
            )

        values = {
            "Giocatore": base_row.get("Giocatore"),
            "Squadra": base_row.get("Squadra"),
            "Ruolo": base_row.get("Ruolo"),
            "Fascia personale": personal_tier_name,
            "In rosa": in_roster,
            "Fantaallenatore": manager_name,
            "Crediti": credits,
            **{header: base_row.get(header) for header in base_headers},
            "Propensione bonus": _percentage_metric(player.get("bonus")),
            "Potenziale": _percentage_metric(player.get("potential")),
            "Profilo": player.get("profile"),
        }
        sheet.append([_excel_value(values.get(header)) for header in headers])
        if personal_tier_name:
            fill_color = TIER_FILLS.get(
                tier_color_by_name.get(personal_tier_name, "gray"), "D9D9D9"
            )
            for cell in sheet[sheet.max_row]:
                cell.fill = PatternFill("solid", fgColor=fill_color)

    _style_listone_sheet(sheet)
    if sheet.max_row > 1:
        table = Table(displayName="ListoneFantacalcio", ref=sheet.dimensions)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium4",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        sheet.add_table(table)

    tiers_sheet = workbook.create_sheet("Fasce personali")
    tiers_sheet.append(["Fascia", "Colore", "Giocatori assegnati"])
    for tier in league.get("auction_tiers", []):
        name = str(tier.get("name") or "")
        color = str(tier.get("color") or "gray")
        tiers_sheet.append([name, color, tier_counts.get(name, 0)])
        fill_color = TIER_FILLS.get(color, "D9D9D9")
        for cell in tiers_sheet[tiers_sheet.max_row]:
            cell.fill = PatternFill("solid", fgColor=fill_color)
    _style_tiers_sheet(tiers_sheet)

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _style_listone_sheet(sheet: Any) -> None:
    header_fill = PatternFill("solid", fgColor="173B33")
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    widths = {
        "Giocatore": 24,
        "Squadra": 12,
        "Ruolo": 9,
        "Fascia personale": 22,
        "In rosa": 11,
        "Fantaallenatore": 22,
        "Crediti": 11,
    }
    for index, header in enumerate((cell.value for cell in sheet[1]), start=1):
        sheet.column_dimensions[sheet.cell(1, index).column_letter].width = widths.get(
            str(header), 16
        )
        if header in {"Quotazione", "FVM / 1000", "Crediti"}:
            for cell in sheet.iter_cols(min_col=index, max_col=index, min_row=2):
                for value_cell in cell:
                    value_cell.number_format = "#,##0"
        elif header in {"FM attesa", "Gol attesi", "Assist attesi"}:
            for cell in sheet.iter_cols(min_col=index, max_col=index, min_row=2):
                for value_cell in cell:
                    value_cell.number_format = "0.00"
        elif header in {
            "Titolarita %",
            "Affidabilita",
            "Rischio",
            "Propensione bonus",
            "Potenziale",
            "Indice",
        }:
            for cell in sheet.iter_cols(min_col=index, max_col=index, min_row=2):
                for value_cell in cell:
                    value_cell.number_format = "0.0"


def _style_tiers_sheet(sheet: Any) -> None:
    for cell in sheet[1]:
        cell.fill = PatternFill("solid", fgColor="173B33")
        cell.font = Font(color="FFFFFF", bold=True)
    sheet.freeze_panes = "A2"
    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["B"].width = 14
    sheet.column_dimensions["C"].width = 22


def _excel_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if math.isnan(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _percentage_metric(value: Any) -> float | None:
    if value is None:
        return None
    try:
        metric = float(value)
    except (TypeError, ValueError):
        return None
    if 0 < metric <= 1:
        metric *= 100
    return round(max(0.0, min(100.0, metric)), 1)
