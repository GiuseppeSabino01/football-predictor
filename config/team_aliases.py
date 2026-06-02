TEAM_ALIASES: dict[str, list[str]] = {
    "Inter": ["Internazionale", "Inter Milan"],
    "Milan": ["AC Milan"],
    "Juventus": ["Juve"],
    "Roma": ["AS Roma"],
    "Napoli": ["SSC Napoli"],
    "Real Madrid": ["Real"],
    "Barcelona": ["Barcellona", "FC Barcelona"],
    "Manchester City": ["Man City", "City"],
    "Manchester United": ["Man United", "Man Utd"],
    "France": ["Francia"],
    "Italy": ["Italia"],
    "Brazil": ["Brasile"],
    "Argentina": ["Albiceleste"],
    "Germany": ["Germania"],
    "Spain": ["Spagna"],
    "England": ["Inghilterra"],
    "Mexico": ["Messico", "Mexiko"],
    "South Africa": ["Sudafrica", "Südafrika", "Sud Africa"],
    "South Korea": ["Corea del Sud", "Korea del Sud"],
    "Czech Republic": ["Repubblica Ceca", "Cechia", "Tschechien"],
    "Canada": ["Kanada"],
    "Bosnia and Herzegovina": ["Bosnia ed Erzegovina", "Bosnia", "Bosnien und Herzegowina"],
    "Netherlands": ["Paesi Bassi", "Olanda", "Niederlande"],
    "Japan": ["Giappone"],
    "Morocco": ["Marocco"],
    "Switzerland": ["Svizzera", "Schweiz"],
    "Turkey": ["Turchia", "Türkiye", "Türkei"],
    "Scotland": ["Scozia", "Schottland"],
    "Qatar": ["Katar"],
    "United States": ["USA", "Stati Uniti"],
}


def aliases_for(team_name: str) -> list[str]:
    values = [team_name]
    values.extend(TEAM_ALIASES.get(team_name, []))
    normalized = team_name.lower()
    for canonical, aliases in TEAM_ALIASES.items():
        alias_values = [canonical, *aliases]
        if any(normalized == alias.lower() for alias in alias_values):
            values.extend(alias_values)
    return sorted(set(values))
