from espn_fixtures import FixtureTransport, settings_and_matchup
from fastapi.testclient import TestClient

from fantasy_football.api.app import create_app
from fantasy_football.api.security import RateLimiter
from fantasy_football.espn.client import ESPNClient
from fantasy_football.models.league import LeagueSettings, RosterSlot, Team


class FakeEspn:
    def get_league_settings(self, league_id, season):
        return LeagueSettings(
            league_id=str(league_id),
            season=season,
            name="Hoboken Local Football League",
            num_teams=12,
            roster_slots=[
                RosterSlot(position="QB", count=1),
                RosterSlot(position="RB", count=2),
                RosterSlot(position="FLEX", count=1, is_flex=True),
            ],
            teams=[
                Team(
                    team_id="1",
                    name="Team One",
                    abbrev="ONE",
                    wins=11,
                    losses=3,
                    points_for=1448.0,
                    playoff_seed=1,
                )
            ],
        )

    def get_draft_inputs(self, league_id, season):
        return self.get_league_settings(league_id, season), None, []

    def get_wire_inputs(self, league_id, season):
        return self.get_league_settings(league_id, season), [], [], {}


def _client() -> TestClient:
    app = create_app(espn_client=FakeEspn(), limiter=RateLimiter(max_calls=100, window_seconds=60))
    return TestClient(app)


def test_rejects_non_digit_league_id():
    res = _client().get("/api/leagues/not-a-league?season=2024")
    assert res.status_code == 422


def test_rejects_sql_injection_shaped_id():
    res = _client().get("/api/leagues/1%20OR%201=1?season=2024")
    assert res.status_code == 422


def test_rejects_out_of_range_season():
    res = _client().get("/api/leagues/96876878?season=1999")
    assert res.status_code == 422


def test_league_lookup_ok():
    res = _client().get("/api/leagues/96876878?season=2024")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Hoboken Local Football League"
    assert body["num_teams"] == 12
    assert body["teams"][0]["name"] == "Team One"
    assert body["teams"][0]["wins"] == 11
    assert body["teams"][0]["playoff_seed"] == 1


def test_security_headers_present():
    res = _client().get("/api/health")
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["X-Content-Type-Options"] == "nosniff"


def test_overview_from_recorded_fixtures():
    espn = ESPNClient(
        transport=FixtureTransport({("mSettings", "mTeam", "mMatchup"): settings_and_matchup()})
    )
    app = create_app(espn_client=espn, limiter=RateLimiter(max_calls=100, window_seconds=60))
    res = TestClient(app).get("/api/leagues/96876878/overview?season=2024")
    assert res.status_code == 200
    body = res.json()
    assert body["standings"][0]["name"] == "Orlando Troll Boys"
    assert body["highest_pf"]["team_name"] == "Union City Bucks"
    assert body["hottest_week"]["value"] == 164.28
    assert body["luckiest"] is not None
    assert body["unluckiest"] is not None
    assert body["luck"]
    assert 2024 in body["available_seasons"]
    assert 2023 in body["available_seasons"]
    assert 2026 in body["available_seasons"] or 2025 in body["available_seasons"]


def test_overview_rejects_non_digit_league_id():
    res = _client().get("/api/leagues/nope/overview?season=2024")
    assert res.status_code == 422


def test_draft_grades_undrafted():
    res = _client().get("/api/leagues/96876878/draft-grades?season=2024")
    assert res.status_code == 200
    body = res.json()
    assert body["drafted"] is False
    assert body["grades"] == []


def test_wire_endpoint_empty():
    res = _client().get("/api/leagues/96876878/wire?season=2024")
    assert res.status_code == 200
    body = res.json()
    assert body["best_adds"] == []
    assert body["worst_drops"] == []
    assert body["best_trades"] == []
    assert body["highest_spends"] == []
    assert body["trades"] == []


class SeasonEspn:
    def discover_seasons(self, league_id, *, current=None):
        return [2026, 2025, 2024, 2023]


def test_seasons_endpoint_lists_discovered_years():
    app = create_app(espn_client=SeasonEspn(), limiter=RateLimiter(max_calls=100, window_seconds=60))
    res = TestClient(app).get("/api/leagues/96876878/seasons")
    assert res.status_code == 200
    body = res.json()
    assert body["league_id"] == "96876878"
    assert body["seasons"] == [2026, 2025, 2024, 2023]
    assert body["current_season"] >= 2025
    assert body["has_espn_session"] is False


def test_seasons_fallback_when_client_lacks_discover():
    res = _client().get("/api/leagues/96876878/seasons")
    assert res.status_code == 200
    body = res.json()
    assert 2026 in body["seasons"] or 2025 in body["seasons"]
    assert body["has_espn_session"] is False
