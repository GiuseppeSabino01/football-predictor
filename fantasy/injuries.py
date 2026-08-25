from __future__ import annotations

from typing import Any

import requests
from bs4 import BeautifulSoup

INJURY_REGISTRY_URL = "https://www.fantacalcio.it/infortunati-serie-a"


def fetch_injury_registry(*, timeout: int = 10) -> list[dict[str, Any]]:
    """Fetch the persistent Serie A injury registry."""
    response = requests.get(
        INJURY_REGISTRY_URL,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 fantasy-decision-center/1.0"},
    )
    response.raise_for_status()
    return parse_injury_registry_html(response.text)


def parse_injury_registry_html(raw: str) -> list[dict[str, Any]]:
    """Convert Fantacalcio's team cards into verified availability evidence."""
    soup = BeautifulSoup(raw, "html.parser")
    items: list[dict[str, Any]] = []
    for card in soup.select(".team-card"):
        team_node = card.select_one(".team-name")
        team = _clean_text(team_node.get_text(" ", strip=True) if team_node else "")
        anchor = str(card.get("id") or "").strip()
        for row in card.select("li"):
            name_node = row.select_one(".item-name")
            description_node = row.select_one(".item-description")
            player_name = _clean_text(
                name_node.get_text(" ", strip=True) if name_node else ""
            )
            description = _clean_text(
                description_node.get_text(" ", strip=True)
                if description_node else ""
            )
            if not player_name or player_name.casefold() == "nessuno" or not description:
                continue
            url = INJURY_REGISTRY_URL + (f"#{anchor}" if anchor else "")
            items.append(
                {
                    "title": f"{player_name}: {description}"[:500],
                    "summary": description,
                    "body": description,
                    "url": url,
                    "source": "Fantacalcio.it · Infortunati Serie A",
                    "verified": True,
                    "status": "injured",
                    "player_name": player_name,
                    "team": team,
                    "registry": True,
                }
            )
    return items


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())
