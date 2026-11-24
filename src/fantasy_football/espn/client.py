"""ESPN Fantasy Football v3 API client."""

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import httpx

from fantasy_football.espn.http import (
    HttpxTransport,
    athlete_url,
    cookies_from_env,
    league_urls,
    leaguedefaults_url,
    players_url,
)
from fantasy_football.seasons import DISCOVER_LOOKBACK, current_nfl_season, merge_available_seasons
from fantasy_football.espn.parse import (
    actual_season_points,
    actual_weekly_points,
    projected_season_line,
    parse_draft,
    parse_league_settings,
    parse_matchups,
    parse_rosters,
    parse_snapshot,
    parse_transactions,
)
from fantasy_football.models.draft import DraftResult, PlayerSeasonStats
from fantasy_football.nfl import bye_week, team_abbr
from fantasy_football.models.league import (
    LeagueSettings,
    LeagueSnapshot,
    LeagueTransaction,
    Matchup,
    RosterEntry,
)
from fantasy_football.positions import DEFAULT_POSITION_ID

# Kept for callers that imported these from the client module.
ESPN_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
ESPN_LEAGUE_DEFAULTS = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons"
ESPN_ATHLETES_V3 = "https://sports.core.api.espn.com/v3/sports/football/nfl/athletes"


class ESPNClient:
    """Public ESPN fantasy adapter. HTTP is allowlisted; parse is fixture-testable."""

    def __init__(
        self,
        *,
        cookies: Optional[Dict[str, str]] = None,
        timeout: float = 15.0,
        transport: Optional[Any] = None,
    ):
        self._cookies = cookies if cookies is not None else cookies_from_env()
        self._timeout = timeout
        self._http = transport or HttpxTransport(cookies=self._cookies, timeout=timeout)

    def _get_json_fallback(
        self, urls: List[str], *, headers: Optional[Dict[str, str]] = None
    ) -> Any:
        last_error: Optional[httpx.HTTPStatusError] = None
        for url in urls:
            try:
                return self._http.get_json(url, headers=headers)
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    last_error = exc
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise ValueError("No ESPN league URL to fetch")

    def _fetch_league(
        self,
        league_id: Union[int, str],
        season: int,
        views: Optional[List[str]] = None,
        *,
        scoring_period_id: Optional[int] = None,
    ) -> dict:
        data = self._get_json_fallback(
            league_urls(league_id, season, views, scoring_period_id=scoring_period_id)
        )
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected API response type: {type(data).__name__}")
        return data

    def get_league_settings(self, league_id: Union[int, str], season: int) -> LeagueSettings:
        raw = self._fetch_league(league_id, season, ["mSettings", "mTeam"])
        return parse_league_settings(raw, league_id=str(league_id), season=season)

    def discover_seasons(
        self, league_id: Union[int, str], *, current: Optional[int] = None
    ) -> List[int]:
        """Walk current year backward until a public season reveals previousSeasons.

        Private years (401/403) still count: ESPN has the season, just not anonymously.
        """
        current = current if current is not None else current_nfl_season()
        years = {current, current - 1, current - 2}
        start = max(current, 2008)
        stop = max(2008, current - DISCOVER_LOOKBACK)
        for year in range(start, stop - 1, -1):
            try:
                settings = self.get_league_settings(league_id, year)
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code if exc.response is not None else 0
                if code in (401, 403):
                    years.add(year)
                    continue
                if code == 404:
                    continue
                break
            except httpx.HTTPError:
                break
            years.add(year)
            years.update(settings.available_seasons or [])
            break
        return merge_available_seasons(years, current)

    def get_matchups(self, league_id: Union[int, str], season: int) -> List[Matchup]:
        raw = self._fetch_league(league_id, season, ["mMatchup"])
        return parse_matchups(raw)

    def get_settings_and_matchups(
        self, league_id: Union[int, str], season: int
    ) -> Tuple[LeagueSettings, List[Matchup]]:
        raw = self._fetch_league(league_id, season, ["mSettings", "mTeam", "mMatchup"])
        settings = parse_league_settings(raw, league_id=str(league_id), season=season)
        return settings, parse_matchups(raw)

    def get_rosters(self, league_id: Union[int, str], season: int) -> Dict[str, List[RosterEntry]]:
        raw = self._fetch_league(league_id, season, ["mRoster"])
        return parse_rosters(raw)

    def get_snapshot(self, league_id: Union[int, str], season: int) -> LeagueSnapshot:
        raw = self._fetch_league(
            league_id, season, ["mSettings", "mTeam", "mRoster", "mMatchup", "mDraftDetail"]
        )
        return parse_snapshot(raw, league_id=str(league_id), season=season)

    def _player_map_from_raw(self, raw: dict) -> Dict[str, dict]:
        """Build player_id -> {fullName, position, ...} from league response (players or slotCounter)."""
        out = {}
        for item in raw.get("players", []) or []:
            if not isinstance(item, dict):
                continue
            obj = item.get("player", item)
            if not isinstance(obj, dict):
                continue
            pid = str(obj.get("id", obj.get("playerId", item.get("id", ""))))
            if not pid:
                continue
            name = (
                obj.get("fullName")
                or (obj.get("firstName", "") + " " + obj.get("lastName", "")).strip()
            )
            pos_id = obj.get("defaultPositionId")
            out[pid] = {
                "name": name or "Unknown",
                "position": DEFAULT_POSITION_ID.get(pos_id, str(pos_id) if pos_id is not None else ""),
                "team_abbr": obj.get("proTeamAbbreviation", ""),
                "injury": obj.get("injuryStatus"),
            }
        return out

    def _fetch_player_map(self, season: int) -> Dict[str, dict]:
        """Fetch player id -> {name, position, ...} from full player pool."""
        try:
            data = self._http.get_json(players_url(season))
            if isinstance(data, list):
                data = {"players": data}
            out = self._player_map_from_raw(data if isinstance(data, dict) else {})
            if out:
                return out
        except Exception:
            pass
        try:
            data = self._http.get_json(leaguedefaults_url(season))
        except Exception:
            return {}
        return self._player_map_from_raw(data if isinstance(data, dict) else {})

    def _fetch_athletes_name_map(self, player_ids: Optional[Iterable[str]] = None) -> Dict[str, str]:
        """Resolve player id -> display name from ESPN Core API."""
        out: Dict[str, str] = {}
        if player_ids is not None:
            for pid in player_ids:
                if not pid or pid in out or not str(pid).isdigit():
                    continue
                try:
                    data = self._http.get_json(athlete_url(pid))
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                name = (
                    data.get("displayName")
                    or data.get("fullName")
                    or (data.get("firstName", "") + " " + data.get("lastName", "")).strip()
                )
                if name and str(name).strip():
                    out[str(pid)] = str(name).strip()
            return out
        return out

    def get_season_points(self, league_id: Union[int, str], season: int) -> Dict[str, float]:
        raw = self._fetch_league(league_id, season, ["mSettings"])
        status = raw.get("status", {}) or {}
        final_period = status.get("finalScoringPeriod") or status.get("latestScoringPeriod") or 18
        try:
            roster_raw = self._fetch_league(
                league_id, season, ["mRoster"], scoring_period_id=int(final_period)
            )
        except Exception:
            roster_raw = raw
        out: Dict[str, float] = {}
        for team in roster_raw.get("teams", []) or []:
            roster = team.get("roster", {}) or {}
            entries = roster.get("entries", []) or []
            for entry in entries:
                player_pool = entry.get("playerPoolEntry", entry)
                player = player_pool.get("player", player_pool)
                if not isinstance(player, dict):
                    continue
                pid = str(player.get("id", player.get("playerId", "")))
                if not pid:
                    continue
                total = actual_season_points(player.get("stats"), season)
                if pid not in out or total > out[pid]:
                    out[pid] = total
        return out

    def get_weekly_points(
        self, league_id: Union[int, str], season: int
    ) -> Dict[str, Dict[int, float]]:
        raw = self._fetch_league(league_id, season, ["mSettings"])
        status = raw.get("status", {}) or {}
        final_period = status.get("finalScoringPeriod") or status.get("latestScoringPeriod") or 18
        try:
            roster_raw = self._fetch_league(
                league_id, season, ["mRoster"], scoring_period_id=int(final_period)
            )
        except Exception:
            return {}

        out: Dict[str, Dict[int, float]] = {}
        for team in roster_raw.get("teams", []) or []:
            roster = team.get("roster", {}) or {}
            entries = roster.get("entries", []) or []
            for entry in entries:
                player_pool = entry.get("playerPoolEntry", entry)
                player = player_pool.get("player", player_pool)
                if not isinstance(player, dict):
                    continue
                pid = str(player.get("id", player.get("playerId", "")))
                if not pid:
                    continue
                weekly = actual_weekly_points(player.get("stats"), season)
                if weekly:
                    if pid not in out or len(weekly) > len(out.get(pid, {})):
                        out[pid] = weekly
        if out:
            return out

        for period in range(1, int(final_period) + 1):
            try:
                week_data = self._fetch_league(
                    league_id, season, ["mRoster"], scoring_period_id=period
                )
            except Exception:
                continue
            for team in week_data.get("teams", []) or []:
                for entry in (team.get("roster", {}) or {}).get("entries", []) or []:
                    player_pool = entry.get("playerPoolEntry", entry)
                    player = player_pool.get("player", player_pool)
                    if not isinstance(player, dict):
                        continue
                    pid = str(player.get("id", player.get("playerId", "")))
                    if not pid:
                        continue
                    weekly = actual_weekly_points(player.get("stats"), season)
                    if period in weekly:
                        out.setdefault(pid, {})[period] = weekly[period]
        return out

    def get_season_player_positions(self, league_id: Union[int, str], season: int) -> Dict[str, str]:
        raw = self._fetch_league(league_id, season, ["mSettings"])
        status = raw.get("status", {}) or {}
        final_period = status.get("finalScoringPeriod") or status.get("latestScoringPeriod") or 18
        try:
            roster_raw = self._fetch_league(
                league_id, season, ["mRoster"], scoring_period_id=int(final_period)
            )
        except Exception:
            return {}
        out: Dict[str, str] = {}
        for team in roster_raw.get("teams", []) or []:
            for entry in (team.get("roster", {}) or {}).get("entries", []) or []:
                player = (entry.get("playerPoolEntry", entry) or {}).get("player", entry)
                if not isinstance(player, dict):
                    continue
                pid = str(player.get("id", player.get("playerId", "")))
                if not pid:
                    continue
                pos_id = player.get("defaultPositionId")
                pos = DEFAULT_POSITION_ID.get(pos_id, str(pos_id) if pos_id is not None else "")
                if pos:
                    out[pid] = pos
        return out

    def get_player_pool(
        self, league_id: Union[int, str], season: int, *, limit: int = 2000
    ) -> List[PlayerSeasonStats]:
        data = self._fetch_player_pool_payload(league_id, season, limit=limit)
        if not isinstance(data, dict):
            return []
        out: List[PlayerSeasonStats] = []
        for item in data.get("players") or []:
            if not isinstance(item, dict):
                continue
            obj = item.get("player", item)
            if not isinstance(obj, dict):
                continue
            pid = str(obj.get("id", obj.get("playerId", item.get("id", ""))))
            if not pid:
                continue
            name = (
                obj.get("fullName")
                or (obj.get("firstName", "") + " " + obj.get("lastName", "")).strip()
            )
            pos_id = obj.get("defaultPositionId")
            position = DEFAULT_POSITION_ID.get(pos_id, str(pos_id) if pos_id is not None else "")
            ownership = obj.get("ownership") or {}
            ranks = obj.get("draftRanksByRankType") or {}
            ppr = ranks.get("PPR") or ranks.get("STANDARD") or {}
            adp_val = ownership.get("averageDraftPosition")
            if adp_val is None:
                adp_val = ppr.get("rank")
            adp = float(adp_val) if adp_val is not None else None
            stats = obj.get("stats")
            proj_total, proj_avg = projected_season_line(stats, season)
            rank_val = ppr.get("rank")
            try:
                ppr_rank = int(rank_val) if rank_val is not None else None
            except (TypeError, ValueError):
                ppr_rank = None
            abbr = team_abbr(obj.get("proTeamId"))
            out.append(
                PlayerSeasonStats(
                    player_id=pid,
                    name=name or f"Player {pid}",
                    position=position,
                    adp=adp,
                    season_points=actual_season_points(stats, season),
                    weekly_points=actual_weekly_points(stats, season),
                    team_abbr=abbr,
                    bye_week=bye_week(season, abbr),
                    projected_points=proj_total,
                    projected_ppw=proj_avg,
                    ppr_rank=ppr_rank,
                    injury_status=obj.get("injuryStatus"),
                )
            )
        return out

    def _fetch_player_pool_payload(
        self, league_id: Union[int, str], season: int, *, limit: int
    ) -> Any:
        weekly = json.dumps(
            {
                "players": {
                    "limit": limit,
                    "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                    "filterStatsForTopScoringPeriodIds": {
                        "value": 18,
                        "additionalValue": [f"00{season}", f"10{season}", f"12{season}"],
                    },
                }
            }
        )
        basic = json.dumps(
            {"players": {"limit": limit, "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}}
        )
        urls = league_urls(league_id, season, ["kona_player_info"])
        try:
            return self._get_json_fallback(urls, headers={"X-Fantasy-Filter": weekly})
        except Exception:
            return self._get_json_fallback(urls, headers={"X-Fantasy-Filter": basic})

    def _latest_scoring_period(self, league_id: Union[int, str], season: int) -> int:
        raw = self._fetch_league(league_id, season, ["mSettings"])
        status = raw.get("status") or {}
        for key in ("latestScoringPeriod", "currentMatchupPeriod", "finalScoringPeriod"):
            value = status.get(key)
            if value:
                try:
                    return max(1, min(int(value), 18))
                except (TypeError, ValueError):
                    continue
        return 18

    def get_wire_inputs(
        self, league_id: Union[int, str], season: int
    ) -> Tuple[
        LeagueSettings,
        List[LeagueTransaction],
        List[PlayerSeasonStats],
        Dict[int, Dict[str, List[RosterEntry]]],
    ]:
        settings = self.get_league_settings(league_id, season)
        latest = self._latest_scoring_period(league_id, season)
        txs: List[LeagueTransaction] = []
        rosters_by_period: Dict[int, Dict[str, List[RosterEntry]]] = {}
        seen = set()
        for period in range(1, latest + 1):
            raw = self._fetch_league(
                league_id, season, ["mTransactions2", "mRoster"], scoring_period_id=period
            )
            for tx in parse_transactions(raw):
                if tx.tx_id in seen:
                    continue
                seen.add(tx.tx_id)
                txs.append(tx)
            rosters_by_period[period] = parse_rosters(raw)
        try:
            pool = self.get_player_pool(league_id, season)
        except Exception:
            pool = []
        return settings, txs, pool, rosters_by_period

    def _enrich_draft(self, raw: dict, draft: DraftResult, season: int) -> DraftResult:
        player_map = self._player_map_from_raw(raw)
        if not player_map:
            player_map = self._player_map_from_raw(raw.get("draftDetail") or {})
        if not player_map:
            player_map = self._fetch_player_map(season)
        missing = [
            pick.player.player_id
            for pick in draft.picks
            if pick.player.player_id and pick.player.name.startswith("Player ")
        ]
        athletes = self._fetch_athletes_name_map(missing) if missing else {}
        enriched = parse_draft(
            raw,
            league_id=draft.league_id,
            season=season,
            player_map=player_map,
            athletes=athletes,
        )
        return enriched or draft

    def get_draft(self, league_id: Union[int, str], season: int) -> Optional[DraftResult]:
        raw = self._fetch_league(league_id, season, ["mDraftDetail", "mSettings", "kona_player_info"])
        draft = parse_draft(raw, league_id=str(league_id), season=season)
        if draft is None:
            return None
        return self._enrich_draft(raw, draft, season)

    def get_draft_inputs(
        self, league_id: Union[int, str], season: int
    ) -> Tuple[LeagueSettings, Optional[DraftResult], List[PlayerSeasonStats]]:
        settings = self.get_league_settings(league_id, season)
        draft = self.get_draft(league_id, season)
        try:
            pool = self.get_player_pool(league_id, season)
        except Exception:
            pool = []
        return settings, draft, pool
