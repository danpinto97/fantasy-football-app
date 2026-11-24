from fastapi.testclient import TestClient
from test_api import FakeEspn

from fantasy_football.api.app import create_app
from fantasy_football.api.espn_session import decrypt_espn_cookies, encrypt_espn_cookies
from fantasy_football.api.security import RateLimiter

SWID_A = "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"
SWID_B = "{BBBBBBBB-CCCC-DDDD-EEEE-FFFFFFFFFFFF}"
S2_A = "visitor-session-token-aaaa"
S2_B = "visitor-session-token-bbbb"


def _gated_app(monkeypatch, *, espn=None, auth_limiter=None):
    monkeypatch.setenv("SITE_PASSWORD", "friends-only")
    monkeypatch.setenv("SESSION_SECRET", "unit-test-session-secret")
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    monkeypatch.delenv("ESPN_SWID", raising=False)
    monkeypatch.delenv("ESPN_S2", raising=False)
    return create_app(
        espn_client=espn or FakeEspn(),
        limiter=RateLimiter(max_calls=100, window_seconds=60),
        auth_limiter=auth_limiter or RateLimiter(max_calls=100, window_seconds=60),
    )


def _login(client: TestClient) -> None:
    res = client.post("/api/auth/login", json={"password": "friends-only"})
    assert res.status_code == 200


def test_encrypt_roundtrip_does_not_embed_plaintext(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "unit-test-session-secret")
    token = encrypt_espn_cookies(SWID_A, S2_A)
    assert SWID_A not in token
    assert S2_A not in token
    assert decrypt_espn_cookies(token) == {"swid": SWID_A, "espn_s2": S2_A}


def test_decrypt_garbage_is_empty(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "unit-test-session-secret")
    assert decrypt_espn_cookies("not-a-token") == {}


def test_login_sets_httponly_gate_cookie(monkeypatch):
    client = TestClient(_gated_app(monkeypatch))
    res = client.post("/api/auth/login", json={"password": "friends-only"})
    assert res.status_code == 200
    cookie = res.headers.get("set-cookie", "").lower()
    assert "ff_gate=" in cookie
    assert "httponly" in cookie
    status = client.get("/api/auth/status").json()
    assert status["authenticated"] is True
    assert status["espn_session_enabled"] is True


def test_wrong_password_is_401(monkeypatch):
    client = TestClient(_gated_app(monkeypatch))
    res = client.post("/api/auth/login", json={"password": "nope"})
    assert res.status_code == 401
    assert "ff_gate=" not in res.headers.get("set-cookie", "").lower()


def test_league_requires_password(monkeypatch):
    client = TestClient(_gated_app(monkeypatch))
    res = client.get("/api/leagues/96876878?season=2024")
    assert res.status_code == 401


def test_login_rate_limited(monkeypatch):
    app = _gated_app(
        monkeypatch,
        auth_limiter=RateLimiter(
            max_calls=3,
            window_seconds=60,
            detail="Too many sign-in attempts. Wait a minute.",
        ),
    )
    client = TestClient(app)
    for _ in range(3):
        assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    res = client.post("/api/auth/login", json={"password": "nope"})
    assert res.status_code == 429
    assert "sign-in" in res.json()["detail"]


def test_espn_session_validation_does_not_echo_secrets(monkeypatch):
    client = TestClient(_gated_app(monkeypatch))
    _login(client)
    secret = "secret-value-should-not-echo-xx"
    res = client.post("/api/espn-session", json={"swid": "x", "espn_s2": secret})
    assert res.status_code == 422
    assert secret not in res.text
    assert "Invalid input" in res.text


def test_espn_session_refused_without_site_password():
    app = create_app(
        espn_client=FakeEspn(),
        limiter=RateLimiter(max_calls=100, window_seconds=60),
    )
    res = TestClient(app).post(
        "/api/espn-session",
        json={"swid": SWID_A, "espn_s2": S2_A},
    )
    assert res.status_code == 403
    assert "SITE_PASSWORD" in res.json()["detail"]


def test_espn_session_sets_encrypted_httponly_cookie(monkeypatch):
    client = TestClient(_gated_app(monkeypatch))
    _login(client)
    res = client.post("/api/espn-session", json={"swid": SWID_A, "espn_s2": S2_A})
    assert res.status_code == 200
    body = res.json()
    assert body == {"ok": True}
    assert SWID_A not in res.text
    assert S2_A not in res.text
    cookie = res.headers.get("set-cookie", "")
    assert "ff_espn=" in cookie.lower()
    assert "httponly" in cookie.lower()
    assert SWID_A not in cookie
    assert S2_A not in cookie
    status = client.get("/api/auth/status").json()
    assert status["visitor_espn_session"] is True
    assert status["has_espn_session"] is True


def test_clear_espn_session(monkeypatch):
    client = TestClient(_gated_app(monkeypatch))
    _login(client)
    client.post("/api/espn-session", json={"swid": SWID_A, "espn_s2": S2_A})
    res = client.delete("/api/espn-session")
    assert res.status_code == 200
    status = client.get("/api/auth/status").json()
    assert status["visitor_espn_session"] is False


def test_logout_clears_espn_cookie(monkeypatch):
    client = TestClient(_gated_app(monkeypatch))
    _login(client)
    client.post("/api/espn-session", json={"swid": SWID_A, "espn_s2": S2_A})
    client.post("/api/auth/logout")
    status = client.get("/api/auth/status").json()
    assert status["authenticated"] is False
    assert status["visitor_espn_session"] is False


class CountingEspn(FakeEspn):
    def __init__(self):
        self.calls = 0

    def get_league_settings(self, league_id, season):
        self.calls += 1
        return super().get_league_settings(league_id, season)


def test_cache_isolated_by_espn_session(monkeypatch):
    espn = CountingEspn()
    app = _gated_app(monkeypatch, espn=espn)
    client_a = TestClient(app)
    client_b = TestClient(app)
    _login(client_a)
    _login(client_b)
    client_a.post("/api/espn-session", json={"swid": SWID_A, "espn_s2": S2_A})
    client_b.post("/api/espn-session", json={"swid": SWID_B, "espn_s2": S2_B})

    assert client_a.get("/api/leagues/96876878?season=2024").status_code == 200
    assert espn.calls == 1
    assert client_b.get("/api/leagues/96876878?season=2024").status_code == 200
    assert espn.calls == 2
    assert client_a.get("/api/leagues/96876878?season=2024").status_code == 200
    assert espn.calls == 2
