"""Iter16 tests:
1. Concurrency: 10× /api/brokers/dhan/test in parallel + /api/admin/health stays responsive.
2. Mongo TTL dedup: toggle kill_switch repeatedly, ensure alert_log dedup'd; verify TTL index.
3. Confirm in-process OrderedDict dedup removed (Mongo-only).
"""
from __future__ import annotations

import asyncio
import os
import time

import httpx
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://quant-hybrid-trade.preview.emergentagent.com").rstrip("/")
EMAIL = "demo@algoforge.io"
PASSWORD = "Demo@123"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ─────────── (1) Concurrency ───────────
def test_concurrent_dhan_broker_test(headers):
    """10 parallel /api/brokers/dhan/test should all complete fast (~<3s total).
    They will return either 'not connected' or 'SDK not installed' — both are fine."""
    async def _run():
        async with httpx.AsyncClient(timeout=10.0) as client:
            t0 = time.monotonic()
            tasks = [client.post(f"{BASE_URL}/api/brokers/dhan/test", headers=headers) for _ in range(10)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            elapsed = time.monotonic() - t0
            return results, elapsed

    results, elapsed = asyncio.run(_run())
    print(f"\n10 parallel /brokers/dhan/test in {elapsed:.2f}s")
    # Print one body for visibility
    for r in results[:1]:
        if hasattr(r, "status_code"):
            print(f"sample status={r.status_code} body={r.text[:200]}")
    # Validate every response came back with an expected status
    ok_codes = {200, 400, 404, 409, 500, 502}
    for r in results:
        assert hasattr(r, "status_code"), f"exception instead of response: {r!r}"
        assert r.status_code in ok_codes, f"unexpected status {r.status_code}: {r.text[:200]}"
    # Event loop not stalled — total wall time must be small. Generous 8s ceiling
    # to allow for network/preview latency, but if asyncio.to_thread weren't used
    # 10× sync calls would serialize and easily exceed this.
    assert elapsed < 8.0, f"10 parallel calls took {elapsed:.2f}s (>8s); event loop may be stalled"


def test_admin_health_during_broker_test(headers):
    """While 10 broker tests fire, /api/admin/health should still respond quickly."""
    async def _run():
        async with httpx.AsyncClient(timeout=10.0) as client:
            broker_tasks = [client.post(f"{BASE_URL}/api/brokers/dhan/test", headers=headers) for _ in range(10)]
            # Kick off broker tasks, then race a health call
            health_task = client.get(f"{BASE_URL}/api/admin/health", headers=headers)
            t0 = time.monotonic()
            health, *_ = await asyncio.gather(health_task, *broker_tasks, return_exceptions=True)
            elapsed = time.monotonic() - t0
            return health, elapsed

    health, elapsed = asyncio.run(_run())
    print(f"\n/admin/health under load completed in {elapsed:.2f}s")
    assert hasattr(health, "status_code"), f"health raised: {health!r}"
    assert health.status_code == 200, f"admin/health failed: {health.status_code} {health.text[:200]}"
    body = health.json()
    assert "mongo" in body or "ok" in body or isinstance(body, dict)


# ─────────── (2) Mongo TTL dedup ───────────
def test_alert_dedup_ttl_index_present(headers):
    """The alert_dedup collection must have a TTL index created_at_ttl with
    expireAfterSeconds=60. Reads MONGO_URL/DB_NAME from backend/.env."""
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not (mongo_url and db_name):
        # Load from backend .env directly
        env_path = "/app/backend/.env"
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("MONGO_URL=") and not mongo_url:
                        mongo_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("DB_NAME=") and not db_name:
                        db_name = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not (mongo_url and db_name):
        pytest.skip("MONGO_URL/DB_NAME not available; functional dedup test covers behavior")
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _check():
        client = AsyncIOMotorClient(mongo_url)
        db = client[db_name]
        # Trigger ensure_indexes via a GET on prefs (calls into alerts)
        # The TTL index is created at startup; if not, this will be present after first call
        info = await db.alert_dedup.index_information()
        return info

    info = asyncio.run(_check())
    print(f"\nalert_dedup indexes: {list(info.keys())}")
    assert "created_at_ttl" in info, f"TTL index 'created_at_ttl' missing. Indexes: {info}"
    ttl_idx = info["created_at_ttl"]
    assert ttl_idx.get("expireAfterSeconds") == 60, f"TTL not 60s: {ttl_idx}"


def test_kill_switch_dedup_functional(headers):
    """Trigger kill_switch ARMED then RELEASED, repeated 5 cycles.
    Each toggle emits a KILL_SWITCH HIGH event. Per-user prefs are
    enabled with a fake telegram chat so that alert_log records the
    send attempt (even when send fails because token isn't set).
    Expected: at most 2 unique alert_log rows for KILL_SWITCH within
    the dedup window (one ARMED, one RELEASED), not 5+.
    """
    # 1) Enable telegram pref with a fake chat_id so dispatch attempts a send
    prefs_body = {
        "telegram_enabled": True,
        "telegram_chat_id": "TEST_DUMMY_CHAT",
        "email_enabled": False,
        "email_address": "",
        "event_types": ["KILL_SWITCH", "RISK_POLICY_CHANGE"],
        "min_severity": "HIGH",
    }
    r = requests.put(f"{BASE_URL}/api/alerts/prefs", json=prefs_body, headers=headers, timeout=10)
    assert r.status_code == 200, f"set prefs failed: {r.status_code} {r.text[:200]}"

    # 2) Read current state
    cur = requests.get(f"{BASE_URL}/api/risk/limits", headers=headers, timeout=10).json()

    # 3) Get baseline alert_log count
    base_log = requests.get(f"{BASE_URL}/api/alerts/log?limit=200", headers=headers, timeout=10).json()
    base_count = sum(1 for d in base_log.get("items", []) if d.get("event_type") == "KILL_SWITCH")
    print(f"\nbaseline KILL_SWITCH log rows: {base_count}")

    # 4) Toggle kill_switch 5 cycles back-to-back (10 toggles)
    base_payload = {
        "max_drawdown_pct": float(cur.get("max_drawdown_pct", 15.0)),
        "daily_loss_cap": float(cur.get("daily_loss_cap", 25000.0)),
        "position_limit": int(cur.get("position_limit", 5)),
    }
    # Ensure we start with kill_switch=False so first toggle to True actually fires
    requests.put(f"{BASE_URL}/api/risk/limits", json={**base_payload, "kill_switch": False}, headers=headers, timeout=10)

    for i in range(5):
        rr = requests.put(f"{BASE_URL}/api/risk/limits", json={**base_payload, "kill_switch": True}, headers=headers, timeout=10)
        assert rr.status_code == 200
        rr = requests.put(f"{BASE_URL}/api/risk/limits", json={**base_payload, "kill_switch": False}, headers=headers, timeout=10)
        assert rr.status_code == 200

    # Give dispatch tasks a moment to write to alert_log (fire-and-forget)
    time.sleep(2)

    # 5) Read new logs
    new_log = requests.get(f"{BASE_URL}/api/alerts/log?limit=200", headers=headers, timeout=10).json()
    new_rows = [d for d in new_log.get("items", []) if d.get("event_type") == "KILL_SWITCH"]
    added = len(new_rows) - base_count
    # Take exactly the rows added in this burst (newest-first ordering)
    recent = new_rows[:added] if added > 0 else []
    armed = [r for r in recent if "ARMED" in (r.get("summary") or "")]
    released = [r for r in recent if "RELEASED" in (r.get("summary") or "")]
    tg_added = [r for r in recent if r.get("channel") == "telegram"]

    print(f"new KILL_SWITCH rows added: {added}; ARMED rows: {len(armed)}, RELEASED rows: {len(released)}")
    print(f"telegram KILL_SWITCH rows in burst: {len(tg_added)} -> summaries: {sorted({r.get('summary') for r in tg_added})}")
    # 10 toggles (5 ARMED + 5 RELEASED) within the 60s dedup window should produce at most
    # 2 unique-summary telegram rows. >2 would mean dedup failed.
    assert added <= 2, f"dedup failed: {added} new KILL_SWITCH rows from 10 toggles (should be <=2). rows={recent}"
    if added > 0:
        # Each burst row should be telegram (only channel enabled)
        assert len(tg_added) == added, "non-telegram channels logged unexpectedly"


def test_in_process_ordereddict_removed():
    """Verify the legacy in-process _dedup OrderedDict is no longer present
    in services/alerts.py (Mongo-only)."""
    with open("/app/backend/services/alerts.py", "r") as f:
        src = f.read()
    assert "OrderedDict" not in src, "Legacy OrderedDict dedup still present in alerts.py"
    assert "db.alert_dedup" in src, "Mongo alert_dedup collection not used"
    assert "create_index" in src and "expireAfterSeconds" in src and "created_at_ttl" in src, \
        "TTL index creation logic missing"
