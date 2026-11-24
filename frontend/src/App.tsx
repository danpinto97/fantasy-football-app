import { FormEvent, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  clearEspnSession,
  currentNflSeason,
  fetchAuthStatus,
  fetchDraftGrades,
  fetchOverview,
  fetchSeasons,
  fetchWire,
  login,
  looksPrivateSeason,
  saveEspnSession,
  seasonChoices,
  type AuthStatus,
  type BoomBustReport,
  type BoomBustRow,
  type DraftBoard,
  type DraftGradeRow,
  type DraftPickRow,
  type LuckRow,
  type Overview,
  type StandingRow,
  type TradeAsset,
  type TradeSide,
  type WireBoard,
  type WireMove,
} from "./api";
import { FoldSection, PassLoader } from "./pixel";

export default function App() {
  const [gate, setGate] = useState<"open" | "locked" | "checking">("checking");
  const [password, setPassword] = useState("");
  const [gateError, setGateError] = useState("");
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [espnEpoch, setEspnEpoch] = useState(0);

  function applyAuth(status: AuthStatus) {
    setAuth(status);
    setGate(status.required && !status.authenticated ? "locked" : "open");
  }

  useEffect(() => {
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), 4000);
    fetchAuthStatus()
      .then(applyAuth)
      .catch(() => setGate("locked"))
      .finally(() => window.clearTimeout(timer));
    return () => {
      window.clearTimeout(timer);
      ctrl.abort();
    };
  }, []);

  async function onUnlock(event: FormEvent) {
    event.preventDefault();
    setGateError("");
    try {
      await login(password);
      applyAuth(await fetchAuthStatus());
    } catch (err) {
      setGateError(err instanceof Error ? err.message : "Could not sign in");
    }
  }

  async function refreshAuth() {
    try {
      applyAuth(await fetchAuthStatus());
    } catch {
      /* ignore */
    }
  }

  async function onForgetEspn() {
    try {
      await clearEspnSession();
      await refreshAuth();
      setEspnEpoch((n) => n + 1);
    } catch {
      /* status refresh is enough */
    }
  }

  if (gate === "checking") {
    return (
      <div className="shell">
        <header className="masthead">
          <div className="wordmark">
            League <span>Intel</span>
          </div>
        </header>
        <PassLoader label="Checking access…" />
      </div>
    );
  }

  if (gate === "locked") {
    return (
      <div className="shell">
        <header className="masthead">
          <div className="wordmark">
            League <span>Intel</span>
          </div>
        </header>
        <p className="eyebrow">Private preview</p>
        <h1>Enter the site password</h1>
        <form className="panel" onSubmit={onUnlock}>
          {gateError ? <p className="error">{gateError}</p> : null}
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <button type="submit">Enter</button>
        </form>
      </div>
    );
  }

  return (
    <div className="shell">
      <header className="masthead">
        <Link to="/" className="wordmark">
          League <span>Intel</span>
        </Link>
        {auth?.visitor_espn_session ? (
          <button type="button" className="linkish" onClick={onForgetEspn}>
            Forget ESPN login
          </button>
        ) : null}
      </header>
      <Routes>
        <Route path="/" element={<HomePage espnEnabled={Boolean(auth?.espn_session_enabled)} />} />
        <Route
          path="/league/:leagueId"
          element={
            <LeaguePage
              auth={auth}
              espnEpoch={espnEpoch}
              onEspnSessionChange={refreshAuth}
            />
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}

function HomePage({ espnEnabled }: { espnEnabled: boolean }) {
  const navigate = useNavigate();
  const [leagueId, setLeagueId] = useState("96876878");
  const [season, setSeason] = useState(() => String(currentNflSeason()));

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const id = leagueId.trim();
    const year = Number(season);
    if (!/^\d{4,12}$/.test(id) || !Number.isInteger(year)) return;
    navigate(`/league/${id}?season=${year}`);
  }

  return (
    <>
      <p className="eyebrow">ESPN redraft</p>
      <h1>Plug in a league ID. See who actually ran the table.</h1>
      <p className="lede">
        {espnEnabled
          ? "Public ESPN leagues work as-is. For a private season, paste that league’s ESPN cookies in this browser after the site password."
          : "Public ESPN leagues only unless the server has an ESPN session."}{" "}
        Standings, weekly highs, consistency, and draft process vs outcome.
      </p>
      <form className="panel" onSubmit={onSubmit}>
        <div className="row">
          <div>
            <label htmlFor="leagueId">ESPN league ID</label>
            <input
              id="leagueId"
              inputMode="numeric"
              autoComplete="off"
              value={leagueId}
              onChange={(e) => setLeagueId(e.target.value.replace(/[^\d]/g, "").slice(0, 12))}
              required
            />
          </div>
          <div>
            <label htmlFor="season">Season</label>
            <input
              id="season"
              inputMode="numeric"
              value={season}
              onChange={(e) => setSeason(e.target.value.replace(/[^\d]/g, "").slice(0, 4))}
              required
            />
          </div>
        </div>
        <button type="submit">Look up league</button>
      </form>
    </>
  );
}

function EspnSessionForm({ onSaved }: { onSaved: () => Promise<void> }) {
  const [swid, setSwid] = useState("");
  const [espnS2, setEspnS2] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError("");
    setBusy(true);
    try {
      await saveEspnSession(swid, espnS2);
      setSwid("");
      setEspnS2("");
      await onSaved();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save ESPN session");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel espn-session" onSubmit={onSubmit}>
      <h2>Unlock this private season</h2>
      <p className="hint">
        On fantasy.espn.com, open DevTools → Application → Cookies. Copy <strong>SWID</strong> and{" "}
        <strong>espn_s2</strong> from a login that can see this league year. They stay in this
        browser (encrypted, httpOnly) for a week — never paste them in chat.
      </p>
      {formError ? <p className="error">{formError}</p> : null}
      <label htmlFor="swid">SWID</label>
      <input
        id="swid"
        autoComplete="off"
        spellCheck={false}
        value={swid}
        onChange={(e) => setSwid(e.target.value)}
        required
      />
      <label htmlFor="espn_s2">espn_s2</label>
      <textarea
        id="espn_s2"
        autoComplete="off"
        spellCheck={false}
        rows={3}
        value={espnS2}
        onChange={(e) => setEspnS2(e.target.value)}
        required
      />
      <button type="submit" disabled={busy}>
        {busy ? "Saving…" : "Save ESPN login"}
      </button>
    </form>
  );
}

function recordOf(row: { wins: number; losses: number; ties: number }): string {
  return row.ties ? `${row.wins}-${row.losses}-${row.ties}` : `${row.wins}-${row.losses}`;
}

function scoringLabel(scoringType: string): string {
  if (scoringType === "H2H_POINTS") return "H2H points";
  return scoringType.replace(/_/g, " ") || "Scoring";
}

function SeasonNav({
  leagueId,
  season,
  available,
}: {
  leagueId: string;
  season: number;
  available?: number[];
}) {
  const years = seasonChoices(season, available);
  return (
    <nav className="seasons" aria-label="Seasons">
      {years.map((year) => (
        <Link
          key={year}
          to={`/league/${leagueId}?season=${year}`}
          className={year === season ? "is-on" : undefined}
        >
          {year}
        </Link>
      ))}
    </nav>
  );
}

function LeaguePage({
  auth,
  espnEpoch,
  onEspnSessionChange,
}: {
  auth: AuthStatus | null;
  espnEpoch: number;
  onEspnSessionChange: () => Promise<void>;
}) {
  const { leagueId = "" } = useParams();
  const [params] = useSearchParams();
  const season = Number(params.get("season") || currentNflSeason());
  const [overview, setOverview] = useState<Overview | null>(null);
  const [draftBoard, setDraftBoard] = useState<DraftBoard | null>(null);
  const [wire, setWire] = useState<WireBoard | null>(null);
  const [available, setAvailable] = useState<number[]>([]);
  const [hasEspnSession, setHasEspnSession] = useState(false);
  const [draftError, setDraftError] = useState("");
  const [wireError, setWireError] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [openTeam, setOpenTeam] = useState<string | null>(null);
  const [espnNonce, setEspnNonce] = useState(0);

  async function afterEspnSession() {
    setEspnNonce((n) => n + 1);
    await onEspnSessionChange();
  }

  useEffect(() => {
    let cancelled = false;
    fetchSeasons(leagueId)
      .then((data) => {
        if (cancelled) return;
        setAvailable(data.seasons);
        setHasEspnSession(data.has_espn_session);
      })
      .catch(() => {
        /* year chips still fall back to current / current-1 / current-2 */
      });
    return () => {
      cancelled = true;
    };
  }, [leagueId, espnNonce, espnEpoch]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setDraftError("");
    setWireError("");
    setDraftBoard(null);
    setWire(null);
    setOpenTeam(null);
    fetchOverview(leagueId, season)
      .then((data) => {
        if (!cancelled) setOverview(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Lookup failed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    fetchDraftGrades(leagueId, season)
      .then((data) => {
        if (!cancelled) setDraftBoard(data);
      })
      .catch((err) => {
        if (!cancelled) setDraftError(err instanceof Error ? err.message : "Draft grades failed");
      });
    fetchWire(leagueId, season)
      .then((data) => {
        if (!cancelled) setWire(data);
      })
      .catch((err) => {
        if (!cancelled) setWireError(err instanceof Error ? err.message : "Wire grades failed");
      });
    return () => {
      cancelled = true;
    };
  }, [leagueId, season, espnNonce, espnEpoch]);

  if (loading) return <PassLoader label={`Fetching league ${leagueId}…`} />;
  if (error) {
    return (
      <>
        <p className="eyebrow">Season {season}</p>
        <h1>Could not load this season</h1>
        <p className="error">{error}</p>
        <SeasonNav leagueId={leagueId} season={season} available={available} />
        <p className="lede">
          {hasEspnSession
            ? "The stored ESPN session did not unlock this season. Try another year above, or paste a member’s cookies for that year."
            : "If ESPN marked this year private, try another season above or paste cookies from someone who can see it."}
        </p>
        {auth?.espn_session_enabled && looksPrivateSeason(error) ? (
          <EspnSessionForm onSaved={afterEspnSession} />
        ) : null}
        <Link to="/">Try another league</Link>
      </>
    );
  }
  if (!overview) return null;

  const starterSlots = overview.roster_slots.filter(
    (slot) => slot.position !== "BE" && slot.position !== "IR",
  );

  return (
    <>
      <p className="eyebrow">Season {overview.season}</p>
      <h1>{overview.name || `League ${overview.league_id}`}</h1>
      <SeasonNav
        leagueId={overview.league_id}
        season={overview.season}
        available={[...available, ...overview.available_seasons]}
      />
      <div className="meta">
        <div>
          <strong>League ID</strong>
          {overview.league_id}
        </div>
        <div>
          <strong>Teams</strong>
          {overview.num_teams}
        </div>
        <div>
          <strong>Format</strong>
          {scoringLabel(overview.scoring_type)}
        </div>
        <div>
          <strong>Regular season</strong>
          {overview.regular_season_periods} weeks
        </div>
      </div>
      <section className="judgments">
        {overview.highest_pf ? (
          <article className="judgment">
            <p className="eyebrow">Highest PF</p>
            <h2>{overview.highest_pf.team_name}</h2>
            <p className="record">{overview.highest_pf.detail}</p>
          </article>
        ) : null}
        {overview.hottest_week ? (
          <article className="judgment">
            <p className="eyebrow">Hottest week</p>
            <h2>{overview.hottest_week.team_name}</h2>
            <p className="record">{overview.hottest_week.detail}</p>
          </article>
        ) : null}
        {overview.most_consistent ? (
          <article className="judgment">
            <p className="eyebrow">Most consistent</p>
            <h2>{overview.most_consistent.team_name}</h2>
            <p className="record">{overview.most_consistent.detail}</p>
          </article>
        ) : null}
        {overview.luckiest ? (
          <article className="judgment">
            <p className="eyebrow">Luckiest</p>
            <h2>{overview.luckiest.team_name}</h2>
            <p className="record">{overview.luckiest.detail}</p>
          </article>
        ) : null}
        {overview.unluckiest ? (
          <article className="judgment">
            <p className="eyebrow">Unluckiest</p>
            <h2>{overview.unluckiest.team_name}</h2>
            <p className="record">{overview.unluckiest.detail}</p>
          </article>
        ) : null}
      </section>
      <FoldSection
        art="standings"
        title="Standings"
        defaultOpen
        lede="Swing is weekly scoring standard deviation — how boom/bust the weeks were. Lower is more consistent."
      >
        {overview.standings.length === 0 ? (
          <p className="lede">No teams in this ESPN payload yet.</p>
        ) : overview.standings.every((row) => row.games === 0) ? (
          <p className="lede">Season is up, but no scored matchups yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="board">
              <thead>
                <tr>
                  <th className="num">Seed</th>
                  <th>Team</th>
                  <th className="num">Rec</th>
                  <th className="num">PF</th>
                  <th className="num">PA</th>
                  <th className="num">Diff</th>
                  <th className="num">Best</th>
                  <th
                    className="num"
                    title="Weekly scoring standard deviation. Higher means more boom/bust weeks."
                  >
                    Swing
                  </th>
                </tr>
              </thead>
              <tbody>
                {overview.standings.map((row) => (
                  <StandingCells key={row.team_id} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </FoldSection>
      {overview.luck.length > 0 ? (
        <FoldSection
          art="luck"
          title="Schedule luck"
          lede="All-play is every other score that week. xW is expected wins: if you played a random opponent each week, that's the chance you'd win, added up for the season. Luck is actual wins minus xW."
        >
          <div className="table-wrap">
            <table className="board">
              <thead>
                <tr>
                  <th>Team</th>
                  <th className="num">Rec</th>
                  <th className="num">All-play</th>
                  <th
                    className="num"
                    title="Expected wins: if you played a random opponent each week, the chance you'd win, added up."
                  >
                    xW
                  </th>
                  <th className="num">Luck</th>
                  <th className="num">Lucky W</th>
                  <th className="num">Unlucky L</th>
                </tr>
              </thead>
              <tbody>
                {overview.luck.map((row) => (
                  <LuckCells key={row.team_id} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        </FoldSection>
      ) : null}
      {overview.top_weeks.length > 0 ? (
        <FoldSection title="Weekly highs">
          <ol className="weeks">
            {overview.top_weeks.map((week) => (
              <li key={`${week.team_id}-${week.period}-${week.points}`}>
                <span>
                  Week {week.period} · {week.team_name}
                </span>
                {week.points.toFixed(1)}
              </li>
            ))}
          </ol>
        </FoldSection>
      ) : null}
      <FoldSection
        art="draft"
        title="Drafters"
        lede="Draft day is who took value at the slot. Season is how those picks actually scored. Click a team to see the cards."
      >
        {draftError ? <p className="error">{draftError}</p> : null}
        {!draftError && !draftBoard ? <PassLoader label="Grading the draft…" /> : null}
        {draftBoard && !draftBoard.drafted ? (
          <p className="lede">No draft on ESPN for this season yet.</p>
        ) : null}
        {draftBoard && draftBoard.drafted ? (
          <DraftersPanel
            grades={draftBoard.grades}
            openTeam={openTeam}
            onOpenTeam={setOpenTeam}
            inProgress={overview.season === currentNflSeason()}
          />
        ) : null}
      </FoldSection>
      <FoldSection
        art="draft"
        title="Draft booms and busts"
        lede="Drafted skill players only. Actual pts/week vs ESPN’s season projection, paced over 16 games. Bye weeks omitted; injury zeros still count. Boom is on pace for 50+ over projection; busts use the 100-point bar."
      >
        {draftError ? <p className="error">{draftError}</p> : null}
        {!draftError && !draftBoard ? <PassLoader label="Scoring the draft…" /> : null}
        {draftBoard?.boom_bust ? <BoomBustPanel board={draftBoard.boom_bust} /> : null}
      </FoldSection>
      <FoldSection
        art="agency"
        title="Free agency"
        lede="Waiver bids first, then the best remaining adds and costliest drops. Points start the week of the move and stop if that team later dropped or traded the player. Bye weeks omitted."
      >
        {wireError ? <p className="error">{wireError}</p> : null}
        {!wireError && !wire ? <PassLoader label="Reading the waiver wire…" /> : null}
        {wire ? <AgencyPanel board={wire} /> : null}
      </FoldSection>
      <FoldSection
        art="trade"
        title="Trades"
        lede="Every completed trade ESPN logged. Points start the week of the trade. Bye weeks omitted."
      >
        {wireError ? <p className="error">{wireError}</p> : null}
        {!wireError && !wire ? <PassLoader label="Reading the trade log…" /> : null}
        {wire ? <TradesPanel board={wire} /> : null}
      </FoldSection>
      <FoldSection title="Roster shape">
        <ul className="slots">
          {starterSlots.map((slot) => (
            <li key={`${slot.position}-${slot.is_flex}`}>
              <span>{slot.is_flex ? "Flex" : "Slot"}</span>
              {slot.count} {slot.position}
            </li>
          ))}
        </ul>
      </FoldSection>
    </>
  );
}

function DraftersPanel({
  grades,
  openTeam,
  onOpenTeam,
  inProgress,
}: {
  grades: DraftGradeRow[];
  openTeam: string | null;
  onOpenTeam: (teamId: string | null) => void;
  inProgress: boolean;
}) {
  const selected = grades.find((row) => row.team_id === openTeam) ?? null;
  return (
    <div className="drafters">
      <div className="table-wrap">
        <table className="board">
          <thead>
            <tr>
              <th className="num">Day</th>
              <th className="num">Season</th>
              <th>Team</th>
              <th className="num">Fell</th>
              <th className="num">Passed</th>
            </tr>
          </thead>
          <tbody>
            {grades.map((row) => {
              const open = row.team_id === openTeam;
              const lead = row.process_rank === 1 ? " is-lead" : "";
              return (
                <tr
                  key={row.team_id}
                  className={`is-click${lead}${open ? " is-open" : ""}`}
                  onClick={() => onOpenTeam(open ? null : row.team_id)}
                >
                  <td className="num" data-label="Draft day">
                    {row.process_rank}
                  </td>
                  <td className="num" data-label="Season">
                    {row.outcome_rank}
                  </td>
                  <td className="is-primary">
                    <button
                      type="button"
                      className="linkish"
                      aria-expanded={open}
                    >
                      {row.team_name}
                    </button>
                  </td>
                  <td className="num" data-label="Fell">
                    {row.steal_count || "—"}
                  </td>
                  <td className="num" data-label="Passed">
                    {row.miss_count || "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {selected ? (
        <TeamPicks row={selected} inProgress={inProgress} />
      ) : (
        <p className="lede pick-empty">
            Click a team. Draft day is the ADP board at pick time. Season is a
            redraft on actual points.
        </p>
      )}
    </div>
  );
}

function TeamPicks({ row, inProgress }: { row: DraftGradeRow; inProgress: boolean }) {
  return (
    <div className="pick-sheet">
      <p className="eyebrow">
        {`Draft day ${row.process_rank}${ordinal(row.process_rank)} · Season ${row.outcome_rank}${ordinal(row.outcome_rank)}`}
      </p>
      <h3>{row.team_name}</h3>
      {row.early_streamable_picks > 0 ? (
        <p className="lede">Took K or DST before the last two rounds.</p>
      ) : null}
      <ol className="picks">
        {row.picks.map((pick) => (
          <PickCard key={pick.overall_pick} pick={pick} inProgress={inProgress} />
        ))}
      </ol>
    </div>
  );
}

function draftAltLine(alts: { name: string; adp: number | null }[]): string {
  return alts
    .map((alt) => (alt.adp != null ? `${alt.name} ADP ${Math.round(alt.adp)}` : alt.name))
    .join(" · ");
}

function formatAdp(adp: number): string {
  return Number.isInteger(adp) ? String(adp) : adp.toFixed(1);
}

function seasonAltLine(
  alts: { name: string; season_points: number; adp: number | null }[],
): string {
  return alts
    .map((alt) => {
      const pts = `${alt.name} ${alt.season_points.toFixed(1)}`;
      return alt.adp != null ? `${pts} (ADP ${formatAdp(alt.adp)})` : pts;
    })
    .join(" · ");
}

function PickCard({ pick, inProgress }: { pick: DraftPickRow; inProgress: boolean }) {
  const paidOff = pick.verdict === "miss" && pick.season_verdict === "hit";
  return (
    <li
      className={`pick is-${pick.verdict} is-season-${pick.season_verdict}${paidOff ? " is-paid-off" : ""}`}
    >
      <div className="pick-top">
        <span className="pick-slot">
          R{pick.round} · Pick {pick.overall_pick}
        </span>
        <span className="pick-pos">{pick.position || "—"}</span>
      </div>
      <div className="pick-who">
        <strong>{pick.player_name}</strong>
        {pick.headline ? <span className="badge">{pick.headline}</span> : null}
        {paidOff ? <span className="badge is-paid-off">Paid off</span> : null}
      </div>
      <div className="pick-lane">
        <p className="eyebrow">Draft day</p>
        {pick.context ? <p className="pick-note">{pick.context}</p> : null}
        {pick.alternatives.length > 0 ? (
          <p className="pick-note">{draftAltLine(pick.alternatives)}</p>
        ) : null}
      </div>
      <div className={`pick-lane is-${pick.season_verdict}`}>
        <p className="eyebrow">Season</p>
        <p className="pick-pts">
          {pick.season_points.toFixed(1)} pts{inProgress ? " so far" : ""}
        </p>
        {pick.season_note ? <p className="pick-note">{pick.season_note}</p> : null}
        {pick.season_alternatives.length > 0 ? (
          <p className="pick-note">{seasonAltLine(pick.season_alternatives)}</p>
        ) : null}
      </div>
    </li>
  );
}

function BoomBustPanel({ board }: { board: BoomBustReport }) {
  if (board.booms.length === 0 && board.busts.length === 0) {
    return <p className="lede">No drafted skill players have cleared the boom or bust bars yet.</p>;
  }
  return (
    <div className="wire">
      <BoomBustTable title="Biggest booms" rows={board.booms} kind="boom" />
      <BoomBustTable title="Biggest busts" rows={board.busts} kind="bust" />
    </div>
  );
}

function BoomBustTable({
  title,
  rows,
  kind,
}: {
  title: string;
  rows: BoomBustRow[];
  kind: "boom" | "bust";
}) {
  return (
    <div>
      <p className="eyebrow">{title}</p>
      {rows.length === 0 ? (
        <p className="lede">None at this threshold.</p>
      ) : (
        <div className="table-wrap">
          <table className="board">
            <thead>
              <tr>
                <th className="num">Pace</th>
                <th className="num">So far</th>
                <th>Player</th>
                <th>Drafted by</th>
                <th className="num">Pts/week</th>
                <th className="num">Proj/week</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.kind}-${row.overall_pick}-${row.player_name}`}>
                  <td className={`num ${kind === "boom" ? "is-hit" : "is-bust"}`} data-label="Pace">
                    {row.pace_delta > 0 ? "+" : ""}
                    {row.pace_delta.toFixed(0)}
                  </td>
                  <td className="num" data-label="So far">
                    {row.surplus_so_far > 0 ? "+" : ""}
                    {row.surplus_so_far.toFixed(1)}
                  </td>
                  <td className="is-primary">
                    {row.player_name}
                    {row.position ? ` · ${row.position}` : ""}
                    <div className="pick-note">
                      {row.badge}
                      {row.imputed ? " · rank fill" : ""}
                      {injuryLabel(row.injury) ? ` · ${injuryLabel(row.injury)}` : ""}
                    </div>
                  </td>
                  <td data-label="Drafted by">
                    {row.team_name}
                    <div className="pick-note">
                      R{row.round} · pick {row.overall_pick}
                      {row.espn_rank != null ? ` · ESPN #${row.espn_rank}` : ""}
                    </div>
                  </td>
                  <td className="num" data-label="Pts/week">
                    {row.actual_ppw.toFixed(2)}
                  </td>
                  <td className="num" data-label="Proj/week">
                    {row.proj_ppw.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function AgencyPanel({ board }: { board: WireBoard }) {
  const empty =
    board.highest_spends.length === 0 &&
    board.best_adds.length === 0 &&
    board.worst_drops.length === 0;
  if (empty) {
    return <p className="lede">No waiver or free-agent moves in the ESPN log yet.</p>;
  }
  return (
    <div className="wire">
      {board.highest_spends.length > 0 ? (
        <div>
          <p className="eyebrow">Highest FA spends</p>
          <div className="table-wrap">
            <table className="board">
              <thead>
                <tr>
                  <th className="num">Bid</th>
                  <th>Player</th>
                  <th>Team</th>
                  <th className="num">Pts</th>
                  <th className="num">Weeks</th>
                  <th className="num">Pts/week</th>
                </tr>
              </thead>
              <tbody>
                {board.highest_spends.map((row) => (
                  <tr key={`${row.team_id}-${row.player_name}-${row.week}-${row.bid}`}>
                    <td className="num is-primary" data-label="Bid">
                      ${row.bid.toFixed(0)}
                    </td>
                    <td>
                      {row.player_name}
                      {row.position ? ` · ${row.position}` : ""}
                    </td>
                    <td data-label="Team">
                      {row.team_name}
                      <div className="pick-note">
                        W{row.week} · {row.source}
                      </div>
                    </td>
                    <td className="num" data-label="Pts">
                      {row.points_after.toFixed(1)}
                    </td>
                    <td className="num" data-label="Weeks">
                      {row.weeks || "—"}
                    </td>
                    <td className={`num ${row.pts_per_week >= 10 ? "is-hit" : ""}`} data-label="Pts/week">
                      {row.pts_per_week.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
      <div className="wire-grid">
        <WireList title="Best adds" rows={board.best_adds} good />
        <WireList title="Worst drops" rows={board.worst_drops} />
      </div>
    </div>
  );
}

function TradesPanel({ board }: { board: WireBoard }) {
  if (board.trades.length === 0) {
    return <p className="lede">No completed trades ESPN will show players for.</p>;
  }
  return (
    <div className="wire">
      {board.trades.map((row) => (
        <article className="trade-card" key={`${row.week}-${row.sides.map((side) => side.team_id).join("-")}`}>
          <p className="eyebrow">Week {row.week}</p>
          <div className="trade-grid">
            {row.sides.map((side) => (
              <TradeSideCard key={`${row.week}-${side.team_id}`} side={side} />
            ))}
          </div>
        </article>
      ))}
    </div>
  );
}

function TradeSideCard({ side }: { side: TradeSide }) {
  const tone = side.net > 0 ? "is-hit" : side.net < 0 ? "is-bust" : undefined;
  return (
    <div>
      <p className="team-label">{side.team_name}</p>
      <AssetTable label="Received" rows={side.received_players} />
      <AssetTable label="Sent" rows={side.sent_players} />
      <p className={`net ${tone ?? ""}`}>
        Net {side.net > 0 ? "+" : ""}
        {side.net.toFixed(1)} pts
        {side.net_ppw ? ` · ${side.net_ppw > 0 ? "+" : ""}${side.net_ppw.toFixed(2)} pts/week` : ""}
      </p>
    </div>
  );
}

function AssetTable({ label, rows }: { label: string; rows: TradeAsset[] }) {
  return (
    <>
      <p className="eyebrow">{label}</p>
      {rows.length === 0 ? (
        <p className="lede">—</p>
      ) : (
        <div className="table-wrap">
          <table className="board">
            <thead>
              <tr>
                <th>Player</th>
                <th className="num">Pts</th>
                <th className="num">Weeks</th>
                <th className="num">Pts/week</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${label}-${row.player_name}-${row.points}`}>
                  <td>
                    {row.player_name}
                    {row.position ? ` · ${row.position}` : ""}
                  </td>
                  <td className="num" data-label="Pts">
                    {row.points.toFixed(1)}
                  </td>
                  <td className="num" data-label="Weeks">
                    {row.weeks}
                  </td>
                  <td className={`num ${row.pts_per_week >= 10 ? "is-hit" : ""}`} data-label="Pts/week">
                    {row.pts_per_week.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function injuryLabel(status: string): string {
  const upper = status.toUpperCase();
  if (!upper || upper === "ACTIVE") return "";
  if (upper === "INJURY_RESERVE") return "IR";
  return status.replace(/_/g, " ");
}

function WireList({
  title,
  rows,
  good = false,
}: {
  title: string;
  rows: WireMove[];
  good?: boolean;
}) {
  return (
    <div>
      <p className="eyebrow">{title}</p>
      {rows.length === 0 ? (
        <p className="lede">None yet.</p>
      ) : (
        <ol className="weeks">
          {rows.map((row) => (
            <li key={`${row.team_id}-${row.player_name}-${row.week}-${row.source}`}>
              <span>
                W{row.week} · {row.source} · {row.team_name}
                <strong>
                  {row.player_name}
                  {row.position ? ` · ${row.position}` : ""}
                </strong>
              </span>
              <em className={good ? "is-hit" : "is-bust"}>
                {row.pts_per_week
                  ? `${row.pts_per_week.toFixed(2)} /wk`
                  : `${row.points_after.toFixed(1)} pts after`}
              </em>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function ordinal(n: number): string {
  const v = n % 100;
  if (v >= 11 && v <= 13) return "th";
  if (n % 10 === 1) return "st";
  if (n % 10 === 2) return "nd";
  if (n % 10 === 3) return "rd";
  return "th";
}

function luckLabel(value: number): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
}

function LuckCells({ row }: { row: LuckRow }) {
  const tone = row.luck > 0.25 ? "is-hit" : row.luck < -0.25 ? "is-bust" : undefined;
  return (
    <tr>
      <td className="is-primary">{row.team_name}</td>
      <td className="num" data-label="Rec">
        {recordOf({
          wins: row.actual_wins,
          losses: row.actual_losses,
          ties: row.actual_ties,
        })}
      </td>
      <td className="num" data-label="All-play">
        {recordOf({
          wins: row.all_play_wins,
          losses: row.all_play_losses,
          ties: row.all_play_ties,
        })}
      </td>
      <td className="num" data-label="xW">
        {row.expected_wins.toFixed(1)}
      </td>
      <td className={`num ${tone ?? ""}`} data-label="Luck">
        {luckLabel(row.luck)}
      </td>
      <td className="num" data-label="Lucky W">
        {row.lucky_wins || "—"}
      </td>
      <td className="num" data-label="Unlucky L">
        {row.unlucky_losses || "—"}
      </td>
    </tr>
  );
}

function StandingCells({ row }: { row: StandingRow }) {
  const seed = row.seed ?? "—";
  const best =
    row.best_week_period != null ? `W${row.best_week_period} ${row.best_week.toFixed(1)}` : "—";
  return (
    <tr className={row.seed === 1 ? "is-lead" : undefined}>
      <td className="num" data-label="Seed">
        {seed}
      </td>
      <td className="is-primary">{row.name}</td>
      <td className="num" data-label="Rec">
        {recordOf(row)}
      </td>
      <td className="num" data-label="PF">
        {row.points_for.toFixed(1)}
      </td>
      <td className="num" data-label="PA">
        {row.points_against.toFixed(1)}
      </td>
      <td className="num" data-label="Diff">
        {row.point_diff.toFixed(1)}
      </td>
      <td className="num" data-label="Best">
        {best}
      </td>
      <td className="num" data-label="Swing">
        {row.stdev.toFixed(1)}
      </td>
    </tr>
  );
}
