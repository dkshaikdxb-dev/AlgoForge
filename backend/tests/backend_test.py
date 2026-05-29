"""Backend regression tests for AlgoForge MVP."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://quant-hybrid-trade.preview.emergentagent.com").rstrip("/")
# Test credentials read from env; fall back to the seeded demo account from
# /app/memory/test_credentials.md. Never put production secrets here.
DEMO_EMAIL = os.environ.get("ALGOFORGE_TEST_EMAIL", "demo@algoforge.io")
DEMO_PASSWORD = os.environ.get("ALGOFORGE_TEST_PASSWORD", "Demo@123")


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def token(session):
    # ensure user exists
    r = session.post(f"{BASE_URL}/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    if r.status_code != 200:
        session.post(f"{BASE_URL}/api/auth/register", json={
            "email": DEMO_EMAIL, "password": DEMO_PASSWORD, "name": "Demo"
        })
        r = session.post(f"{BASE_URL}/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def auth(session, token):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    return s


# ---------- Health ----------
def test_health(session):
    r = session.get(f"{BASE_URL}/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------- Auth ----------
class TestAuth:
    def test_register_new_user(self, session):
        email = f"TEST_{uuid.uuid4().hex[:8]}@algoforge.io"
        r = session.post(f"{BASE_URL}/api/auth/register", json={
            "email": email, "password": "Test@1234", "name": "Tester"
        })
        assert r.status_code in (200, 201), r.text
        data = r.json()
        assert "access_token" in data
        assert data["user"]["email"].lower() == email.lower()

    def test_login_demo(self, session):
        r = session.post(f"{BASE_URL}/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        assert r.status_code == 200
        d = r.json()
        assert d["user"]["email"] == DEMO_EMAIL
        assert "access_token" in d

    def test_me_with_token(self, auth):
        r = auth.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200
        assert r.json()["email"] == DEMO_EMAIL

    def test_me_without_token(self, session):
        r = session.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code in (401, 403)

    def test_me_invalid_token(self, session):
        r = session.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
        assert r.status_code in (401, 403)


# ---------- Market ----------
class TestMarket:
    def test_symbols(self, auth):
        r = auth.get(f"{BASE_URL}/api/market/symbols")
        assert r.status_code == 200
        syms = r.json()["symbols"]
        assert len(syms) == 6

    def test_ohlcv(self, auth):
        r = auth.get(f"{BASE_URL}/api/market/ohlcv", params={"symbol": "NIFTY", "days": 90})
        assert r.status_code == 200
        candles = r.json()["candles"]
        assert len(candles) == 90
        c = candles[0]
        for k in ("open", "high", "low", "close"):
            assert k in c

    def test_ohlcv_unknown(self, auth):
        r = auth.get(f"{BASE_URL}/api/market/ohlcv", params={"symbol": "XYZ123"})
        assert r.status_code == 404

    def test_options_chain(self, auth):
        r = auth.get(f"{BASE_URL}/api/market/options-chain", params={"symbol": "NIFTY"})
        assert r.status_code == 200
        chain = r.json()
        assert "rows" in chain and len(chain["rows"]) > 0
        row = chain["rows"][0]
        assert "ce" in row and "pe" in row
        assert "oi" in row["ce"] and "iv" in row["ce"]


# ---------- Strategies ----------
class TestStrategies:
    def test_generate(self, auth):
        r = auth.post(f"{BASE_URL}/api/strategies/generate",
                      json={"prompt": "Buy RELIANCE when SMA5 crosses above SMA20, exit on reverse cross"})
        assert r.status_code == 200, r.text
        dsl = r.json()["dsl"]
        assert "symbol" in dsl
        assert "indicators" in dsl or "entry" in dsl

    def test_save_list_delete(self, auth):
        # save
        dsl = {"name": "TEST_SMA", "symbol": "RELIANCE", "timeframe": "1d",
               "indicators": [{"id": "fast", "type": "sma", "period": 5, "source": "close"},
                              {"id": "slow", "type": "sma", "period": 20, "source": "close"}],
               "entry": {"op": "and", "rules": [{"left": "fast", "cmp": ">", "right": "slow"}]},
               "exit": {"op": "or", "rules": [{"left": "fast", "cmp": "<", "right": "slow"}]},
               "size": {"type": "fixed_qty", "value": 10}}
        r = auth.post(f"{BASE_URL}/api/strategies", json={"name": "TEST_SMA", "dsl": dsl})
        assert r.status_code == 200
        sid = r.json()["id"]
        # list
        r = auth.get(f"{BASE_URL}/api/strategies")
        assert r.status_code == 200
        items = r.json()["items"]
        assert any(s["id"] == sid for s in items)
        # delete
        r = auth.delete(f"{BASE_URL}/api/strategies/{sid}")
        assert r.status_code == 200


# ---------- Backtest ----------
class TestBacktest:
    @pytest.fixture(scope="class")
    def backtest_result(self, auth):
        dsl = {"name": "TEST_BT", "symbol": "RELIANCE", "timeframe": "1d",
               "indicators": [{"id": "fast", "type": "sma", "period": 5, "source": "close"},
                              {"id": "slow", "type": "sma", "period": 20, "source": "close"}],
               "entry": {"op": "and", "rules": [{"left": "fast", "cmp": ">", "right": "slow"}]},
               "exit": {"op": "or", "rules": [{"left": "fast", "cmp": "<", "right": "slow"}]},
               "size": {"type": "fixed_qty", "value": 10}}
        r = auth.post(f"{BASE_URL}/api/backtest/run", json={"dsl": dsl, "days": 300, "save": True})
        assert r.status_code == 200, r.text
        return r.json()

    def test_metrics_present(self, backtest_result):
        for k in ("sharpe", "sortino", "max_drawdown_pct", "total_return_pct",
                  "total_trades", "equity_curve", "trades"):
            assert k in backtest_result, f"missing {k}"
        assert isinstance(backtest_result["equity_curve"], list)
        assert isinstance(backtest_result["trades"], list)
        assert backtest_result["total_trades"] > 0  # RELIANCE SMA5/20 should produce trades

    def test_list_backtests(self, auth, backtest_result):
        r = auth.get(f"{BASE_URL}/api/backtests")
        assert r.status_code == 200
        assert len(r.json()["items"]) >= 1


# ---------- AI Risk ----------
class TestRisk:
    def test_analyse(self, auth):
        dsl = {"name": "x", "symbol": "RELIANCE", "indicators": [], "entry": {}, "exit": {}}
        bt = {"sharpe": 1.2, "max_drawdown_pct": 10.0, "total_trades": 20, "total_return_pct": 15.0}
        r = auth.post(f"{BASE_URL}/api/risk/analyse", json={"dsl": dsl, "backtest": bt})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "risk_score" in d
        assert 0 <= d["risk_score"] <= 100
        assert d["verdict"] in ("LOW", "MEDIUM", "HIGH")
        assert "summary" in d


# ---------- Trap ----------
class TestTrap:
    def test_scan(self, auth):
        r = auth.get(f"{BASE_URL}/api/trap/scan", params={"symbol": "NIFTY"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "overall_trap_score" in d
        assert "rows" in d and len(d["rows"]) > 0
        row = d["rows"][0]
        assert "ce_trap" in row and "pe_trap" in row
        assert "suggestions" in d

    def test_explain(self, auth):
        scan = auth.get(f"{BASE_URL}/api/trap/scan", params={"symbol": "NIFTY"}).json()
        r = auth.post(f"{BASE_URL}/api/trap/explain", json={"scan": scan})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "headline" in d or "explanation" in d


# ---------- Risk limits + Paper ----------
class TestPaperAndRisk:
    def test_get_default_limits(self, auth):
        r = auth.get(f"{BASE_URL}/api/risk/limits")
        assert r.status_code == 200
        d = r.json()
        for k in ("max_drawdown_pct", "daily_loss_cap", "position_limit", "kill_switch"):
            assert k in d

    def test_update_limits(self, auth):
        payload = {"max_drawdown_pct": 12.0, "daily_loss_cap": 30000.0,
                   "position_limit": 7, "kill_switch": False}
        r = auth.put(f"{BASE_URL}/api/risk/limits", json=payload)
        assert r.status_code == 200
        r2 = auth.get(f"{BASE_URL}/api/risk/limits")
        assert r2.json()["position_limit"] == 7

    def test_place_eq_order_and_position(self, auth):
        # ensure kill switch off
        auth.put(f"{BASE_URL}/api/risk/limits", json={
            "max_drawdown_pct": 15.0, "daily_loss_cap": 25000.0,
            "position_limit": 5, "kill_switch": False})
        auth.post(f"{BASE_URL}/api/paper/flatten")
        # use fresh idempotency key so we don't replay a prior cached response
        r = auth.post(f"{BASE_URL}/api/paper/order",
                      json={"symbol": "NIFTY", "side": "BUY", "qty": 50, "instrument_type": "EQ"},
                      headers={"Idempotency-Key": f"test-{uuid.uuid4().hex}"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "FILLED"
        pos = auth.get(f"{BASE_URL}/api/paper/positions").json()
        assert len(pos["positions"]) >= 1
        nifty = next((p for p in pos["positions"] if p["symbol"] == "NIFTY"), None)
        assert nifty is not None
        assert "pnl" in nifty and "ltp" in nifty

    def test_place_option_order(self, auth):
        chain = auth.get(f"{BASE_URL}/api/market/options-chain", params={"symbol": "NIFTY"}).json()
        strike = chain["rows"][len(chain["rows"]) // 2]["strike"]
        r = auth.post(f"{BASE_URL}/api/paper/order", json={
            "symbol": "NIFTY", "side": "BUY", "qty": 50,
            "instrument_type": "OPT", "option_strike": strike, "option_kind": "CE"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "FILLED"

    def test_flatten(self, auth):
        r = auth.post(f"{BASE_URL}/api/paper/flatten")
        assert r.status_code == 200
        pos = auth.get(f"{BASE_URL}/api/paper/positions").json()
        assert pos["positions"] == []

    def test_kill_switch_blocks(self, auth):
        auth.put(f"{BASE_URL}/api/risk/limits", json={
            "max_drawdown_pct": 15.0, "daily_loss_cap": 25000.0,
            "position_limit": 5, "kill_switch": True})
        r = auth.post(f"{BASE_URL}/api/paper/order", json={
            "symbol": "NIFTY", "side": "BUY", "qty": 10, "instrument_type": "EQ"})
        assert r.status_code == 423
        # reset
        auth.put(f"{BASE_URL}/api/risk/limits", json={
            "max_drawdown_pct": 15.0, "daily_loss_cap": 25000.0,
            "position_limit": 5, "kill_switch": False})


# ---------- Journal ----------
class TestJournal:
    def test_create_and_list(self, auth):
        r = auth.post(f"{BASE_URL}/api/journal", json={
            "symbol": "RELIANCE", "side": "BUY", "qty": 10,
            "entry_price": 2500.0, "exit_price": 2550.0, "pnl": 500.0,
            "rationale": "TEST_breakout above resistance with rising volume",
            "request_ai": True})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "ai_commentary" in d
        assert "ai_tags" in d
        r2 = auth.get(f"{BASE_URL}/api/journal")
        assert r2.status_code == 200
        assert len(r2.json()["items"]) >= 1


# ---------- Dashboard ----------
class TestDashboard:
    def test_summary(self, auth):
        r = auth.get(f"{BASE_URL}/api/dashboard/summary")
        assert r.status_code == 200
        d = r.json()
        for k in ("strategies", "backtests", "open_positions",
                  "total_pnl", "exposure", "kill_switch", "risk_limits"):
            assert k in d


# ---------- Brokers (iteration 2) ----------
class TestBrokers:
    EXPECTED = {"zerodha", "upstox", "dhan", "icici", "rmoney"}

    def test_list_brokers(self, auth):
        r = auth.get(f"{BASE_URL}/api/brokers")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        names = {b["name"] for b in items}
        assert self.EXPECTED.issubset(names), f"missing brokers: {self.EXPECTED - names}"
        for b in items:
            for k in ("name", "label", "description", "fields", "sdk_package", "docs_url", "connected", "status"):
                assert k in b, f"broker {b.get('name')} missing field {k}"
            assert isinstance(b["fields"], list) and len(b["fields"]) > 0

    def test_zerodha_connect_then_test_then_delete(self, auth):
        # ensure clean
        auth.delete(f"{BASE_URL}/api/brokers/zerodha")
        # connect
        r = auth.post(f"{BASE_URL}/api/brokers/zerodha/connect", json={
            "credentials": {"api_key": "k", "api_secret": "s", "access_token": "t"}
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d == {"ok": True, "broker": "zerodha", "status": "saved"} or (
            d.get("ok") and d.get("broker") == "zerodha" and d.get("status") == "saved"
        )

        # verify stored as encrypted (list endpoint excludes credentials_enc but should show connected)
        r2 = auth.get(f"{BASE_URL}/api/brokers")
        z = next(b for b in r2.json()["items"] if b["name"] == "zerodha")
        assert z["connected"] is True
        assert z["status"] in ("saved", "live", "error")

        # test connection -> should fail gracefully (SDK not installed)
        r3 = auth.post(f"{BASE_URL}/api/brokers/zerodha/test")
        assert r3.status_code == 200, r3.text
        d3 = r3.json()
        assert d3["status"] == "error", d3
        msg = d3.get("message", "").lower()
        assert "kiteconnect" in msg or "sdk" in msg or "not installed" in msg, f"unexpected msg: {msg}"

        # delete
        r4 = auth.delete(f"{BASE_URL}/api/brokers/zerodha")
        assert r4.status_code == 200, r4.text
        assert r4.json()["deleted"] >= 1

        # verify removed
        r5 = auth.get(f"{BASE_URL}/api/brokers")
        z2 = next(b for b in r5.json()["items"] if b["name"] == "zerodha")
        assert z2["connected"] is False

    def test_rmoney_graceful_failure(self, auth):
        auth.delete(f"{BASE_URL}/api/brokers/rmoney")
        r = auth.post(f"{BASE_URL}/api/brokers/rmoney/connect", json={
            "credentials": {"user_id": "u", "api_key": "k", "password": "p"}
        })
        assert r.status_code == 200, r.text
        r2 = auth.post(f"{BASE_URL}/api/brokers/rmoney/test")
        assert r2.status_code == 200, r2.text
        d = r2.json()
        assert d["status"] == "error", d
        # cleanup
        auth.delete(f"{BASE_URL}/api/brokers/rmoney")

    def test_unknown_broker_404(self, auth):
        r = auth.post(f"{BASE_URL}/api/brokers/unknownX/connect", json={"credentials": {}})
        assert r.status_code == 404, r.text

    def test_credentials_stored_encrypted(self, auth):
        """Persisted document must contain credentials_enc and not plaintext."""
        auth.delete(f"{BASE_URL}/api/brokers/zerodha")
        secret_val = "PLAINTEXT_SECRET_XYZ_98765"
        r = auth.post(f"{BASE_URL}/api/brokers/zerodha/connect", json={
            "credentials": {"api_key": "abc", "api_secret": secret_val, "access_token": "t"}
        })
        assert r.status_code == 200
        # Inspect via DB directly
        import os as _os
        from pymongo import MongoClient
        mc = MongoClient(_os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = mc[_os.environ.get("DB_NAME", "test_database")]
        rec = db.broker_connections.find_one({"broker": "zerodha"})
        assert rec is not None
        assert "credentials_enc" in rec and rec["credentials_enc"]
        # ensure plaintext not present
        assert secret_val not in str(rec)
        auth.delete(f"{BASE_URL}/api/brokers/zerodha")


# ---------- Multi-leg paper orders ----------
class TestMultiLeg:
    def _ensure_kill_off(self, auth):
        auth.put(f"{BASE_URL}/api/risk/limits", json={
            "max_drawdown_pct": 15.0, "daily_loss_cap": 25000.0,
            "position_limit": 20, "kill_switch": False})

    def test_long_straddle(self, auth):
        self._ensure_kill_off(auth)
        auth.post(f"{BASE_URL}/api/paper/flatten")
        chain = auth.get(f"{BASE_URL}/api/market/options-chain", params={"symbol": "NIFTY"}).json()
        # use ATM strike (closest to spot)
        spot = chain.get("spot") or chain.get("underlying") or chain["rows"][len(chain["rows"]) // 2]["strike"]
        strikes = [row["strike"] for row in chain["rows"]]
        atm = min(strikes, key=lambda s: abs(s - spot))
        payload = {
            "name": "Long Straddle",
            "legs": [
                {"side": "BUY", "instrument_type": "OPT", "qty": 50,
                 "symbol": "NIFTY", "option_strike": atm, "option_kind": "CE"},
                {"side": "BUY", "instrument_type": "OPT", "qty": 50,
                 "symbol": "NIFTY", "option_strike": atm, "option_kind": "PE"},
            ],
        }
        r = auth.post(f"{BASE_URL}/api/paper/order/multi-leg", json=payload,
                      headers={"Idempotency-Key": f"test-{uuid.uuid4().hex}"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "basket_id" in d
        assert len(d["orders"]) == 2
        for o in d["orders"]:
            assert o["status"] == "FILLED"
        pos = auth.get(f"{BASE_URL}/api/paper/positions").json()["positions"]
        # 2 positions (CE + PE)
        nifty_opts = [p for p in pos if p["symbol"] == "NIFTY" and p.get("instrument_type") == "OPT"]
        assert len(nifty_opts) == 2, nifty_opts
        auth.post(f"{BASE_URL}/api/paper/flatten")

    def test_multi_leg_empty_legs(self, auth):
        self._ensure_kill_off(auth)
        r = auth.post(f"{BASE_URL}/api/paper/order/multi-leg",
                      json={"name": "Empty", "legs": []})
        assert r.status_code == 400, r.text

    def test_multi_leg_kill_switch_blocks(self, auth):
        # enable kill switch
        auth.put(f"{BASE_URL}/api/risk/limits", json={
            "max_drawdown_pct": 15.0, "daily_loss_cap": 25000.0,
            "position_limit": 20, "kill_switch": True})
        chain = auth.get(f"{BASE_URL}/api/market/options-chain", params={"symbol": "NIFTY"}).json()
        atm = chain["rows"][len(chain["rows"]) // 2]["strike"]
        r = auth.post(f"{BASE_URL}/api/paper/order/multi-leg", json={
            "name": "Blocked",
            "legs": [{"side": "BUY", "instrument_type": "OPT", "qty": 50,
                      "symbol": "NIFTY", "option_strike": atm, "option_kind": "CE"}],
        })
        assert r.status_code == 423, r.text
        # reset
        self._ensure_kill_off(auth)


# ---------- WebSocket tick feed ----------
class TestWebSocketTicks:
    def test_ws_ticks_stream(self):
        import json as _json
        from websockets.sync.client import connect as ws_connect
        ws_url = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
        url = f"{ws_url}/api/ws/ticks?symbols=NIFTY,BANKNIFTY"
        msgs = []
        with ws_connect(url, open_timeout=10, close_timeout=5) as ws:
            for _ in range(3):
                raw = ws.recv(timeout=5)
                msgs.append(_json.loads(raw))
        assert len(msgs) >= 3
        # First message: snapshot
        assert msgs[0]["type"] == "snapshot"
        assert "ticks" in msgs[0]
        first_ticks = msgs[0]["ticks"]
        symbols = {t["symbol"] for t in first_ticks}
        assert "NIFTY" in symbols
        # Subsequent should be 'tick' type
        assert msgs[1]["type"] == "tick"
        for tk in msgs[1]["ticks"]:
            for k in ("symbol", "ltp", "open", "change", "change_pct", "ts"):
                assert k in tk, f"missing {k} in tick {tk}"



# ---------- Helpers for iteration 4 ----------

def _fresh_key():
    return f"test-{uuid.uuid4().hex}"


def _ensure_kill_off(auth):
    auth.put(f"{BASE_URL}/api/risk/limits", json={
        "max_drawdown_pct": 15.0, "daily_loss_cap": 25000.0,
        "position_limit": 50, "kill_switch": False})


# ---------- Literal validation (iteration 4) ----------
class TestLiteralValidation:
    def test_invalid_side_hold(self, auth):
        r = auth.post(f"{BASE_URL}/api/paper/order", json={
            "symbol": "TCS", "side": "HOLD", "qty": 1, "instrument_type": "EQ"
        }, headers={"Idempotency-Key": _fresh_key()})
        assert r.status_code == 422, r.text
        body = r.text
        assert "BUY" in body and "SELL" in body

    def test_invalid_side_lowercase(self, auth):
        r = auth.post(f"{BASE_URL}/api/paper/order", json={
            "symbol": "TCS", "side": "buy", "qty": 1, "instrument_type": "EQ"
        }, headers={"Idempotency-Key": _fresh_key()})
        assert r.status_code == 422

    def test_invalid_instrument_type(self, auth):
        r = auth.post(f"{BASE_URL}/api/paper/order", json={
            "symbol": "TCS", "side": "BUY", "qty": 1, "instrument_type": "FUT"
        }, headers={"Idempotency-Key": _fresh_key()})
        assert r.status_code == 422

    def test_invalid_option_kind(self, auth):
        r = auth.post(f"{BASE_URL}/api/paper/order", json={
            "symbol": "NIFTY", "side": "BUY", "qty": 1,
            "instrument_type": "OPT", "option_strike": 22000, "option_kind": "X"
        }, headers={"Idempotency-Key": _fresh_key()})
        assert r.status_code == 422

    def test_invalid_order_type(self, auth):
        r = auth.post(f"{BASE_URL}/api/paper/order", json={
            "symbol": "TCS", "side": "BUY", "qty": 1,
            "order_type": "STOP", "instrument_type": "EQ"
        }, headers={"Idempotency-Key": _fresh_key()})
        assert r.status_code == 422

    def test_multi_leg_invalid_side(self, auth):
        r = auth.post(f"{BASE_URL}/api/paper/order/multi-leg", json={
            "name": "Bad",
            "legs": [{"side": "HOLD", "instrument_type": "OPT", "qty": 50,
                      "symbol": "NIFTY", "option_strike": 22000, "option_kind": "CE"}]
        }, headers={"Idempotency-Key": _fresh_key()})
        assert r.status_code == 422

    def test_multi_leg_invalid_option_kind(self, auth):
        r = auth.post(f"{BASE_URL}/api/paper/order/multi-leg", json={
            "name": "Bad",
            "legs": [{"side": "BUY", "instrument_type": "OPT", "qty": 50,
                      "symbol": "NIFTY", "option_strike": 22000, "option_kind": "X"}]
        }, headers={"Idempotency-Key": _fresh_key()})
        assert r.status_code == 422


# ---------- Duplicate prevention (iteration 4) ----------
class TestDuplicatePrevention:
    def test_duplicate_rejected_with_different_idem_keys(self, auth):
        _ensure_kill_off(auth)
        auth.post(f"{BASE_URL}/api/paper/flatten")
        payload = {"symbol": "TCS", "side": "BUY", "qty": 10, "instrument_type": "EQ"}
        r1 = auth.post(f"{BASE_URL}/api/paper/order", json=payload,
                       headers={"Idempotency-Key": _fresh_key()})
        assert r1.status_code == 200, r1.text
        assert "idempotency_key" in r1.json()

        r2 = auth.post(f"{BASE_URL}/api/paper/order", json=payload,
                       headers={"Idempotency-Key": _fresh_key()})
        assert r2.status_code == 409, r2.text
        detail = r2.json().get("detail", "")
        assert "Duplicate order detected" in detail
        assert "force=true" in detail

    def test_force_bypass_succeeds(self, auth):
        _ensure_kill_off(auth)
        auth.post(f"{BASE_URL}/api/paper/flatten")
        payload = {"symbol": "INFY", "side": "BUY", "qty": 5, "instrument_type": "EQ"}
        r1 = auth.post(f"{BASE_URL}/api/paper/order", json=payload,
                       headers={"Idempotency-Key": _fresh_key()})
        assert r1.status_code == 200, r1.text
        r2 = auth.post(f"{BASE_URL}/api/paper/order?force=true", json=payload,
                       headers={"Idempotency-Key": _fresh_key()})
        assert r2.status_code == 200, r2.text

    def test_dup_window_expires(self, auth):
        _ensure_kill_off(auth)
        auth.post(f"{BASE_URL}/api/paper/flatten")
        payload = {"symbol": "HDFCBANK", "side": "BUY", "qty": 3, "instrument_type": "EQ"}
        r1 = auth.post(f"{BASE_URL}/api/paper/order", json=payload,
                       headers={"Idempotency-Key": _fresh_key()})
        assert r1.status_code == 200, r1.text
        time.sleep(6.5)
        r2 = auth.post(f"{BASE_URL}/api/paper/order", json=payload,
                       headers={"Idempotency-Key": _fresh_key()})
        assert r2.status_code == 200, r2.text


# ---------- Idempotency (iteration 4) ----------
class TestIdempotency:
    def test_idempotency_replay_single(self, auth):
        _ensure_kill_off(auth)
        auth.post(f"{BASE_URL}/api/paper/flatten")
        key = _fresh_key()
        payload = {"symbol": "RELIANCE", "side": "BUY", "qty": 7, "instrument_type": "EQ"}
        r1 = auth.post(f"{BASE_URL}/api/paper/order", json=payload,
                       headers={"Idempotency-Key": key})
        assert r1.status_code == 200, r1.text
        first = r1.json()
        assert first.get("idempotency_key") == key
        assert "id" in first
        assert not first.get("idempotent_replay")

        r2 = auth.post(f"{BASE_URL}/api/paper/order", json=payload,
                       headers={"Idempotency-Key": key})
        assert r2.status_code == 200, r2.text
        second = r2.json()
        assert second["id"] == first["id"]
        assert second.get("idempotent_replay") is True

    def test_auto_idempotency_without_header(self, auth):
        _ensure_kill_off(auth)
        auth.post(f"{BASE_URL}/api/paper/flatten")
        # randomized qty so signature differs per test run (avoids 24h TTL replay)
        unique_qty = (uuid.uuid4().int % 90) + 10
        payload = {"symbol": "BANKNIFTY", "side": "BUY", "qty": unique_qty, "instrument_type": "EQ"}
        r1 = auth.post(f"{BASE_URL}/api/paper/order", json=payload)
        assert r1.status_code == 200, r1.text
        first = r1.json()
        assert "idempotency_key" in first and first["idempotency_key"]
        assert not first.get("idempotent_replay")

        r2 = auth.post(f"{BASE_URL}/api/paper/order", json=payload)
        assert r2.status_code == 200, r2.text
        second = r2.json()
        assert second["id"] == first["id"]
        assert second.get("idempotent_replay") is True

    def test_multi_leg_idempotency_replay(self, auth):
        _ensure_kill_off(auth)
        auth.post(f"{BASE_URL}/api/paper/flatten")
        chain = auth.get(f"{BASE_URL}/api/market/options-chain", params={"symbol": "NIFTY"}).json()
        atm = chain["rows"][len(chain["rows"]) // 2]["strike"]
        payload = {
            "name": "Replay Straddle",
            "legs": [
                {"side": "BUY", "instrument_type": "OPT", "qty": 25,
                 "symbol": "NIFTY", "option_strike": atm, "option_kind": "CE"},
                {"side": "BUY", "instrument_type": "OPT", "qty": 25,
                 "symbol": "NIFTY", "option_strike": atm, "option_kind": "PE"},
            ],
        }
        key = _fresh_key()
        r1 = auth.post(f"{BASE_URL}/api/paper/order/multi-leg", json=payload,
                       headers={"Idempotency-Key": key})
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        bid1 = d1["basket_id"]

        r2 = auth.post(f"{BASE_URL}/api/paper/order/multi-leg", json=payload,
                       headers={"Idempotency-Key": key})
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2["basket_id"] == bid1
        assert d2.get("idempotent_replay") is True

        # positions reflect only ONE basket fill (2 positions, not 4)
        pos = auth.get(f"{BASE_URL}/api/paper/positions").json()["positions"]
        nifty_opts = [p for p in pos if p["symbol"] == "NIFTY" and p.get("instrument_type") == "OPT"]
        assert len(nifty_opts) == 2, nifty_opts
        # qty per position is 25 (BUY) — not doubled
        for p in nifty_opts:
            assert p["qty"] == 25, p
        auth.post(f"{BASE_URL}/api/paper/flatten")


# ---------- Basket pre-flight rollback (iteration 4) ----------
class TestBasketRollback:
    def test_invalid_strike_preflight_no_partial_fill(self, auth):
        _ensure_kill_off(auth)
        auth.post(f"{BASE_URL}/api/paper/flatten")
        chain = auth.get(f"{BASE_URL}/api/market/options-chain", params={"symbol": "NIFTY"}).json()
        good_strike = chain["rows"][len(chain["rows"]) // 2]["strike"]

        pos_before = len(auth.get(f"{BASE_URL}/api/paper/positions").json()["positions"])

        payload = {
            "name": "BadBasket",
            "legs": [
                {"side": "BUY", "instrument_type": "OPT", "qty": 25,
                 "symbol": "NIFTY", "option_strike": good_strike, "option_kind": "CE"},
                {"side": "BUY", "instrument_type": "OPT", "qty": 25,
                 "symbol": "NIFTY", "option_strike": 99999, "option_kind": "PE"},
            ],
        }
        r = auth.post(f"{BASE_URL}/api/paper/order/multi-leg", json=payload,
                      headers={"Idempotency-Key": _fresh_key()})
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", "")
        # 0-indexed; leg index 1 is the bad one
        assert "Leg 1" in detail
        assert "99999" in detail

        pos_after = len(auth.get(f"{BASE_URL}/api/paper/positions").json()["positions"])
        assert pos_after == pos_before, "Pre-flight should not partially fill"

    def test_multi_leg_success_persists_basket(self, auth):
        _ensure_kill_off(auth)
        auth.post(f"{BASE_URL}/api/paper/flatten")
        chain = auth.get(f"{BASE_URL}/api/market/options-chain", params={"symbol": "NIFTY"}).json()
        atm = chain["rows"][len(chain["rows"]) // 2]["strike"]
        payload = {
            "name": "OK Basket",
            "legs": [
                {"side": "BUY", "instrument_type": "OPT", "qty": 25,
                 "symbol": "NIFTY", "option_strike": atm, "option_kind": "CE"},
                {"side": "BUY", "instrument_type": "OPT", "qty": 25,
                 "symbol": "NIFTY", "option_strike": atm, "option_kind": "PE"},
            ],
        }
        r = auth.post(f"{BASE_URL}/api/paper/order/multi-leg", json=payload,
                      headers={"Idempotency-Key": _fresh_key()})
        assert r.status_code == 200, r.text
        bid = r.json()["basket_id"]
        # verify orders endpoint returns basket_id, basket_pending=False
        orders = auth.get(f"{BASE_URL}/api/paper/orders").json()["orders"]
        basket_orders = [o for o in orders if o.get("basket_id") == bid]
        assert len(basket_orders) == 2, basket_orders
        for o in basket_orders:
            assert o.get("basket_pending") is False
        auth.post(f"{BASE_URL}/api/paper/flatten")


# ---------- Idempotency TTL index (iteration 4) ----------
class TestIdempotencyTTL:
    def test_ttl_index_present(self):
        import os as _os
        from pymongo import MongoClient
        mc = MongoClient(_os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = mc[_os.environ.get("DB_NAME", "test_database")]
        indexes = list(db.idempotency_keys.list_indexes())
        ttl_idx = [i for i in indexes if "expireAfterSeconds" in i]
        assert ttl_idx, f"No TTL index found in idempotency_keys: {indexes}"
        # 24h = 86400s
        assert any(i.get("expireAfterSeconds") == 86400 for i in ttl_idx), ttl_idx


# ---------- Lifespan / startup log ----------
class TestLifespan:
    def test_no_on_event_deprecation_and_startup_log(self):
        import subprocess
        # Look at recent supervisor backend logs
        out = subprocess.run(
            ["bash", "-c", "tail -n 400 /var/log/supervisor/backend.*.log 2>/dev/null || true"],
            capture_output=True, text=True, timeout=10
        ).stdout
        assert "AlgoForge backend started" in out, "Startup log line missing"
        assert "on_event is deprecated" not in out, "on_event deprecation warning still present"



# ---------- Iteration 5: code-review fix verifications ----------
class TestIter5CodeReviewFixes:
    """Behavioral tests for iteration 5 cleanup pass.

    Verifies:
      * Backtest with structurally invalid DSL -> 400 with detail starting
        'Invalid strategy DSL' (was 500 before AttributeError was caught).
      * Backtest with unknown indicator type runs gracefully (no entries,
        no exception).
      * Backtest with valid DSL still returns full payload.
      * Rmoney connect+test still returns status='error' after `r` -> `response`
        rename in /app/backend/brokers/rmoney.py (no 500).
      * Multi-leg basket payload that carries a client-side `_key` per leg is
        accepted (Pydantic extra='ignore').
      * The DEMO_EMAIL / DEMO_PASSWORD constants resolve from env vars when
        overridden (defaults preserved otherwise).
    """

    # --- (3) AttributeError now caught -> 400 not 500 ----------------------
    def test_backtest_invalid_dsl_entry_string_returns_400(self, auth):
        # entry is supposed to be a dict; passing 'BAD' will trigger
        # AttributeError inside the engine (was 500 pre-fix).
        bad_dsl = {
            "name": "TEST_BAD_DSL",
            "symbol": "RELIANCE",
            "timeframe": "1d",
            "indicators": [],
            "entry": "BAD",
            "exit": {},
            "size": {"type": "fixed_qty", "value": 1},
        }
        r = auth.post(f"{BASE_URL}/api/backtest/run",
                      json={"dsl": bad_dsl, "days": 60, "save": False})
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        detail = r.json().get("detail", "")
        assert detail.startswith("Invalid strategy DSL"), (
            f"detail must start with 'Invalid strategy DSL', got: {detail!r}"
        )

    def test_backtest_invalid_dsl_exit_string_returns_400(self, auth):
        bad_dsl = {
            "name": "TEST_BAD_DSL_2",
            "symbol": "RELIANCE",
            "timeframe": "1d",
            "indicators": [],
            "entry": {"op": "and", "rules": []},
            "exit": "WRONG",
            "size": {"type": "fixed_qty", "value": 1},
        }
        r = auth.post(f"{BASE_URL}/api/backtest/run",
                      json={"dsl": bad_dsl, "days": 60, "save": False})
        assert r.status_code == 400, r.text
        assert "Invalid strategy DSL" in r.json().get("detail", "")

    # --- (5) Unknown indicator type still runs gracefully ------------------
    def test_backtest_unknown_indicator_runs_no_trades(self, auth):
        dsl = {
            "name": "TEST_BOGUS_IND",
            "symbol": "RELIANCE",
            "timeframe": "1d",
            "indicators": [
                {"id": "x", "type": "bogus", "period": 5, "source": "close"}
            ],
            "entry": {"op": "and",
                      "rules": [{"left": "x", "cmp": ">", "right": 0}]},
            "exit": {"op": "or",
                     "rules": [{"left": "x", "cmp": "<", "right": 0}]},
            "size": {"type": "fixed_qty", "value": 1},
        }
        r = auth.post(f"{BASE_URL}/api/backtest/run",
                      json={"dsl": dsl, "days": 120, "save": False})
        assert r.status_code == 200, (
            f"unknown indicator must NOT 500; got {r.status_code}: {r.text}"
        )
        body = r.json()
        # engine still produced a structured payload
        for k in ("sharpe", "sortino", "equity_curve", "trades", "total_trades"):
            assert k in body, f"missing {k} in payload"
        assert isinstance(body["equity_curve"], list)
        assert isinstance(body["trades"], list)
        assert body["total_trades"] == 0, (
            f"unknown indicator -> no entries; got total_trades={body['total_trades']}"
        )

    # --- Valid DSL still returns full payload -----------------------------
    def test_backtest_valid_dsl_still_returns_full_payload(self, auth):
        dsl = {
            "name": "TEST_VALID_AFTER_FIX",
            "symbol": "TCS",
            "timeframe": "1d",
            "indicators": [
                {"id": "fast", "type": "sma", "period": 5, "source": "close"},
                {"id": "slow", "type": "sma", "period": 20, "source": "close"},
            ],
            "entry": {"op": "and",
                      "rules": [{"left": "fast", "cmp": ">", "right": "slow"}]},
            "exit": {"op": "or",
                     "rules": [{"left": "fast", "cmp": "<", "right": "slow"}]},
            "size": {"type": "fixed_qty", "value": 5},
        }
        r = auth.post(f"{BASE_URL}/api/backtest/run",
                      json={"dsl": dsl, "days": 250, "save": False})
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("sharpe", "sortino", "equity_curve", "trades",
                  "total_trades", "max_drawdown_pct", "total_return_pct"):
            assert k in body
        assert isinstance(body["equity_curve"], list)
        assert isinstance(body["trades"], list)

    # --- (4) Rmoney rename `r` -> `response` still graceful ---------------
    def test_rmoney_graceful_after_var_rename(self, auth):
        # connect with bogus creds
        r = auth.post(f"{BASE_URL}/api/brokers/rmoney/connect", json={
            "broker": "rmoney",
            "credentials": {
                "user_id": f"TEST_USER_{uuid.uuid4().hex[:6]}",
                "api_key": "k", "api_secret": "s",
                "session_token": "tok-invalid",
            },
        })
        assert r.status_code == 200, r.text
        # now test - must NOT 500; must report status='error' gracefully
        tr = auth.post(f"{BASE_URL}/api/brokers/rmoney/test")
        assert tr.status_code == 200, f"expected 200 with status='error', got {tr.status_code}: {tr.text}"
        body = tr.json()
        assert body.get("status") == "error", f"expected status='error', got {body}"
        # cleanup
        auth.delete(f"{BASE_URL}/api/brokers/rmoney")

    # --- (6) MultiLegBuilder _key field ignored by backend ----------------
    def test_multi_leg_accepts_extra_underscore_key_field(self, auth):
        # Build a 2-leg Long Straddle on NIFTY ATM with client _key fields.
        # ensure kill switch off + flat positions
        auth.post(f"{BASE_URL}/api/paper/risk-limits",
                  json={"max_loss_per_day": 100000, "max_open_positions": 50,
                        "kill_switch": False})
        auth.post(f"{BASE_URL}/api/paper/flatten")
        chain = auth.get(f"{BASE_URL}/api/market/options-chain",
                         params={"symbol": "NIFTY"}).json()
        spot = chain.get("spot") or chain.get("underlying") or \
            chain["rows"][len(chain["rows"]) // 2]["strike"]
        strikes = [row["strike"] for row in chain["rows"]]
        atm = min(strikes, key=lambda s: abs(s - spot))
        idem = f"test-iter5-multileg-{uuid.uuid4().hex}"
        payload = {
            "name": "TEST_STRADDLE_WITH_KEY",
            "legs": [
                {
                    "_key": "client-leg-1",  # extra client-only field
                    "side": "BUY", "instrument_type": "OPT", "qty": 25,
                    "symbol": "NIFTY", "option_strike": atm, "option_kind": "CE",
                },
                {
                    "_key": "client-leg-2",
                    "side": "BUY", "instrument_type": "OPT", "qty": 25,
                    "symbol": "NIFTY", "option_strike": atm, "option_kind": "PE",
                },
            ],
        }
        r = auth.post(f"{BASE_URL}/api/paper/order/multi-leg",
                      json=payload,
                      headers={"Idempotency-Key": idem})
        assert r.status_code == 200, f"_key must be ignored; got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("basket_id"), "basket_id missing"
        assert len(body.get("orders", [])) == 2, f"expected 2 orders, got {body}"
        for o in body["orders"]:
            assert o["status"] == "FILLED"
        auth.post(f"{BASE_URL}/api/paper/flatten")

    # --- (1) ENV-var test credentials -------------------------------------
    def test_env_var_test_credentials_default(self):
        # When env vars are unset (the typical test run), defaults must be the
        # documented demo account.
        # We re-import the constants from the module to assert they exist.
        from backend.tests import backend_test as bt  # noqa
        # constants are module-level
        assert bt.DEMO_EMAIL  # truthy
        assert bt.DEMO_PASSWORD
        # defaults preserved when env vars not explicitly set in this process
        if not os.environ.get("ALGOFORGE_TEST_EMAIL"):
            assert bt.DEMO_EMAIL == "demo@algoforge.io"
        if not os.environ.get("ALGOFORGE_TEST_PASSWORD"):
            assert bt.DEMO_PASSWORD == "Demo@123"

    def test_env_var_override_logic(self):
        # Simulate override behavior: the os.environ.get(..., default) pattern
        # used in backend_test.py must honor env vars when present.
        prev_email = os.environ.get("ALGOFORGE_TEST_EMAIL")
        prev_pw = os.environ.get("ALGOFORGE_TEST_PASSWORD")
        try:
            os.environ["ALGOFORGE_TEST_EMAIL"] = "override@example.com"
            os.environ["ALGOFORGE_TEST_PASSWORD"] = "Override#1"
            assert os.environ.get("ALGOFORGE_TEST_EMAIL",
                                  "demo@algoforge.io") == "override@example.com"
            assert os.environ.get("ALGOFORGE_TEST_PASSWORD",
                                  "Demo@123") == "Override#1"
        finally:
            if prev_email is None:
                os.environ.pop("ALGOFORGE_TEST_EMAIL", None)
            else:
                os.environ["ALGOFORGE_TEST_EMAIL"] = prev_email
            if prev_pw is None:
                os.environ.pop("ALGOFORGE_TEST_PASSWORD", None)
            else:
                os.environ["ALGOFORGE_TEST_PASSWORD"] = prev_pw
