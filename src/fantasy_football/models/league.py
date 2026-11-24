"""League settings, standings, matchups, and roster entries."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from fantasy_football.models.draft import DraftResult


class RosterSlot(BaseModel):
    """One roster position (e.g. QB, RB, WR) and how many are allowed."""

    position: str = Field(..., description="Position abbreviation (QB, RB, WR, TE, etc.)")
    count: int = Field(..., ge=0, description="Number of this position allowed on roster")
    is_flex: bool = Field(default=False, description="Whether this is a flex slot")


class Team(BaseModel):
    """A franchise in the league, including season record when ESPN sent it."""

    team_id: str
    name: str
    abbrev: str = ""
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0
    points_against: float = 0.0
    playoff_seed: Optional[int] = None
    waiver_rank: Optional[int] = None


class MatchupSide(BaseModel):
    team_id: str
    points: float = 0.0
    points_by_period: Dict[int, float] = Field(default_factory=dict)


class Matchup(BaseModel):
    matchup_id: int
    period: int
    home: MatchupSide
    away: Optional[MatchupSide] = None
    winner: str = "UNDECIDED"


class RosterEntry(BaseModel):
    player_id: str
    name: str
    position: str
    slot: str
    lineup_slot_id: int
    points: float = 0.0
    on_team_id: str = ""


class TransactionItem(BaseModel):
    player_id: str
    item_type: str
    from_team_id: str = "0"
    to_team_id: str = "0"


class LeagueTransaction(BaseModel):
    tx_id: str
    tx_type: str
    status: str = ""
    scoring_period: int
    team_id: str = ""
    bid_amount: float = 0.0
    items: List[TransactionItem] = Field(default_factory=list)


class LeagueSettings(BaseModel):
    """League configuration from provider (roster slots, scoring, etc.)."""

    league_id: str
    season: int
    name: str = ""
    roster_slots: List[RosterSlot] = Field(default_factory=list)
    num_teams: int = 0
    teams: List[Team] = Field(default_factory=list)
    regular_season_periods: int = 14
    playoff_team_count: int = 0
    scoring_type: str = ""
    available_seasons: List[int] = Field(default_factory=list)


class LeagueSnapshot(BaseModel):
    """Parsed ESPN views for one league/season."""

    settings: LeagueSettings
    matchups: List[Matchup] = Field(default_factory=list)
    rosters: Dict[str, List[RosterEntry]] = Field(default_factory=dict)
    draft: Optional[DraftResult] = None
