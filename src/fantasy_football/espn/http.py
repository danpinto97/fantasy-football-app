"""Allowlisted ESPN HTTP: URL builders and a thin transport."""

import os
from typing import Any, Dict, Iterable, List, Optional, Protocol
from urllib.parse import urlparse

import httpx

ESPN_LEAGUE_HOST = "lm-api-reads.fantasy.espn.com"
ESPN_CORE_HOST = "sports.core.api.espn.com"
ALLOWED_HOSTS = frozenset({ESPN_LEAGUE_HOST, ESPN_CORE_HOST})
ALLOWED_VIEWS = frozenset(
    {
        "mTeam",
        "mSettings",
        "mRoster",
        "mMatchup",
        "mDraftDetail",
        "kona_player_info",
        "players_wl",
        "mTransactions2",
    }
)
CURRENT_SEASON_CUTOFF = 2022
SNAPSHOT_VIEWS: List[str] = ["mSettings", "mTeam", "mRoster", "mMatchup", "mDraftDetail"]


def assert_espn_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("ESPN adapter only allows HTTPS")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"Refusing non-ESPN host: {host or 'missing'}")


def _digits(value: Any, *, label: str) -> str:
    text = str(value).strip()
    if not text.isdigit():
        raise ValueError(f"{label} must be digits")
    return text


def _views(views: Optional[Iterable[str]]) -> List[str]:
    out = list(views or [])
    unknown = [view for view in out if view not in ALLOWED_VIEWS]
    if unknown:
        raise ValueError(f"Unknown ESPN views: {unknown}")
    return out


def _query(views: List[str], scoring_period_id: Optional[int], extra: Optional[List[str]] = None) -> str:
    params: List[str] = list(extra or [])
    for view in views:
        params.append(f"view={view}")
    if scoring_period_id is not None:
        params.append(f"scoringPeriodId={int(scoring_period_id)}")
    if not params:
        return ""
    return "?" + "&".join(params)


def _normalize_season(league_id: Any, season: int, views: Optional[Iterable[str]]) -> tuple:
    league_id = _digits(league_id, label="league_id")
    if not isinstance(season, int) or season < 2008 or season > 2030:
        raise ValueError("season out of range")
    return league_id, season, _views(views)


def current_league_url(
    league_id: Any,
    season: int,
    views: Optional[Iterable[str]] = None,
    *,
    scoring_period_id: Optional[int] = None,
) -> str:
    league_id, season, view_list = _normalize_season(league_id, season, views)
    path = (
        f"https://{ESPN_LEAGUE_HOST}/apis/v3/games/ffl/seasons/{season}"
        f"/segments/0/leagues/{league_id}"
    )
    return path + _query(view_list, scoring_period_id)


def history_league_url(
    league_id: Any,
    season: int,
    views: Optional[Iterable[str]] = None,
    *,
    scoring_period_id: Optional[int] = None,
) -> str:
    league_id, season, view_list = _normalize_season(league_id, season, views)
    path = f"https://{ESPN_LEAGUE_HOST}/apis/v3/games/ffl/leagueHistory/{league_id}"
    return path + _query(view_list, scoring_period_id, extra=[f"seasonId={season}"])


def league_url(
    league_id: Any,
    season: int,
    views: Optional[Iterable[str]] = None,
    *,
    scoring_period_id: Optional[int] = None,
) -> str:
    """Preferred single URL. 2022+ current path; older seasons use leagueHistory."""
    if season >= CURRENT_SEASON_CUTOFF:
        return current_league_url(
            league_id, season, views, scoring_period_id=scoring_period_id
        )
    return history_league_url(league_id, season, views, scoring_period_id=scoring_period_id)


def league_urls(
    league_id: Any,
    season: int,
    views: Optional[Iterable[str]] = None,
    *,
    scoring_period_id: Optional[int] = None,
) -> List[str]:
    """Try current path first for modern seasons, then history (ESPN moves years)."""
    if season >= CURRENT_SEASON_CUTOFF:
        return [
            current_league_url(league_id, season, views, scoring_period_id=scoring_period_id),
            history_league_url(league_id, season, views, scoring_period_id=scoring_period_id),
        ]
    return [history_league_url(league_id, season, views, scoring_period_id=scoring_period_id)]


def cookies_from_env() -> Dict[str, str]:
    """swid / espn_s2 for private seasons. Never log these values."""
    cookies: Dict[str, str] = {}
    swid = os.environ.get("ESPN_SWID", "").strip()
    s2 = os.environ.get("ESPN_S2", "").strip()
    if swid:
        cookies["swid"] = swid
    if s2:
        cookies["espn_s2"] = s2
    return cookies


def has_espn_session() -> bool:
    cookies = cookies_from_env()
    return bool(cookies.get("swid") and cookies.get("espn_s2"))


def players_url(season: int) -> str:
    return (
        f"https://{ESPN_LEAGUE_HOST}/apis/v3/games/ffl/seasons/{int(season)}/players"
        "?scoringPeriodId=0&view=players_wl&view=kona_player_info"
    )


def leaguedefaults_url(season: int) -> str:
    return (
        f"https://{ESPN_LEAGUE_HOST}/apis/v3/games/ffl/seasons/{int(season)}"
        "/segments/0/leaguedefaults/3?view=kona_player_info"
    )


def athlete_url(player_id: Any) -> str:
    pid = _digits(player_id, label="player_id")
    return f"https://{ESPN_CORE_HOST}/v3/sports/football/nfl/athletes/{pid}"


class EspnTransport(Protocol):
    def get_json(self, url: str, *, headers: Optional[Dict[str, str]] = None) -> Any:
        ...


class HttpxTransport:
    """Live ESPN GET. Rejects any host outside the allowlist."""

    def __init__(self, *, cookies: Optional[Dict[str, str]] = None, timeout: float = 15.0):
        self._cookies = cookies or {}
        self._timeout = timeout

    def get_json(self, url: str, *, headers: Optional[Dict[str, str]] = None) -> Any:
        assert_espn_url(url)
        with httpx.Client(timeout=self._timeout, cookies=self._cookies) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
        if isinstance(data, list) and data:
            return data[0]
        return data
