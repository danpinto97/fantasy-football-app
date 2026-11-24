The point of this file is to be a discourse and planning session between the developer and cursor.

## Current sequencing (Nov 2026)

1. **DONE — Draft accuracy rework** (canvas: `draft-accuracy-rework`)
   - Process vs outcome grader, FLEX-aware VBD, ADP window, CLI, tests.
   - Future API must call `DraftGrader`, not the deleted four-mode VORP analyzer.

2. **NOW — League Intel rework** (canvas: `league-intel-rework`)
   - P0 done: FastAPI + React, league ID + season lookup.
   - **Palette restyled to NFL+ grit** (plus.nfl.com tokens): soot `--bg #13141d` / `--surface #272731`; steel text `--text #c6cbd7`; accent `--accent #004fff`; `--danger #d50a0a` only for errors/live. Barlow Condensed + IBM Plex Sans. Not khaki/teal/bordeaux.
   - P0b done: ESPN adapter splits allowlisted HTTP from parse. Recorded fixtures for league 96876878 / 2024 cover mTeam, mSettings, mRoster, mMatchup, mDraftDetail. Team records and matchups are parsed; lookup UI shows W-L and PF.
   - P1 done: overview kernel ranks standings, highest PF, hottest week, lowest weekly swing. League page consumes `/api/leagues/{id}/overview`.
   - P1b done: process/outcome drafter leaderboard on the league page (`/draft-grades`).
   - **P1c done — pick drill-down:** click a team. Green/red is draft day (ADP steal/reach + names still on the board). Season is a redraft on actual points (where that pick would go today + production alts). No K/DST season alts except last two rounds; no QB alts once the team has a QB.
   - **Revisit later — draft-day “On the board” / late-reach cap:** even picks are within ~4 ADP spots, but after round 4 we only badge the two worst reaches so the board doesn’t go all red. Quiet late cards can still be mild darts (ADP line is the tell). Revisit once waiver/FA/trades and luck are in.
   - **P1d done — adds / drops / trades:** ESPN `mTransactions2` per scoring period. Best waiver/FA adds, worst drops, best/worst trades on the league page (`/wire`). Grade on points after the move (adds stop if that team later dropped the player). Completed ESPN trades omit player lists — reconstruct from roster diffs in weeks with TRADE_ACCEPT.
   - **P1e done — schedule luck:** all-play record vs H2H, expected wins, luck = actual − expected, lucky wins / unlucky losses. Lives on overview (same matchup fetch). **xW** = expected wins = each week, the chance you’d beat a random opponent (all-play wins / (n−1), ties count half), summed over the regular season.
   - **Standings “Swing”** is weekly PF population standard deviation (how boom/bust the weeks were). “Most consistent” is the lowest swing.
   - **Season alts:** names still available whose ADP is within 18 spots of the pick, and who outscored that pick. Late reaches that paid off (season hit) keep the miss + Paid off badge; other late misses stay capped at two.
   - **P2 done — Unraid image:** root `Dockerfile` builds the Vite UI and serves it from FastAPI (`UI_DIST`). Env: `SITE_PASSWORD`, `SESSION_SECRET`, `ESPN_SWID`, `ESPN_S2`, `PORT`. No host paths, no secrets in the image.
   - **Seasons:** default lookup is the current NFL year (Aug–Jul). Adapter tries the current ESPN path then `leagueHistory`. `/seasons` walks current→history so year chips include private years plus the last public season. Hoboken **2026 is public** (as of Nov 9 2026); **2025 still 401 private**; 2024 public.
   - **Friends-only gate + per-browser ESPN cookies:** `SITE_PASSWORD` is a shared HMAC cookie (`ff_gate`), not accounts — 5 sign-in attempts/min per IP. After the gate, a visitor can paste `SWID` + `espn_s2`; stored encrypted httpOnly (`ff_espn`, Fernet from `SESSION_SECRET`), cache keyed by session, Forget ESPN login / logout clears it. Paste is refused unless `SITE_PASSWORD` is set (no public credential sink). Optional operator `ESPN_SWID`/`ESPN_S2` remain a fallback. Never log cookie values.
   - Site-wide password is a shared speed bump, not identity. Still rate-limit lookups, validate league IDs, isolate ESPN cache by session.
   - **Deploy target: Unraid.** App must stay containerizable: one image that serves FastAPI + the built React UI, config via env (`SITE_PASSWORD`, `ESPN_SWID`, `ESPN_S2`, bind host/port), no host-specific paths. Compose/Postgres/Redis only if we outgrow in-memory cache. Do not bake secrets into the image.

Test league: ESPN `96876878` (Hoboken Local Football League).

---

## Original goals

This project aims to create an application that tracks certain stats from a user's given fantasy football league.

Considerations:
- Experience is in C++ and Python
- A GUI will be added (now planned as a public web app)
- ESPN first; Yahoo and Sleeper later

1. Track who drafted the most accurately in a given year
   - Compare each pick to a realistic best available (ADP window, not this league's later reaches)
   - Roster construction and scoring settings from the league
   - Score process (ADP) separately from outcome (production)
2. GUI: league ID input, draft grades, later more league intel
3. More features after 1 and 2 (standings, trades, waivers, luck)
   - After pick cards: waiver/FA adds, drops, and trades (ESPN `mTransactions2` per scoring period). Schedule luck and the Unraid image are in. Revisit draft-day even/late-reach badges later.
