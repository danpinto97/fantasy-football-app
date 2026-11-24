# Fantasy Football App

Track draft accuracy and league stats from ESPN Fantasy (and later Yahoo, Sleeper).

Phase 1 is a CLI. The draft grader is the analysis kernel (process vs outcome). A public web app is next — see `cursor.md`.

## Setup

- Python 3.10+
- Create a virtualenv and install in editable mode:

```bash
python3 -m venv .venv
source .venv/bin/activate   # or `.venv\Scripts\activate` on Windows
pip install -e ".[dev]"
```

## Usage (CLI)

Default league ID is `96876878` (override with `--league-id`).

```bash
# League info (roster slots, name, etc.)
ff league --league-id 96876878 --season 2024

# One team's draft: process (ADP vs pick) and outcome (VBD vs slot)
ff draft-accuracy --league-id 96876878 --season 2024 --team-id 1

# Every team's process / outcome ranks
ff draft-accuracy --league-id 96876878 --season 2024 --leaderboard
```

Private ESPN seasons return 401 without a session. With `SITE_PASSWORD` set, a signed-in visitor can paste their own ESPN `SWID` and `espn_s2` cookies in the browser; they are stored encrypted and httpOnly on that device. Optional server `ESPN_SWID` / `ESPN_S2` remain a fallback. Never bake cookies into an image, never log them, never paste them in chat.

## Web app (dev)

```bash
# API
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn fantasy_football.api.app:app --reload --port 8000

# UI (separate terminal)
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173 — enter an ESPN league ID. Set `SITE_PASSWORD` (and `SESSION_SECRET`) to gate the site and to allow per-browser ESPN cookies for private seasons. Optional env fallback: `ESPN_SWID`, `ESPN_S2`. Default season is the current NFL year.

## Unraid / Docker

One image serves FastAPI and the built UI on port 8000. No host paths. Secrets only via env.

```bash
docker build -t league-intel .
docker run --name league-intel -p 8000:8000 \
  -e SITE_PASSWORD=change-me \
  -e SESSION_SECRET=change-me-too \
  -e ESPN_SWID='{...}' \
  -e ESPN_S2='...' \
  league-intel
```

Or `docker compose up --build`. Then open `http://<host>:8000`.

Unraid Docker tab: add a container from this image, map host port 8000, WebUI `http://[IP]:[PORT:8000]/`. Environment:

| Variable | Required | Purpose |
| --- | --- | --- |
| `SITE_PASSWORD` | for private-league paste | Shared friends-only gate. Required before the app will store visitor ESPN cookies. |
| `SESSION_SECRET` | if password is set | Cookie HMAC + ESPN cookie encryption (defaults to the password; set a separate secret) |
| `ESPN_SWID` | optional fallback | Operator ESPN `swid` if you do not want visitors to paste |
| `ESPN_S2` | optional fallback | Operator ESPN `espn_s2` |
| `PORT` | no | Listen port inside the container (default 8000) |
| `CORS_ORIGINS` | no | Comma-separated origins if the UI is on another host |

Do not mount `/mnt/user/...` into the app. Do not copy cookies into the image.

## Project layout

```
src/fantasy_football/
  espn/            # Allowlisted ESPN adapter (HTTP + parse, settings/teams/rosters/matchups/draft)
  models/          # Pydantic models
  draft_accuracy/  # FLEX-aware VBD + process/outcome grader
  positions.py     # ESPN slot / position maps
  cli/             # Click CLI (ff league, ff draft-accuracy)
tests/             # Grader + adapter tests on recorded ESPN fixtures (no live ESPN)
```
