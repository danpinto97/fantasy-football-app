"""Drafted-player boom/bust vs ESPN season projection. No HTTP."""

from __future__ import annotations

import statistics
from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from fantasy_football.models.draft import DraftResult, PlayerSeasonStats
from fantasy_football.models.league import LeagueSettings
from fantasy_football.nfl import ESPN_PROJ_GAMES, completed_scoring_week

SKILL = {"QB", "RB", "WR", "TE"}
BOOM_PACE = 50.0
BIG_BOOM_PACE = 100.0
BUST_PACE = -100.0
BIG_BUST_PACE = -100.0


class BoomBustRow(BaseModel):
    player_name: str
    position: str
    team_id: str
    team_name: str
    round: int
    overall_pick: int
    espn_rank: Optional[int] = None
    actual_points: float = 0.0
    expected_so_far: float = 0.0
    surplus_so_far: float = 0.0
    actual_ppw: float = 0.0
    proj_ppw: float = 0.0
    pace_delta: float = 0.0
    games: int = 0
    bye_week: Optional[int] = None
    injury: str = ""
    imputed: bool = False
    kind: str = "boom"
    badge: str = "Boom"


class BoomBustReport(BaseModel):
    league_id: str
    season: int
    completed_week: int = 0
    boom_threshold: float = BOOM_PACE
    bust_threshold: float = BUST_PACE
    booms: List[BoomBustRow] = Field(default_factory=list)
    busts: List[BoomBustRow] = Field(default_factory=list)


def build_boom_bust(
    settings: LeagueSettings,
    draft: Optional[DraftResult],
    pool: Sequence[PlayerSeasonStats],
) -> BoomBustReport:
    empty = BoomBustReport(league_id=settings.league_id, season=settings.season)
    if draft is None or not draft.picks:
        return empty
    names = {team.team_id: team.name for team in settings.teams}
    players = {row.player_id: row for row in pool}
    completed = completed_scoring_week(row.weekly_points for row in pool)
    empty.completed_week = completed
    if completed <= 0:
        return empty
    neighbors: Dict[str, List[PlayerSeasonStats]] = {}
    for row in pool:
        if row.position in SKILL and row.projected_points > 20 and row.projected_ppw > 0 and row.ppr_rank is not None:
            neighbors.setdefault(row.position, []).append(row)
    rows: List[BoomBustRow] = []
    for pick in draft.picks:
        stats = players.get(pick.player.player_id)
        pos = (stats.position if stats else pick.player.position) or ""
        if pos not in SKILL:
            continue
        proj, proj_ppw, imputed = _projection(stats, pos, neighbors)
        if proj is None or proj_ppw is None:
            continue
        bye = stats.bye_week if stats else None
        weekly = dict(stats.weekly_points) if stats else {}
        games = 0
        pts = 0.0
        for week in range(1, completed + 1):
            if bye and week == bye:
                continue
            games += 1
            pts += weekly.get(week, 0.0)
        if games <= 0:
            continue
        actual_ppw = pts / games
        expected = proj_ppw * games
        pace_delta = actual_ppw * ESPN_PROJ_GAMES - proj
        kind, badge = _label(pace_delta)
        if kind is None:
            continue
        team_name = pick.team_name or names.get(pick.team_id) or f"Team {pick.team_id}"
        rows.append(
            BoomBustRow(
                player_name=(stats.name if stats else pick.player.name),
                position=pos,
                team_id=pick.team_id,
                team_name=team_name,
                round=pick.round,
                overall_pick=pick.overall_pick,
                espn_rank=stats.ppr_rank if stats else None,
                actual_points=round(pts, 1),
                expected_so_far=round(expected, 1),
                surplus_so_far=round(pts - expected, 1),
                actual_ppw=round(actual_ppw, 2),
                proj_ppw=round(proj_ppw, 2),
                pace_delta=round(pace_delta, 1),
                games=games,
                bye_week=bye,
                injury=(stats.injury_status or "") if stats else "",
                imputed=imputed,
                kind=kind,
                badge=badge,
            )
        )
    booms = sorted((row for row in rows if row.kind == "boom"), key=lambda row: -row.pace_delta)
    busts = sorted((row for row in rows if row.kind == "bust"), key=lambda row: row.pace_delta)
    return BoomBustReport(
        league_id=settings.league_id,
        season=settings.season,
        completed_week=completed,
        booms=booms,
        busts=busts,
    )


def _projection(
    stats: Optional[PlayerSeasonStats],
    pos: str,
    neighbors: Dict[str, List[PlayerSeasonStats]],
) -> tuple:
    if stats is not None and stats.projected_points > 0 and stats.projected_ppw > 0:
        return stats.projected_points, stats.projected_ppw, False
    rank = stats.ppr_rank if stats is not None else None
    cands = [row for row in neighbors.get(pos) or [] if row.ppr_rank is not None]
    if not cands:
        return None, None, False
    if rank is None:
        return (
            statistics.median(row.projected_points for row in cands),
            statistics.median(row.projected_ppw for row in cands),
            True,
        )
    closest = sorted(cands, key=lambda row: abs((row.ppr_rank or 0) - rank))[:5]
    return (
        statistics.median(row.projected_points for row in closest),
        statistics.median(row.projected_ppw for row in closest),
        True,
    )


def _label(pace_delta: float) -> tuple:
    if pace_delta >= BIG_BOOM_PACE:
        return "boom", "Big boom"
    if pace_delta >= BOOM_PACE:
        return "boom", "Boom"
    if pace_delta <= BIG_BUST_PACE:
        return "bust", "Big bust"
    if pace_delta <= BUST_PACE:
        return "bust", "Bust"
    return None, ""
