from __future__ import annotations

from schemas import MarketPick


class ShotsModel:
    def team_shots(self, home_team: str, away_team: str, home_xg: float, away_xg: float) -> list[MarketPick]:
        home_shots = (home_xg * 6.2) + 3.6
        away_shots = (away_xg * 6.2) + 3.2
        return [
            self._team_pick(home_team, "Over 10.5 tiri squadra", home_shots, 10.5),
            self._team_pick(home_team, "Under 14.5 tiri squadra", home_shots, 14.5, under=True),
            self._team_pick(away_team, "Over 9.5 tiri squadra", away_shots, 9.5),
            self._team_pick(away_team, "Under 13.5 tiri squadra", away_shots, 13.5, under=True),
        ]

    def player_props(self, lineups: list[dict] | None = None) -> list[MarketPick]:
        if not lineups:
            return [
                MarketPick(
                    market="Tiri giocatore",
                    selection="Dati insufficienti",
                    probability=0.0,
                    recommendation="No-bet",
                    confidence="bassa",
                    notes=[
                        "Lineup o storico tiri giocatore non disponibili gratuitamente per questa partita.",
                        "Il modello non forza una pick player prop senza dati minimi.",
                    ],
                )
            ]
        return []

    @staticmethod
    def _team_pick(team: str, market: str, expected_shots: float, line: float, under: bool = False) -> MarketPick:
        # Approximation for an MVP: converts expected volume into a soft probability around the line.
        edge = expected_shots - line
        probability = 0.5 + max(min(edge * 0.065, 0.24), -0.24)
        if under:
            probability = 1 - probability
        return MarketPick(
            market=market,
            selection=team,
            probability=round(probability, 3),
            fair_odd=round(1 / probability, 2) if probability > 0 else None,
            recommendation="Lean" if probability >= 0.56 else "No-bet",
            confidence="bassa",
            notes=["Mercato tiri stimato indirettamente da xG e volume atteso: confidenza bassa."],
        )

