from espn_fixtures import LEAGUE_ID, SEASON, matchup, settings_and_matchup, settings_team
from fantasy_football.espn.parse import parse_league_settings, parse_matchups
from fantasy_football.league_intel.overview import build_overview


def _report():
    settings = parse_league_settings(settings_team(), league_id=LEAGUE_ID, season=SEASON)
    return build_overview(settings, parse_matchups(matchup()))


def test_standings_follow_playoff_seed():
    report = _report()
    assert report.name == "Hoboken Local Football League"
    assert report.regular_season_periods == 14
    assert [row.seed for row in report.standings] == list(range(1, 13))
    assert report.standings[0].name == "Orlando Troll Boys"
    assert report.standings[0].wins == 11
    assert report.standings[0].losses == 3
    assert all(row.games == 14 for row in report.standings)


def test_highest_pf_is_union_city_not_the_champion():
    report = _report()
    assert report.highest_pf is not None
    assert report.highest_pf.team_name == "Union City Bucks"
    assert report.highest_pf.value == 1584.4


def test_hottest_week_is_week_14_mouse_hunters():
    report = _report()
    assert report.hottest_week is not None
    assert report.hottest_week.team_id == "10"
    assert report.hottest_week.team_name == "Monroe St. Mouse Hunters"
    assert report.hottest_week.value == 164.28
    assert "Week 14" in report.hottest_week.detail
    assert report.top_weeks[0].period == 14
    assert report.top_weeks[0].points == 164.28


def test_most_consistent_uses_regular_season_stdev():
    report = _report()
    assert report.most_consistent is not None
    lowest = min(report.standings, key=lambda row: (row.stdev, -row.points_for))
    assert report.most_consistent.team_id == lowest.team_id
    assert report.most_consistent.value == lowest.stdev


def test_combined_settings_matchup_payload_parses():
    raw = settings_and_matchup()
    settings = parse_league_settings(raw, league_id=LEAGUE_ID, season=SEASON)
    report = build_overview(settings, parse_matchups(raw))
    assert len(report.standings) == 12
    assert len(report.top_weeks) == 8
