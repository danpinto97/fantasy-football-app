export type RosterSlot = {
  position: string;
  count: number;
  is_flex: boolean;
};

export type Team = {
  team_id: string;
  name: string;
  abbrev: string;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  points_against: number;
  playoff_seed: number | null;
};

export type League = {
  league_id: string;
  season: number;
  name: string;
  num_teams: number;
  roster_slots: RosterSlot[];
  teams: Team[];
};

export type StandingRow = {
  team_id: string;
  name: string;
  abbrev: string;
  seed: number | null;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  points_against: number;
  point_diff: number;
  avg_weekly: number;
  best_week: number;
  best_week_period: number | null;
  stdev: number;
  games: number;
};

export type WeeklyScore = {
  team_id: string;
  team_name: string;
  period: number;
  points: number;
};

export type Performer = {
  team_id: string;
  team_name: string;
  value: number;
  detail: string;
};

export type LuckRow = {
  team_id: string;
  team_name: string;
  actual_wins: number;
  actual_losses: number;
  actual_ties: number;
  all_play_wins: number;
  all_play_losses: number;
  all_play_ties: number;
  expected_wins: number;
  luck: number;
  lucky_wins: number;
  unlucky_losses: number;
  games: number;
};

export type Overview = {
  league_id: string;
  season: number;
  name: string;
  num_teams: number;
  scoring_type: string;
  regular_season_periods: number;
  playoff_team_count: number;
  roster_slots: RosterSlot[];
  standings: StandingRow[];
  top_weeks: WeeklyScore[];
  highest_pf: Performer | null;
  hottest_week: Performer | null;
  most_consistent: Performer | null;
  luck: LuckRow[];
  luckiest: Performer | null;
  unluckiest: Performer | null;
  available_seasons: number[];
};

export type PickAlt = {
  name: string;
  position: string;
  adp: number | null;
  season_points: number;
};

export type DraftPickRow = {
  round: number;
  overall_pick: number;
  player_name: string;
  position: string;
  adp: number | null;
  verdict: "steal" | "miss" | "even" | string;
  headline: string;
  context: string;
  alternatives: PickAlt[];
  season_alternatives: PickAlt[];
  season_verdict: "hit" | "bust" | "even" | string;
  season_note: string;
  season_points: number;
  redraft_rank: number | null;
};

export type DraftGradeRow = {
  team_id: string;
  team_name: string;
  process_score: number;
  outcome_score: number;
  process_rank: number;
  outcome_rank: number;
  early_streamable_picks: number;
  steal_count: number;
  miss_count: number;
  picks: DraftPickRow[];
};

export type BoomBustRow = {
  player_name: string;
  position: string;
  team_id: string;
  team_name: string;
  round: number;
  overall_pick: number;
  espn_rank: number | null;
  actual_points: number;
  expected_so_far: number;
  surplus_so_far: number;
  actual_ppw: number;
  proj_ppw: number;
  pace_delta: number;
  games: number;
  bye_week: number | null;
  injury: string;
  imputed: boolean;
  kind: "boom" | "bust" | string;
  badge: string;
};

export type BoomBustReport = {
  league_id: string;
  season: number;
  completed_week: number;
  boom_threshold: number;
  bust_threshold: number;
  booms: BoomBustRow[];
  busts: BoomBustRow[];
};

export type DraftBoard = {
  league_id: string;
  season: number;
  drafted: boolean;
  grades: DraftGradeRow[];
  boom_bust: BoomBustReport | null;
};

export type WireMove = {
  team_id: string;
  team_name: string;
  player_name: string;
  position: string;
  source: string;
  week: number;
  points_after: number;
  bid: number;
  weeks: number;
  pts_per_week: number;
};

export type TradeAsset = {
  player_name: string;
  position: string;
  points: number;
  weeks: number;
  pts_per_week: number;
};

export type TradeSide = {
  team_id: string;
  team_name: string;
  received: string[];
  sent: string[];
  received_players: TradeAsset[];
  sent_players: TradeAsset[];
  net: number;
  net_ppw: number;
};

export type TradeRow = {
  week: number;
  sides: TradeSide[];
};

export type WireBoard = {
  league_id: string;
  season: number;
  completed_week: number;
  best_adds: WireMove[];
  worst_drops: WireMove[];
  highest_spends: WireMove[];
  best_trades: TradeRow[];
  worst_trades: TradeRow[];
  trades: TradeRow[];
};

export type AuthStatus = {
  required: boolean;
  authenticated: boolean;
  has_espn_session: boolean;
  visitor_espn_session: boolean;
  espn_session_enabled: boolean;
};

export type SeasonList = {
  league_id: string;
  seasons: number[];
  current_season: number;
  has_espn_session: boolean;
};

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) return body.detail.map((d: { msg?: string }) => d.msg).join(" ");
  } catch {
    /* ignore */
  }
  return res.statusText || "Request failed";
}

export async function fetchAuthStatus(): Promise<AuthStatus> {
  const res = await fetch("/api/auth/status", { credentials: "include" });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function login(password: string): Promise<void> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function saveEspnSession(swid: string, espnS2: string): Promise<void> {
  const res = await fetch("/api/espn-session", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ swid, espn_s2: espnS2 }),
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function clearEspnSession(): Promise<void> {
  const res = await fetch("/api/espn-session", {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) throw new Error(await readError(res));
}

export function looksPrivateSeason(message: string): boolean {
  return /private|rejected .*session|paste your ESPN|not authorized/i.test(message);
}

export async function fetchLeague(leagueId: string, season: number): Promise<League> {
  const res = await fetch(`/api/leagues/${encodeURIComponent(leagueId)}?season=${season}`, {
    credentials: "include",
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function fetchOverview(leagueId: string, season: number): Promise<Overview> {
  const res = await fetch(`/api/leagues/${encodeURIComponent(leagueId)}/overview?season=${season}`, {
    credentials: "include",
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function fetchSeasons(leagueId: string): Promise<SeasonList> {
  const res = await fetch(`/api/leagues/${encodeURIComponent(leagueId)}/seasons`, {
    credentials: "include",
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function fetchDraftGrades(leagueId: string, season: number): Promise<DraftBoard> {
  const res = await fetch(
    `/api/leagues/${encodeURIComponent(leagueId)}/draft-grades?season=${season}`,
    { credentials: "include" },
  );
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function fetchWire(leagueId: string, season: number): Promise<WireBoard> {
  const res = await fetch(`/api/leagues/${encodeURIComponent(leagueId)}/wire?season=${season}`, {
    credentials: "include",
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export function currentNflSeason(now = new Date()): number {
  return now.getMonth() >= 7 ? now.getFullYear() : now.getFullYear() - 1;
}

export function seasonChoices(requested: number, available: number[] = []): number[] {
  const current = currentNflSeason();
  const years = new Set<number>([
    requested,
    current,
    current - 1,
    current - 2,
    ...available,
  ]);
  return [...years].filter((year) => year >= 2008 && year <= 2030).sort((a, b) => b - a);
}
