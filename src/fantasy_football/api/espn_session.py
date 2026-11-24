"""Per-browser ESPN cookies: encrypted httpOnly, never logged."""

from __future__ import annotations

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request, Response

from fantasy_football.api.security import cookie_secure, session_secret
from fantasy_football.espn.http import cookies_from_env

ESPN_COOKIE_NAME = "ff_espn"
ESPN_COOKIE_MAX_AGE = 60 * 60 * 24 * 7
_SWID_MAX = 200
_S2_MAX = 2000


def _fernet() -> Fernet:
    digest = hashlib.sha256(b"ff-espn-v1:" + session_secret().encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_espn_cookies(swid: str, espn_s2: str) -> str:
    payload = json.dumps({"swid": swid, "espn_s2": espn_s2}, separators=(",", ":")).encode("utf-8")
    return _fernet().encrypt(payload).decode("ascii")


def decrypt_espn_cookies(token: str) -> dict[str, str]:
    if not token:
        return {}
    try:
        raw = _fernet().decrypt(token.encode("ascii"), ttl=ESPN_COOKIE_MAX_AGE + 300)
        data = json.loads(raw)
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError, UnicodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    swid = str(data.get("swid") or "").strip()
    espn_s2 = str(data.get("espn_s2") or "").strip()
    if not swid or not espn_s2 or len(swid) > _SWID_MAX or len(espn_s2) > _S2_MAX:
        return {}
    if any(ch in swid or ch in espn_s2 for ch in "\r\n;"):
        return {}
    return {"swid": swid, "espn_s2": espn_s2}


def visitor_espn_cookies(request: Request) -> dict[str, str]:
    return decrypt_espn_cookies(request.cookies.get(ESPN_COOKIE_NAME, ""))


def espn_cookies_for_request(request: Request) -> dict[str, str]:
    visitor = visitor_espn_cookies(request)
    if visitor.get("swid") and visitor.get("espn_s2"):
        return visitor
    return cookies_from_env()


def request_has_espn_session(request: Request) -> bool:
    cookies = espn_cookies_for_request(request)
    return bool(cookies.get("swid") and cookies.get("espn_s2"))


def has_visitor_espn_session(request: Request) -> bool:
    visitor = visitor_espn_cookies(request)
    return bool(visitor.get("swid") and visitor.get("espn_s2"))


def cache_namespace(request: Request) -> str:
    visitor = visitor_espn_cookies(request)
    if visitor.get("swid") and visitor.get("espn_s2"):
        material = f"{visitor['swid']}\0{visitor['espn_s2']}".encode()
        return "v:" + hashlib.sha256(material).hexdigest()[:16]
    env = cookies_from_env()
    if env.get("swid") and env.get("espn_s2"):
        return "env"
    return "public"


def set_espn_cookie(response: Response, swid: str, espn_s2: str) -> None:
    response.set_cookie(
        ESPN_COOKIE_NAME,
        encrypt_espn_cookies(swid, espn_s2),
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
        max_age=ESPN_COOKIE_MAX_AGE,
        path="/",
    )


def clear_espn_cookie(response: Response) -> None:
    response.delete_cookie(ESPN_COOKIE_NAME, path="/")


def cache_key(request: Request, *parts) -> tuple:
    return (cache_namespace(request),) + parts
