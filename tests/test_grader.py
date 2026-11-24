from fantasy_football.draft_accuracy.grader import DraftGrader
from fantasy_football.models.draft import DraftPick, DraftResult, Player, PlayerSeasonStats
from fantasy_football.models.league import LeagueSettings, RosterSlot


def _settings() -> LeagueSettings:
    return LeagueSettings(
        league_id="test",
        season=2024,
        name="Test",
        num_teams=12,
        roster_slots=[
            RosterSlot(position="QB", count=1),
            RosterSlot(position="RB", count=2),
            RosterSlot(position="WR", count=2),
            RosterSlot(position="TE", count=1),
            RosterSlot(position="FLEX", count=1, is_flex=True),
            RosterSlot(position="K", count=1),
            RosterSlot(position="D/ST", count=1),
        ],
    )


def _player(pid, name, pos, adp, pts):
    return PlayerSeasonStats(
        player_id=pid, name=name, position=pos, adp=adp, season_points=pts
    )


def _pick(overall, round_num, team_id, stats: PlayerSeasonStats) -> DraftPick:
    return DraftPick(
        round=round_num,
        round_pick=((overall - 1) % 12) + 1,
        overall_pick=overall,
        team_id=team_id,
        team_name=f"Team {team_id}",
        player=Player(
            player_id=stats.player_id,
            name=stats.name,
            position=stats.position,
            adp=stats.adp,
            season_points=stats.season_points,
        ),
    )


def _pool_and_draft():
    """
    16-round snake skeleton: team 1 picks 1, 24, 25, 48, ...
    Pool includes stars with realistic ADPs plus a monster kicker (late ADP).
    """
    rb1 = _player("rb1", "CMC", "RB", 1.2, 320)
    wr1 = _player("wr1", "Jefferson", "WR", 4.0, 280)
    wr2 = _player("wr2", "Chase", "WR", 8.0, 270)
    rb2 = _player("rb2", "Bijan", "RB", 6.0, 260)
    qb_early = _player("qb1", "Lamar", "QB", 42.0, 430)  # round-4 ADP
    wr_mid = _player("wr3", "Nico", "WR", 28.0, 240)
    te1 = _player("te1", "Bowers", "TE", 22.0, 210)
    k1 = _player("k1", "Boswell", "K", 140.0, 188)
    qb_stream = _player("qb2", "Streamer", "QB", 110.0, 300)
    filler = []
    for i in range(3, 40):
        filler.append(_player(f"rb{i}", f"RB{i}", "RB", 50.0 + i, 120 - i))
        filler.append(_player(f"wr{i+10}", f"WR{i}", "WR", 55.0 + i, 118 - i))
    for i in range(2, 16):
        filler.append(_player(f"qb{i+2}", f"QB{i}", "QB", 70.0 + i, 250 - i * 8))
        filler.append(_player(f"te{i}", f"TE{i}", "TE", 80.0 + i, 100 - i))
        filler.append(_player(f"k{i}", f"K{i}", "K", 145.0 + i, 140 - i))

    stars = [rb1, wr1, wr2, rb2, qb_early, wr_mid, te1, k1, qb_stream]
    pool = stars + filler

    # Team 1 takes CMC then later filler so Lamar is still on the board at pick 25/48.
    picks = [
        _pick(1, 1, "1", rb1),
        _pick(2, 1, "2", wr1),
        _pick(3, 1, "3", wr2),
        _pick(24, 2, "1", rb2),
        _pick(25, 3, "1", wr_mid),
        _pick(48, 4, "1", te1),
    ]
    # Pad remaining picks so total_rounds == 16 (K/DST last two).
    overall = 49
    for rnd in range(5, 17):
        for team in range(1, 13):
            if overall == 48:
                overall += 1
            filler_p = _player(f"pad-{overall}", f"Pad{overall}", "RB", float(overall), 50)
            pool.append(filler_p)
            if not any(p.overall_pick == overall for p in picks):
                picks.append(_pick(overall, rnd, str(team), filler_p))
            overall += 1

    draft = DraftResult(league_id="test", season=2024, picks=picks)
    return pool, draft


def test_kicker_is_not_best_in_round_3():
    pool, draft = _pool_and_draft()
    grader = DraftGrader(draft, _settings(), pool)
    grade = grader.grade_team("1", max_round=4)
    round3 = next(g for g in grade.picks if g.round_num == 3)
    assert round3.best is not None
    assert round3.best.position not in {"K", "D/ST"}
    assert round3.best.player_id != "k1"


def test_streaming_qb_not_best_in_round_3():
    pool, draft = _pool_and_draft()
    grader = DraftGrader(draft, _settings(), pool)
    grade = grader.grade_team("1", max_round=4)
    round3 = next(g for g in grade.picks if g.round_num == 3)
    assert round3.best is not None
    assert round3.best.player_id != "qb2"


def test_round_1_best_is_skill_with_early_adp():
    pool, draft = _pool_and_draft()
    grader = DraftGrader(draft, _settings(), pool)
    grade = grader.grade_team("1", max_round=1)
    r1 = grade.picks[0]
    assert r1.best is not None
    assert r1.best.position in {"RB", "WR", "TE"}
    # Lamar ADP 42 is outside pick 1 + 0.5*12 = 7
    assert r1.best.player_id != "qb1"


def test_round_4_lamar_can_be_best_when_adp_matches():
    pool, draft = _pool_and_draft()
    grader = DraftGrader(draft, _settings(), pool)
    grade = grader.grade_team("1", max_round=4)
    r4 = next(g for g in grade.picks if g.round_num == 4)
    assert r4.best is not None
    assert r4.best.player_id == "qb1"
    assert r4.best.position == "QB"


def test_process_value_positive_on_a_faller():
    pool, draft = _pool_and_draft()
    grader = DraftGrader(draft, _settings(), pool)
    # Team 1 pick 24 is Bijan ADP 6 — he fell 18 spots (steal).
    grade = grader.grade_team("1", max_round=2)
    r2 = next(g for g in grade.picks if g.round_num == 2)
    assert r2.process_value > 0
    assert r2.verdict == "steal"
    assert r2.headline.startswith("Fell")
    assert "ahead of this slot" in r2.context
    # CMC ADP 1.2 at pick 1 is roughly even
    r1 = grade.picks[0]
    assert abs(r1.process_value) < 2
    assert r1.verdict == "even"
    assert r1.headline == "On the board"
    assert "ADP had them" in r1.context


def test_reach_lists_players_still_on_the_board():
    pool, draft = _pool_and_draft()
    for pick in draft.picks:
        if pick.overall_pick == 25:
            pick.player = Player(
                player_id="k1",
                name="Boswell",
                position="K",
                adp=140.0,
                season_points=188,
            )
            break
    grader = DraftGrader(draft, _settings(), pool)
    grade = grader.grade_team("1", max_round=3)
    r3 = next(g for g in grade.picks if g.round_num == 3)
    assert r3.verdict == "miss"
    assert r3.headline.startswith("Reached")
    assert r3.alternatives
    assert all(alt.player_id != "k1" for alt in r3.alternatives)
    assert "ADP had them" in r3.context


def test_late_miss_badges_are_capped():
    pool, draft = _pool_and_draft()
    grade = DraftGrader(draft, _settings(), pool).grade_team("1")
    late = [pick for pick in grade.picks if pick.verdict == "miss" and pick.round_num > 4]
    assert len(late) <= 2


def test_paid_off_late_reach_keeps_miss_badge():
    hero = _player("hero", "Wilson", "WR", 67.0, 400)
    busts = [
        _player("b1", "Bust1", "RB", 160.0, 8),
        _player("b2", "Bust2", "RB", 170.0, 7),
        _player("b3", "Bust3", "RB", 180.0, 6),
    ]
    early = [_player(f"e{i}", f"Early{i}", "WR", float(i), 90) for i in range(1, 5)]
    board = [_player(f"board{i}", f"Board{i}", "WR", 50.0 + i, 70) for i in range(8)]
    pool = [hero, *busts, *early, *board]
    picks = [
        _pick(1, 1, "1", early[0]),
        _pick(2, 1, "1", early[1]),
        _pick(3, 1, "1", early[2]),
        _pick(4, 1, "1", early[3]),
        _pick(49, 5, "1", hero),
        _pick(72, 6, "1", busts[0]),
        _pick(73, 7, "1", busts[1]),
        _pick(96, 8, "1", busts[2]),
    ]
    draft = DraftResult(league_id="test", season=2026, picks=picks)
    grade = DraftGrader(draft, _settings(), pool).grade_team("1")
    paid = next(pick for pick in grade.picks if pick.actual.player_id == "hero")
    assert paid.verdict == "miss"
    assert paid.season_verdict == "hit"
    unpaid_late = [
        pick
        for pick in grade.picks
        if pick.verdict == "miss" and pick.round_num > 4 and pick.season_verdict != "hit"
    ]
    assert len(unpaid_late) <= 2


def test_early_adp_reach_stays_a_miss():
    rb_star = _player("bijan", "Bijan", "RB", 2.0, 260)
    wr_star = _player("chase", "Chase", "WR", 3.0, 270)
    saquon = _player("saq", "Saquon", "RB", 33.0, 80)
    filler = [_player(f"x{i}", f"X{i}", "WR", 8.0 + i, 100) for i in range(20)]
    pool = [rb_star, wr_star, saquon] + filler
    picks = [
        _pick(1, 1, "1", saquon),
        _pick(2, 1, "2", rb_star),
        _pick(3, 1, "3", wr_star),
    ]
    for i, stats in enumerate(filler, start=4):
        picks.append(_pick(i, 1 + (i - 1) // 12, "2", stats))
    draft = DraftResult(league_id="test", season=2026, picks=picks)
    grade = DraftGrader(draft, _settings(), pool).grade_team("1", max_round=1)
    r1 = grade.picks[0]
    assert r1.verdict == "miss"
    assert "Reached" in r1.headline
    assert r1.season_verdict == "bust"
    names = {alt.name for alt in r1.alternatives}
    assert "QB" not in {alt.position for alt in r1.alternatives}
    assert names & {"Bijan", "Chase"}


def test_does_not_recommend_qb_once_roster_has_one():
    qb1 = _player("qb1", "Lamar", "QB", 5.0, 400)
    qb2 = _player("qb2", "Allen", "QB", 7.0, 390)
    wr1 = _player("wr1", "Chase", "WR", 4.0, 280)
    wr2 = _player("wr2", "Nico", "WR", 8.0, 200)
    reach = _player("rb-late", "LateRB", "RB", 40.0, 70)
    pool = [qb1, qb2, wr1, wr2, reach]
    picks = [
        _pick(1, 1, "1", qb1),
        _pick(2, 1, "2", wr1),
        _pick(13, 2, "1", reach),
        _pick(14, 2, "2", wr2),
    ]
    draft = DraftResult(league_id="test", season=2026, picks=picks)
    grade = DraftGrader(draft, _settings(), pool).grade_team("1", max_round=2)
    r2 = next(g for g in grade.picks if g.round_num == 2)
    assert r2.verdict == "miss"
    assert all(alt.position != "QB" for alt in r2.alternatives)
    assert all(alt.position != "QB" for alt in r2.season_alternatives)


def test_skill_reach_does_not_list_qbs():
    qb = _player("qb1", "Allen", "QB", 4.0, 400)
    rb = _player("rb1", "Bijan", "RB", 2.0, 300)
    taken = _player("saq", "Saquon", "RB", 30.0, 90)
    pool = [qb, rb, taken]
    picks = [_pick(1, 1, "1", taken), _pick(2, 1, "2", rb)]
    draft = DraftResult(league_id="test", season=2026, picks=picks)
    grade = DraftGrader(draft, _settings(), pool).grade_team("1", max_round=1)
    r1 = grade.picks[0]
    assert r1.verdict == "miss"
    assert all(alt.position != "QB" for alt in r1.alternatives)
    assert any(alt.name == "Bijan" for alt in r1.alternatives)
    assert all(alt.position != "QB" for alt in r1.season_alternatives)


def test_season_alts_stay_near_the_slot_adp():
    star = _player("chase", "Chase", "WR", 3.0, 280)
    bust = _player("saq", "Saquon", "RB", 1.5, 50)
    nearby = _player("near", "Nearby", "RB", 12.0, 300)
    sleeper = _player("sleep", "Sleeper", "RB", 80.0, 350)
    rest = [_player(f"w{i}", f"WR{i}", "WR", 10.0 + i, 200 - i) for i in range(12)]
    pool = [star, bust, nearby, sleeper] + rest
    picks = [_pick(1, 1, "1", bust), _pick(2, 1, "2", star)]
    draft = DraftResult(league_id="test", season=2026, picks=picks)
    grade = DraftGrader(draft, _settings(), pool).grade_team("1", max_round=1)
    r1 = grade.picks[0]
    draft_names = {alt.name for alt in r1.alternatives}
    season_names = {alt.name for alt in r1.season_alternatives}
    assert "Sleeper" not in draft_names
    assert "Sleeper" not in season_names
    assert "Nearby" in season_names
    assert r1.redraft_rank is not None
    assert r1.redraft_rank > 1
    assert r1.season_verdict == "bust"
    assert "redraft" in r1.season_note.lower()


def test_season_alts_ignore_names_well_outside_the_slot():
    bust = _player("saq", "Saquon", "RB", 86.0, 50)
    nearby = _player("near", "Nearby", "WR", 90.0, 200)
    leftover = _player("gold", "Golden", "WR", 64.0, 350)
    sleeper = _player("sleep", "Sleeper", "RB", 140.0, 400)
    worse = _player("meh", "Meh", "WR", 88.0, 40)
    pool = [bust, nearby, leftover, sleeper, worse]
    picks = [_pick(86, 8, "1", bust), _pick(87, 8, "2", nearby)]
    draft = DraftResult(league_id="test", season=2026, picks=picks)
    grade = DraftGrader(draft, _settings(), pool).grade_team("1", max_round=8)
    r8 = next(pick for pick in grade.picks if pick.overall_pick == 86)
    names = {alt.name for alt in r8.season_alternatives}
    assert names == {"Nearby"}
    assert "Golden" not in names
    assert "Sleeper" not in names
    assert "Meh" not in names


def test_reach_that_leads_the_board_is_a_season_hit():
    hero = _player("hero", "Hero", "RB", 40.0, 400)
    others = [_player(f"p{i}", f"P{i}", "RB", float(i), 90.0) for i in range(1, 40) if i != 8]
    pool = [hero] + others
    picks = [_pick(8, 1, "1", hero)]
    for stats in others:
        picks.append(_pick(int(stats.adp), 1, "2", stats))
    draft = DraftResult(league_id="test", season=2026, picks=picks)
    grade = DraftGrader(draft, _settings(), pool).grade_team("1", max_round=1)
    r1 = grade.picks[0]
    assert r1.verdict == "miss"
    assert "Reached" in r1.headline
    assert r1.season_verdict == "hit"
    assert r1.redraft_rank == 1
