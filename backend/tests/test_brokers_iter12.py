"""Iter 12 broker adapter migration tests (Dhan / ICICI / Rmoney → BrokerAdapter ABC).

Covers:
- GET /api/brokers shape parity across all 5 adapters.
- connect → test → disconnect cycle for dhan, icici, rmoney.
- Audit events recorded (BROKER_TEST severity=WARN, BROKER_DISCONNECT severity=WARN).
- Reconciler health is 'running'.
- Regression: zerodha / upstox still work the same way.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import requests


def _load_backend_url() -> str:
    url = os.environ.get("REACT_APP_BACKEND_URL", "")
    if not url:
        env_path = Path("/app/frontend/.env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("REACT_APP_BACKEND_URL="):
                    url = line.split("=", 1)[1].strip()
                    break
    assert url, "REACT_APP_BACKEND_URL not configured"
    return url.rstrip("/")


BASE_URL = _load_backend_url()
API = f"{BASE_URL}/api"

CRED = {"email": "demo@algoforge.io", "password": "Demo@123"}

CAPS_KEYS = {
    "supports_modify",
    "supports_amo",
    "supports_iceberg",
    "supports_basket_native",
    "supports_postback_ws",
    "supports_options",
    "supports_options_multi_leg",
    "max_qty_per_order",
    "min_qty_per_order",
}

FAKE_CREDS = {
    "zerodha": {"api_key": "fk", "api_secret": "fs", "access_token": "ft"},
    "upstox": {"api_key": "fk", "api_secret": "fs", "access_token": "ft"},
    "dhan": {"client_id": "fk", "access_token": "ft"},
    "icici": {"api_key": "fk", "api_secret": "fs", "session_token": "fst"},
    "rmoney": {"user_id": "fu", "api_key": "fk", "password": "fp"},
}


@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(f"{API}/auth/login", json=CRED, timeout=15)
    if r.status_code != 200:
        # try register
        requests.post(f"{API}/auth/register", json={**CRED, "name": "Demo"}, timeout=15)
        r = requests.post(f"{API}/auth/login", json=CRED, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in {data}"
    return tok


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---- 1. GET /api/brokers shape parity --------------------------------------

def test_brokers_list_shape(auth):
    r = requests.get(f"{API}/brokers", headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    items = r.json().get("items", [])
    names = {it["name"] for it in items}
    assert {"zerodha", "upstox", "dhan", "icici", "rmoney"}.issubset(names), names
    for it in items:
        assert "capabilities" in it, it
        caps = it["capabilities"]
        assert set(caps.keys()) == CAPS_KEYS, f"{it['name']} caps={caps}"
        for k, v in caps.items():
            if k in ("max_qty_per_order", "min_qty_per_order"):
                assert v is None or isinstance(v, int), f"{it['name']}.{k}={v!r}"
            else:
                assert isinstance(v, bool), f"{it['name']}.{k}={v!r} not bool"


# ---- 2/3/4. connect + test flows -------------------------------------------

@pytest.mark.parametrize(
    "broker,expected_substrings",
    [
        ("dhan", ["dhanhq SDK not installed"]),
        ("icici", ["breeze-connect not installed", "ICICI Direct keys missing"]),
        ("rmoney", ["Rmoney returned", "Rmoney network error"]),
    ],
)
def test_connect_then_test_graceful_error(auth, broker, expected_substrings):
    # connect
    r = requests.post(
        f"{API}/brokers/{broker}/connect",
        headers=auth,
        json={"credentials": FAKE_CREDS[broker]},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "saved", body

    # test → expected graceful error
    r = requests.post(f"{API}/brokers/{broker}/test", headers=auth, timeout=20)
    assert r.status_code == 200, f"{broker} returned {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("status") == "error", body
    msg = body.get("message") or ""
    assert any(sub in msg for sub in expected_substrings), f"{broker} msg={msg!r}"


# ---- 5. Audit events present with severity=WARN ----------------------------

def test_audit_events_warn_for_broker_tests(auth):
    # Give backend a moment to flush audit writes
    time.sleep(0.5)
    r = requests.get(f"{API}/audit/events?limit=100", headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    events = r.json().get("items") or r.json().get("events") or r.json()
    assert isinstance(events, list), events
    test_events = [e for e in events if e.get("event_type") == "BROKER_TEST"]
    assert test_events, "no BROKER_TEST audit events found"
    for e in test_events[:5]:
        assert e.get("severity") == "WARN", e


# ---- 6. Regression: zerodha + upstox still respond (connect + test) --------

@pytest.mark.parametrize("broker", ["zerodha", "upstox"])
def test_existing_brokers_no_regression(auth, broker):
    r = requests.post(
        f"{API}/brokers/{broker}/connect",
        headers=auth,
        json={"credentials": FAKE_CREDS[broker]},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "saved"

    r = requests.post(f"{API}/brokers/{broker}/test", headers=auth, timeout=20)
    assert r.status_code == 200, r.text
    # With fake creds expect status=error but not a 500.
    assert r.json().get("status") in {"error", "live"}, r.json()


# ---- 7. Reconciler health --------------------------------------------------

def test_admin_health_reconciler_running(auth):
    r = requests.get(f"{API}/admin/health", headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    rec = data.get("reconciler")
    assert rec == "running", f"reconciler={rec!r} full={data}"


# ---- 8. DELETE broker writes BROKER_DISCONNECT WARN audit event -----------

def test_disconnect_writes_audit_event(auth):
    # ensure dhan is connected
    requests.post(
        f"{API}/brokers/dhan/connect",
        headers=auth,
        json={"credentials": FAKE_CREDS["dhan"]},
        timeout=15,
    )
    r = requests.delete(f"{API}/brokers/dhan", headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("deleted", 0) >= 1, r.json()

    time.sleep(0.5)
    r = requests.get(f"{API}/audit/events?limit=50", headers=auth, timeout=15)
    events = r.json().get("items") or r.json().get("events") or r.json()
    disc = [e for e in events if e.get("event_type") == "BROKER_DISCONNECT"]
    assert disc, "BROKER_DISCONNECT event not found"
    assert disc[0].get("severity") == "WARN", disc[0]


# ---- 9. Cleanup: leave broker_connections clean ----------------------------

def test_cleanup_all_test_connections(auth):
    for b in ["zerodha", "upstox", "dhan", "icici", "rmoney"]:
        requests.delete(f"{API}/brokers/{b}", headers=auth, timeout=15)
    r = requests.get(f"{API}/brokers", headers=auth, timeout=15)
    items = r.json().get("items", [])
    for it in items:
        assert it.get("connected") is False, f"{it['name']} still connected"
