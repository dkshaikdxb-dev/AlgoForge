"""Iter 11 — P1 Alerts: per-user prefs + transports + dispatch + dedup + admin/health."""
import os
import time
import uuid
import pytest
import requests


def _load_url():
    u = os.environ.get("REACT_APP_BACKEND_URL", "").strip()
    if u:
        return u.rstrip("/")
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE = _load_url()
API = f"{BASE}/api"

ADMIN_EMAIL = "demo@algoforge.io"
ADMIN_PASS = "Demo@123"

DEFAULT_EVT = [
    "KILL_SWITCH",
    "BROKER_DISCONNECT",
    "BASKET_ROLLBACK",
    "RISK_POLICY_CHANGE",
    "OVERRIDE",
]


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def fresh_user():
    email = f"alerts_{uuid.uuid4().hex[:8]}@test.io"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": "Test@1234", "name": "AlertsT"}, timeout=15)
    assert r.status_code in (200, 201), r.text
    return {"email": email, "headers": {"Authorization": f"Bearer {r.json()['access_token']}", "Content-Type": "application/json"}}


# ---------- GET /api/alerts/prefs defaults ----------

def test_get_prefs_defaults_fresh_user(fresh_user):
    r = requests.get(f"{API}/alerts/prefs", headers=fresh_user["headers"], timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "prefs" in body and "transports" in body and "available_event_types" in body
    p = body["prefs"]
    assert p["telegram_enabled"] is False
    assert p["email_enabled"] is False
    assert p["min_severity"] == "HIGH"
    assert sorted(p["event_types"]) == sorted(DEFAULT_EVT)
    t = body["transports"]
    assert "telegram" in t and "email" in t
    assert t["telegram"] == "missing TELEGRAM_BOT_TOKEN"
    assert t["email"] == "missing SMTP_* env vars"
    assert sorted(body["available_event_types"]) == sorted(DEFAULT_EVT)


# ---------- PUT round-trip ----------

def test_put_prefs_round_trip(fresh_user):
    payload = {
        "telegram_enabled": True,
        "telegram_chat_id": "1234567890",
        "email_enabled": True,
        "email_address": "tester@example.com",
        "event_types": ["KILL_SWITCH", "OVERRIDE"],
        "min_severity": "HIGH",
    }
    r = requests.put(f"{API}/alerts/prefs", json=payload, headers=fresh_user["headers"], timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # GET round-trip
    r2 = requests.get(f"{API}/alerts/prefs", headers=fresh_user["headers"], timeout=15)
    assert r2.status_code == 200
    p = r2.json()["prefs"]
    assert p["telegram_enabled"] is True
    assert p["telegram_chat_id"] == "1234567890"
    assert p["email_enabled"] is True
    assert p["email_address"] == "tester@example.com"
    assert sorted(p["event_types"]) == sorted(["KILL_SWITCH", "OVERRIDE"])


# ---------- POST /api/alerts/test ----------

def test_post_test_telegram_400_no_token(admin_headers):
    # ensure chat_id set so error is the token-missing one, not chat_id-missing
    requests.put(f"{API}/alerts/prefs",
                 json={"telegram_enabled": True, "telegram_chat_id": "999", "email_enabled": False,
                       "email_address": "", "event_types": DEFAULT_EVT, "min_severity": "HIGH"},
                 headers=admin_headers, timeout=15)
    r = requests.post(f"{API}/alerts/test", json={"channel": "telegram"}, headers=admin_headers, timeout=15)
    assert r.status_code == 400, r.text
    assert "TELEGRAM_BOT_TOKEN" in (r.json().get("detail") or "")


def test_post_test_email_400_no_smtp(admin_headers):
    requests.put(f"{API}/alerts/prefs",
                 json={"telegram_enabled": False, "telegram_chat_id": "", "email_enabled": True,
                       "email_address": "x@test.io", "event_types": DEFAULT_EVT, "min_severity": "HIGH"},
                 headers=admin_headers, timeout=15)
    r = requests.post(f"{API}/alerts/test", json={"channel": "email"}, headers=admin_headers, timeout=15)
    assert r.status_code == 400, r.text
    assert "SMTP" in (r.json().get("detail") or "")


def test_post_test_invalid_channel(admin_headers):
    r = requests.post(f"{API}/alerts/test", json={"channel": "invalid"}, headers=admin_headers, timeout=15)
    assert r.status_code == 400
    assert "channel must be" in (r.json().get("detail") or "")


# ---------- Auth gating ----------

@pytest.mark.parametrize("method,path,body", [
    ("GET", "/alerts/prefs", None),
    ("PUT", "/alerts/prefs", {"telegram_enabled": False}),
    ("POST", "/alerts/test", {"channel": "telegram"}),
    ("GET", "/alerts/log", None),
])
def test_alerts_require_auth(method, path, body):
    r = requests.request(method, f"{API}{path}", json=body, timeout=15)
    assert r.status_code in (401, 403), f"{method} {path} expected 401/403 got {r.status_code}"


# ---------- Audit auto-dispatch on HIGH severity ----------

def test_kill_switch_toggle_emits_alert_log(admin_headers):
    # Configure both channels with destinations + include KILL_SWITCH (default)
    requests.put(f"{API}/alerts/prefs", json={
        "telegram_enabled": True, "telegram_chat_id": "999",
        "email_enabled": True, "email_address": "ks@test.io",
        "event_types": DEFAULT_EVT, "min_severity": "HIGH",
    }, headers=admin_headers, timeout=15)

    # Iter16 introduced persistent Mongo TTL dedup (60s). Clear any prior dedup
    # keys for this user so the toggle is guaranteed to dispatch fresh rows.
    try:
        import os as _os
        from pymongo import MongoClient as _MC
        _mongo = _os.environ.get("MONGO_URL")
        _dbname = _os.environ.get("DB_NAME")
        if not (_mongo and _dbname):
            with open("/app/backend/.env") as _f:
                for _ln in _f:
                    _ln = _ln.strip()
                    if _ln.startswith("MONGO_URL=") and not _mongo:
                        _mongo = _ln.split("=", 1)[1].strip().strip('"').strip("'")
                    elif _ln.startswith("DB_NAME=") and not _dbname:
                        _dbname = _ln.split("=", 1)[1].strip().strip('"').strip("'")
        if _mongo and _dbname:
            _MC(_mongo)[_dbname].alert_dedup.delete_many({})
    except Exception as _e:
        print(f"warn: could not clear alert_dedup: {_e}")

    # Snapshot log size
    before = requests.get(f"{API}/alerts/log", headers=admin_headers, params={"limit": 100}, timeout=15).json()["items"]
    before_n = len(before)

    # Use uuid in summary to avoid dedup with previous runs
    # Toggle kill switch via /api/risk/limits — get current then flip
    cur = requests.get(f"{API}/risk/limits", headers=admin_headers, timeout=15).json()
    new_ks = not bool(cur.get("kill_switch"))
    r = requests.put(f"{API}/risk/limits", json={
        "max_drawdown_pct": cur.get("max_drawdown_pct", 5),
        "daily_loss_cap": cur.get("daily_loss_cap", 5000),
        "position_limit": cur.get("position_limit", 5),
        "kill_switch": new_ks,
    }, headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text

    # Wait for async dispatch
    time.sleep(2.5)
    after = requests.get(f"{API}/alerts/log", headers=admin_headers, params={"limit": 100}, timeout=15).json()["items"]
    new_rows = after[: len(after) - before_n] if len(after) > before_n else []
    # We expect at least 2 fresh rows (telegram + email) with event_type KILL_SWITCH and ok=false
    ks_rows = [r for r in new_rows if r.get("event_type") == "KILL_SWITCH"]
    assert len(ks_rows) >= 2, f"Expected >=2 KILL_SWITCH log rows after toggle, got {len(ks_rows)}: {new_rows}"
    channels = {r["channel"] for r in ks_rows}
    assert "telegram" in channels and "email" in channels
    for row in ks_rows:
        assert row["ok"] is False
        if row["channel"] == "telegram":
            assert "TELEGRAM_BOT_TOKEN" in (row.get("error") or "")
        if row["channel"] == "email":
            assert "SMTP" in (row.get("error") or "")

    # Reset kill switch back for hygiene
    requests.put(f"{API}/risk/limits", json={
        "max_drawdown_pct": cur.get("max_drawdown_pct", 5),
        "daily_loss_cap": cur.get("daily_loss_cap", 5000),
        "position_limit": cur.get("position_limit", 5),
        "kill_switch": bool(cur.get("kill_switch")),
    }, headers=admin_headers, timeout=15)


def test_dedup_60s_window(admin_headers):
    """Toggle kill_switch rapidly 3x — only 1 row per channel within 60s for the same summary."""
    requests.put(f"{API}/alerts/prefs", json={
        "telegram_enabled": True, "telegram_chat_id": "999",
        "email_enabled": True, "email_address": "ks@test.io",
        "event_types": DEFAULT_EVT, "min_severity": "HIGH",
    }, headers=admin_headers, timeout=15)

    cur = requests.get(f"{API}/risk/limits", headers=admin_headers, timeout=15).json()
    base = {
        "max_drawdown_pct": cur.get("max_drawdown_pct", 5),
        "daily_loss_cap": cur.get("daily_loss_cap", 5000),
        "position_limit": cur.get("position_limit", 5),
    }
    # snapshot
    before = requests.get(f"{API}/alerts/log", headers=admin_headers, params={"limit": 200}, timeout=15).json()["items"]
    before_n = len(before)

    # Toggle ARM 3 times: ON -> OFF -> ON -> OFF -> ON (3 ARM events)
    for _ in range(3):
        requests.put(f"{API}/risk/limits", json={**base, "kill_switch": False}, headers=admin_headers, timeout=15)
        requests.put(f"{API}/risk/limits", json={**base, "kill_switch": True}, headers=admin_headers, timeout=15)
    time.sleep(2.5)

    after = requests.get(f"{API}/alerts/log", headers=admin_headers, params={"limit": 200}, timeout=15).json()["items"]
    fresh = after[: len(after) - before_n] if len(after) > before_n else []
    # Group by (channel, summary)
    armed_rows = [r for r in fresh if r.get("event_type") == "KILL_SWITCH" and "ARMED" in (r.get("summary") or "").upper()]
    # Per-channel ARM count
    from collections import Counter
    by_ch = Counter(r["channel"] for r in armed_rows)
    # Dedup window allows only 1 ARM per channel within 60s
    for ch, cnt in by_ch.items():
        assert cnt == 1, f"Dedup failed: channel {ch} got {cnt} ARM rows, expected 1. rows={armed_rows}"

    # Reset
    requests.put(f"{API}/risk/limits", json={**base, "kill_switch": bool(cur.get("kill_switch"))},
                 headers=admin_headers, timeout=15)


# ---------- Admin health alerts block ----------

def test_admin_health_contains_alerts(admin_headers):
    r = requests.get(f"{API}/admin/health", headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "alerts" in data, f"missing 'alerts' in admin/health: {data}"
    a = data["alerts"]
    for k in ("telegram", "email", "global_telegram", "global_email"):
        assert k in a, f"alerts.{k} missing"
    assert isinstance(a["global_telegram"], bool)
    assert isinstance(a["global_email"], bool)
