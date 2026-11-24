from fantasy_football.league_intel.luck import build_luck, luck_leaders
from fantasy_football.league_intel.overview import build_overview
from fantasy_football.models.league import (
    LeagueSettings,
    Matchup,
    MatchupSide,
    RosterSlot,
    Team,
)
from espn_fixtures import LEAGUE_ID, SEASON, matchup, settings_team
from fantasy_football.espn.parse import parse_league_settings, parse_matchups


def _team(tid: str, name: str) -> Team:
    return Team(team_id=tid, name=name)


def _game(mid: int, period: int, home_id: str, home_pts: float, away_id: str, away_pts: float) -> Matchup:
    winner = "HOME" if home_pts > away_pts else "AWAY" if away_pts > home_pts else "TIE"
    return Matchup(
        matchup_id=mid,
        period=period,
        home=MatchupSide(team_id=home_id, points=home_pts),
        away=MatchupSide(team_id=away_id, points=away_pts),
        winner=winner,
    )


def _settings() -> LeagueSettings:
    return LeagueSettings(
        league_id="test",
        season=2024,
        name="Test",
        num_teams=4,
        regular_season_periods=1,
        teams=[
            _team("1", "Alpha"),
            _team("2", "Bravo"),
            _team("3", "Charlie"),
            _team("4", "Delta"),
        ],
        roster_slots=[RosterSlot(position="RB", count=2)],
    )


def test_lucky_win_is_below_median_and_unlucky_loss_is_above():
    # A 100 beats B 90; C 80 beats D 70. Median 85.
    # C wins while below median (lucky). B loses while above median (unlucky).
    games = [
        _game(1, 1, "1", 100, "2", 90),
        _game(2, 1, "3", 80, "4", 70),
    ]
    rows = {row.team_id: row for row in build_luck(_settings(), games)}
    assert rows["1"].actual_wins == 1
    assert rows["1"].all_play_wins == 3
    assert rows["1"].expected_wins == 1.0
    assert rows["1"].luck == 0.0
    assert rows["2"].actual_wins == 0
    assert rows["2"].all_play_wins == 2
    assert rows["2"].unlucky_losses == 1
    assert rows["2"].luck == -0.67
    assert rows["3"].actual_wins == 1
    assert rows["3"].all_play_wins == 1
    assert rows["3"].lucky_wins == 1
    assert rows["3"].luck == 0.67
    luckiest, unluckiest = luck_leaders(list(rows.values()))
    assert luckiest is not None and luckiest.team_id == "3"
    assert unluckiest is not None and unluckiest.team_id == "2"


def test_2024_fixture_luck_sums_near_zero():
    settings = parse_league_settings(settings_team(), league_id=LEAGUE_ID, season=SEASON)
    report = build_overview(settings, parse_matchups(matchup()))
    assert report.luck
    assert report.luckiest is not None
    assert report.unluckiest is not None
    assert report.luckiest.team_id != report.unluckiest.team_id
    total = sum(row.luck for row in report.luck)
    assert abs(total) < 0.15
    played = [row for row in report.luck if row.games]
    assert all(row.games == 14 for row in played)
