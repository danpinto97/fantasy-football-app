"""League-wide process vs outcome draft leaderboard. No HTTP."""

from typing import List, Optional, Sequence

from pydantic import BaseModel, Field

from fantasy_football.draft_accuracy.grader import DraftGrader, merge_pool_with_draft
from fantasy_football.league_intel.boom_bust import BoomBustReport, build_boom_bust
from fantasy_football.models.draft import DraftResult, PlayerSeasonStats
from fantasy_football.models.league import LeagueSettings


class PickAlt(BaseModel):
    name: str
    position: str
    adp: Optional[float] = None
    season_points: float = 0.0


class DraftPickRow(BaseModel):
    round: int
    overall_pick: int
    player_name: str
    position: str
    adp: Optional[float] = None
    verdict: str
    headline: str
    context: str
    alternatives: List[PickAlt] = Field(default_factory=list)
    season_alternatives: List[PickAlt] = Field(default_factory=list)
    season_verdict: str = "even"
    season_note: str = ""
    season_points: float = 0.0
    redraft_rank: Optional[int] = None


class DraftGradeRow(BaseModel):
    team_id: str
    team_name: str
    process_score: float
    outcome_score: float
    process_rank: int
    outcome_rank: int
    early_streamable_picks: int = 0
    steal_count: int = 0
    miss_count: int = 0
    picks: List[DraftPickRow] = Field(default_factory=list)


class DraftBoardReport(BaseModel):
    league_id: str
    season: int
    drafted: bool
    grades: List[DraftGradeRow] = Field(default_factory=list)
    boom_bust: Optional[BoomBustReport] = None


def build_draft_board(
    settings: LeagueSettings,
    draft: Optional[DraftResult],
    pool: Sequence[PlayerSeasonStats],
) -> DraftBoardReport:
    if draft is None or not draft.picks:
        return DraftBoardReport(
            league_id=settings.league_id,
            season=settings.season,
            drafted=False,
            boom_bust=build_boom_bust(settings, draft, pool),
        )
    names = {team.team_id: team.name for team in settings.teams}
    merged = merge_pool_with_draft(pool, draft)
    grades = DraftGrader(draft, settings, merged).grade_league()
    process_order = sorted(grades, key=lambda row: (-row.process_score, row.team_id))
    outcome_order = sorted(grades, key=lambda row: (-row.outcome_score, row.team_id))
    process_rank = {row.team_id: index + 1 for index, row in enumerate(process_order)}
    outcome_rank = {row.team_id: index + 1 for index, row in enumerate(outcome_order)}
    rows = [
        DraftGradeRow(
            team_id=row.team_id,
            team_name=names.get(row.team_id) or row.team_name or f"Team {row.team_id}",
            process_score=round(row.process_score, 1),
            outcome_score=round(row.outcome_score, 1),
            process_rank=process_rank[row.team_id],
            outcome_rank=outcome_rank[row.team_id],
            early_streamable_picks=row.early_streamable_picks,
            steal_count=row.steal_count,
            miss_count=row.miss_count,
            picks=[
                DraftPickRow(
                    round=pick.round_num,
                    overall_pick=pick.overall_pick,
                    player_name=pick.actual.name,
                    position=pick.actual.position,
                    adp=None if pick.actual_adp is None else round(pick.actual_adp, 1),
                    verdict=pick.verdict,
                    headline=pick.headline,
                    context=pick.context,
                    season_verdict=pick.season_verdict,
                    season_note=pick.season_note,
                    season_points=round(pick.actual.season_points or 0.0, 1),
                    redraft_rank=pick.redraft_rank,
                    alternatives=[
                        PickAlt(
                            name=alt.name,
                            position=alt.position,
                            adp=None if alt.adp is None else round(alt.adp, 1),
                            season_points=round(alt.season_points or 0.0, 1),
                        )
                        for alt in pick.alternatives
                    ]
                    if pick.verdict == "miss"
                    else [],
                    season_alternatives=[
                        PickAlt(
                            name=alt.name,
                            position=alt.position,
                            adp=None if alt.adp is None else round(alt.adp, 1),
                            season_points=round(alt.season_points or 0.0, 1),
                        )
                        for alt in pick.season_alternatives
                    ],
                )
                for pick in row.picks
            ],
        )
        for row in process_order
    ]
    return DraftBoardReport(
        league_id=settings.league_id,
        season=settings.season,
        drafted=True,
        grades=rows,
        boom_bust=build_boom_bust(settings, draft, pool),
    )
