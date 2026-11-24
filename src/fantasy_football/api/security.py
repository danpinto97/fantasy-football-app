"""Password gate, rate limit, and input rules for the public API."""

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict
from typing import DefaultDict, List, Optional

from fastapi import HTTPException, Request, Response, status

COOKIE_NAME = "ff_gate"
LEAGUE_ID_MIN_LEN = 4
LEAGUE_ID_MAX_LEN = 12
SEASON_MIN = 2008
SEASON_MAX = 2030


def site_password() -> str:
    return os.environ.get("SITE_PASSWORD", "")


def session_secret() -> str:
    return os.environ.get("SESSION_SECRET") or site_password() or "dev-insecure-change-me"


def password_required() -> bool:
    return bool(site_password())


def gate_token() -> str:
    return hmac.new(
        session_secret().encode("utf-8"),
        b"league-intel-ok",
        hashlib.sha256,
    ).hexdigest()


def check_password(password: str) -> bool:
    expected = site_password()
    if not expected:
        return True
    return secrets.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))


def is_authenticated(request: Request) -> bool:
    if not password_required():
        return True
    cookie = request.cookies.get(COOKIE_NAME, "")
    return secrets.compare_digest(cookie.encode("utf-8"), gate_token().encode("utf-8"))


def set_gate_cookie(response: Response) -> None:
    response.set_cookie(
        COOKIE_NAME,
        gate_token(),
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
        max_age=60 * 60 * 24 * 7,
        path="/",
    )


def clear_gate_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def require_auth(request: Request) -> None:
    if not is_authenticated(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Password required")


def parse_league_id(raw: str) -> str:
    value = (raw or "").strip()
    if not value.isdigit() or not (LEAGUE_ID_MIN_LEN <= len(value) <= LEAGUE_ID_MAX_LEN):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="League ID must be 4–12 digits",
        )
    return value


def parse_season(season: int) -> int:
    if season < SEASON_MIN or season > SEASON_MAX:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Season must be between {SEASON_MIN} and {SEASON_MAX}",
        )
    return season


class RateLimiter:
    """In-memory per-key sliding window. Not a substitute for an edge limiter."""

    def __init__(
        self,
        max_calls: int,
        window_seconds: float,
        *,
        detail: str = "Too many lookups. Wait a minute and try again.",
    ):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.detail = detail
        self._lock = threading.Lock()
        self._hits: DefaultDict[str, List[float]] = defaultdict(list)

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._hits[key] if now - t < self.window_seconds]
            if len(recent) >= self.max_calls:
                self._hits[key] = recent
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=self.detail,
                )
            recent.append(now)
            self._hits[key] = recent


class TtlCache:
    def __init__(self, ttl_seconds: float = 600.0):
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._data = {}

    def get(self, key):
        now = time.monotonic()
        with self._lock:
            row = self._data.get(key)
            if not row:
                return None
            value, expires = row
            if now >= expires:
                self._data.pop(key, None)
                return None
            return value

    def set(self, key, value) -> None:
        with self._lock:
            self._data[key] = (value, time.monotonic() + self.ttl_seconds)


def cookie_secure() -> bool:
    return os.environ.get("COOKIE_SECURE", "").lower() in ("1", "true", "yes")


def client_ip(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip", "").strip()
    if cf:
        return cf[:64]
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]
