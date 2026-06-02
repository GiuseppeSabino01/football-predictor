from __future__ import annotations

import math

from schemas import MarketPick


class ShotsModel:
    def team_shots(self, home_team: str, away_team: str, home_xg: float, away_xg: float) -> list[MarketPick]:
        home_shots = (home_xg * 6.2) + 3.6
        away_shots = (away_xg * 6.2) + 3.2
        home_corners = self._expected_corners(home_xg, away_xg)
        away_corners = self._expected_corners(away_xg, home_xg)
        return [
            *self._team_total_picks("tiri", "casa", home_team, home_shots),
            *self._team_total_picks("tiri", "ospiti", away_team, away_shots),
            *self._team_total_picks("angoli", "casa", home_team, home_corners),
            *self._team_total_picks("angoli", "ospiti", away_team, away_corners),
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

    def _team_total_picks(self, stat_name: str, side: str, team: str, expected_count: float) -> list[MarketPick]:
        line = self._dynamic_half_line(expected_count)
        over_probability = self._poisson_over_probability(expected_count, line)
        under_probability = 1 - over_probability
        note = (
            f"{team}: volume {stat_name} atteso {expected_count:.1f}; "
            f"linea dinamica scelta {line:.1f}."
        )
        return [
            self._total_pick(
                market=f"Over {stat_name} squadra {side}",
                line=line,
                probability=over_probability,
                note=note,
            ),
            self._total_pick(
                market=f"Under {stat_name} squadra {side}",
                line=line,
                probability=under_probability,
                note=note,
            ),
        ]

    @staticmethod
    def _total_pick(market: str, line: float, probability: float, note: str) -> MarketPick:
        probability = max(0.01, min(0.99, probability))
        return MarketPick(
            market=market,
            selection=f"{line:.1f}",
            probability=round(probability, 3),
            fair_odd=round(1 / probability, 2),
            recommendation="Lean" if probability >= 0.56 else "No-bet",
            confidence="bassa",
            notes=[
                note,
                "Mercato stimato indirettamente da xG e volume atteso: confidenza bassa.",
            ],
        )

    @staticmethod
    def _dynamic_half_line(expected_count: float) -> float:
        line = math.floor(expected_count) + 0.5
        return max(0.5, min(35.5, line))

    @staticmethod
    def _poisson_over_probability(expected_count: float, line: float) -> float:
        threshold = int(math.floor(line)) + 1
        return 1 - sum(
            math.exp(-expected_count) * (expected_count ** count) / math.factorial(count)
            for count in range(threshold)
        )

    @staticmethod
    def _expected_corners(team_xg: float, opponent_xg: float) -> float:
        dominance = max(-1.4, min(1.4, team_xg - opponent_xg))
        return max(1.5, min(10.5, 3.1 + (team_xg * 1.9) + (dominance * 0.85)))
