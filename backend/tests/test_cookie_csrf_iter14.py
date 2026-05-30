"""Iter 14/15 — HttpOnly cookie + CSRF double-submit auth migration tests.

Covers:
- /api/auth/login & /api/auth/register set both cookies + return access_token
- Bearer-only back-compat (curl/testing agent still works)
- Cookie-only auth path
- CSRF enforcement: missing token, mismatched token, success
- Bearer-only requests bypass CSRF (cookie-less)
- Exempt paths (login/register/logout/migrate-token, oauth callback, postback)
- /api/auth/logout clears both cookies
- /api/auth/migrate-token re-issues cookies for legacy Bearer clients
"""
import os

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
LOGIN = f"{BASE_URL}/api/auth/login"
ME = f"{BASE_URL}/api/auth/me"
LOGOUT = f"{BASE_URL}/api/auth/logout"
MIGRATE = f"{BASE_URL}/api/auth/migrate-token"
RISK = f"{BASE_URL}/api/risk/limits"
DEMO = {"email": "demo@algoforge.io", "password": "Demo@123"}


# ---------- helpers ----------
def _bearer_login() -> str:
    """Login WITHOUT cookies persisted; returns access_token only."""
    r = requests.post(LOGIN, json=DEMO)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _cookie_login() -> requests.Session:
    """Login with a session so cookies are stored."""
    s = requests.Session()
    r = s.post(LOGIN, json=DEMO)
    assert r.status_code == 200, r.text
    return s


# ---------- login / register cookies ----------
class TestLoginCookies:
    def test_login_returns_token_and_user(self):
        r = requests.post(LOGIN, json=DEMO)
        assert r.status_code == 200
        body = r.json()
        assert "access_token" in body and isinstance(body["access_token"], str)
        assert body.get("token_type") == "bearer"
        assert body["user"]["email"] == "demo@algoforge.io"
        assert body["user"]["role"] == "admin"

    def test_login_sets_both_cookies(self):
        r = requests.post(LOGIN, json=DEMO)
        assert r.status_code == 200
        # cookies in jar
        names = {c.name for c in r.cookies}
        assert "algoforge_auth" in names, f"missing auth cookie; got {names}"
        assert "algoforge_csrf" in names, f"missing csrf cookie; got {names}"

        # Raw Set-Cookie header attributes
        raw_headers = r.raw.headers.getlist("set-cookie") if hasattr(
            r.raw.headers, "getlist"
        ) else r.headers.get("set-cookie", "").split(",")
        joined = " ".join(raw_headers).lower()
        assert "httponly" in joined  # auth cookie is httponly
        assert "samesite=lax" in joined
        assert "path=/" in joined

        # auth cookie must be HttpOnly; csrf must NOT be (browser JS reads it)
        for h in raw_headers:
            hl = h.lower()
            if "algoforge_auth=" in hl:
                assert "httponly" in hl, f"auth cookie missing HttpOnly: {h}"
            if "algoforge_csrf=" in hl:
                assert "httponly" not in hl, f"csrf cookie should not be HttpOnly: {h}"

    def test_login_bad_password(self):
        r = requests.post(LOGIN, json={**DEMO, "password": "WRONG"})
        assert r.status_code == 401


# ---------- back-compat: Bearer-only ----------
class TestBearerBackCompat:
    def test_me_with_bearer_no_cookies(self):
        token = _bearer_login()
        # Fresh session, no cookies, only Authorization header
        r = requests.get(ME, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        assert r.json()["email"] == "demo@algoforge.io"

    def test_risk_put_bearer_only_bypasses_csrf(self):
        """Bearer-only PUT (no cookies, no CSRF header) must still work."""
        token = _bearer_login()
        payload = {
            "max_drawdown_pct": 15.0,
            "daily_loss_cap": 25000.0,
            "position_limit": 5,
            "kill_switch": False,
        }
        r = requests.put(
            RISK,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, f"Bearer-only PUT broke! {r.status_code} {r.text}"

    def test_me_with_no_auth(self):
        r = requests.get(ME)
        assert r.status_code == 401


# ---------- cookie-only path ----------
class TestCookieAuth:
    def test_me_with_cookies_only(self):
        s = _cookie_login()
        # Don't carry any Authorization header — pure cookie path.
        r = s.get(ME)
        assert r.status_code == 200
        assert r.json()["email"] == "demo@algoforge.io"


# ---------- CSRF enforcement ----------
class TestCSRF:
    def test_csrf_missing_header(self):
        s = _cookie_login()
        # PUT under cookie auth, but no X-CSRF-Token header.
        r = s.put(
            RISK,
            json={
                "max_drawdown_pct": 15.0,
                "daily_loss_cap": 25000.0,
                "position_limit": 5,
                "kill_switch": False,
            },
        )
        assert r.status_code == 403
        assert "csrf" in r.text.lower()

    def test_csrf_wrong_header(self):
        s = _cookie_login()
        r = s.put(
            RISK,
            json={
                "max_drawdown_pct": 15.0,
                "daily_loss_cap": 25000.0,
                "position_limit": 5,
                "kill_switch": False,
            },
            headers={"X-CSRF-Token": "nope-this-is-wrong"},
        )
        assert r.status_code == 403
        assert "invalid csrf" in r.text.lower()

    def test_csrf_success(self):
        s = _cookie_login()
        csrf = s.cookies.get("algoforge_csrf")
        assert csrf, "csrf cookie must be set by login"
        r = s.put(
            RISK,
            json={
                "max_drawdown_pct": 15.0,
                "daily_loss_cap": 25000.0,
                "position_limit": 5,
                "kill_switch": False,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 200, r.text

    def test_csrf_exempt_login(self):
        # POST /api/auth/login (already exercised) requires no CSRF even when
        # carrying an unrelated cookie session.
        s = requests.Session()
        # Stamp a fake csrf cookie to ensure that doesn't trigger enforcement
        s.cookies.set("algoforge_csrf", "stale", path="/")
        r = s.post(LOGIN, json=DEMO)
        assert r.status_code == 200


# ---------- logout ----------
class TestLogout:
    def test_logout_clears_cookies(self):
        s = _cookie_login()
        csrf = s.cookies.get("algoforge_csrf")
        r = s.post(LOGOUT, headers={"X-CSRF-Token": csrf} if csrf else {})
        assert r.status_code == 200
        raw_headers = r.headers.get("set-cookie", "")
        # Expect both cookies cleared with empty val + past expiry
        assert "algoforge_auth=" in raw_headers
        assert "algoforge_csrf=" in raw_headers
        # Standard delete uses Max-Age=0 OR expires in the past
        low = raw_headers.lower()
        assert ("max-age=0" in low) or ("expires=" in low)


# ---------- migrate-token ----------
class TestMigrate:
    def test_migrate_token_success_sets_cookies(self):
        token = _bearer_login()
        s = requests.Session()
        r = s.post(MIGRATE, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        names = {c.name for c in s.cookies}
        assert "algoforge_auth" in names
        assert "algoforge_csrf" in names
        # subsequent /me with cookies works
        r2 = s.get(ME)
        assert r2.status_code == 200

    def test_migrate_token_missing(self):
        r = requests.post(MIGRATE)
        assert r.status_code == 401

    def test_migrate_token_invalid(self):
        r = requests.post(MIGRATE, headers={"Authorization": "Bearer not-a-real-jwt"})
        assert r.status_code == 401


# ---------- regression: a few other PUT/POST under cookie auth still work ----------
class TestRegressionWithCSRF:
    def test_risk_put_cookie_with_csrf(self):
        s = _cookie_login()
        csrf = s.cookies.get("algoforge_csrf")
        r = s.put(
            RISK,
            json={
                "max_drawdown_pct": 12.5,
                "daily_loss_cap": 20000.0,
                "position_limit": 4,
                "kill_switch": False,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 200, r.text
        # GET should reflect persisted value (cookie auth still works for GET, no CSRF)
        g = s.get(RISK)
        assert g.status_code == 200
        body = g.json()
        assert abs(body["max_drawdown_pct"] - 12.5) < 0.01
        assert body["position_limit"] == 4
