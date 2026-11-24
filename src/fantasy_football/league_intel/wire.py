"""Best waiver/FA adds, worst drops, and reconstructed trades. No HTTP."""

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from fantasy_football.models.draft import PlayerSeasonStats
from fantasy_football.models.league import (
    LeagueSettings,
    LeagueTransaction,
    RosterEntry,
    TransactionItem,
)
from fantasy_football.nfl import completed_scoring_week

TOP_N = 5
WIRE_TYPES = {"WAIVER", "FREEAGENT"}
TRADE_MARKERS = {"TRADE_ACCEPT", "TRADE_UPHOLD"}


class WireMove(BaseModel):
    team_id: str
    team_name: str
    player_name: str
    position: str
    source: str
    week: int
    points_after: float
    bid: float = 0.0
    weeks: int = 0
    pts_per_week: float = 0.0


class TradeAsset(BaseModel):
    player_name: str
    position: str
    points: float = 0.0
    weeks: int = 0
    pts_per_week: float = 0.0


class TradeSide(BaseModel):
    team_id: str
    team_name: str
    received: List[str] = Field(default_factory=list)
    sent: List[str] = Field(default_factory=list)
    received_players: List[TradeAsset] = Field(default_factory=list)
    sent_players: List[TradeAsset] = Field(default_factory=list)
    net: float = 0.0
    net_ppw: float = 0.0


class TradeRow(BaseModel):
    week: int
    sides: List[TradeSide] = Field(default_factory=list)


class WireReport(BaseModel):
    league_id: str
    season: int
    completed_week: int = 0
    best_adds: List[WireMove] = Field(default_factory=list)
    worst_drops: List[WireMove] = Field(default_factory=list)
    highest_spends: List[WireMove] = Field(default_factory=list)
    best_trades: List[TradeRow] = Field(default_factory=list)
    worst_trades: List[TradeRow] = Field(default_factory=list)
    trades: List[TradeRow] = Field(default_factory=list)


def _executed(tx: LeagueTransaction) -> bool:
    status = (tx.status or "").upper()
    if status in {"CANCELED", "CANCELLED", "FAILED", "VETOED"}:
        return False
    if tx.tx_type in TRADE_MARKERS:
        return True
    return status in {"", "EXECUTED", "SUCCESS"}


def _window(
    weekly: Dict[int, float],
    start: int,
    *,
    end: Optional[int] = None,
    bye: Optional[int] = None,
    completed: int = 0,
) -> Tuple[float, int]:
    last = completed if completed else max(weekly, default=start)
    if end is not None:
        last = min(last, end - 1)
    if last < start:
        return 0.0, 0
    total = 0.0
    games = 0
    for week in range(start, last + 1):
        if bye and week == bye:
            continue
        games += 1
        total += weekly.get(week, 0.0)
    return total, games


def _points_from(
    weekly: Dict[int, float],
    start: int,
    end: Optional[int] = None,
    *,
    bye: Optional[int] = None,
    completed: int = 0,
) -> float:
    return _window(weekly, start, end=end, bye=bye, completed=completed)[0]


def _dedupe(txs: Sequence[LeagueTransaction]) -> List[LeagueTransaction]:
    seen = set()
    out: List[LeagueTransaction] = []
    for tx in txs:
        if tx.tx_id in seen:
            continue
        seen.add(tx.tx_id)
        out.append(tx)
    return out


def build_wire_report(
    settings: LeagueSettings,
    transactions: Sequence[LeagueTransaction],
    pool: Sequence[PlayerSeasonStats],
    rosters_by_period: Optional[Dict[int, Dict[str, List[RosterEntry]]]] = None,
) -> WireReport:
    names = {team.team_id: team.name for team in settings.teams}
    players = {row.player_id: row for row in pool}
    completed = completed_scoring_week(row.weekly_points for row in pool)
    txs = _dedupe(transactions)
    adds, drops = _wire_moves(txs, players, names, rosters_by_period or {}, completed)
    trades = _reconstruct_trades(txs, rosters_by_period or {}, players, names, completed)
    best_trades = [row for row in sorted(trades, key=_best_net, reverse=True) if _best_net(row) > 0][:TOP_N]
    worst_trades = [row for row in sorted(trades, key=_worst_net) if _worst_net(row) < 0][:TOP_N]
    spends = sorted([row for row in adds if row.bid > 0], key=lambda row: (-row.bid, row.week, row.player_name))
    return WireReport(
        league_id=settings.league_id,
        season=settings.season,
        completed_week=completed,
        best_adds=sorted([row for row in adds if row.points_after > 0], key=lambda row: -row.points_after)[:TOP_N],
        worst_drops=sorted([row for row in drops if row.points_after > 0], key=lambda row: -row.points_after)[:TOP_N],
        highest_spends=spends,
        best_trades=best_trades,
        worst_trades=worst_trades,
        trades=sorted(trades, key=lambda row: row.week),
    )


def _player_label(pid: str, players: Dict[str, PlayerSeasonStats], fallback: str = "") -> Tuple[str, str]:
    stats = players.get(pid)
    if stats is None:
        return fallback or f"Player {pid}", ""
    return stats.name, stats.position


def _weekly(pid: str, players: Dict[str, PlayerSeasonStats]) -> Dict[int, float]:
    stats = players.get(pid)
    return dict(stats.weekly_points) if stats is not None else {}


def _next_drop_period(
    drops: Sequence[Tuple[int, str, str]],
    *,
    team_id: str,
    player_id: str,
    after: int,
) -> Optional[int]:
    later = [
        period
        for period, tid, pid in drops
        if tid == team_id and pid == player_id and period >= after
    ]
    return min(later) if later else None


def _first_absent(
    rosters_by_period: Dict[int, Dict[str, List[RosterEntry]]],
    *,
    team_id: str,
    player_id: str,
    after: int,
) -> Optional[int]:
    for period in sorted(rosters_by_period):
        if period <= after:
            continue
        roster = rosters_by_period.get(period, {}).get(team_id) or []
        if player_id not in {entry.player_id for entry in roster}:
            return period
    return None


def _ppw(points: float, weeks: int) -> float:
    if weeks <= 0:
        return 0.0
    return round(points / weeks, 2)


def _move(
    *,
    team_id: str,
    names: Dict[str, str],
    player_name: str,
    position: str,
    source: str,
    week: int,
    points: float,
    weeks: int,
    bid: float = 0.0,
) -> WireMove:
    return WireMove(
        team_id=team_id,
        team_name=names.get(team_id) or f"Team {team_id}",
        player_name=player_name,
        position=position,
        source=source,
        week=week,
        points_after=round(points, 1),
        bid=bid,
        weeks=weeks,
        pts_per_week=_ppw(points, weeks),
    )


def _wire_moves(
    txs: Sequence[LeagueTransaction],
    players: Dict[str, PlayerSeasonStats],
    names: Dict[str, str],
    rosters_by_period: Dict[int, Dict[str, List[RosterEntry]]],
    completed: int,
) -> Tuple[List[WireMove], List[WireMove]]:
    drop_index: List[Tuple[int, str, str]] = []
    add_items: List[Tuple[LeagueTransaction, TransactionItem]] = []
    drop_items: List[Tuple[LeagueTransaction, TransactionItem]] = []
    for tx in txs:
        if not _executed(tx) or tx.tx_type not in WIRE_TYPES:
            continue
        for item in tx.items:
            if item.item_type == "ADD" and item.to_team_id not in {"", "0"}:
                add_items.append((tx, item))
            elif item.item_type == "DROP" and item.from_team_id not in {"", "0"}:
                drop_items.append((tx, item))
                drop_index.append((tx.scoring_period, item.from_team_id, item.player_id))

    adds: List[WireMove] = []
    for tx, item in add_items:
        ends = [
            _next_drop_period(
                drop_index,
                team_id=item.to_team_id,
                player_id=item.player_id,
                after=tx.scoring_period,
            ),
            _first_absent(
                rosters_by_period,
                team_id=item.to_team_id,
                player_id=item.player_id,
                after=tx.scoring_period,
            ),
        ]
        present = [end for end in ends if end is not None]
        end = min(present) if present else None
        stats = players.get(item.player_id)
        pts, weeks = _window(
            _weekly(item.player_id, players),
            tx.scoring_period,
            end=end,
            bye=stats.bye_week if stats else None,
            completed=completed,
        )
        name, pos = _player_label(item.player_id, players)
        adds.append(
            _move(
                team_id=item.to_team_id,
                names=names,
                player_name=name,
                position=pos,
                source="Waiver" if tx.tx_type == "WAIVER" else "Free agent",
                week=tx.scoring_period,
                points=pts,
                weeks=weeks,
                bid=tx.bid_amount,
            )
        )

    drops: List[WireMove] = []
    for tx, item in drop_items:
        stats = players.get(item.player_id)
        pts, weeks = _window(
            _weekly(item.player_id, players),
            tx.scoring_period,
            bye=stats.bye_week if stats else None,
            completed=completed,
        )
        name, pos = _player_label(item.player_id, players)
        drops.append(
            _move(
                team_id=item.from_team_id,
                names=names,
                player_name=name,
                position=pos,
                source="Waiver" if tx.tx_type == "WAIVER" else "Free agent",
                week=tx.scoring_period,
                points=pts,
                weeks=weeks,
            )
        )
    return adds, drops


def _roster_ids(entries: Iterable[RosterEntry]) -> Dict[str, RosterEntry]:
    return {entry.player_id: entry for entry in entries}


def _reconstruct_trades(
    txs: Sequence[LeagueTransaction],
    rosters_by_period: Dict[int, Dict[str, List[RosterEntry]]],
    players: Dict[str, PlayerSeasonStats],
    names: Dict[str, str],
    completed: int,
) -> List[TradeRow]:
    if not rosters_by_period:
        return []
    periods = sorted(
        {
            tx.scoring_period
            for tx in txs
            if tx.tx_type in TRADE_MARKERS and _executed(tx)
        }
    )
    rows: List[TradeRow] = []
    seen_pairs = set()
    for period in periods:
        prev = rosters_by_period.get(period - 1)
        curr = rosters_by_period.get(period)
        if not prev or not curr:
            continue
        wire_ids = {
            item.player_id
            for tx in txs
            if tx.scoring_period == period and tx.tx_type in WIRE_TYPES and _executed(tx)
            for item in tx.items
        }
        prev_team = {tid: _roster_ids(entries) for tid, entries in prev.items()}
        curr_of: Dict[str, str] = {}
        for tid, entries in curr.items():
            for entry in entries:
                curr_of[entry.player_id] = tid
        moves: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        for tid, roster in prev_team.items():
            for pid in roster:
                dest = curr_of.get(pid)
                if dest is None or dest == tid or pid in wire_ids:
                    continue
                moves[(tid, dest)].append(pid)
        pairs = []
        for src, dest in moves:
            key = tuple(sorted((src, dest)))
            stamp = (period, key[0], key[1])
            if stamp in seen_pairs:
                continue
            seen_pairs.add(stamp)
            pairs.append(key)
        for a, b in pairs:
            received_a = moves.get((b, a), [])
            received_b = moves.get((a, b), [])
            if not received_a and not received_b:
                continue
            side_a = _trade_side(a, names, players, received_a, received_b, period, completed)
            side_b = _trade_side(b, names, players, received_b, received_a, period, completed)
            rows.append(TradeRow(week=period, sides=[side_a, side_b]))
    return rows


def _trade_asset(
    pid: str,
    players: Dict[str, PlayerSeasonStats],
    period: int,
    completed: int,
) -> TradeAsset:
    name, pos = _player_label(pid, players)
    stats = players.get(pid)
    pts, weeks = _window(
        _weekly(pid, players),
        period,
        bye=stats.bye_week if stats else None,
        completed=completed,
    )
    return TradeAsset(
        player_name=name,
        position=pos,
        points=round(pts, 1),
        weeks=weeks,
        pts_per_week=_ppw(pts, weeks),
    )


def _trade_side(
    team_id: str,
    names: Dict[str, str],
    players: Dict[str, PlayerSeasonStats],
    received: Sequence[str],
    sent: Sequence[str],
    period: int,
    completed: int,
) -> TradeSide:
    rec = [_trade_asset(pid, players, period, completed) for pid in received]
    sent_assets = [_trade_asset(pid, players, period, completed) for pid in sent]
    rec_pts = sum(asset.points for asset in rec)
    sent_pts = sum(asset.points for asset in sent_assets)
    rec_ppw = sum(asset.pts_per_week for asset in rec)
    sent_ppw = sum(asset.pts_per_week for asset in sent_assets)
    return TradeSide(
        team_id=team_id,
        team_name=names.get(team_id) or f"Team {team_id}",
        received=[asset.player_name for asset in rec],
        sent=[asset.player_name for asset in sent_assets],
        received_players=rec,
        sent_players=sent_assets,
        net=round(rec_pts - sent_pts, 1),
        net_ppw=round(rec_ppw - sent_ppw, 2),
    )


def _best_net(row: TradeRow) -> float:
    return max((side.net for side in row.sides), default=0.0)


def _worst_net(row: TradeRow) -> float:
    return min((side.net for side in row.sides), default=0.0)
