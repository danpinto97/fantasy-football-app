"""Draft and player models."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Player(BaseModel):
    """A player (from draft or ADP)."""

    player_id: str
    name: str
    position: str
    team_abbr: str = ""
    adp: Optional[float] = Field(default=None, description="Average draft position (where they were taken)")
    injury_status: Optional[str] = None
    season_points: Optional[float] = Field(default=None, description="Fantasy points for the season (for performance rank)")


class PlayerSeasonStats(BaseModel):
    """Full-pool season line used for VBD (not limited to end-of-year rosters)."""

    player_id: str
    name: str
    position: str
    adp: Optional[float] = None
    season_points: float = 0.0
    weekly_points: Dict[int, float] = Field(default_factory=dict)
    team_abbr: str = ""
    bye_week: Optional[int] = None
    projected_points: float = 0.0
    projected_ppw: float = 0.0
    ppr_rank: Optional[int] = None
    injury_status: Optional[str] = None


class DraftPick(BaseModel):
    """A single draft pick."""

    round: int
    round_pick: int  # 1-based pick within round
    overall_pick: int
    team_id: str
    team_name: str = ""
    player: Player
    keeper: bool = False


class DraftResult(BaseModel):
    """Full draft result for a league."""

    league_id: str
    season: int
    picks: List[DraftPick] = Field(default_factory=list)
