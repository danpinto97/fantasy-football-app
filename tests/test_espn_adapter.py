from urllib.parse import urlparse

import httpx
import pytest

from espn_fixtures import (
    FixtureTransport,
    LEAGUE_ID,
    SEASON,
    draft,
    matchup,
    roster,
    settings_team,
)
from fantasy_football.espn.client import ESPNClient
from fantasy_football.espn.http import assert_espn_url, league_url
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


def test_league_url_current_season_repeats_views():
    url = league_url(LEAGUE_ID, 2024, ["mSettings", "mTeam"])
    assert url.startswith("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2024/")
    assert "leagues/96876878" in url
    assert url.count("view=mSettings") == 1
    assert url.count("view=mTeam") == 1


def test_league_url_history_uses_season_query():
    url = league_url(LEAGUE_ID, 2019, ["mMatchup"])
    assert "leagueHistory/96876878" in url
    assert "seasonId=2019" in url
    assert "view=mMatchup" in url


def test_league_url_rejects_non_digit_id():
    with pytest.raises(ValueError, match="digits"):
        league_url("96876878/../../../etc/passwd", 2024, ["mTeam"])


def test_league_url_rejects_unknown_view():
    with pytest.raises(ValueError, match="Unknown ESPN views"):
        league_url(LEAGUE_ID, 2024, ["mTeam", "http://evil.example"])


def test_assert_espn_url_rejects_other_hosts():
    with pytest.raises(ValueError, match="non-ESPN"):
        assert_espn_url("https://evil.example/apis/v3/games/ffl/seasons/2024")


def test_assert_espn_url_rejects_http():
    with pytest.raises(ValueError, match="HTTPS"):
        assert_espn_url("http://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl")


def test_parse_settings_and_standings_from_fixture():
    settings = parse_league_settings(settings_team(), league_id=LEAGUE_ID, season=SEASON)
    assert settings.name == "Hoboken Local Football League"
    assert settings.num_teams == 12
    qb = next(slot for slot in settings.roster_slots if slot.position == "QB")
    assert qb.count == 1
    flex = next(slot for slot in settings.roster_slots if slot.position == "FLEX")
    assert flex.is_flex
    champ = next(team for team in settings.teams if team.team_id == "8")
    assert champ.name == "Orlando Troll Boys"
    assert champ.wins == 11
    assert champ.losses == 3
    assert champ.playoff_seed == 1
    assert champ.points_for == 1448.0
    assert settings.regular_season_periods == 14
    assert settings.playoff_team_count == 6
    assert settings.scoring_type == "H2H_POINTS"
    assert settings.available_seasons == [2024, 2023, 2022, 2021, 2020]


def test_parse_matchups_includes_bye_and_week_one():
    matchups = parse_matchups(matchup())
    assert len(matchups) == 103
    week1 = next(item for item in matchups if item.matchup_id == 1)
    assert week1.period == 1
    assert week1.home.team_id == "7"
    assert week1.away is not None
    assert week1.away.team_id == "3"
    assert week1.winner == "AWAY"
    assert week1.away.points == 96.64
    bye = next(item for item in matchups if item.matchup_id == 85)
    assert bye.away is None
    assert bye.winner == "UNDECIDED"


def test_parse_rosters_keeps_qb_slot_zero():
    rosters = parse_rosters(roster())
    team1 = rosters["1"]
    lamar = next(entry for entry in team1 if entry.player_id == "3916387")
    assert lamar.name == "Lamar Jackson"
    assert lamar.position == "QB"
    assert lamar.slot == "QB"
    assert lamar.lineup_slot_id == 0
    jets = next(entry for entry in team1 if entry.player_id == "-16020")
    assert jets.slot == "D/ST"
    assert jets.position == "D/ST"


def test_parse_draft_snake_and_negative_dst_ids():
    result = parse_draft(draft(), league_id=LEAGUE_ID, season=SEASON)
    assert result is not None
    assert len(result.picks) == 192
    first = result.picks[0]
    assert first.overall_pick == 1
    assert first.team_id == "2"
    assert first.player.player_id == "3117251"
    dst = next(pick for pick in result.picks if pick.player.player_id == "-16005")
    assert dst.overall_pick == 119
    assert dst.round == 10


def test_parse_snapshot_merges_views():
    raw = {}
    raw.update(settings_team())
    raw["schedule"] = matchup()["schedule"]
    raw["draftDetail"] = draft()["draftDetail"]
    raw["teams"] = [
        {**team, **roster_team}
        for team in settings_team()["teams"]
        for roster_team in roster()["teams"]
        if team["id"] == roster_team["id"]
    ]
    snapshot = parse_snapshot(raw, league_id=LEAGUE_ID, season=SEASON)
    assert snapshot.settings.num_teams == 12
    assert len(snapshot.matchups) == 103
    assert len(snapshot.rosters) == 12
    assert snapshot.draft is not None
    assert len(snapshot.draft.picks) == 192


def test_client_reads_fixtures_without_network():
    transport = FixtureTransport(
        {
            ("mSettings", "mTeam"): settings_team(),
            ("mMatchup",): matchup(),
            ("mRoster",): roster(),
        }
    )
    client = ESPNClient(transport=transport)
    settings = client.get_league_settings(LEAGUE_ID, SEASON)
    assert settings.teams[0].wins == 8
    games = client.get_matchups(LEAGUE_ID, SEASON)
    assert games[0].winner == "AWAY"
    rosters = client.get_rosters(LEAGUE_ID, SEASON)
    assert "Lamar Jackson" in {entry.name for entry in rosters["1"]}
    assert all(urlparse(url).hostname == "lm-api-reads.fantasy.espn.com" for url in transport.urls)


def test_client_falls_back_to_history_on_404():
    class BoomThenOk:
        def __init__(self):
            self.urls = []

        def get_json(self, url, *, headers=None):
            self.urls.append(url)
            if "leagueHistory" not in url:
                request = httpx.Request("GET", url)
                response = httpx.Response(404, request=request)
                raise httpx.HTTPStatusError("404", request=request, response=response)
            return settings_team()

    transport = BoomThenOk()
    settings = ESPNClient(transport=transport).get_league_settings(LEAGUE_ID, 2025)
    assert settings.name == "Hoboken Local Football League"
    assert any("leagueHistory" in url for url in transport.urls)


def test_actual_season_points_uses_this_year_not_last_year_or_projections():
    stats = [
        {
            "seasonId": 2025,
            "scoringPeriodId": 0,
            "statSourceId": 0,
            "statSplitTypeId": 0,
            "appliedTotal": 213.8,
        },
        {
            "seasonId": 2026,
            "scoringPeriodId": 0,
            "statSourceId": 0,
            "statSplitTypeId": 0,
            "appliedTotal": 55.2,
        },
        {
            "seasonId": 2026,
            "scoringPeriodId": 0,
            "statSourceId": 1,
            "statSplitTypeId": 0,
            "appliedTotal": 99.2,
        },
    ]
    assert actual_season_points(stats, 2026) == 55.2
    assert actual_season_points(stats, 2025) == 213.8
    assert actual_weekly_points(
        [
            {"seasonId": 2025, "scoringPeriodId": 1, "statSourceId": 0, "appliedTotal": 20},
            {"seasonId": 2026, "scoringPeriodId": 1, "statSourceId": 0, "appliedTotal": 4.5},
            {"seasonId": 2026, "scoringPeriodId": 1, "statSourceId": 1, "appliedTotal": 12},
        ],
        2026,
    ) == {1: 4.5}


def test_projected_season_line_uses_split_2_not_rest_of_season():
    stats = [
        {
            "seasonId": 2026,
            "scoringPeriodId": 0,
            "statSourceId": 1,
            "statSplitTypeId": 0,
            "appliedTotal": 166.1,
            "appliedAverage": 23.7,
        },
        {
            "seasonId": 2026,
            "scoringPeriodId": 0,
            "statSourceId": 1,
            "statSplitTypeId": 2,
            "appliedTotal": 353.8,
            "appliedAverage": 22.11,
        },
    ]
    assert projected_season_line(stats, 2026) == (353.8, 22.11)


def test_parse_transactions_reads_waiver_add_and_drop():
    raw = {
        "transactions": [
            {
                "id": "w1",
                "type": "WAIVER",
                "status": "EXECUTED",
                "scoringPeriodId": 2,
                "teamId": 5,
                "bidAmount": 12,
                "items": [
                    {
                        "playerId": 3128390,
                        "type": "ADD",
                        "fromTeamId": 0,
                        "toTeamId": 5,
                    },
                    {
                        "playerId": -16001,
                        "type": "DROP",
                        "fromTeamId": 5,
                        "toTeamId": 0,
                    },
                ],
            }
        ]
    }
    txs = parse_transactions(raw)
    assert len(txs) == 1
    assert txs[0].tx_type == "WAIVER"
    assert txs[0].bid_amount == 12
    assert [item.item_type for item in txs[0].items] == ["ADD", "DROP"]
    assert txs[0].items[1].player_id == "-16001"
