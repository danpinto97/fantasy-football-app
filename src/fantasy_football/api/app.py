"""FastAPI app: league lookup with validation, cache, and optional site password."""

import os
from pathlib import Path
from typing import Any, List, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from fantasy_football.api.espn_session import (
    cache_key as namespaced_key,
)
from fantasy_football.api.espn_session import (
    clear_espn_cookie,
    espn_cookies_for_request,
    has_visitor_espn_session,
    request_has_espn_session,
    set_espn_cookie,
)
from fantasy_football.api.security import (
    RateLimiter,
    TtlCache,
    check_password,
    clear_gate_cookie,
    client_ip,
    is_authenticated,
    parse_league_id,
    parse_season,
    password_required,
    require_auth,
    set_gate_cookie,
)
from fantasy_football.espn.client import ESPNClient
from fantasy_football.league_intel.draft_board import DraftBoardReport, build_draft_board
from fantasy_football.league_intel.overview import OverviewReport, build_overview
from fantasy_football.league_intel.wire import WireReport, build_wire_report
from fantasy_football.models.league import LeagueSettings
from fantasy_football.seasons import current_nfl_season, merge_available_seasons


class LoginBody(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    password: str = Field(..., min_length=1, max_length=200)


class EspnSessionBody(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    swid: str = Field(..., min_length=8, max_length=200)
    espn_s2: str = Field(..., min_length=20, max_length=2000)

    @field_validator("swid", "espn_s2")
    @classmethod
    def no_cookie_meta(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(ch in cleaned for ch in "\r\n;"):
            raise ValueError("Invalid cookie value")
        return cleaned


class RosterSlotOut(BaseModel):
    position: str
    count: int
    is_flex: bool


class TeamOut(BaseModel):
    team_id: str
    name: str
    abbrev: str = ""
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0
    points_against: float = 0.0
    playoff_seed: Optional[int] = None


class LeagueOut(BaseModel):
    league_id: str
    season: int
    name: str
    num_teams: int
    roster_slots: List[RosterSlotOut]
    teams: List[TeamOut]


class AuthStatusOut(BaseModel):
    required: bool
    authenticated: bool
    has_espn_session: bool
    visitor_espn_session: bool
    espn_session_enabled: bool


class SeasonsOut(BaseModel):
    league_id: str
    seasons: List[int]
    current_season: int
    has_espn_session: bool


def ui_dist() -> Optional[Path]:
    env = os.environ.get("UI_DIST", "").strip()
    candidates = [Path(env)] if env else []
    here = Path(__file__).resolve()
    candidates.extend(
        [
            here.parents[3] / "frontend" / "dist",
            Path("/app/frontend/dist"),
        ]
    )
    for path in candidates:
        if (path / "index.html").is_file():
            return path
    return None


def _cors_origins() -> List[str]:
    raw = os.environ.get("CORS_ORIGINS", "").strip()
    if raw == "*":
        return ["*"]
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return ["http://127.0.0.1:5173", "http://localhost:5173"]


def _mount_ui(app: FastAPI) -> None:
    dist = ui_dist()
    if dist is None:
        return
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="ui-assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="Not found")
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


def _espn_http_error(exc: Exception, request: Request) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            if has_visitor_espn_session(request):
                detail = (
                    "ESPN rejected this browser's session for that season. "
                    "Forget ESPN login and paste cookies again, or try another year."
                )
            elif request_has_espn_session(request):
                detail = "ESPN rejected the stored server session for this season."
            else:
                detail = (
                    "ESPN says this league is private for that season. "
                    "Paste your ESPN SWID and espn_s2 cookies to unlock it in this browser."
                )
            return HTTPException(status_code=403, detail=detail)
        if code == 404:
            return HTTPException(status_code=404, detail="League not found for that season.")
        return HTTPException(status_code=502, detail="ESPN request failed.")
    if isinstance(exc, httpx.HTTPError):
        return HTTPException(status_code=502, detail="Could not reach ESPN.")
    return HTTPException(status_code=502, detail="Unexpected league payload.")


def create_app(
    *,
    espn_client: Optional[Any] = None,
    limiter: Optional[RateLimiter] = None,
    cache: Optional[TtlCache] = None,
    auth_limiter: Optional[RateLimiter] = None,
) -> FastAPI:
    app = FastAPI(title="League Intel", version="0.2.0")
    app.state.espn = espn_client
    app.state.limiter = limiter or RateLimiter(max_calls=20, window_seconds=60.0)
    app.state.cache = cache or TtlCache(ttl_seconds=600.0)
    app.state.auth_limiter = auth_limiter or RateLimiter(
        max_calls=5,
        window_seconds=60.0,
        detail="Too many sign-in attempts. Wait a minute.",
    )
    app.state.espn_session_limiter = RateLimiter(
        max_calls=8,
        window_seconds=60.0,
        detail="Too many ESPN session updates. Wait a minute.",
    )

    origins = _cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    def get_espn(request: Request) -> Any:
        override = app.state.espn
        if override is not None:
            return override
        return ESPNClient(cookies=espn_cookies_for_request(request), timeout=20.0)

    @app.exception_handler(RequestValidationError)
    async def hide_secret_validation(request: Request, exc: RequestValidationError):
        if request.url.path in {"/api/espn-session", "/api/auth/login"}:
            return JSONResponse(status_code=422, content={"detail": "Invalid input"})
        return await request_validation_exception_handler(request, exc)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/auth/status", response_model=AuthStatusOut)
    def auth_status(request: Request) -> AuthStatusOut:
        return AuthStatusOut(
            required=password_required(),
            authenticated=is_authenticated(request),
            has_espn_session=request_has_espn_session(request),
            visitor_espn_session=has_visitor_espn_session(request),
            espn_session_enabled=password_required(),
        )

    @app.post("/api/auth/login")
    def login(body: LoginBody, request: Request, response: Response) -> dict:
        if not password_required():
            return {"ok": True}
        app.state.auth_limiter.check(f"login:{client_ip(request)}")
        if not check_password(body.password):
            raise HTTPException(status_code=401, detail="Incorrect password")
        set_gate_cookie(response)
        return {"ok": True}

    @app.post("/api/auth/logout")
    def logout(response: Response) -> dict:
        clear_gate_cookie(response)
        clear_espn_cookie(response)
        return {"ok": True}

    @app.post("/api/espn-session")
    def save_espn_session(body: EspnSessionBody, request: Request, response: Response) -> dict:
        if not password_required():
            raise HTTPException(
                status_code=403,
                detail="ESPN sessions need SITE_PASSWORD so this is not a public drop box.",
            )
        require_auth(request)
        app.state.espn_session_limiter.check(f"espn:{client_ip(request)}")
        set_espn_cookie(response, body.swid, body.espn_s2)
        return {"ok": True}

    @app.delete("/api/espn-session")
    def forget_espn_session(request: Request, response: Response) -> dict:
        require_auth(request)
        clear_espn_cookie(response)
        return {"ok": True}

    @app.get("/api/leagues/{league_id}/seasons", response_model=SeasonsOut)
    def get_seasons(
        league_id: str,
        request: Request,
        espn: Any = Depends(get_espn),
    ) -> SeasonsOut:
        require_auth(request)
        league_id = parse_league_id(league_id)
        app.state.limiter.check(f"lookup:{client_ip(request)}")
        key = namespaced_key(request, "seasons", league_id)
        cached = app.state.cache.get(key)
        if cached is not None:
            return cached
        current = current_nfl_season()
        try:
            seasons = espn.discover_seasons(league_id, current=current)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            seasons = merge_available_seasons([], current)
        payload = SeasonsOut(
            league_id=league_id,
            seasons=seasons,
            current_season=current,
            has_espn_session=request_has_espn_session(request),
        )
        app.state.cache.set(key, payload)
        return payload

    @app.get("/api/leagues/{league_id}", response_model=LeagueOut)
    def get_league(
        league_id: str,
        request: Request,
        season: Optional[int] = Query(default=None),
        espn: Any = Depends(get_espn),
    ) -> LeagueOut:
        require_auth(request)
        league_id = parse_league_id(league_id)
        season = parse_season(season if season is not None else current_nfl_season())
        app.state.limiter.check(f"lookup:{client_ip(request)}")
        key = namespaced_key(request, league_id, season)
        cached = app.state.cache.get(key)
        if cached is not None:
            return cached
        try:
            settings: LeagueSettings = espn.get_league_settings(league_id, season)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise _espn_http_error(exc, request) from exc

        payload = LeagueOut(
            league_id=settings.league_id,
            season=settings.season,
            name=settings.name,
            num_teams=settings.num_teams,
            roster_slots=[
                RosterSlotOut(position=s.position, count=s.count, is_flex=s.is_flex)
                for s in settings.roster_slots
            ],
            teams=[
                TeamOut(
                    team_id=t.team_id,
                    name=t.name,
                    abbrev=t.abbrev,
                    wins=t.wins,
                    losses=t.losses,
                    ties=t.ties,
                    points_for=t.points_for,
                    points_against=t.points_against,
                    playoff_seed=t.playoff_seed,
                )
                for t in settings.teams
            ],
        )
        app.state.cache.set(key, payload)
        return payload

    @app.get("/api/leagues/{league_id}/overview", response_model=OverviewReport)
    def get_overview(
        league_id: str,
        request: Request,
        season: Optional[int] = Query(default=None),
        espn: Any = Depends(get_espn),
    ) -> OverviewReport:
        require_auth(request)
        league_id = parse_league_id(league_id)
        season = parse_season(season if season is not None else current_nfl_season())
        app.state.limiter.check(f"lookup:{client_ip(request)}")
        key = namespaced_key(request, "overview", league_id, season)
        cached = app.state.cache.get(key)
        if cached is not None:
            return cached
        try:
            settings, matchups = espn.get_settings_and_matchups(league_id, season)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise _espn_http_error(exc, request) from exc
        payload = build_overview(settings, matchups)
        app.state.cache.set(key, payload)
        return payload

    @app.get("/api/leagues/{league_id}/draft-grades", response_model=DraftBoardReport)
    def get_draft_grades(
        league_id: str,
        request: Request,
        season: Optional[int] = Query(default=None),
        espn: Any = Depends(get_espn),
    ) -> DraftBoardReport:
        require_auth(request)
        league_id = parse_league_id(league_id)
        season = parse_season(season if season is not None else current_nfl_season())
        app.state.limiter.check(f"lookup:{client_ip(request)}")
        key = namespaced_key(request, "draft-grades", league_id, season)
        cached = app.state.cache.get(key)
        if cached is not None:
            return cached
        try:
            settings, draft, pool = espn.get_draft_inputs(league_id, season)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise _espn_http_error(exc, request) from exc
        payload = build_draft_board(settings, draft, pool)
        app.state.cache.set(key, payload)
        return payload

    @app.get("/api/leagues/{league_id}/wire", response_model=WireReport)
    def get_wire(
        league_id: str,
        request: Request,
        season: Optional[int] = Query(default=None),
        espn: Any = Depends(get_espn),
    ) -> WireReport:
        require_auth(request)
        league_id = parse_league_id(league_id)
        season = parse_season(season if season is not None else current_nfl_season())
        app.state.limiter.check(f"lookup:{client_ip(request)}")
        key = namespaced_key(request, "wire", league_id, season)
        cached = app.state.cache.get(key)
        if cached is not None:
            return cached
        try:
            settings, txs, pool, rosters = espn.get_wire_inputs(league_id, season)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise _espn_http_error(exc, request) from exc
        payload = build_wire_report(settings, txs, pool, rosters)
        app.state.cache.set(key, payload)
        return payload

    _mount_ui(app)
    return app


app = create_app()
