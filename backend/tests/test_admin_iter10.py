"""Iter 10 — Admin Console endpoints E2E (super-admin dashboard)."""
import os
import uuid
import time
import pytest
import requests

def _load_url():
    u = os.environ.get("REACT_APP_BACKEND_URL", "").strip()
    if u:
        return u.rstrip("/")
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    except FileNotFoundError:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not set")

BASE_URL = _load_url()
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "demo@algoforge.io"
ADMIN_PASS = "Demo@123"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def regular_user():
    """Create a fresh non-admin user."""
    email = f"trader_{uuid.uuid4().hex[:8]}@test.io"
    password = "Test@1234"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": password, "name": "T1"}, timeout=15)
    assert r.status_code in (200, 201), r.text
    token = r.json()["access_token"]
    user_id = r.json()["user"]["id"]
    return {"email": email, "password": password, "token": token, "id": user_id}


# ---------- Admin endpoint smoke ----------

def test_admin_health(admin_headers):
    r = requests.get(f"{API}/admin/health", headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mongo"] == "ok"
    assert data["reconciler"] == "running"
    assert data["emergent_llm_key"] in ("configured", "missing")
    assert isinstance(data["users"], int) and data["users"] >= 1
    assert "paper_orders" in data
    assert "live_brokers" in data


def test_admin_audit_list(admin_headers):
    r = requests.get(f"{API}/admin/audit", headers=admin_headers, params={"limit": 10}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "has_more" in body


def test_admin_risk_users(admin_headers):
    r = requests.get(f"{API}/admin/risk/users", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    items = r.json()["items"]
    assert isinstance(items, list)
    assert len(items) >= 1
    sample = items[0]
    for k in ("id", "email", "role", "kill_switch", "open_positions", "total_pnl", "exposure"):
        assert k in sample, f"missing {k}"


def test_admin_brokers_map(admin_headers):
    r = requests.get(f"{API}/admin/brokers/map", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "connections" in body and "by_broker" in body
    assert isinstance(body["connections"], list)
    assert isinstance(body["by_broker"], dict)


def test_admin_events_list(admin_headers):
    r = requests.get(f"{API}/admin/events", headers=admin_headers, params={"limit": 20}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert isinstance(body["items"], list)


# ---------- 403 negative ----------

@pytest.mark.parametrize("path", [
    "/admin/health",
    "/admin/audit",
    "/admin/risk/users",
    "/admin/brokers/map",
    "/admin/events",
])
def test_admin_endpoints_forbid_regular_user(regular_user, path):
    h = {"Authorization": f"Bearer {regular_user['token']}"}
    r = requests.get(f"{API}{path}", headers=h, timeout=15)
    assert r.status_code == 403, f"{path} expected 403, got {r.status_code}: {r.text[:200]}"


def test_admin_kill_forbid_regular_user(regular_user):
    h = {"Authorization": f"Bearer {regular_user['token']}", "Content-Type": "application/json"}
    r = requests.post(f"{API}/admin/risk/kill",
                      json={"user_id": regular_user["id"], "kill_switch": True, "reason": "x"},
                      headers=h, timeout=15)
    assert r.status_code == 403


# ---------- Force-kill flow + audit ----------

def test_force_kill_and_release_and_admin_trail(admin_headers, regular_user):
    uid = regular_user["id"]
    # ARM
    r = requests.post(f"{API}/admin/risk/kill",
                      json={"user_id": uid, "kill_switch": True, "reason": "iter10 test arm"},
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["kill_switch"] is True and body["user_id"] == uid

    # verify in risk/users
    r2 = requests.get(f"{API}/admin/risk/users", headers=admin_headers, timeout=15)
    row = next((u for u in r2.json()["items"] if u["id"] == uid), None)
    assert row is not None and row["kill_switch"] is True

    # verify admin event written
    time.sleep(0.5)
    ev = requests.get(f"{API}/admin/events", headers=admin_headers, params={"limit": 20}, timeout=15).json()
    matches = [e for e in ev["items"]
               if e.get("action") == "FORCE_KILL_SWITCH"
               and e.get("target_user_id") == uid
               and "iter10 test arm" in (e.get("summary") or "")]
    assert matches, f"FORCE_KILL_SWITCH event not found. recent: {ev['items'][:3]}"

    # RELEASE
    r3 = requests.post(f"{API}/admin/risk/kill",
                       json={"user_id": uid, "kill_switch": False, "reason": "iter10 test release"},
                       headers=admin_headers, timeout=15)
    assert r3.status_code == 200
    r4 = requests.get(f"{API}/admin/risk/users", headers=admin_headers, timeout=15)
    row = next((u for u in r4.json()["items"] if u["id"] == uid), None)
    assert row is not None and row["kill_switch"] is False


def test_force_kill_unknown_user_404(admin_headers):
    r = requests.post(f"{API}/admin/risk/kill",
                      json={"user_id": "non-existent-uid", "kill_switch": True, "reason": "x"},
                      headers=admin_headers, timeout=15)
    assert r.status_code == 404


# ---------- Regression smoke (core endpoints) ----------

def test_regression_dashboard(admin_headers):
    r = requests.get(f"{API}/dashboard/summary", headers=admin_headers, timeout=20)
    assert r.status_code == 200


def test_regression_audit_query(admin_headers):
    r = requests.get(f"{API}/audit/events", headers=admin_headers, params={"limit": 5}, timeout=15)
    assert r.status_code == 200


def test_regression_brokers_list(admin_headers):
    r = requests.get(f"{API}/brokers", headers=admin_headers, timeout=15)
    assert r.status_code == 200


def test_regression_trap_scan(admin_headers):
    r = requests.get(f"{API}/trap/scan", headers=admin_headers, params={"symbol": "NIFTY"}, timeout=30)
    assert r.status_code in (200, 201)
