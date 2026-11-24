from fantasy_football.draft_accuracy.baselines import flex_aware_replacement, vbd_for_player
from fantasy_football.models.draft import PlayerSeasonStats
from fantasy_football.models.league import LeagueSettings, RosterSlot


def _standard_settings(num_teams: int = 12) -> LeagueSettings:
    return LeagueSettings(
        league_id="test",
        season=2024,
        name="Test",
        num_teams=num_teams,
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


def _n_players(position: str, n: int, top: float, step: float) -> list:
    out = []
    for i in range(n):
        out.append(
            PlayerSeasonStats(
                player_id=f"{position}-{i+1}",
                name=f"{position}{i+1}",
                position=position,
                adp=float(i + 1),
                season_points=top - i * step,
            )
        )
    return out


def test_qb_replacement_is_last_starter():
    pool = _n_players("QB", 20, 400, 10)
    levels = flex_aware_replacement(pool, _standard_settings(), 12)
    # QB12 = 400 - 11*10 = 290
    assert levels.last_starter["QB"] == 290
    assert levels.qb_streaming is not None


def test_flex_raises_wr_replacement_when_flex_is_wrs():
    # Dedicated: 24 RB, 24 WR, 12 TE. FLEX 12 more, all WRs if WRs outscore leftover RBs.
    rbs = _n_players("RB", 40, 250, 5)  # RB25 = 130
    wrs = _n_players("WR", 50, 240, 4)  # leftover WRs still high
    tes = _n_players("TE", 20, 180, 8)
    qbs = _n_players("QB", 16, 350, 8)
    levels = flex_aware_replacement(rbs + wrs + tes + qbs, _standard_settings(), 12)
    assert levels.last_starter["QB"] == 350 - 11 * 8
    # WR24 dedicated, then FLEX takes leftover RB/WR/TE, so last starter can be past Nth.
    wr24 = 240 - 23 * 4
    rb24 = 250 - 23 * 5
    assert levels.last_starter["WR"] < wr24
    assert levels.last_starter["RB"] <= rb24


def test_unknown_position_does_not_use_raw_points():
    pool = _n_players("QB", 12, 300, 5) + _n_players("RB", 24, 200, 4)
    levels = flex_aware_replacement(pool, _standard_settings(), 12)
    raw = 430.0
    vbd = vbd_for_player(raw, "", levels)
    assert vbd < raw
    assert vbd == raw - max(levels.last_starter.values())
