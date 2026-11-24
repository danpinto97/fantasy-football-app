"""Process vs outcome draft grades. No HTTP, no CLI."""

from dataclasses import dataclass, field
from statistics import median
from typing import Dict, Iterable, List, Optional, Sequence

from fantasy_football.draft_accuracy.baselines import (
    ReplacementLevels,
    flex_aware_replacement,
    is_streamable,
    vbd_for_player,
)
from fantasy_football.models.draft import DraftPick, DraftResult, Player, PlayerSeasonStats
from fantasy_football.models.league import LeagueSettings

# Positive process_value = player fell to you (steal). Negative = reach.
EARLY_STREAMABLE_PENALTY = 20.0
# Reach cap: ADP may be at most this many rounds later than the pick.
# Fallers (ADP earlier than the pick) stay eligible. 0.5 rounds keeps round-2
# QBs out of pick 8 while still flagging Lamar if he falls to round 3.
DEFAULT_ADP_WINDOW_ROUNDS = 0.5
DEFAULT_PROCESS_ROUNDS = 10
SLOT_EXPECT_HALF_ROUNDS = 0.5
# Green if the player fell at least this many spots vs ADP.
STEAL_SPOTS = 4.0
# Red if they took someone this many ADP spots later than the typical remaining option.
MISS_SPOTS = 4.0
ALT_LIMIT = 3
# Season "better picks" must have been in the ADP conversation at this slot.
# 18 spots either side is about “will he last until my next pick,” not a
# leftover round-5 name or a round-8 boom nobody would take here.
SEASON_ALT_ADP_SPOTS = 18
EARLY_ROUNDS = 4
# Later rounds only: keep the board from becoming a sea of red.
MAX_LATE_MISS_BADGES = 2


@dataclass
class PickGrade:
    round_num: int
    overall_pick: int
    actual: Player
    actual_adp: Optional[float]
    actual_vbd: float
    process_value: float
    expected_slot_vbd: float
    outcome_value: float
    best: Optional[Player]
    best_adp: Optional[float]
    best_vbd: Optional[float]
    verdict: str = "even"
    headline: str = ""
    context: str = ""
    alternatives: List[Player] = field(default_factory=list)
    season_alternatives: List[Player] = field(default_factory=list)
    season_verdict: str = "even"
    season_note: str = ""
    redraft_rank: Optional[int] = None


@dataclass
class TeamDraftGrade:
    team_id: str
    team_name: str
    process_score: float
    outcome_score: float
    early_streamable_picks: int
    steal_count: int = 0
    miss_count: int = 0
    picks: List[PickGrade] = field(default_factory=list)


class DraftGrader:
    """
    Grade a completed draft.

    Process: overall_pick - ADP (steal if the player fell).
    Outcome: player VBD - expected VBD of that overall pick (ADP-near-slot median).
    Best available: undrafted, ADP <= pick + window, K/DST only in the last two rounds.
    """

    def __init__(
        self,
        draft: DraftResult,
        settings: LeagueSettings,
        pool: Sequence[PlayerSeasonStats],
        *,
        adp_round_window: float = DEFAULT_ADP_WINDOW_ROUNDS,
        process_rounds: int = DEFAULT_PROCESS_ROUNDS,
    ):
        self.draft = draft
        self.settings = settings
        self.adp_round_window = adp_round_window
        self.process_rounds = process_rounds
        self.num_teams = (
            settings.num_teams
            or len({p.team_id for p in draft.picks})
            or 12
        )
        self.total_rounds = max((p.round for p in draft.picks), default=1)
        self._pool_by_id: Dict[str, PlayerSeasonStats] = {p.player_id: p for p in pool}
        self.levels: ReplacementLevels = flex_aware_replacement(pool, settings, self.num_teams)
        self._vbd: Dict[str, float] = {
            p.player_id: vbd_for_player(p.season_points, p.position, self.levels) for p in pool
        }
        self._expected_by_pick = self._build_expected_slot_vbd()
        self._picks_by_overall: Dict[int, DraftPick] = {p.overall_pick: p for p in draft.picks}
        self._drafted_ids = {p.player.player_id for p in draft.picks}
        self._redraft_rank = self._build_redraft_ranks()

    def _adp(self, player_id: str, fallback: Optional[float] = None) -> Optional[float]:
        stats = self._pool_by_id.get(player_id)
        if stats and stats.adp is not None:
            return stats.adp
        return fallback

    def _points(self, player_id: str, fallback: float = 0.0) -> float:
        stats = self._pool_by_id.get(player_id)
        if stats:
            return stats.season_points
        return fallback

    def _position(self, player: Player) -> str:
        stats = self._pool_by_id.get(player.player_id)
        if stats and stats.position:
            return stats.position
        return (player.position or "").strip().upper()

    def _vbd_id(self, player_id: str, position: str, points: float) -> float:
        if player_id in self._vbd:
            return self._vbd[player_id]
        return vbd_for_player(points, position, self.levels)

    def _build_redraft_ranks(self) -> Dict[str, int]:
        """1 = best VBD among players who would still be drafted."""
        relevant = [
            p
            for p in self._pool_by_id.values()
            if self._vbd.get(p.player_id, 0.0) > 0 or p.player_id in self._drafted_ids
        ]
        ordered = sorted(
            relevant,
            key=lambda p: (self._vbd.get(p.player_id, 0.0), p.season_points),
            reverse=True,
        )
        return {p.player_id: index + 1 for index, p in enumerate(ordered)}

    def _build_expected_slot_vbd(self) -> Dict[int, float]:
        """Median VBD of pool players whose ADP is within half a round of this pick."""
        half = SLOT_EXPECT_HALF_ROUNDS * self.num_teams
        with_adp = [p for p in self._pool_by_id.values() if p.adp is not None]
        expected: Dict[int, float] = {}
        max_pick = max((p.overall_pick for p in self.draft.picks), default=self.num_teams)
        for n in range(1, max_pick + 1):
            nearby = [self._vbd.get(p.player_id, 0.0) for p in with_adp if abs(p.adp - n) <= half]
            if nearby:
                expected[n] = float(median(nearby))
            else:
                # Nearest ADP player if the slot window is empty.
                nearest = min(with_adp, key=lambda p: abs(p.adp - n), default=None)
                expected[n] = self._vbd.get(nearest.player_id, 0.0) if nearest else 0.0
        return expected

    def _drafted_before(self, overall_pick: int) -> set:
        return {
            self._picks_by_overall[n].player.player_id
            for n in range(1, overall_pick)
            if n in self._picks_by_overall
        }

    def _pool_as_player(self, stats: PlayerSeasonStats) -> Player:
        return Player(
            player_id=stats.player_id,
            name=stats.name,
            position=stats.position,
            adp=stats.adp,
            season_points=stats.season_points,
        )

    def _available_candidates(
        self, overall_pick: int, round_num: int
    ) -> List[PlayerSeasonStats]:
        drafted = self._drafted_before(overall_pick)
        max_adp = overall_pick + self.adp_round_window * self.num_teams
        late_rounds = {self.total_rounds, max(self.total_rounds - 1, 1)}
        allow_streamable = round_num in late_rounds
        candidates: List[PlayerSeasonStats] = []
        for stats in self._pool_by_id.values():
            if stats.player_id in drafted:
                continue
            if stats.adp is None:
                continue
            if stats.adp > max_adp:
                continue
            if is_streamable(stats.position) and not allow_streamable:
                continue
            candidates.append(stats)
        candidates.sort(
            key=lambda p: (self._vbd.get(p.player_id, 0.0), p.season_points),
            reverse=True,
        )
        return candidates

    def _best_available(self, overall_pick: int, round_num: int) -> Optional[PlayerSeasonStats]:
        candidates = self._available_candidates(overall_pick, round_num)
        return candidates[0] if candidates else None

    def _filter_alternatives(
        self,
        others: Sequence[PlayerSeasonStats],
        *,
        actual_pos: str,
        have_qb: bool,
    ) -> List[PlayerSeasonStats]:
        """Never pitch a QB once the team has one, or as the answer to a skill pick."""
        actual_pos = (actual_pos or "").strip().upper()
        filtered: List[PlayerSeasonStats] = []
        for stats in others:
            pos = (stats.position or "").strip().upper()
            if pos == "QB":
                if have_qb or actual_pos != "QB":
                    continue
            elif actual_pos == "QB" and not have_qb and pos != "QB":
                continue
            filtered.append(stats)
        return filtered

    def _alts_near_slot(
        self,
        others: Sequence[PlayerSeasonStats],
        overall_pick: int,
    ) -> List[Player]:
        half = self.adp_round_window * self.num_teams
        with_adp = [stats for stats in others if stats.adp is not None]
        on_slot = [
            stats for stats in with_adp if abs(stats.adp - overall_pick) <= half
        ]
        pool = on_slot or with_adp
        by_slot = sorted(pool, key=lambda stats: abs(stats.adp - overall_pick))[:ALT_LIMIT]
        return [self._pool_as_player(stats) for stats in by_slot]

    def _ordinal(self, n: int) -> str:
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    def _redraft_story(self, overall_pick: int, redraft_rank: Optional[int], vbd: float) -> tuple:
        if redraft_rank is None or vbd <= 0:
            return "bust", "Would go undrafted in a redraft."
        delta = overall_pick - redraft_rank
        place = self._ordinal(redraft_rank)
        if delta >= STEAL_SPOTS:
            return "hit", f"Would go {place} in a redraft."
        if delta <= -STEAL_SPOTS:
            return "bust", f"Would go {place} in a redraft."
        return "even", f"Would go {place} in a redraft."

    def _season_alternatives(
        self,
        *,
        overall_pick: int,
        round_num: int,
        actual_id: str,
        actual_pos: str,
        have_qb: bool,
    ) -> List[Player]:
        drafted = self._drafted_before(overall_pick) | {actual_id}
        late_rounds = {self.total_rounds, max(self.total_rounds - 1, 1)}
        allow_streamable = round_num in late_rounds
        actual_pts = self._points(actual_id)
        others = []
        for stats in self._pool_by_id.values():
            if stats.player_id in drafted:
                continue
            if stats.adp is None:
                continue
            if abs(stats.adp - overall_pick) > SEASON_ALT_ADP_SPOTS:
                continue
            if stats.season_points <= actual_pts:
                continue
            if is_streamable(stats.position) and not allow_streamable:
                continue
            others.append(stats)
        filtered = self._filter_alternatives(others, actual_pos=actual_pos, have_qb=have_qb)
        ranked = sorted(
            filtered,
            key=lambda stats: (self._vbd.get(stats.player_id, 0.0), stats.season_points),
            reverse=True,
        )
        return [self._pool_as_player(stats) for stats in ranked[:ALT_LIMIT]]

    def _pick_story(
        self,
        *,
        actual: Player,
        actual_pos: str,
        adp: Optional[float],
        process_value: float,
        overall_pick: int,
        round_num: int,
        have_qb: bool,
        candidates: Sequence[PlayerSeasonStats],
    ) -> tuple:
        others = self._filter_alternatives(
            [stats for stats in candidates if stats.player_id != actual.player_id],
            actual_pos=actual_pos,
            have_qb=have_qb,
        )
        if process_value >= STEAL_SPOTS:
            n = max(1, int(round(process_value)))
            unit = "spot" if n == 1 else "spots"
            adp_n = int(round(adp)) if adp is not None else None
            context = (
                f"ADP had them around pick {adp_n} — they were ahead of this slot."
                if adp_n is not None
                else "They were ranked ahead of this slot on draft day."
            )
            return "steal", f"Fell {n} {unit}", context, []
        board = [stats.adp for stats in candidates if stats.adp is not None]
        board_adp = float(median(board)) if board else None
        early = round_num <= EARLY_ROUNDS
        reached = process_value <= -STEAL_SPOTS if early else (
            adp is not None
            and board_adp is not None
            and adp >= board_adp + MISS_SPOTS
        )
        alts = self._alts_near_slot(others, overall_pick) if others else []
        if reached:
            n = max(1, int(round(-process_value)))
            unit = "spot" if n == 1 else "spots"
            adp_n = int(round(adp)) if adp is not None else None
            if adp_n is not None:
                context = f"ADP had them around pick {adp_n}."
            else:
                context = "Better names were still sitting there."
            return "miss", f"Reached {n} {unit}", context, alts
        return "even", "On the board", self._adp_context(adp), []

    def _adp_context(self, adp: Optional[float]) -> str:
        if adp is None:
            return "Drafted around where the board had them."
        return f"ADP had them around pick {int(round(adp))}."

    def grade_team(self, team_id: str, max_round: int = 11) -> TeamDraftGrade:
        team_picks = [
            p
            for p in self.draft.picks
            if p.team_id == team_id and 1 <= p.round <= max_round
        ]
        team_picks.sort(key=lambda p: (p.round, p.overall_pick))
        team_name = next((p.team_name for p in team_picks), team_id)

        grades: List[PickGrade] = []
        early_streamable = 0
        taken_positions: List[str] = []
        for pick in team_picks:
            player = pick.player
            pos = self._position(player)
            if pos and not (player.position or "").strip():
                player = player.model_copy(update={"position": pos})
            have_qb = any(p == "QB" for p in taken_positions)
            adp = self._adp(player.player_id, player.adp if player.adp is not None else float(pick.overall_pick))
            points = self._points(player.player_id, player.season_points or 0.0)
            actual_vbd = self._vbd_id(player.player_id, pos, points)
            process_value = (pick.overall_pick - adp) if adp is not None else 0.0
            expected = self._expected_by_pick.get(pick.overall_pick, 0.0)
            outcome_value = actual_vbd - expected
            redraft_rank = self._redraft_rank.get(player.player_id)
            season_verdict, season_note = self._redraft_story(
                pick.overall_pick, redraft_rank, actual_vbd
            )
            if is_streamable(pos) and pick.round < self.total_rounds - 1:
                early_streamable += 1
            candidates = self._available_candidates(pick.overall_pick, pick.round)
            best_stats = candidates[0] if candidates else None
            best_player = self._pool_as_player(best_stats) if best_stats else None
            verdict, headline, context, alternatives = self._pick_story(
                actual=player,
                actual_pos=pos,
                adp=adp,
                process_value=process_value,
                overall_pick=pick.overall_pick,
                round_num=pick.round,
                have_qb=have_qb,
                candidates=candidates,
            )
            season_alts = self._season_alternatives(
                overall_pick=pick.overall_pick,
                round_num=pick.round,
                actual_id=player.player_id,
                actual_pos=pos,
                have_qb=have_qb,
            )
            if player.season_points is None or player.season_points == 0:
                player = player.model_copy(update={"season_points": points})
            grades.append(
                PickGrade(
                    round_num=pick.round,
                    overall_pick=pick.overall_pick,
                    actual=player,
                    actual_adp=adp,
                    actual_vbd=actual_vbd,
                    process_value=process_value,
                    expected_slot_vbd=expected,
                    outcome_value=outcome_value,
                    best=best_player,
                    best_adp=best_stats.adp if best_stats else None,
                    best_vbd=self._vbd.get(best_stats.player_id) if best_stats else None,
                    verdict=verdict,
                    headline=headline,
                    context=context,
                    alternatives=alternatives if verdict == "miss" else [],
                    season_alternatives=season_alts,
                    season_verdict=season_verdict,
                    season_note=season_note,
                    redraft_rank=redraft_rank,
                )
            )
            if pos:
                taken_positions.append(pos)

        self._cap_miss_badges(grades)
        scored = [g for g in grades if g.round_num <= self.process_rounds]
        process = (
            sum(g.process_value for g in scored) - EARLY_STREAMABLE_PENALTY * early_streamable
        )
        outcome = sum(g.outcome_value for g in scored)
        return TeamDraftGrade(
            team_id=team_id,
            team_name=team_name or team_id,
            process_score=process,
            outcome_score=outcome,
            early_streamable_picks=early_streamable,
            steal_count=sum(1 for g in scored if g.verdict == "steal"),
            miss_count=sum(1 for g in scored if g.verdict == "miss"),
            picks=grades,
        )

    def _cap_miss_badges(self, grades: List[PickGrade]) -> None:
        late = [g for g in grades if g.verdict == "miss" and g.round_num > EARLY_ROUNDS]
        paid = [g for g in late if g.season_verdict == "hit"]
        unpaid = [g for g in late if g.season_verdict != "hit"]
        keep = {id(row) for row in paid} | {
            id(row)
            for row in sorted(unpaid, key=lambda g: (g.process_value, g.round_num))[
                :MAX_LATE_MISS_BADGES
            ]
        }
        for row in late:
            if id(row) in keep:
                continue
            row.verdict = "even"
            row.headline = "On the board"
            row.context = self._adp_context(row.actual_adp)
            row.alternatives = []

    def grade_league(self, max_round: int = 11) -> List[TeamDraftGrade]:
        team_ids = sorted(
            {p.team_id for p in self.draft.picks},
            key=lambda tid: int(tid) if tid.isdigit() else tid,
        )
        return [self.grade_team(tid, max_round=max_round) for tid in team_ids]


def merge_pool_with_draft(
    pool: Iterable[PlayerSeasonStats],
    draft: DraftResult,
) -> List[PlayerSeasonStats]:
    """Ensure every drafted player has a pool row (ADP/points may still be missing)."""
    by_id = {p.player_id: p for p in pool}
    for pick in draft.picks:
        player = pick.player
        existing = by_id.get(player.player_id)
        if existing is None:
            by_id[player.player_id] = PlayerSeasonStats(
                player_id=player.player_id,
                name=player.name,
                position=player.position,
                adp=player.adp,
                season_points=player.season_points or 0.0,
            )
            continue
        by_id[player.player_id] = existing.model_copy(
            update={
                "name": existing.name or player.name,
                "position": existing.position or player.position,
                "adp": existing.adp if existing.adp is not None else player.adp,
                "season_points": (
                    existing.season_points
                    if existing.season_points > 0
                    else (player.season_points or 0.0)
                ),
            }
        )
    return list(by_id.values())
