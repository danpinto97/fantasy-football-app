from fantasy_football.league_intel.wire import build_wire_report
from fantasy_football.models.draft import PlayerSeasonStats
from fantasy_football.models.league import (
    LeagueSettings,
    LeagueTransaction,
    RosterEntry,
    RosterSlot,
    Team,
    TransactionItem,
)


def _settings() -> LeagueSettings:
    return LeagueSettings(
        league_id="test",
        season=2024,
        name="Test",
        num_teams=2,
        teams=[
            Team(team_id="1", name="Alpha"),
            Team(team_id="2", name="Beta"),
        ],
        roster_slots=[RosterSlot(position="RB", count=2)],
    )


def _player(pid, name, weekly):
    return PlayerSeasonStats(
        player_id=pid,
        name=name,
        position="RB",
        season_points=sum(weekly.values()),
        weekly_points=weekly,
    )


def _entry(pid, name, team_id):
    return RosterEntry(
        player_id=pid,
        name=name,
        position="RB",
        slot="RB",
        lineup_slot_id=2,
        on_team_id=team_id,
    )


def test_waiver_add_counts_points_after_the_claim():
    star = _player("rb1", "Sleeper", {1: 10, 2: 10, 5: 40, 6: 50})
    tx = LeagueTransaction(
        tx_id="a1",
        tx_type="WAIVER",
        status="EXECUTED",
        scoring_period=5,
        team_id="1",
        items=[TransactionItem(player_id="rb1", item_type="ADD", from_team_id="0", to_team_id="1")],
    )
    report = build_wire_report(_settings(), [tx], [star], {})
    assert report.best_adds
    add = report.best_adds[0]
    assert add.player_name == "Sleeper"
    assert add.source == "Waiver"
    assert add.week == 5
    assert add.points_after == 90.0


def test_drop_counts_rest_of_season_and_add_stops_at_later_drop():
    player = _player("rb1", "Dart", {3: 5, 4: 20, 5: 30, 6: 40})
    add = LeagueTransaction(
        tx_id="add",
        tx_type="FREEAGENT",
        status="EXECUTED",
        scoring_period=3,
        team_id="1",
        items=[TransactionItem(player_id="rb1", item_type="ADD", from_team_id="0", to_team_id="1")],
    )
    drop = LeagueTransaction(
        tx_id="drop",
        tx_type="FREEAGENT",
        status="EXECUTED",
        scoring_period=5,
        team_id="1",
        items=[TransactionItem(player_id="rb1", item_type="DROP", from_team_id="1", to_team_id="0")],
    )
    report = build_wire_report(_settings(), [add, drop], [player], {})
    assert report.best_adds[0].points_after == 25.0  # weeks 3-4
    assert report.worst_drops[0].player_name == "Dart"
    assert report.worst_drops[0].points_after == 70.0  # weeks 5-6


def test_same_week_add_and_drop_does_not_claim_the_season():
    player = _player("rb1", "Dart", {1: 10, 2: 40, 3: 50})
    add = LeagueTransaction(
        tx_id="add",
        tx_type="FREEAGENT",
        status="EXECUTED",
        scoring_period=1,
        team_id="1",
        items=[TransactionItem(player_id="rb1", item_type="ADD", from_team_id="0", to_team_id="1")],
    )
    drop = LeagueTransaction(
        tx_id="drop",
        tx_type="FREEAGENT",
        status="EXECUTED",
        scoring_period=1,
        team_id="1",
        items=[TransactionItem(player_id="rb1", item_type="DROP", from_team_id="1", to_team_id="0")],
    )
    report = build_wire_report(_settings(), [add, drop], [player], {})
    assert report.best_adds == []
    assert report.worst_drops[0].points_after == 100.0


def test_canceled_trade_proposal_is_ignored():
    tx = LeagueTransaction(
        tx_id="p1",
        tx_type="TRADE_PROPOSAL",
        status="CANCELED",
        scoring_period=4,
        team_id="1",
        items=[
            TransactionItem(player_id="a", item_type="TRADE", from_team_id="1", to_team_id="2"),
            TransactionItem(player_id="b", item_type="TRADE", from_team_id="2", to_team_id="1"),
        ],
    )
    report = build_wire_report(_settings(), [tx], [], {})
    assert report.best_trades == []
    assert report.worst_trades == []


def test_trade_from_roster_swap_after_accept():
    left = _player("star", "Star", {4: 5, 5: 40, 6: 50})
    right = _player("bust", "Bust", {4: 5, 5: 2, 6: 3})
    txs = [
        LeagueTransaction(
            tx_id="accept",
            tx_type="TRADE_ACCEPT",
            status="",
            scoring_period=5,
            team_id="2",
        )
    ]
    rosters = {
        4: {
            "1": [_entry("star", "Star", "1")],
            "2": [_entry("bust", "Bust", "2")],
        },
        5: {
            "1": [_entry("bust", "Bust", "1")],
            "2": [_entry("star", "Star", "2")],
        },
    }
    report = build_wire_report(_settings(), txs, [left, right], rosters)
    assert report.best_trades
    trade = report.best_trades[0]
    assert trade.week == 5
    winner = next(side for side in trade.sides if side.team_id == "2")
    assert winner.received == ["Star"]
    assert winner.sent == ["Bust"]
    assert winner.net == 85.0
    assert report.worst_trades
    loser = next(side for side in report.worst_trades[0].sides if side.team_id == "1")
    assert loser.net == -85.0
    assert report.trades
    assert report.trades[0].week == 5
    winner_asset = winner.received_players[0]
    assert winner_asset.player_name == "Star"
    assert winner_asset.pts_per_week == 45.0


def test_highest_spends_ranks_waiver_bids():
    cheap = _player("rb1", "Cheap", {4: 10, 5: 10})
    pricey = _player("rb2", "Pricey", {4: 8, 5: 8})
    txs = [
        LeagueTransaction(
            tx_id="w1",
            tx_type="WAIVER",
            status="EXECUTED",
            scoring_period=4,
            team_id="1",
            bid_amount=12,
            items=[TransactionItem(player_id="rb1", item_type="ADD", from_team_id="0", to_team_id="1")],
        ),
        LeagueTransaction(
            tx_id="w2",
            tx_type="WAIVER",
            status="EXECUTED",
            scoring_period=4,
            team_id="2",
            bid_amount=55,
            items=[TransactionItem(player_id="rb2", item_type="ADD", from_team_id="0", to_team_id="2")],
        ),
        LeagueTransaction(
            tx_id="fa",
            tx_type="FREEAGENT",
            status="EXECUTED",
            scoring_period=4,
            team_id="1",
            items=[TransactionItem(player_id="rb1", item_type="ADD", from_team_id="0", to_team_id="1")],
        ),
    ]
    report = build_wire_report(_settings(), txs, [cheap, pricey], {})
    assert [row.player_name for row in report.highest_spends] == ["Pricey", "Cheap"]
    assert report.highest_spends[0].bid == 55
    assert report.highest_spends[0].pts_per_week == 8.0


def test_bye_week_is_omitted_from_add_average():
    player = PlayerSeasonStats(
        player_id="rb1",
        name="Bye Add",
        position="RB",
        season_points=40,
        weekly_points={3: 20, 5: 20},
        bye_week=4,
    )
    tx = LeagueTransaction(
        tx_id="a1",
        tx_type="WAIVER",
        status="EXECUTED",
        scoring_period=3,
        team_id="1",
        bid_amount=20,
        items=[TransactionItem(player_id="rb1", item_type="ADD", from_team_id="0", to_team_id="1")],
    )
    report = build_wire_report(_settings(), [tx], [player], {})
    add = report.best_adds[0]
    assert add.points_after == 40.0
    assert add.weeks == 2
    assert add.pts_per_week == 20.0
