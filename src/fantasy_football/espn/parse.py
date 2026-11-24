"""Parse ESPN v3 league views into domain models. No HTTP."""

from typing import Any, Dict, List, Optional, Tuple

from fantasy_football.models.draft import DraftPick, DraftResult, Player
from fantasy_football.models.league import (
    LeagueSettings,
    LeagueSnapshot,
    LeagueTransaction,
    Matchup,
    MatchupSide,
    RosterEntry,
    RosterSlot,
    Team,
    TransactionItem,
)
from fantasy_football.positions import DEFAULT_POSITION_ID, LINEUP_SLOT_ID


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _stat_season(row: dict) -> Optional[int]:
    raw = row.get("seasonId")
    if raw is None:
        token = str(row.get("id") or row.get("externalId") or "")
        if len(token) >= 4 and token[-4:].isdigit():
            return int(token[-4:])
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def actual_season_points(stats: Any, season: int) -> float:
    """Year-to-date actual points for `season`. Ignore projections and prior years."""
    for row in _as_list(stats):
        if not isinstance(row, dict):
            continue
        if _stat_season(row) != season:
            continue
        if row.get("statSourceId") != 0:
            continue
        if row.get("scoringPeriodId") != 0:
            continue
        split = row.get("statSplitTypeId")
        if split not in (0, None):
            continue
        try:
            return float(row.get("appliedTotal") or 0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def actual_weekly_points(stats: Any, season: int) -> Dict[int, float]:
    weekly: Dict[int, float] = {}
    for row in _as_list(stats):
        if not isinstance(row, dict):
            continue
        if _stat_season(row) != season:
            continue
        if row.get("statSourceId") != 0:
            continue
        period = row.get("scoringPeriodId")
        if period is None or period == 0:
            continue
        try:
            weekly[int(period)] = float(row.get("appliedTotal") or 0)
        except (TypeError, ValueError):
            continue
    return weekly


def projected_season_line(stats: Any, season: int) -> Tuple[float, float]:
    """ESPN full-season projection (statSourceId 1, split 2). ROS is split 0."""
    total = 0.0
    avg = 0.0
    for row in _as_list(stats):
        if not isinstance(row, dict):
            continue
        if _stat_season(row) != season:
            continue
        if row.get("statSourceId") != 1:
            continue
        if row.get("scoringPeriodId") not in (0, None):
            continue
        if row.get("statSplitTypeId") != 2:
            continue
        try:
            total = float(row.get("appliedTotal") or 0)
        except (TypeError, ValueError):
            total = 0.0
        try:
            avg = float(row.get("appliedAverage") or 0)
        except (TypeError, ValueError):
            avg = 0.0
        return total, avg
    return total, avg


def _team_name(raw: dict) -> str:
    loc = str(raw.get("location") or "").strip()
    nick = str(raw.get("nickname") or "").strip()
    name = str(raw.get("name") or "").strip() or f"{loc} {nick}".strip()
    abbrev = str(raw.get("abbrev") or "").strip()
    return name or abbrev or str(raw.get("id", ""))


def _slot_id(raw_id: Any) -> Optional[int]:
    if raw_id is None or raw_id is False:
        return None
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def parse_teams(raw: dict) -> List[Team]:
    teams: List[Team] = []
    for item in _as_list(_as_dict(raw).get("teams")):
        if not isinstance(item, dict) or "id" not in item:
            continue
        overall = _as_dict(_as_dict(item.get("record")).get("overall"))
        seed = item.get("playoffSeed")
        waiver = item.get("waiverRank")
        teams.append(
            Team(
                team_id=str(item["id"]),
                name=_team_name(item),
                abbrev=str(item.get("abbrev") or "").strip(),
                wins=int(overall.get("wins") or 0),
                losses=int(overall.get("losses") or 0),
                ties=int(overall.get("ties") or 0),
                points_for=float(overall.get("pointsFor") or 0),
                points_against=float(overall.get("pointsAgainst") or 0),
                playoff_seed=int(seed) if seed is not None else None,
                waiver_rank=int(waiver) if waiver is not None else None,
            )
        )
    return teams


def parse_roster_slots(raw: dict) -> List[RosterSlot]:
    settings = _as_dict(_as_dict(raw).get("settings"))
    roster = _as_dict(settings.get("rosterSettings"))
    lineup_slots = roster.get("lineupSlotCounts") or []
    if isinstance(lineup_slots, dict):
        lineup_slots = [{"id": _slot_id(k), "count": v} for k, v in lineup_slots.items()]
    elif not isinstance(lineup_slots, list):
        lineup_slots = []
    slots: List[RosterSlot] = []
    for slot in lineup_slots:
        if not isinstance(slot, dict):
            continue
        pos_id = slot.get("id")
        if pos_id is None:
            pos_id = slot.get("lineupSlotId")
        pos_id = _slot_id(pos_id)
        count = slot.get("count")
        if count is None:
            count = slot.get("num") or 0
        try:
            count = int(count)
        except (TypeError, ValueError):
            continue
        if count <= 0 or pos_id is None:
            continue
        position = LINEUP_SLOT_ID.get(pos_id, f"SLOT_{pos_id}")
        is_flex = position == "FLEX" or "FLEX" in str(position)
        slots.append(RosterSlot(position=position, count=count, is_flex=is_flex))
    return slots


def parse_league_settings(raw: dict, *, league_id: str, season: int) -> LeagueSettings:
    payload = _as_dict(raw)
    settings = _as_dict(payload.get("settings"))
    teams = parse_teams(payload)
    num_teams = len(teams) or int(settings.get("size") or settings.get("numTeams") or 0)
    schedule = _as_dict(settings.get("scheduleSettings"))
    scoring = _as_dict(settings.get("scoringSettings"))
    try:
        regular_season_periods = int(schedule.get("matchupPeriodCount") or 14)
    except (TypeError, ValueError):
        regular_season_periods = 14
    try:
        playoff_team_count = int(schedule.get("playoffTeamCount") or 0)
    except (TypeError, ValueError):
        playoff_team_count = 0
    years = {int(season)}
    payload_season = payload.get("seasonId")
    if payload_season is not None:
        try:
            years.add(int(payload_season))
        except (TypeError, ValueError):
            pass
    for year in _as_list(_as_dict(payload.get("status")).get("previousSeasons")):
        try:
            years.add(int(year))
        except (TypeError, ValueError):
            continue
    return LeagueSettings(
        league_id=str(league_id),
        season=season,
        name=str(settings.get("name") or payload.get("name") or ""),
        roster_slots=parse_roster_slots(payload),
        num_teams=num_teams,
        teams=teams,
        regular_season_periods=max(regular_season_periods, 1),
        playoff_team_count=max(playoff_team_count, 0),
        scoring_type=str(scoring.get("scoringType") or ""),
        available_seasons=sorted(years, reverse=True),
    )


def _parse_side(raw: Any) -> Optional[MatchupSide]:
    if not isinstance(raw, dict) or raw.get("teamId") is None:
        return None
    weekly = raw.get("pointsByScoringPeriod") or {}
    points_by_period: Dict[int, float] = {}
    if isinstance(weekly, dict):
        for key, value in weekly.items():
            try:
                points_by_period[int(key)] = float(value or 0)
            except (TypeError, ValueError):
                continue
    return MatchupSide(
        team_id=str(raw["teamId"]),
        points=float(raw.get("totalPoints") or 0),
        points_by_period=points_by_period,
    )


def parse_matchups(raw: dict) -> List[Matchup]:
    matchups: List[Matchup] = []
    for item in _as_list(_as_dict(raw).get("schedule")):
        if not isinstance(item, dict):
            continue
        home = _parse_side(item.get("home"))
        if home is None:
            continue
        period = item.get("matchupPeriodId")
        matchup_id = item.get("id")
        if period is None or matchup_id is None:
            continue
        matchups.append(
            Matchup(
                matchup_id=int(matchup_id),
                period=int(period),
                home=home,
                away=_parse_side(item.get("away")),
                winner=str(item.get("winner") or "UNDECIDED"),
            )
        )
    return matchups


def _player_from_entry(entry: dict) -> dict:
    pool = _as_dict(entry.get("playerPoolEntry") or entry)
    player = _as_dict(pool.get("player") or pool)
    return {"pool": pool, "player": player}


def parse_rosters(raw: dict) -> Dict[str, List[RosterEntry]]:
    rosters: Dict[str, List[RosterEntry]] = {}
    for team in _as_list(_as_dict(raw).get("teams")):
        if not isinstance(team, dict) or "id" not in team:
            continue
        team_id = str(team["id"])
        entries: List[RosterEntry] = []
        roster = _as_dict(team.get("roster"))
        for entry in _as_list(roster.get("entries")):
            if not isinstance(entry, dict):
                continue
            parts = _player_from_entry(entry)
            player = parts["player"]
            pool = parts["pool"]
            pid = str(player.get("id") or player.get("playerId") or entry.get("playerId") or "")
            if not pid:
                continue
            slot_id = _slot_id(entry.get("lineupSlotId"))
            if slot_id is None:
                slot_id = -1
            pos_id = player.get("defaultPositionId")
            position = DEFAULT_POSITION_ID.get(pos_id, str(pos_id) if pos_id is not None else "")
            name = (
                player.get("fullName")
                or f"{player.get('firstName', '')} {player.get('lastName', '')}".strip()
            )
            entries.append(
                RosterEntry(
                    player_id=pid,
                    name=name or f"Player {pid}",
                    position=position,
                    slot=LINEUP_SLOT_ID.get(slot_id, f"SLOT_{slot_id}"),
                    lineup_slot_id=slot_id,
                    points=float(pool.get("appliedStatTotal") or 0),
                    on_team_id=str(pool.get("onTeamId") or team_id),
                )
            )
        rosters[team_id] = entries
    return rosters


def parse_transactions(raw: dict) -> List[LeagueTransaction]:
    out: List[LeagueTransaction] = []
    for item in _as_list(_as_dict(raw).get("transactions")):
        if not isinstance(item, dict):
            continue
        tx_id = str(item.get("id") or "")
        tx_type = str(item.get("type") or "")
        period = item.get("scoringPeriodId")
        if not tx_id or not tx_type or period is None:
            continue
        try:
            scoring_period = int(period)
        except (TypeError, ValueError):
            continue
        pieces: List[TransactionItem] = []
        for raw_item in _as_list(item.get("items")):
            if not isinstance(raw_item, dict):
                continue
            pid = raw_item.get("playerId")
            if pid is None:
                continue
            pieces.append(
                TransactionItem(
                    player_id=str(pid),
                    item_type=str(raw_item.get("type") or ""),
                    from_team_id=str(raw_item.get("fromTeamId") if raw_item.get("fromTeamId") is not None else 0),
                    to_team_id=str(raw_item.get("toTeamId") if raw_item.get("toTeamId") is not None else 0),
                )
            )
        try:
            bid = float(item.get("bidAmount") or 0)
        except (TypeError, ValueError):
            bid = 0.0
        out.append(
            LeagueTransaction(
                tx_id=tx_id,
                tx_type=tx_type,
                status=str(item.get("status") or ""),
                scoring_period=scoring_period,
                team_id=str(item.get("teamId") if item.get("teamId") is not None else ""),
                bid_amount=bid,
                items=pieces,
            )
        )
    return out


def parse_draft(
    raw: dict,
    *,
    league_id: str,
    season: int,
    player_map: Optional[Dict[str, dict]] = None,
    athletes: Optional[Dict[str, str]] = None,
) -> Optional[DraftResult]:
    payload = _as_dict(raw)
    draft_detail = payload.get("draftDetail") or payload.get("draftDetailMeta")
    if not isinstance(draft_detail, dict):
        return None
    picks_raw = _as_list(draft_detail.get("picks"))
    if not picks_raw:
        return None

    teams_by_id: Dict[Any, str] = {}
    for team in parse_teams(payload):
        teams_by_id[int(team.team_id) if team.team_id.isdigit() else team.team_id] = team.name
        teams_by_id[team.team_id] = team.name
    for item in _as_list(payload.get("teams")):
        if isinstance(item, dict) and "id" in item:
            teams_by_id[item["id"]] = _team_name(item)
            teams_by_id[str(item["id"])] = _team_name(item)

    player_map = player_map or {}
    athletes = athletes or {}
    picks: List[DraftPick] = []
    for item in picks_raw:
        if not isinstance(item, dict):
            continue
        player_data = item.get("playerId") if item.get("playerId") is not None else item.get("player")
        adp_val = None
        if isinstance(player_data, dict):
            pid = str(player_data.get("id", player_data.get("playerId", "")))
            name = (
                player_data.get("fullName")
                or f"{player_data.get('firstName', '')} {player_data.get('lastName', '')}".strip()
            )
            pos = player_data.get("defaultPositionId")
            position = DEFAULT_POSITION_ID.get(pos, str(pos) if pos is not None else "")
            team_abbr = player_data.get("proTeamAbbreviation", "")
            injury = player_data.get("injuryStatus")
            adp_val = player_data.get("averageDraftPosition") or player_data.get("draftRank")
        else:
            pid = str(player_data) if player_data else ""
            name = item.get("playerName") or ""
            position = item.get("position") or ""
            team_abbr = item.get("proTeamAbbreviation") or ""
            injury = item.get("injuryStatus")
            adp_val = item.get("averageDraftPosition") or item.get("draftRank")
            if not name and pid:
                info = player_map.get(pid, {})
                name = info.get("name", "") or athletes.get(pid, "") or f"Player {pid}"
                if not position:
                    position = info.get("position", "")
                if not team_abbr:
                    team_abbr = info.get("team_abbr", "")
                if injury is None:
                    injury = info.get("injury")
        overall = item.get("overallPickNumber", item.get("overallPick", 0)) or 0
        adp_float = float(adp_val) if adp_val is not None else float(overall)
        team_id = str(item.get("teamId", ""))
        team_name = teams_by_id.get(item.get("teamId"), teams_by_id.get(team_id, ""))
        picks.append(
            DraftPick(
                round=item.get("roundId", item.get("round", 0)) or 0,
                round_pick=item.get("roundPickNumber", item.get("pickNumber", 0)) or 0,
                overall_pick=int(overall),
                team_id=team_id,
                team_name=team_name,
                player=Player(
                    player_id=pid,
                    name=name or "Unknown",
                    position=position,
                    team_abbr=team_abbr,
                    adp=adp_float,
                    injury_status=injury,
                ),
                keeper=bool(item.get("keeper", False)),
            )
        )
    return DraftResult(league_id=str(league_id), season=season, picks=picks)


def parse_snapshot(raw: dict, *, league_id: str, season: int) -> LeagueSnapshot:
    return LeagueSnapshot(
        settings=parse_league_settings(raw, league_id=league_id, season=season),
        matchups=parse_matchups(raw),
        rosters=parse_rosters(raw),
        draft=parse_draft(raw, league_id=league_id, season=season),
    )
