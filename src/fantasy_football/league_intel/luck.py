"""Head-to-head record vs all-play expected wins. No HTTP."""

from collections import defaultdict
from statistics import median
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from fantasy_football.models.league import LeagueSettings, Matchup, MatchupSide


class LuckRow(BaseModel):
    team_id: str
    team_name: str
    actual_wins: int = 0
    actual_losses: int = 0
    actual_ties: int = 0
    all_play_wins: int = 0
    all_play_losses: int = 0
    all_play_ties: int = 0
    expected_wins: float = 0.0
    luck: float = 0.0
    lucky_wins: int = 0
    unlucky_losses: int = 0
    games: int = 0


def _sides(matchup: Matchup) -> List[MatchupSide]:
    sides = [matchup.home]
    if matchup.away is not None:
        sides.append(matchup.away)
    return sides


def _played(matchup: Matchup) -> bool:
    sides = _sides(matchup)
    if any(side.points for side in sides):
        return True
    return matchup.winner in {"HOME", "AWAY", "TIE"}


def _h2h_result(matchup: Matchup, team_id: str) -> Optional[str]:
    """win / loss / tie, or None if this team did not play a H2H game."""
    if matchup.away is None:
        return None
    home_id = matchup.home.team_id
    away_id = matchup.away.team_id
    if team_id not in {home_id, away_id}:
        return None
    winner = (matchup.winner or "").upper()
    if winner == "TIE":
        return "tie"
    if winner == "HOME":
        return "win" if team_id == home_id else "loss"
    if winner == "AWAY":
        return "win" if team_id == away_id else "loss"
    home_pts = matchup.home.points
    away_pts = matchup.away.points
    if home_pts == away_pts:
        return "tie"
    home_won = home_pts > away_pts
    if team_id == home_id:
        return "win" if home_won else "loss"
    return "win" if not home_won else "loss"


def build_luck(settings: LeagueSettings, matchups: List[Matchup]) -> List[LuckRow]:
    names = {team.team_id: team.name for team in settings.teams}
    regular = settings.regular_season_periods or 14
    by_period: Dict[int, List[Matchup]] = defaultdict(list)
    for matchup in matchups:
        if 1 <= matchup.period <= regular and _played(matchup):
            by_period[matchup.period].append(matchup)

    totals: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {
            "actual_wins": 0,
            "actual_losses": 0,
            "actual_ties": 0,
            "all_play_wins": 0,
            "all_play_losses": 0,
            "all_play_ties": 0,
            "expected_wins": 0.0,
            "lucky_wins": 0,
            "unlucky_losses": 0,
            "games": 0,
        }
    )

    for week in by_period.values():
        scores: Dict[str, float] = {}
        for matchup in week:
            for side in _sides(matchup):
                scores[side.team_id] = side.points
        if len(scores) < 2:
            continue
        mid = float(median(scores.values()))
        ids = list(scores)
        opponents = len(ids) - 1
        for team_id, pts in scores.items():
            row = totals[team_id]
            wins = losses = ties = 0
            for other in ids:
                if other == team_id:
                    continue
                other_pts = scores[other]
                if pts > other_pts:
                    wins += 1
                elif pts < other_pts:
                    losses += 1
                else:
                    ties += 1
            row["all_play_wins"] += wins
            row["all_play_losses"] += losses
            row["all_play_ties"] += ties
            if opponents:
                row["expected_wins"] += wins / opponents + 0.5 * ties / opponents

        for matchup in week:
            if matchup.away is None:
                continue
            for team_id in (matchup.home.team_id, matchup.away.team_id):
                result = _h2h_result(matchup, team_id)
                if result is None:
                    continue
                row = totals[team_id]
                row["games"] += 1
                pts = scores.get(team_id, 0.0)
                if result == "win":
                    row["actual_wins"] += 1
                    if pts < mid:
                        row["lucky_wins"] += 1
                elif result == "loss":
                    row["actual_losses"] += 1
                    if pts > mid:
                        row["unlucky_losses"] += 1
                else:
                    row["actual_ties"] += 1

    rows: List[LuckRow] = []
    team_ids = [team.team_id for team in settings.teams] or list(totals)
    for team_id in team_ids:
        stats = totals[team_id]
        expected = float(stats["expected_wins"])
        actual = float(stats["actual_wins"]) + 0.5 * float(stats["actual_ties"])
        rows.append(
            LuckRow(
                team_id=team_id,
                team_name=names.get(team_id) or f"Team {team_id}",
                actual_wins=int(stats["actual_wins"]),
                actual_losses=int(stats["actual_losses"]),
                actual_ties=int(stats["actual_ties"]),
                all_play_wins=int(stats["all_play_wins"]),
                all_play_losses=int(stats["all_play_losses"]),
                all_play_ties=int(stats["all_play_ties"]),
                expected_wins=round(expected, 2),
                luck=round(actual - expected, 2),
                lucky_wins=int(stats["lucky_wins"]),
                unlucky_losses=int(stats["unlucky_losses"]),
                games=int(stats["games"]),
            )
        )
    rows.sort(key=lambda row: (-row.luck, -row.expected_wins, row.team_name.lower()))
    return rows


def luck_leaders(rows: List[LuckRow]) -> Tuple[Optional[LuckRow], Optional[LuckRow]]:
    played = [row for row in rows if row.games]
    if not played:
        return None, None
    luckiest = max(played, key=lambda row: (row.luck, row.actual_wins))
    unluckiest = min(played, key=lambda row: (row.luck, -row.actual_wins))
    return luckiest, unluckiest
