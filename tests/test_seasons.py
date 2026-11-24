from datetime import date
from urllib.parse import parse_qs, urlparse

import httpx

from espn_fixtures import settings_team
from fantasy_football.espn.client import ESPNClient
from fantasy_football.espn.http import league_urls
from fantasy_football.seasons import current_nfl_season, merge_available_seasons


def test_current_nfl_season_flips_in_august():
    assert current_nfl_season(date(2026, 7, 31)) == 2025
    assert current_nfl_season(date(2026, 8, 1)) == 2026
    assert current_nfl_season(date(2026, 11, 9)) == 2026


def test_merge_available_seasons_keeps_current_window():
    years = merge_available_seasons([2020, 2023], 2024, today=date(2026, 11, 9))
    assert years[:3] == [2026, 2025, 2024]
    assert 2023 in years
    assert 2020 in years


def test_league_urls_tries_history_after_current_for_modern_years():
    urls = league_urls("96876878", 2025, ["mTeam"])
    assert "seasons/2025/segments/0/leagues/96876878" in urls[0]
    assert "leagueHistory/96876878" in urls[1]
    assert "seasonId=2025" in urls[1]


def _season_from_url(url: str) -> int:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if "seasonId" in query:
        return int(query["seasonId"][0])
    parts = parsed.path.split("/")
    if "seasons" in parts:
        return int(parts[parts.index("seasons") + 1])
    raise AssertionError(f"no season in {url}")


class StatusBySeasonTransport:
    def __init__(self, by_season):
        self.by_season = by_season

    def get_json(self, url: str, *, headers=None):
        season = _season_from_url(url)
        spec = self.by_season[season]
        if isinstance(spec, int):
            request = httpx.Request("GET", url)
            response = httpx.Response(spec, request=request)
            raise httpx.HTTPStatusError("espn", request=request, response=response)
        return spec


def test_discover_seasons_keeps_private_years_and_public_history():
    espn = ESPNClient(
        transport=StatusBySeasonTransport(
            {
                2026: 401,
                2025: 401,
                2024: settings_team(),
            }
        )
    )
    years = espn.discover_seasons("96876878", current=2026)
    assert years[:3] == [2026, 2025, 2024]
    assert 2023 in years
    assert 2020 in years
