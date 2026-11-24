from fantasy_football.league_intel.draft_board import build_draft_board
from test_grader import _pool_and_draft, _settings


def test_draft_board_ranks_process_and_outcome():
    pool, draft = _pool_and_draft()
    report = build_draft_board(_settings(), draft, pool)
    assert report.drafted
    assert report.grades
    assert report.grades[0].process_rank == 1
    ranks = {row.process_rank for row in report.grades}
    assert ranks == set(range(1, len(report.grades) + 1))
    names = {row.team_id: row.team_name for row in report.grades}
    assert names["1"] == "Team 1"
    team1 = next(row for row in report.grades if row.team_id == "1")
    assert team1.picks
    bijan = next(pick for pick in team1.picks if pick.overall_pick == 24)
    assert bijan.verdict == "steal"
    assert bijan.player_name == "Bijan"
    assert bijan.headline.startswith("Fell")
    assert bijan.season_points > 0
    assert bijan.redraft_rank is not None
    assert bijan.season_note
    assert report.boom_bust is not None


def test_draft_board_empty_when_undrafted():
    report = build_draft_board(_settings(), None, [])
    assert report.drafted is False
    assert report.grades == []
    assert report.boom_bust is not None
    assert report.boom_bust.booms == []
