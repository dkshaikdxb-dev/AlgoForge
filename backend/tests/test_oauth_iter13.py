"""Iter 13 — Broker OAuth wizard endpoints (URLs, start, callback, postback)."""
import os
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://quant-hybrid-trade.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

DEMO_EMAIL = "demo@algoforge.io"
DEMO_PASSWORD = "Demo@123"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=20)
    if r.status_code != 200:
        # try register then login
        requests.post(f"{API}/auth/register", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD, "name": "Demo"}, timeout=20)
        r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── URL surface ──────────────────────────────────────────────────────────
class TestOauthUrls:
    def test_zerodha_urls(self, auth_headers):
        r = requests.get(f"{API}/brokers/zerodha/oauth/urls", headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["oauth_supported"] is True
        assert data["redirect_url"].startswith("https://")
        assert data["redirect_url"].endswith("/api/brokers/zerodha/oauth/callback")
        assert "/api/brokers/zerodha/postback" in data["postback_url"]

    def test_upstox_supported(self, auth_headers):
        r = requests.get(f"{API}/brokers/upstox/oauth/urls", headers=auth_headers, timeout=20)
        assert r.status_code == 200
        assert r.json()["oauth_supported"] is True

    @pytest.mark.parametrize("name", ["dhan", "icici", "rmoney"])
    def test_others_not_supported(self, auth_headers, name):
        r = requests.get(f"{API}/brokers/{name}/oauth/urls", headers=auth_headers, timeout=20)
        assert r.status_code == 200, f"{name} -> {r.status_code} {r.text}"
        assert r.json()["oauth_supported"] is False

    def test_urls_require_auth(self):
        r = requests.get(f"{API}/brokers/zerodha/oauth/urls", timeout=15)
        assert r.status_code in (401, 403)


# ── Start ────────────────────────────────────────────────────────────────
class TestOauthStart:
    def test_zerodha_start(self, auth_headers):
        r = requests.post(f"{API}/brokers/zerodha/oauth/start", headers=auth_headers,
                          json={"api_key": "TEST_KEY_Z", "api_secret": "TEST_SECRET_Z"}, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "state" in d and len(d["state"]) > 10
        assert "kite.zerodha.com/connect/login" in d["login_url"]
        assert "api_key=TEST_KEY_Z" in d["login_url"]
        assert d["expires_in"] == 600
        assert d["redirect_url"].endswith("/api/brokers/zerodha/oauth/callback")

    def test_upstox_start(self, auth_headers):
        r = requests.post(f"{API}/brokers/upstox/oauth/start", headers=auth_headers,
                          json={"api_key": "TEST_KEY_U", "api_secret": "TEST_SECRET_U"}, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "api.upstox.com/v2/login/authorization/dialog" in d["login_url"]
        assert "client_id=TEST_KEY_U" in d["login_url"]
        assert "response_type=code" in d["login_url"]
        assert "state=" in d["login_url"]

    def test_dhan_start_rejected(self, auth_headers):
        r = requests.post(f"{API}/brokers/dhan/oauth/start", headers=auth_headers,
                          json={"api_key": "x", "api_secret": "y"}, timeout=20)
        assert r.status_code == 400
        assert "does not support OAuth wizard" in r.text

    def test_start_requires_creds(self, auth_headers):
        r = requests.post(f"{API}/brokers/zerodha/oauth/start", headers=auth_headers,
                          json={"api_key": "", "api_secret": ""}, timeout=20)
        assert r.status_code == 400

    def test_start_requires_auth(self):
        r = requests.post(f"{API}/brokers/zerodha/oauth/start",
                          json={"api_key": "a", "api_secret": "b"}, timeout=15)
        assert r.status_code in (401, 403)


# ── Callback (returns HTML; tested without authentication) ───────────────
class TestOauthCallback:
    def test_zerodha_callback_bad_state(self):
        r = requests.get(f"{API}/brokers/zerodha/oauth/callback?request_token=fake&state=invalid",
                         timeout=20, allow_redirects=False)
        # We expect 400/500 but always HTML — server should not crash
        assert r.status_code in (400, 500), r.status_code
        assert "text/html" in r.headers.get("content-type", "").lower()
        assert "<html" in r.text.lower()

    def test_upstox_callback_bad_state(self):
        r = requests.get(f"{API}/brokers/upstox/oauth/callback?code=fake&state=invalid",
                         timeout=20, allow_redirects=False)
        assert r.status_code in (400, 500)
        assert "text/html" in r.headers.get("content-type", "").lower()

    def test_unsupported_broker_callback(self):
        r = requests.get(f"{API}/brokers/dhan/oauth/callback", timeout=15)
        assert r.status_code == 400
        assert "text/html" in r.headers.get("content-type", "").lower()


# ── Postback ─────────────────────────────────────────────────────────────
class TestPostback:
    def test_postback_no_token(self):
        r = requests.post(f"{API}/brokers/zerodha/postback", json={"order_id": "X"}, timeout=15)
        assert r.status_code == 403

    def test_postback_invalid_token(self):
        r = requests.post(f"{API}/brokers/zerodha/postback?token=garbage_token", json={"order_id": "X"}, timeout=15)
        assert r.status_code == 403

    def test_unknown_broker_postback(self):
        r = requests.post(f"{API}/brokers/unknown123/postback?token=x", json={}, timeout=15)
        assert r.status_code == 404


# ── TTL index on oauth_states ────────────────────────────────────────────
def test_oauth_states_ttl_index():
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    try:
        db = client[db_name]
        # Trigger lazy index creation via a start call (need auth)
        indexes = db.oauth_states.index_information()
        ttl = [v for k, v in indexes.items() if k == "created_at_ttl"]
        assert ttl, f"created_at_ttl missing in {list(indexes.keys())}"
        assert ttl[0].get("expireAfterSeconds") == 600
    finally:
        client.close()


# ── Cleanup TEST_ data ───────────────────────────────────────────────────
@pytest.fixture(scope="session", autouse=True)
def _cleanup():
    yield
    try:
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "test_database")
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=3000)
        client[db_name].oauth_states.delete_many({"api_key": {"$regex": "^TEST_"}})
        client.close()
    except Exception:
        pass
