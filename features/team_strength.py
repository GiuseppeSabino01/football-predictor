from __future__ import annotations

import math
import unicodedata

from features.market_features import normalize_probabilities


TEAM_NAME_ALIASES = {
    "argentina": "Argentina",
    "australia": "Australia",
    "austria": "Austria",
    "bosnia ed erzegovina": "Bosnia and Herzegovina",
    "bosnia and herzegovina": "Bosnia and Herzegovina",
    "brasil": "Brazil",
    "brasile": "Brazil",
    "brazil": "Brazil",
    "canada": "Canada",
    "kanada": "Canada",
    "cile": "Chile",
    "chile": "Chile",
    "colombia": "Colombia",
    "colombie": "Colombia",
    "corea del sud": "South Korea",
    "costa d avorio": "Ivory Coast",
    "costa d'avorio": "Ivory Coast",
    "costa rica": "Costa Rica",
    "croazia": "Croatia",
    "croatia": "Croatia",
    "curacao": "Curacao",
    "czech republic": "Czech Republic",
    "ecuador": "Ecuador",
    "england": "England",
    "francia": "France",
    "france": "France",
    "germany": "Germany",
    "germania": "Germany",
    "ghana": "Ghana",
    "giappone": "Japan",
    "galles": "Wales",
    "haiti": "Haiti",
    "inghilterra": "England",
    "iran": "Iran",
    "italia": "Italy",
    "italy": "Italy",
    "japan": "Japan",
    "marocco": "Morocco",
    "mexico": "Mexico",
    "messico": "Mexico",
    "morocco": "Morocco",
    "netherlands": "Netherlands",
    "nigeria": "Nigeria",
    "norvegia": "Norway",
    "norway": "Norway",
    "paesi bassi": "Netherlands",
    "paraguay": "Paraguay",
    "polonia": "Poland",
    "poland": "Poland",
    "portugal": "Portugal",
    "qatar": "Qatar",
    "repubblica ceca": "Czech Republic",
    "scozia": "Scotland",
    "scotland": "Scotland",
    "senegal": "Senegal",
    "serbia": "Serbia",
    "south africa": "South Africa",
    "south korea": "South Korea",
    "spagna": "Spain",
    "spain": "Spain",
    "sudafrica": "South Africa",
    "svizzera": "Switzerland",
    "turchia": "Turkey",
    "turkey": "Turkey",
    "turkiye": "Turkey",
    "ucraina": "Ukraine",
    "ukraine": "Ukraine",
    "ungheria": "Hungary",
    "hungary": "Hungary",
    "usa": "United States",
    "united states": "United States",
    "uruguay": "Uruguay",
}


HOST_NATIONS = {"Canada", "Mexico", "United States"}


FALLBACK_NATIONAL_ELO = {
    "Argentina": 2113,
    "Australia": 1775,
    "Austria": 1768,
    "Bosnia and Herzegovina": 1616,
    "Brazil": 1988,
    "Canada": 1784,
    "Chile": 1771,
    "Colombia": 1975,
    "Costa Rica": 1623,
    "Croatia": 1882,
    "Curacao": 1522,
    "Czech Republic": 1812,
    "Ecuador": 1935,
    "England": 2020,
    "France": 2081,
    "Germany": 1925,
    "Ghana": 1698,
    "Haiti": 1456,
    "Hungary": 1739,
    "Iran": 1810,
    "Ivory Coast": 1791,
    "Italy": 1856,
    "Japan": 1906,
    "Mexico": 1868,
    "Morocco": 1822,
    "Netherlands": 1961,
    "Nigeria": 1695,
    "Norway": 1763,
    "Paraguay": 1833,
    "Poland": 1764,
    "Portugal": 1984,
    "Qatar": 1423,
    "Scotland": 1742,
    "Senegal": 1770,
    "Serbia": 1732,
    "South Africa": 1517,
    "Switzerland": 1894,
    "Spain": 2165,
    "Turkey": 1902,
    "Ukraine": 1760,
    "United States": 1733,
    "Uruguay": 1892,
    "Wales": 1628,
}


def canonical_team_name(team_name: str) -> str:
    normalized = _normalize(team_name)
    return TEAM_NAME_ALIASES.get(normalized, team_name)


def national_elo_for(team_name: str, ratings: dict[str, int] | None = None) -> int | None:
    ratings = ratings or {}
    canonical = canonical_team_name(team_name)
    if canonical in ratings:
        return ratings[canonical]
    return FALLBACK_NATIONAL_ELO.get(canonical)


def rating_based_1x2(
    home_team: str,
    away_team: str,
    ratings: dict[str, int] | None = None,
    neutral: bool = True,
) -> dict[str, float] | None:
    home_rating = national_elo_for(home_team, ratings)
    away_rating = national_elo_for(away_team, ratings)
    if home_rating is None or away_rating is None:
        return None

    home_canonical = canonical_team_name(home_team)
    away_canonical = canonical_team_name(away_team)
    host_bonus = 0
    if neutral:
        if home_canonical in HOST_NATIONS:
            host_bonus += 55
        if away_canonical in HOST_NATIONS:
            host_bonus -= 55
    else:
        host_bonus += 70

    diff = home_rating - away_rating + host_bonus
    home_or_away = 1 / (1 + math.pow(10, -diff / 400))
    draw = max(0.18, min(0.31, 0.285 - abs(diff) * 0.00018))
    return normalize_probabilities(
        {
            "home": (1 - draw) * home_or_away,
            "draw": draw,
            "away": (1 - draw) * (1 - home_or_away),
        }
    )


def blend_probabilities(primary: dict[str, float], secondary: dict[str, float], primary_weight: float) -> dict[str, float]:
    secondary_weight = 1 - primary_weight
    return normalize_probabilities(
        {
            key: primary[key] * primary_weight + secondary[key] * secondary_weight
            for key in primary
        }
    )


def _normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_value.lower().replace(".", "").split())
