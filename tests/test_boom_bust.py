from fantasy_football.league_intel.boom_bust import build_boom_bust
from fantasy_football.models.draft import DraftPick, DraftResult, Player, PlayerSeasonStats
from fantasy_football.models.league import LeagueSettings, Team


def _settings() -> LeagueSettings:
    return LeagueSettings(
        league_id="test",
        season=2026,
        name="Test",
        num_teams=2,
        teams=[Team(team_id="1", name="Alpha"), Team(team_id="2", name="Beta")],
    )


def _stats(**kwargs) -> PlayerSeasonStats:
    weekly = kwargs.pop("weekly_points", {week: 10.0 for week in range(1, 12)})
    return PlayerSeasonStats(weekly_points=weekly, **kwargs)


def _draft(*picks: DraftPick) -> DraftResult:
    return DraftResult(league_id="test", season=2026, picks=list(picks))


def _pick(overall: int, team_id: str, stats: PlayerSeasonStats, round_num: int = 1) -> DraftPick:
    return DraftPick(
        round=round_num,
        round_pick=1,
        overall_pick=overall,
        team_id=team_id,
        team_name="",
        player=Player(
            player_id=stats.player_id,
            name=stats.name,
            position=stats.position,
        ),
    )


def test_boom_and_bust_use_paced_projection_gap():
    boom = _stats(
        player_id="b1",
        name="Boom Guy",
        position="RB",
        projected_points=160.0,
        projected_ppw=10.0,
        weekly_points={week: 20.0 for week in range(1, 12)},
    )
    bust = _stats(
        player_id="u1",
        name="Bust Guy",
        position="WR",
        projected_points=240.0,
        projected_ppw=15.0,
        weekly_points={week: 2.0 for week in range(1, 12)},
    )
    kicker = _stats(
        player_id="k1",
        name="Leg",
        position="K",
        projected_points=80.0,
        projected_ppw=5.0,
        weekly_points={week: 20.0 for week in range(1, 12)},
    )
    report = build_boom_bust(
        _settings(),
        _draft(_pick(1, "1", boom), _pick(2, "2", bust), _pick(3, "1", kicker, round_num=16)),
        [boom, bust, kicker],
    )
    assert report.completed_week == 11
    assert [row.player_name for row in report.booms] == ["Boom Guy"]
    assert report.booms[0].badge == "Big boom"
    assert report.booms[0].team_name == "Alpha"
    assert report.booms[0].pace_delta >= 100
    assert [row.player_name for row in report.busts] == ["Bust Guy"]
    assert report.busts[0].badge == "Big bust"
    assert all(row.position != "K" for row in report.booms + report.busts)


def test_bye_week_is_omitted_from_games_and_points():
    player = _stats(
        player_id="rb1",
        name="Bye Boom",
        position="RB",
        projected_points=160.0,
        projected_ppw=10.0,
        bye_week=6,
        weekly_points={week: 20.0 for week in range(1, 12) if week != 6},
    )
    report = build_boom_bust(_settings(), _draft(_pick(1, "1", player)), [player])
    assert report.booms
    assert report.booms[0].games == 10
    assert report.booms[0].actual_points == 200.0


def test_zeroed_projection_is_filled_from_rank_neighbors():
    injured = _stats(
        player_id="ir1",
        name="IR Star",
        position="RB",
        ppr_rank=12,
        projected_points=0.0,
        projected_ppw=0.0,
        injury_status="INJURY_RESERVE",
        weekly_points={week: 0.0 for week in range(1, 12)},
    )
    neighbors = [
        _stats(
            player_id=f"n{i}",
            name=f"Peer {i}",
            position="RB",
            ppr_rank=10 + i,
            projected_points=240.0,
            projected_ppw=15.0,
        )
        for i in range(5)
    ]
    report = build_boom_bust(
        _settings(),
        _draft(_pick(18, "2", injured, round_num=2)),
        [injured, *neighbors],
    )
    assert report.busts
    row = report.busts[0]
    assert row.imputed
    assert row.proj_ppw == 15.0
    assert row.injury == "INJURY_RESERVE"


def test_empty_when_no_draft():
    report = build_boom_bust(_settings(), None, [])
    assert report.booms == []
    assert report.busts == []
    assert report.completed_week == 0
