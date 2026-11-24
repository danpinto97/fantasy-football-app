"""Standings and best-performer judgments from league settings + matchups."""

from collections import defaultdict
from statistics import pstdev
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from fantasy_football.league_intel.luck import LuckRow, build_luck, luck_leaders
from fantasy_football.models.league import LeagueSettings, Matchup, RosterSlot
from fantasy_football.seasons import merge_available_seasons


class StandingRow(BaseModel):
    team_id: str
    name: str
    abbrev: str = ""
    seed: Optional[int] = None
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0
    points_against: float = 0.0
    point_diff: float = 0.0
    avg_weekly: float = 0.0
    best_week: float = 0.0
    best_week_period: Optional[int] = None
    stdev: float = 0.0
    games: int = 0


class WeeklyScore(BaseModel):
    team_id: str
    team_name: str
    period: int
    points: float


class Performer(BaseModel):
    team_id: str
    team_name: str
    value: float
    detail: str


class OverviewReport(BaseModel):
    league_id: str
    season: int
    name: str
    num_teams: int
    scoring_type: str = ""
    regular_season_periods: int = 14
    playoff_team_count: int = 0
    roster_slots: List[RosterSlot] = Field(default_factory=list)
    standings: List[StandingRow] = Field(default_factory=list)
    top_weeks: List[WeeklyScore] = Field(default_factory=list)
    highest_pf: Optional[Performer] = None
    hottest_week: Optional[Performer] = None
    most_consistent: Optional[Performer] = None
    luck: List[LuckRow] = Field(default_factory=list)
    luckiest: Optional[Performer] = None
    unluckiest: Optional[Performer] = None
    available_seasons: List[int] = Field(default_factory=list)


def _team_weeks(
    matchups: List[Matchup], *, max_period: Optional[int] = None
) -> List[WeeklyScore]:
    rows: List[WeeklyScore] = []
    for matchup in matchups:
        if max_period is not None and matchup.period > max_period:
            continue
        sides = [matchup.home]
        if matchup.away is not None:
            sides.append(matchup.away)
        elif matchup.winner == "UNDECIDED":
            continue
        for side in sides:
            rows.append(
                WeeklyScore(
                    team_id=side.team_id,
                    team_name="",
                    period=matchup.period,
                    points=side.points,
                )
            )
    return rows


def _stdev(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(pstdev(values))


def _standings_key(row: StandingRow) -> Tuple:
    seed = row.seed if row.seed is not None else 999
    return (seed, -row.wins, -row.points_for, row.name.lower())


def build_overview(settings: LeagueSettings, matchups: List[Matchup]) -> OverviewReport:
    names: Dict[str, str] = {team.team_id: team.name for team in settings.teams}
    abbrev: Dict[str, str] = {team.team_id: team.abbrev for team in settings.teams}
    regular = settings.regular_season_periods or 14
    regular_weeks = _team_weeks(matchups, max_period=regular)
    all_weeks = _team_weeks(matchups)
    by_team: Dict[str, List[WeeklyScore]] = defaultdict(list)
    for week in regular_weeks:
        week.team_name = names.get(week.team_id, f"Team {week.team_id}")
        by_team[week.team_id].append(week)
    for week in all_weeks:
        week.team_name = names.get(week.team_id, f"Team {week.team_id}")

    standings: List[StandingRow] = []
    for team in settings.teams:
        weeks = by_team.get(team.team_id, [])
        scores = [item.points for item in weeks]
        best = max(weeks, key=lambda item: item.points) if weeks else None
        avg = sum(scores) / len(scores) if scores else 0.0
        standings.append(
            StandingRow(
                team_id=team.team_id,
                name=team.name,
                abbrev=abbrev.get(team.team_id, ""),
                seed=team.playoff_seed,
                wins=team.wins,
                losses=team.losses,
                ties=team.ties,
                points_for=team.points_for,
                points_against=team.points_against,
                point_diff=team.points_for - team.points_against,
                avg_weekly=round(avg, 2),
                best_week=best.points if best else 0.0,
                best_week_period=best.period if best else None,
                stdev=round(_stdev(scores), 2),
                games=len(scores),
            )
        )
    standings.sort(key=_standings_key)

    top_weeks = sorted(all_weeks, key=lambda item: (-item.points, item.period, item.team_id))[:8]

    highest_pf = None
    if standings:
        pf_leader = max(standings, key=lambda row: (row.points_for, -row.stdev))
        highest_pf = Performer(
            team_id=pf_leader.team_id,
            team_name=pf_leader.name,
            value=pf_leader.points_for,
            detail=f"{pf_leader.points_for:.1f} PF",
        )

    hottest_week = None
    if top_weeks:
        hot = top_weeks[0]
        hottest_week = Performer(
            team_id=hot.team_id,
            team_name=hot.team_name,
            value=hot.points,
            detail=f"Week {hot.period} · {hot.points:.1f}",
        )

    most_consistent = None
    eligible = [row for row in standings if row.games >= 8]
    if eligible:
        steady = min(eligible, key=lambda row: (row.stdev, -row.points_for))
        most_consistent = Performer(
            team_id=steady.team_id,
            team_name=steady.name,
            value=steady.stdev,
            detail=f"σ {steady.stdev:.1f} over {steady.games} weeks",
        )


    luck_rows = build_luck(settings, matchups)
    luckiest_row, unluckiest_row = luck_leaders(luck_rows)
    luckiest_perf = None
    if luckiest_row is not None:
        luckiest_perf = Performer(
            team_id=luckiest_row.team_id,
            team_name=luckiest_row.team_name,
            value=luckiest_row.luck,
            detail=f"{luckiest_row.luck:+.1f} vs expected",
        )
    unluckiest_perf = None
    if unluckiest_row is not None:
        unluckiest_perf = Performer(
            team_id=unluckiest_row.team_id,
            team_name=unluckiest_row.team_name,
            value=unluckiest_row.luck,
            detail=f"{unluckiest_row.luck:+.1f} vs expected",
        )

    return OverviewReport(
        league_id=settings.league_id,
        season=settings.season,
        name=settings.name,
        num_teams=settings.num_teams,
        scoring_type=settings.scoring_type,
        regular_season_periods=regular,
        playoff_team_count=settings.playoff_team_count,
        roster_slots=list(settings.roster_slots),
        standings=standings,
        top_weeks=top_weeks,
        highest_pf=highest_pf,
        hottest_week=hottest_week,
        most_consistent=most_consistent,
        luck=luck_rows,
        luckiest=luckiest_perf,
        unluckiest=unluckiest_perf,
        available_seasons=merge_available_seasons(
            settings.available_seasons, settings.season
        ),
    )
