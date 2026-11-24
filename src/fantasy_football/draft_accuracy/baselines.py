"""FLEX-aware replacement levels (VOLS) from a full player pool."""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from fantasy_football.models.draft import PlayerSeasonStats
from fantasy_football.models.league import LeagueSettings
from fantasy_football.positions import FLEX_ELIGIBLE, STARTER_POSITIONS, STREAMABLE


@dataclass(frozen=True)
class ReplacementLevels:
    """Points of the last starter at each position (VOLS)."""

    last_starter: Dict[str, float]
    qb_streaming: Optional[float] = None  # average of QB15–QB18, informational


def starter_slot_totals(settings: LeagueSettings, num_teams: int) -> Tuple[Dict[str, int], int]:
    """Return (dedicated starters per position across the league, FLEX starter count)."""
    dedicated: Dict[str, int] = {}
    flex = 0
    for slot in settings.roster_slots:
        pos = (slot.position or "").strip().upper()
        if slot.count <= 0:
            continue
        if slot.is_flex or pos == "FLEX":
            flex += slot.count * num_teams
            continue
        if pos not in STARTER_POSITIONS or pos == "FLEX":
            continue
        dedicated[pos] = dedicated.get(pos, 0) + slot.count * num_teams
    return dedicated, flex


def flex_aware_replacement(
    pool: Iterable[PlayerSeasonStats],
    settings: LeagueSettings,
    num_teams: int,
) -> ReplacementLevels:
    """
    Last starter at each position, counting FLEX.

    Fill dedicated slots first (top N at each position), then fill FLEX from the
    remaining RB/WR/TE by points. Replacement for a position is the lowest-scoring
    player at that position who still made a starting lineup.
    """
    by_pos: Dict[str, List[PlayerSeasonStats]] = {}
    for player in pool:
        pos = (player.position or "").strip().upper()
        if not pos or player.season_points <= 0:
            continue
        by_pos.setdefault(pos, []).append(player)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda p: -p.season_points)

    dedicated, flex_n = starter_slot_totals(settings, num_teams)
    used = set()
    last_starter: Dict[str, float] = {}

    for pos, n in dedicated.items():
        taken = [p for p in by_pos.get(pos, []) if p.player_id not in used][:n]
        for p in taken:
            used.add(p.player_id)
        if taken:
            last_starter[pos] = taken[-1].season_points
        else:
            last_starter[pos] = 0.0

    flex_cands: List[PlayerSeasonStats] = []
    for pos in FLEX_ELIGIBLE:
        for p in by_pos.get(pos, []):
            if p.player_id not in used:
                flex_cands.append(p)
    flex_cands.sort(key=lambda p: -p.season_points)
    for p in flex_cands[:flex_n]:
        used.add(p.player_id)
        last_starter[p.position.strip().upper()] = p.season_points

    qb_streaming = None
    qbs = by_pos.get("QB") or []
    window = qbs[14:18]  # QB15–QB18
    if window:
        qb_streaming = sum(p.season_points for p in window) / float(len(window))

    return ReplacementLevels(last_starter=last_starter, qb_streaming=qb_streaming)


def vbd_for_player(points: float, position: str, levels: ReplacementLevels) -> float:
    pos = (position or "").strip().upper()
    replacement = levels.last_starter.get(pos)
    if replacement is None:
        # Unknown position: do not treat raw points as VBD (old Lamar bug).
        replacement = max(levels.last_starter.values()) if levels.last_starter else 0.0
    return points - replacement


def is_streamable(position: str) -> bool:
    return (position or "").strip().upper() in STREAMABLE
