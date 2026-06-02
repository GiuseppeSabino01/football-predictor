from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from features.team_strength import canonical_team_name


@dataclass(slots=True)
class ResultSummary:
    date: str
    match: str
    score: str
    winner: str

    def as_row(self) -> dict[str, str]:
        return {
            "Data": self.date,
            "Partita": self.match,
            "Risultato": self.score,
            "Vincitore": self.winner,
        }


@dataclass(slots=True)
class TeamRecentStats:
    team: str
    matches: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    scored: int = 0
    conceded: int = 0
    over25: int = 0
    btts: int = 0
    results: list[ResultSummary] = field(default_factory=list)

    @property
    def points_per_game(self) -> float:
        return ((self.wins * 3) + self.draws) / self.matches if self.matches else 1.0

    @property
    def avg_goals_for(self) -> float:
        return self.goals_for / self.matches if self.matches else 1.15

    @property
    def avg_goals_against(self) -> float:
        return self.goals_against / self.matches if self.matches else 1.15

    @property
    def scored_rate(self) -> float:
        return self.scored / self.matches if self.matches else 0.55

    @property
    def conceded_rate(self) -> float:
        return self.conceded / self.matches if self.matches else 0.55

    @property
    def over25_rate(self) -> float:
        return self.over25 / self.matches if self.matches else 0.50

    @property
    def btts_rate(self) -> float:
        return self.btts / self.matches if self.matches else 0.50


@dataclass(slots=True)
class HeadToHeadStats:
    matches: int = 0
    home_wins: int = 0
    draws: int = 0
    away_wins: int = 0
    home_goals: int = 0
    away_goals: int = 0
    over25: int = 0
    btts: int = 0
    score_counts: Counter[tuple[int, int]] = field(default_factory=Counter)
    results: list[ResultSummary] = field(default_factory=list)

    @property
    def avg_home_goals(self) -> float | None:
        return self.home_goals / self.matches if self.matches else None

    @property
    def avg_away_goals(self) -> float | None:
        return self.away_goals / self.matches if self.matches else None

    @property
    def draw_rate(self) -> float | None:
        return self.draws / self.matches if self.matches else None

    @property
    def over25_rate(self) -> float | None:
        return self.over25 / self.matches if self.matches else None

    @property
    def btts_rate(self) -> float | None:
        return self.btts / self.matches if self.matches else None

    @property
    def most_common_score(self) -> tuple[tuple[int, int], float] | None:
        if not self.score_counts or not self.matches:
            return None
        score, count = self.score_counts.most_common(1)[0]
        return score, count / self.matches


@dataclass(slots=True)
class MatchHistoricalStats:
    home_recent: TeamRecentStats
    away_recent: TeamRecentStats
    h2h: HeadToHeadStats
    notes: list[str]

    @property
    def has_meaningful_data(self) -> bool:
        return self.home_recent.matches >= 3 and self.away_recent.matches >= 3

    def result_tables(self, home_label: str, away_label: str) -> dict[str, list[dict[str, str]]]:
        return {
            f"Ultime partite {home_label}": [result.as_row() for result in self.home_recent.results],
            f"Ultime partite {away_label}": [result.as_row() for result in self.away_recent.results],
            "Scontri diretti": [result.as_row() for result in self.h2h.results],
        }


class HistoricalStatsBuilder:
    def __init__(self, results: pd.DataFrame):
        self.results = results.copy()
        self.results["home_canonical"] = self.results["home_team"].map(canonical_team_name)
        self.results["away_canonical"] = self.results["away_team"].map(canonical_team_name)

    def build(self, home_team: str, away_team: str, recent_n: int = 10, h2h_n: int = 8) -> MatchHistoricalStats:
        home = canonical_team_name(home_team)
        away = canonical_team_name(away_team)
        home_recent = self._recent_team_stats(home, recent_n)
        away_recent = self._recent_team_stats(away, recent_n)
        h2h = self._h2h_stats(home, away, h2h_n)
        notes = self._notes(home_team, away_team, home_recent, away_recent, h2h)
        return MatchHistoricalStats(home_recent, away_recent, h2h, notes)

    def _recent_team_stats(self, team: str, n: int) -> TeamRecentStats:
        mask = (self.results["home_canonical"] == team) | (self.results["away_canonical"] == team)
        rows = self.results[mask].sort_values("date", ascending=False).head(n)
        stats = TeamRecentStats(team=team)
        for row in rows.to_dict("records"):
            is_home = row["home_canonical"] == team
            goals_for = int(row["home_score"] if is_home else row["away_score"])
            goals_against = int(row["away_score"] if is_home else row["home_score"])
            self._add_team_result(stats, goals_for, goals_against)
            stats.results.append(self._team_result_summary(row))
        return stats

    def _h2h_stats(self, home: str, away: str, n: int) -> HeadToHeadStats:
        mask = (
            ((self.results["home_canonical"] == home) & (self.results["away_canonical"] == away))
            | ((self.results["home_canonical"] == away) & (self.results["away_canonical"] == home))
        )
        rows = self.results[mask].sort_values("date", ascending=False).head(n)
        stats = HeadToHeadStats()
        for row in rows.to_dict("records"):
            same_order = row["home_canonical"] == home
            home_goals = int(row["home_score"] if same_order else row["away_score"])
            away_goals = int(row["away_score"] if same_order else row["home_score"])
            stats.matches += 1
            stats.home_goals += home_goals
            stats.away_goals += away_goals
            stats.over25 += int(home_goals + away_goals >= 3)
            stats.btts += int(home_goals > 0 and away_goals > 0)
            stats.score_counts[(home_goals, away_goals)] += 1
            stats.results.append(self._h2h_result_summary(row, same_order))
            if home_goals > away_goals:
                stats.home_wins += 1
            elif home_goals == away_goals:
                stats.draws += 1
            else:
                stats.away_wins += 1
        return stats

    @staticmethod
    def _add_team_result(stats: TeamRecentStats, goals_for: int, goals_against: int) -> None:
        stats.matches += 1
        stats.goals_for += goals_for
        stats.goals_against += goals_against
        stats.scored += int(goals_for > 0)
        stats.conceded += int(goals_against > 0)
        stats.over25 += int(goals_for + goals_against >= 3)
        stats.btts += int(goals_for > 0 and goals_against > 0)
        if goals_for > goals_against:
            stats.wins += 1
        elif goals_for == goals_against:
            stats.draws += 1
        else:
            stats.losses += 1

    @staticmethod
    def _team_result_summary(
        row: dict[str, Any],
    ) -> ResultSummary:
        home_team = str(row["home_team"])
        away_team = str(row["away_team"])
        home_score = int(row["home_score"])
        away_score = int(row["away_score"])
        winner = _winner_label(home_team, away_team, home_score, away_score)
        return ResultSummary(
            date=str(row["date"]),
            match=f"{home_team} vs {away_team}",
            score=f"{home_score}-{away_score}",
            winner=winner,
        )

    @staticmethod
    def _h2h_result_summary(
        row: dict[str, Any],
        same_order: bool,
    ) -> ResultSummary:
        source_home = str(row["home_team"])
        source_away = str(row["away_team"])
        source_home_score = int(row["home_score"])
        source_away_score = int(row["away_score"])
        winner = _winner_label(source_home, source_away, source_home_score, source_away_score)
        order_note = "" if same_order else " (ordine invertito)"
        return ResultSummary(
            date=str(row["date"]),
            match=f"{source_home} vs {source_away}{order_note}",
            score=f"{source_home_score}-{source_away_score}",
            winner=winner,
        )

    @staticmethod
    def _notes(
        home_label: str,
        away_label: str,
        home: TeamRecentStats,
        away: TeamRecentStats,
        h2h: HeadToHeadStats,
    ) -> list[str]:
        notes = [
            _team_form_note(home_label, home),
            _team_form_note(away_label, away),
        ]
        if h2h.matches:
            notes.append(
                f"H2H {home_label} vs {away_label}: {h2h.matches} precedenti, "
                f"{home_label} {h2h.home_wins}V-{h2h.draws}N-{h2h.away_wins}P, "
                f"{away_label} {h2h.away_wins}V-{h2h.draws}N-{h2h.home_wins}P. "
                f"Gol: {home_label} {h2h.home_goals} ({_optional_avg(h2h.avg_home_goals)}/partita), "
                f"{away_label} {h2h.away_goals} ({_optional_avg(h2h.avg_away_goals)}/partita). "
                f"Goal/no goal {h2h.btts_rate:.0%}, over 2.5 {h2h.over25_rate:.0%}."
            )
            common = h2h.most_common_score
            if common:
                score, frequency = common
                notes.append(f"Risultato H2H piu frequente: {score[0]}-{score[1]} ({frequency:.0%}).")
        else:
            notes.append("Nessun head-to-head recente trovato nello storico gratuito.")
        return notes


def frame_is_usable(value: Any) -> bool:
    return isinstance(value, pd.DataFrame) and not value.empty


def _winner_label(home_team: str, away_team: str, home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return home_team
    if home_score < away_score:
        return away_team
    return "Pareggio"


def _team_form_note(label: str, stats: TeamRecentStats) -> str:
    return (
        f"{label}: ultime {stats.matches}, {stats.wins} vinte, {stats.draws} pareggiate, "
        f"{stats.losses} perse. Gol fatti {stats.goals_for} ({stats.avg_goals_for:.2f}/partita), "
        f"gol subiti {stats.goals_against} ({stats.avg_goals_against:.2f}/partita). "
        f"Ha segnato in {stats.scored}/{stats.matches} ({stats.scored_rate:.0%}), "
        f"ha subito gol in {stats.conceded}/{stats.matches} ({stats.conceded_rate:.0%})."
    )


def _optional_avg(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "-"
