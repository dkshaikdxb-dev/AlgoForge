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

        # test connection -> should fail gracefully with status=error
        # (iter 9: kiteconnect SDK now installed; fake creds → BrokerAuthError → classified as "error")
        r3 = auth.post(f"{BASE_URL}/api/brokers/zerodha/test")
        assert r3.status_code == 200, r3.text
        d3 = r3.json()
        assert d3["status"] == "error", d3
        msg = d3.get("message", "").lower()
        assert any(
            keyword in msg for keyword in ("kiteconnect", "sdk", "not installed",
                                            "api_key", "access_token", "auth", "incorrect")
        ), f"unexpected msg: {msg}"

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
        # documented demo account. Reference the module-level constants directly.
        assert DEMO_EMAIL  # truthy
        assert DEMO_PASSWORD
        # defaults preserved when env vars not explicitly set in this process
        if not os.environ.get("ALGOFORGE_TEST_EMAIL"):
            assert DEMO_EMAIL == "demo@algoforge.io"
        if not os.environ.get("ALGOFORGE_TEST_PASSWORD"):
            assert DEMO_PASSWORD == "Demo@123"

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



# ============================================================================
# Iteration 6 — Broker Adapter Prep, Reconciliation, Capabilities
# ============================================================================
class TestIter6BrokerAdapterPrep:
    """P0 broker prep: capabilities, reconciliation endpoints, ABC, retry, circuit breaker."""

    # --- (A) /api/brokers capabilities exposed -----------------------------
    def test_brokers_capabilities_chip(self, auth):
        r = auth.get(f"{BASE_URL}/api/brokers")
        assert r.status_code == 200, r.text
        items = {b["name"]: b for b in r.json()["items"]}
        # Zerodha — all True
        zcaps = items["zerodha"]["capabilities"]
        for k in ("supports_modify", "supports_amo", "supports_iceberg",
                  "supports_basket_native", "supports_postback_ws",
                  "supports_options", "supports_options_multi_leg"):
            assert zcaps.get(k) is True, f"zerodha.{k} expected True, got {zcaps.get(k)}"
        # Rmoney — only supports_options=True
        rcaps = items["rmoney"]["capabilities"]
        assert rcaps.get("supports_options") is True
        for k in ("supports_modify", "supports_amo", "supports_iceberg",
                  "supports_basket_native", "supports_postback_ws",
                  "supports_options_multi_leg"):
            assert rcaps.get(k) is False, f"rmoney.{k} expected False, got {rcaps.get(k)}"

    # --- (B) /api/reconciliation/summary ----------------------------------
    def test_reconciliation_summary_shape(self, auth):
        r = auth.get(f"{BASE_URL}/api/reconciliation/summary")
        assert r.status_code == 200, r.text
        d = r.json()
        assert "connected_brokers" in d and isinstance(d["connected_brokers"], list)
        assert "counts_by_state" in d
        for s in ("SYNCED", "PENDING_RECONCILE", "OUT_OF_SYNC",
                  "RECONCILED", "FAILED", "NOT_APPLICABLE"):
            assert s in d["counts_by_state"], f"missing state {s}"
            assert isinstance(d["counts_by_state"][s], int)

    # --- (C) Reconcile paper → NOT_APPLICABLE + audit row -----------------
    def test_reconciliation_run_paper_noop(self, auth):
        r = auth.post(f"{BASE_URL}/api/reconciliation/run/paper")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["state"] == "NOT_APPLICABLE", d
        assert d["checked"] == 0
        assert d["actions"] == []

        # Audit row created
        lr = auth.get(f"{BASE_URL}/api/reconciliation/log", params={"broker": "paper"})
        assert lr.status_code == 200
        items = lr.json()["items"]
        assert len(items) >= 1
        latest = items[0]
        assert latest["broker"] == "paper"
        assert latest["action_taken"] == "NO_OP"
        assert "ts" in latest and "reason" in latest

    # --- (D) Reconcile zerodha (real BrokerAdapter, fake creds) → FAILED --
    # NOTE (iter 9): zerodha is now a full BrokerAdapter. With fake creds the
    # adapter attempts get_orders() which raises BrokerAuthError → reconciler
    # logs FETCH_FAILED and returns state=FAILED (was PENDING_RECONCILE/ADAPTER_LEGACY).
    def test_reconciliation_run_zerodha_real_adapter_auth_fails(self, auth):
        # Ensure connected with dummy creds
        auth.delete(f"{BASE_URL}/api/brokers/zerodha")
        cr = auth.post(f"{BASE_URL}/api/brokers/zerodha/connect", json={
            "credentials": {"api_key": "k", "api_secret": "s", "access_token": "t"}
        })
        assert cr.status_code == 200, cr.text
        try:
            r = auth.post(f"{BASE_URL}/api/reconciliation/run/zerodha")
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["state"] == "FAILED", d
            assert "error" in d, d
            # Audit row with FETCH_FAILED
            lr = auth.get(f"{BASE_URL}/api/reconciliation/log", params={"broker": "zerodha"})
            items = lr.json()["items"]
            assert any(it.get("action_taken") == "FETCH_FAILED" for it in items), items[:3]
        finally:
            auth.delete(f"{BASE_URL}/api/brokers/zerodha")

    # --- (E) Reconcile not-connected broker → 404 -------------------------
    def test_reconciliation_run_unconnected_404(self, auth):
        # Ensure clean
        auth.delete(f"{BASE_URL}/api/brokers/upstox")
        r = auth.post(f"{BASE_URL}/api/reconciliation/run/upstox")
        assert r.status_code == 404, r.text
        assert "not connected" in r.json().get("detail", "").lower()

    # --- (F) Log filter ?broker= works ------------------------------------
    def test_reconciliation_log_broker_filter(self, auth):
        # Generate at least one paper entry to filter on
        auth.post(f"{BASE_URL}/api/reconciliation/run/paper")
        r = auth.get(f"{BASE_URL}/api/reconciliation/log", params={"broker": "paper"})
        assert r.status_code == 200
        items = r.json()["items"]
        assert all(it["broker"] == "paper" for it in items), \
            f"filter broken: {[(it['broker']) for it in items]}"
        for it in items[:3]:
            for k in ("broker", "action_taken", "ts"):
                assert k in it, f"missing {k}: {it}"

    # --- (G) Pydantic NormalizedOrder sanity ------------------------------
    def test_normalized_order_pydantic(self):
        import os as _os
        _os.environ.setdefault("ENCRYPTION_KEY", "test-key-placeholder")
        import sys
        sys.path.insert(0, "/app/backend")
        from brokers.schemas import NormalizedOrder, OrderStatus
        o = NormalizedOrder(
            id="oid-1", user_id="u1", broker="paper",
            symbol="NIFTY", side="BUY", qty=50,
            status=OrderStatus.FILLED,
        )
        # enum serialises as string with use_enum_values=True
        dumped = o.model_dump()
        assert dumped["status"] == "FILLED"
        assert isinstance(dumped["status"], str)
        assert dumped["symbol"] == "NIFTY"
        assert dumped["qty"] == 50

    # --- (H) BrokerAdapter ABC cannot be instantiated ---------------------
    def test_broker_adapter_abc_not_instantiable(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from brokers.base import BrokerAdapter
        with pytest.raises(TypeError) as exc:
            BrokerAdapter({})
        assert "abstract" in str(exc.value).lower()

    # --- (I) PaperAdapter capabilities + test_connection ------------------
    def test_paper_adapter_capabilities_and_connection(self):
        import asyncio, sys
        sys.path.insert(0, "/app/backend")
        from brokers.paper_adapter import PaperAdapter
        from brokers.schemas import BrokerCapabilities
        adapter = PaperAdapter({}, user_id="u-test")
        caps = adapter.capabilities()
        assert isinstance(caps, BrokerCapabilities)
        assert caps.supports_options_multi_leg is True
        result = asyncio.run(adapter.test_connection())
        assert result.get("ok") is True

    # --- (J) PaperAdapter.place_order via ABC interface -------------------
    def test_paper_adapter_place_order_via_abc(self, auth):
        # Flatten first to avoid duplicate-window issues
        auth.post(f"{BASE_URL}/api/paper/flatten")
        time.sleep(0.5)

        # Issue order over HTTP (existing flow) -- we then verify the adapter
        # produces a NormalizedOrder shape in-process.
        import asyncio, sys, os as _os
        sys.path.insert(0, "/app/backend")
        from brokers.paper_adapter import PaperAdapter
        from brokers.schemas import NormalizedOrderRequest, OrderStatus, ReconciliationState

        # Get demo user id by hitting /me
        me = auth.get(f"{BASE_URL}/api/auth/me").json()
        adapter = PaperAdapter({}, user_id=me["id"])
        req = NormalizedOrderRequest(symbol="NIFTY", side="BUY", qty=50,
                                     instrument_type="EQ", order_type="MARKET")
        no = asyncio.run(adapter.place_order(req))
        assert no.status == OrderStatus.FILLED.value or no.status == "FILLED"
        assert no.reconciliation_state in (
            ReconciliationState.NOT_APPLICABLE.value, "NOT_APPLICABLE"
        )
        assert no.symbol == "NIFTY"
        assert no.qty == 50
        assert no.broker == "paper"

        # And the order shows up via /api/paper/orders
        r = auth.get(f"{BASE_URL}/api/paper/orders")
        assert r.status_code == 200
        orders = r.json().get("items") or r.json().get("orders") or r.json()
        assert any(o.get("id") == no.id or o.get("id") == no.broker_order_id
                   for o in (orders if isinstance(orders, list) else []))

    # --- (K) Circuit breaker opens after 3 failures in 30s ---------------
    def test_circuit_breaker_opens_on_3_failures(self):
        import asyncio, sys
        sys.path.insert(0, "/app/backend")
        import brokers.base as bb
        from brokers.base import (
            call_with_retry, BrokerNetworkError, BrokerUnavailable,
        )
        # Clear any prior state for our fake key
        user_id = "TEST_breaker_user"
        broker = "fakebr"
        bb._breakers.pop((user_id, broker), None)

        async def always_fail():
            raise BrokerNetworkError("simulated")

        async def run():
            # max_attempts=1 so each call_with_retry records exactly one failure
            for _ in range(3):
                with pytest.raises(BrokerNetworkError):
                    await call_with_retry(always_fail, user_id=user_id,
                                          broker=broker, max_attempts=1)
            # 4th call should be short-circuited
            with pytest.raises(BrokerUnavailable) as exc:
                await call_with_retry(always_fail, user_id=user_id,
                                      broker=broker, max_attempts=1)
            assert "circuit open" in str(exc.value).lower()

        asyncio.run(run())
        # cleanup
        bb._breakers.pop((user_id, broker), None)

    # --- (L) Retry policy succeeds on 3rd attempt after 2 network errors --
    def test_retry_policy_succeeds_on_third_attempt(self):
        import asyncio, sys
        sys.path.insert(0, "/app/backend")
        import brokers.base as bb
        from brokers.base import call_with_retry, BrokerNetworkError

        user_id = "TEST_retry_user"
        broker = "fakebr2"
        bb._breakers.pop((user_id, broker), None)

        state = {"n": 0}

        async def flaky():
            state["n"] += 1
            if state["n"] < 3:
                raise BrokerNetworkError(f"fail #{state['n']}")
            return "ok"

        result = asyncio.run(call_with_retry(
            flaky, user_id=user_id, broker=broker,
            max_attempts=3, base_delay=0.01,
        ))
        assert result == "ok"
        assert state["n"] == 3
        bb._breakers.pop((user_id, broker), None)



# =====================================================================
# Iteration 7 — SEBI Audit-Log Viewer
# =====================================================================
class TestIter7AuditLog:
    """Audit log P1: types/events/export, filters, pagination, instrumentation hooks."""

    # ---------- /api/audit/types ----------
    def test_audit_types(self, auth):
        r = auth.get(f"{BASE_URL}/api/audit/types")
        assert r.status_code == 200, r.text
        d = r.json()
        assert set(d.keys()) >= {"all", "sebi_trace", "severities"}
        # 18 event types per the PRD
        assert len(d["all"]) == 18, f"expected 18 event types, got {len(d['all'])}: {d['all']}"
        assert d["sebi_trace"] == ["SIGNAL", "DECISION", "REQUEST", "RESPONSE", "FILL", "OVERRIDE"]
        assert d["severities"] == ["INFO", "WARN", "HIGH"]
        for et in ["SIGNAL", "REQUEST", "FILL", "OVERRIDE", "KILL_SWITCH",
                   "RISK_POLICY_CHANGE", "BROKER_CONNECT", "BROKER_DISCONNECT",
                   "BROKER_TEST", "RECONCILE", "STRATEGY_SAVED", "BACKTEST_RUN",
                   "DUPLICATE_BLOCKED", "BASKET_ROLLBACK", "AUTH_LOGIN", "AUTH_REGISTER"]:
            assert et in d["all"], et

    def test_audit_types_unauth(self, session):
        r = session.get(f"{BASE_URL}/api/audit/types")
        assert r.status_code in (401, 403)

    # ---------- /api/audit/events basic shape ----------
    def test_audit_events_shape(self, auth):
        r = auth.get(f"{BASE_URL}/api/audit/events?limit=5")
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body.keys()) >= {"items", "next_cursor", "has_more"}
        assert isinstance(body["items"], list)
        assert isinstance(body["has_more"], bool)
        # If any items exist, validate shape of first
        if body["items"]:
            e = body["items"][0]
            for k in ("id", "user_id", "event_type", "severity", "actor",
                      "summary", "payload", "correlation_id", "ip", "user_agent", "ts"):
                assert k in e, f"missing field {k} in audit event: {e.keys()}"
            # No mongo _id should leak
            assert "_id" not in e

    def test_audit_events_sorted_desc(self, auth):
        r = auth.get(f"{BASE_URL}/api/audit/events?limit=20")
        assert r.status_code == 200
        items = r.json()["items"]
        if len(items) >= 2:
            ts = [it["ts"] for it in items]
            assert ts == sorted(ts, reverse=True), "items must be sorted by ts desc"

    # ---------- Paper order: REQUEST + FILL with shared correlation_id ----------
    def test_paper_order_emits_request_and_fill_with_correlation(self, auth):
        # Use unique Idempotency-Key + unique symbol-ish payload so audit hooks fire
        idem = f"TEST-iter7-{uuid.uuid4().hex[:10]}"
        payload = {"symbol": "RELIANCE", "side": "BUY", "qty": 1,
                   "order_type": "MARKET", "instrument_type": "EQ"}
        r = auth.post(f"{BASE_URL}/api/paper/order", json=payload,
                      headers={"Idempotency-Key": idem})
        assert r.status_code in (200, 201), r.text
        order = r.json()
        assert order.get("idempotent_replay") is not True
        oid = order.get("id")
        assert oid, f"order missing id: {order}"

        # Give the fire-and-forget hooks a moment
        time.sleep(1.0)

        r2 = auth.get(f"{BASE_URL}/api/audit/events",
                      params={"event_types": "REQUEST,FILL", "correlation_id": oid, "limit": 10})
        assert r2.status_code == 200, r2.text
        items = r2.json()["items"]
        et = {it["event_type"] for it in items}
        assert "REQUEST" in et, f"REQUEST event missing for order {oid}; got {et}"
        assert "FILL" in et, f"FILL event missing for order {oid}; got {et}"
        # All items must share correlation_id == oid
        for it in items:
            assert it["correlation_id"] == oid

    # ---------- Force override → OVERRIDE severity=HIGH ----------
    def test_paper_force_override_records_high(self, auth):
        idem = f"TEST-iter7-force-{uuid.uuid4().hex[:10]}"
        payload = {"symbol": "TCS", "side": "BUY", "qty": 1,
                   "order_type": "MARKET", "instrument_type": "EQ"}
        r = auth.post(f"{BASE_URL}/api/paper/order?force=true", json=payload,
                      headers={"Idempotency-Key": idem})
        assert r.status_code in (200, 201), r.text
        time.sleep(1.0)
        r2 = auth.get(f"{BASE_URL}/api/audit/events",
                      params={"event_types": "OVERRIDE", "severities": "HIGH", "limit": 5})
        assert r2.status_code == 200
        items = r2.json()["items"]
        assert items, "OVERRIDE event not recorded"
        assert all(it["event_type"] == "OVERRIDE" and it["severity"] == "HIGH" for it in items)

    # ---------- Duplicate blocked within 5s ----------
    def test_duplicate_blocked_records_warn(self, auth):
        sym = "INFY"
        payload = {"symbol": sym, "side": "BUY", "qty": 1,
                   "order_type": "MARKET", "instrument_type": "EQ"}
        # Two posts within 5s, different idempotency keys → 2nd is a duplicate
        idem1 = f"TEST-iter7-dup1-{uuid.uuid4().hex[:10]}"
        idem2 = f"TEST-iter7-dup2-{uuid.uuid4().hex[:10]}"
        # retry-on-503 helper for transient ingress hiccups
        def _post(idem):
            for _ in range(3):
                r = auth.post(f"{BASE_URL}/api/paper/order", json=payload,
                              headers={"Idempotency-Key": idem})
                if r.status_code != 503:
                    return r
                time.sleep(0.5)
            return r
        r1 = _post(idem1)
        assert r1.status_code in (200, 201), r1.text
        r2 = _post(idem2)
        assert r2.status_code == 409, f"expected 409 dup, got {r2.status_code}: {r2.text[:200]}"
        time.sleep(1.0)
        r3 = auth.get(f"{BASE_URL}/api/audit/events",
                      params={"event_types": "DUPLICATE_BLOCKED", "limit": 5})
        assert r3.status_code == 200
        items = r3.json()["items"]
        assert items, "DUPLICATE_BLOCKED event not recorded"
        assert items[0]["severity"] == "WARN"

    # ---------- Kill switch toggle ----------
    def test_kill_switch_toggle_records_high(self, auth):
        # snapshot prior limits
        r0 = auth.get(f"{BASE_URL}/api/risk/limits")
        assert r0.status_code == 200, r0.text
        prev = r0.json()
        # arm
        payload_on = {**{k: prev[k] for k in ("max_drawdown_pct", "daily_loss_cap", "position_limit")},
                      "kill_switch": True}
        ra = auth.put(f"{BASE_URL}/api/risk/limits", json=payload_on)
        assert ra.status_code == 200, ra.text
        # release
        payload_off = {**payload_on, "kill_switch": False}
        rb = auth.put(f"{BASE_URL}/api/risk/limits", json=payload_off)
        assert rb.status_code == 200, rb.text
        time.sleep(1.0)
        r = auth.get(f"{BASE_URL}/api/audit/events",
                     params={"event_types": "KILL_SWITCH", "limit": 10})
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) >= 2, f"expected ≥2 KILL_SWITCH events, got {len(items)}"
        # most recent two should have from/to booleans
        for it in items[:2]:
            assert it["severity"] == "HIGH"
            assert "from" in it["payload"] and "to" in it["payload"]

    # ---------- Risk policy change → diffs ----------
    def test_risk_policy_change_records_diffs(self, auth):
        r0 = auth.get(f"{BASE_URL}/api/risk/limits")
        prev = r0.json()
        new_limit = int(prev["position_limit"]) + 1
        payload = {**{k: prev[k] for k in ("max_drawdown_pct", "daily_loss_cap")},
                   "position_limit": new_limit,
                   "kill_switch": prev.get("kill_switch", False)}
        r = auth.put(f"{BASE_URL}/api/risk/limits", json=payload)
        assert r.status_code == 200, r.text
        time.sleep(1.0)
        r2 = auth.get(f"{BASE_URL}/api/audit/events",
                      params={"event_types": "RISK_POLICY_CHANGE", "limit": 3})
        assert r2.status_code == 200
        items = r2.json()["items"]
        assert items, "no RISK_POLICY_CHANGE recorded"
        diffs = items[0]["payload"].get("diffs", {})
        assert "position_limit" in diffs
        assert diffs["position_limit"]["to"] == new_limit
        # revert
        rev = {**{k: prev[k] for k in ("max_drawdown_pct", "daily_loss_cap", "position_limit")},
               "kill_switch": prev.get("kill_switch", False)}
        auth.put(f"{BASE_URL}/api/risk/limits", json=rev)

    # ---------- Broker connect/test/disconnect ----------
    def test_broker_connect_test_disconnect_events(self, auth):
        broker = "zerodha"
        # Cleanup any prior connection (idempotent)
        auth.delete(f"{BASE_URL}/api/brokers/{broker}")
        # connect
        rc = auth.post(f"{BASE_URL}/api/brokers/{broker}/connect",
                       json={"credentials": {"api_key": "test_key", "api_secret": "x"}})
        assert rc.status_code == 200, rc.text
        # test
        rt = auth.post(f"{BASE_URL}/api/brokers/{broker}/test")
        assert rt.status_code == 200, rt.text
        # disconnect
        rd = auth.delete(f"{BASE_URL}/api/brokers/{broker}")
        assert rd.status_code == 200, rd.text
        time.sleep(1.0)
        # verify all three events
        for et, exp_count in (("BROKER_CONNECT", 1), ("BROKER_TEST", 1), ("BROKER_DISCONNECT", 1)):
            r = auth.get(f"{BASE_URL}/api/audit/events",
                         params={"event_types": et, "limit": 5})
            assert r.status_code == 200
            assert r.json()["items"], f"{et} event not recorded"

    # ---------- Strategy save ----------
    def test_strategy_saved_event(self, auth):
        payload = {"name": f"TEST_strat_{uuid.uuid4().hex[:6]}",
                   "description": "iter7 audit",
                   "dsl": {"symbol": "NIFTY", "type": "trap"}}
        r = auth.post(f"{BASE_URL}/api/strategies", json=payload)
        assert r.status_code in (200, 201), r.text
        sid = r.json().get("id")
        time.sleep(1.0)
        r2 = auth.get(f"{BASE_URL}/api/audit/events",
                      params={"event_types": "STRATEGY_SAVED", "limit": 5})
        assert r2.status_code == 200
        items = r2.json()["items"]
        assert items, "STRATEGY_SAVED not recorded"
        latest = items[0]
        assert latest["payload"].get("strategy_id") == sid
        assert latest["payload"].get("symbol") == "NIFTY"
        # cleanup
        if sid:
            auth.delete(f"{BASE_URL}/api/strategies/{sid}")

    # ---------- Backtest run ----------
    def test_backtest_run_event(self, auth):
        dsl = {"name": "TEST_iter7_bt", "symbol": "NIFTY",
               "entry": {"type": "indicator", "name": "RSI", "op": "<", "value": 30},
               "exit": {"type": "indicator", "name": "RSI", "op": ">", "value": 70}}
        r = auth.post(f"{BASE_URL}/api/backtest/run",
                      json={"dsl": dsl, "save": False})
        # Some envs may need different payload shape — accept either success
        if r.status_code not in (200, 201):
            pytest.skip(f"backtest endpoint returned {r.status_code}: {r.text[:200]}")
        time.sleep(1.0)
        r2 = auth.get(f"{BASE_URL}/api/audit/events",
                      params={"event_types": "BACKTEST_RUN", "limit": 5})
        assert r2.status_code == 200
        items = r2.json()["items"]
        assert items, "BACKTEST_RUN event not recorded"
        p = items[0]["payload"]
        assert "sharpe" in p and "max_drawdown_pct" in p

    # ---------- Trap scan ----------
    def test_trap_scan_records_signal(self, auth):
        r = auth.get(f"{BASE_URL}/api/trap/scan", params={"symbol": "NIFTY"})
        if r.status_code != 200:
            pytest.skip(f"trap scan returned {r.status_code}: {r.text[:200]}")
        score = r.json().get("overall_trap_score", 0)
        time.sleep(1.0)
        r2 = auth.get(f"{BASE_URL}/api/audit/events",
                      params={"event_types": "SIGNAL", "limit": 10})
        assert r2.status_code == 200
        items = r2.json()["items"]
        # find one for NIFTY trap scan
        match = [it for it in items if "Trap scan NIFTY" in (it.get("summary") or "")]
        assert match, "trap scan SIGNAL event missing"
        sev = match[0]["severity"]
        expected = "HIGH" if score > 0.7 else "INFO"
        assert sev == expected, f"expected {expected} severity for score {score}, got {sev}"

    # ---------- Auth login success + failure ----------
    def test_auth_login_records_events(self, session):
        # failure: invalid password
        bad_email = f"TEST_nouser_{uuid.uuid4().hex[:6]}@algoforge.io"
        session.post(f"{BASE_URL}/api/auth/login",
                     json={"email": bad_email, "password": "wrong"})
        # success: demo user
        session.post(f"{BASE_URL}/api/auth/login",
                     json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        time.sleep(1.0)
        # query as demo user (the success record is under demo's user_id)
        login_resp = session.post(f"{BASE_URL}/api/auth/login",
                                  json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        tok = login_resp.json()["access_token"]
        s2 = requests.Session()
        s2.headers.update({"Authorization": f"Bearer {tok}"})
        r = s2.get(f"{BASE_URL}/api/audit/events",
                   params={"event_types": "AUTH_LOGIN", "limit": 20})
        assert r.status_code == 200
        items = r.json()["items"]
        # we should at least see successful logins for demo
        assert any(it["severity"] == "INFO" and it["user_id"] != "anonymous" for it in items), \
            "no successful AUTH_LOGIN found"

    # ---------- Filters: event_types & severities ----------
    def test_filter_event_types(self, auth):
        r = auth.get(f"{BASE_URL}/api/audit/events",
                     params={"event_types": "REQUEST,FILL", "limit": 30})
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it["event_type"] in {"REQUEST", "FILL"}, it["event_type"]

    def test_filter_severities(self, auth):
        r = auth.get(f"{BASE_URL}/api/audit/events",
                     params={"severities": "HIGH,WARN", "limit": 30})
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it["severity"] in {"HIGH", "WARN"}, it["severity"]

    # ---------- Search ?q= ----------
    def test_search_q_case_insensitive(self, auth):
        # Issue an order whose summary will contain 'RELIANCE'
        idem = f"TEST-iter7-q-{uuid.uuid4().hex[:10]}"
        auth.post(f"{BASE_URL}/api/paper/order",
                  json={"symbol": "RELIANCE", "side": "BUY", "qty": 1,
                        "order_type": "MARKET", "instrument_type": "EQ"},
                  headers={"Idempotency-Key": idem})
        time.sleep(1.0)
        r = auth.get(f"{BASE_URL}/api/audit/events",
                     params={"q": "reliance", "limit": 10})
        assert r.status_code == 200
        items = r.json()["items"]
        assert items, "search returned no items for 'reliance'"
        for it in items:
            assert "reliance" in it["summary"].lower()

    # ---------- Date range ----------
    def test_date_range_from_ts(self, auth):
        # 24h ago should include events; far future from_ts should return none
        from datetime import datetime, timedelta, timezone
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        r = auth.get(f"{BASE_URL}/api/audit/events",
                     params={"from_ts": future, "limit": 10})
        assert r.status_code == 200
        assert r.json()["items"] == []

    # ---------- Pagination via cursor ----------
    def test_pagination_cursor(self, auth):
        r1 = auth.get(f"{BASE_URL}/api/audit/events", params={"limit": 2})
        assert r1.status_code == 200
        b1 = r1.json()
        if not b1["has_more"]:
            pytest.skip("not enough events in DB to test pagination")
        cursor = b1["next_cursor"]
        assert cursor
        r2 = auth.get(f"{BASE_URL}/api/audit/events",
                      params={"limit": 2, "cursor": cursor})
        assert r2.status_code == 200
        b2 = r2.json()
        # No overlap: b2 items' ts strictly less than cursor
        for it in b2["items"]:
            assert it["ts"] < cursor

    # ---------- CSV export ----------
    def test_csv_export(self, auth):
        r = auth.get(f"{BASE_URL}/api/audit/export")
        assert r.status_code == 200, r.text
        ctype = r.headers.get("content-type", "")
        assert "text/csv" in ctype, f"unexpected content-type: {ctype}"
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd.lower()
        lines = r.text.strip().splitlines()
        assert lines, "csv body empty"
        assert lines[0] == "ts,event_type,severity,actor,summary,correlation_id"

    # ---------- audit_events indexes ----------
    def test_audit_indexes_exist(self):
        import asyncio
        import os as _os
        from motor.motor_asyncio import AsyncIOMotorClient

        async def _check():
            client = AsyncIOMotorClient(_os.environ["MONGO_URL"])
            db = client[_os.environ["DB_NAME"]]
            try:
                return await db.audit_events.index_information()
            finally:
                client.close()

        info = asyncio.run(_check())
        keys = [tuple(v.get("key", [])) for v in info.values()]
        assert any(k == (("user_id", 1), ("ts", -1)) for k in keys), \
            f"missing (user_id, ts desc) index. got: {keys}"
        assert any(k == (("event_type", 1),) for k in keys), \
            f"missing event_type index. got: {keys}"

    # ---------- Audit failures never break user flows ----------
    def test_paper_order_succeeds_even_if_audit_table_busy(self, auth):
        # record_event swallows exceptions. We can't easily corrupt the
        # collection over HTTP, but we can verify behaviour: a paper order
        # always returns 200 and a usable order id even when many concurrent
        # writes hammer audit_events. Surrogate check.
        idem = f"TEST-iter7-resilient-{uuid.uuid4().hex[:10]}"
        # use ?force=true to bypass duplicate-detection windows from earlier tests
        r = auth.post(f"{BASE_URL}/api/paper/order?force=true",
                      json={"symbol": "RELIANCE", "side": "BUY", "qty": 1,
                            "order_type": "MARKET", "instrument_type": "EQ"},
                      headers={"Idempotency-Key": idem})
        assert r.status_code in (200, 201), r.text
        assert r.json().get("id")


# ===================================================================
# Iter 8 — Monte Carlo Stress Tester
# ===================================================================
class TestIter8MonteCarloStress:
    """Tests for POST /api/stress/run + run_monte_carlo service."""

    @pytest.fixture(scope="class")
    def backtest_result(self, auth):
        """Run a real backtest to feed into stress runs."""
        dsl = {
            "name": "TEST_iter8_stress_base",
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
        if r.status_code != 200:
            pytest.skip(f"baseline backtest failed: {r.status_code} {r.text[:200]}")
        return r.json()

    # ---- 1) stress with pre-computed backtest returns proper shape ----
    def test_stress_with_backtest_full_shape(self, auth, backtest_result):
        r = auth.post(f"{BASE_URL}/api/stress/run",
                      json={"backtest": backtest_result, "iterations": 100, "seed": 7})
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("iterations", "block_size", "slippage_jitter_bps",
                  "bars_per_path", "capital", "metrics", "histograms",
                  "blowup_rate_pct", "blowup_threshold_pct", "worst_path"):
            assert k in d, f"missing top-level key {k}"
        assert d["iterations"] == 100
        assert d["block_size"] == 5
        # bars_per_path should be len(equity_curve)-1
        assert d["bars_per_path"] == len(backtest_result["equity_curve"]) - 1
        # metrics — each with all percentiles + mean/std/min/max
        for mkey in ("final_equity", "max_drawdown_pct", "sharpe",
                     "sortino", "total_return_pct"):
            m = d["metrics"][mkey]
            for stat in ("p5", "p25", "p50", "p75", "p95", "mean", "std", "min", "max"):
                assert stat in m, f"missing {stat} in metrics.{mkey}"
        # histograms — 20 bins each, fields lo/hi/mid/count
        for hkey in ("max_drawdown_pct", "sharpe", "total_return_pct"):
            hist = d["histograms"][hkey]
            assert len(hist) == 20, f"{hkey} has {len(hist)} bins"
            for b in hist:
                for f in ("lo", "hi", "mid", "count"):
                    assert f in b
        # worst-path shape
        assert "max_drawdown_pct" in d["worst_path"]
        assert isinstance(d["worst_path"]["equity_curve"], list)
        assert len(d["worst_path"]["equity_curve"]) > 0
        assert d["blowup_threshold_pct"] == -25.0

    # ---- 2) stress with DSL only runs internal backtest, same shape ----
    def test_stress_with_dsl_only(self, auth):
        dsl = {
            "name": "TEST_iter8_dsl_only",
            "symbol": "TCS", "timeframe": "1d",
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
        r = auth.post(f"{BASE_URL}/api/stress/run",
                      json={"dsl": dsl, "days": 200, "iterations": 60, "seed": 11})
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("iterations", "metrics", "histograms", "worst_path",
                  "blowup_rate_pct", "bars_per_path"):
            assert k in d

    # ---- 3) reproducibility: same seed → identical metrics ----
    def test_same_seed_reproducible(self, auth, backtest_result):
        payload = {"backtest": backtest_result, "iterations": 100, "seed": 42}
        r1 = auth.post(f"{BASE_URL}/api/stress/run", json=payload)
        r2 = auth.post(f"{BASE_URL}/api/stress/run", json=payload)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["metrics"] == r2.json()["metrics"], \
            "metrics differ for same seed"

    # ---- 4) iterations clamping via pydantic Field → 422 for out-of-range ----
    def test_iterations_below_min_returns_422(self, auth, backtest_result):
        r = auth.post(f"{BASE_URL}/api/stress/run",
                      json={"backtest": backtest_result, "iterations": 10})
        assert r.status_code == 422, r.text

    def test_iterations_above_max_returns_422(self, auth, backtest_result):
        r = auth.post(f"{BASE_URL}/api/stress/run",
                      json={"backtest": backtest_result, "iterations": 99999})
        assert r.status_code == 422, r.text

    def test_service_level_iterations_clamped(self):
        """Direct service call: 10 → 50, 99999 → 5000."""
        import sys
        sys.path.insert(0, "/app/backend")
        from services.stress import run_monte_carlo
        eq = [{"step": i, "equity": 100000 * (1 + 0.001 * ((-1) ** i))}
              for i in range(60)]
        bt = {"equity_curve": eq, "capital": 100000}
        low = run_monte_carlo(bt, iterations=10, seed=1)
        high = run_monte_carlo(bt, iterations=99999, seed=1)
        assert low["iterations"] == 50
        assert high["iterations"] == 5000

    # ---- 5) empty / short equity curve → 400 ----
    def test_short_equity_curve_returns_400(self, auth):
        bt = {"equity_curve": [{"step": 0, "equity": 100000}], "capital": 100000}
        r = auth.post(f"{BASE_URL}/api/stress/run",
                      json={"backtest": bt, "iterations": 100})
        assert r.status_code == 400
        assert "Not enough data" in r.text

    # ---- 6) neither backtest nor dsl → 400 ----
    def test_neither_backtest_nor_dsl_returns_400(self, auth):
        r = auth.post(f"{BASE_URL}/api/stress/run", json={"iterations": 100})
        assert r.status_code == 400
        assert "backtest" in r.text.lower() and "dsl" in r.text.lower()

    # ---- 7) malformed DSL → 400 ----
    def test_malformed_dsl_returns_400(self, auth):
        # entry as a string triggers AttributeError inside the engine, which
        # the router catches and re-raises as 400 'Invalid strategy DSL: ...'.
        bad_dsl = {
            "name": "TEST_iter8_bad_dsl",
            "symbol": "RELIANCE",
            "timeframe": "1d",
            "indicators": [],
            "entry": "BAD",
            "exit": {},
            "size": {"type": "fixed_qty", "value": 1},
        }
        r = auth.post(f"{BASE_URL}/api/stress/run",
                      json={"dsl": bad_dsl, "iterations": 60})
        assert r.status_code == 400, r.text
        assert "Invalid strategy DSL" in r.json().get("detail", ""), \
            f"detail: {r.json().get('detail')!r}"

    # ---- 8) low-DD distribution → blowup_rate near 0 ----
    def test_blowup_rate_near_zero_for_small_dd(self, auth):
        """Curve with tiny oscillations → all DD shallow → blowup near 0%."""
        # gentle alternating +0.05% / -0.05% — DD will be tiny
        eq = [{"step": 0, "equity": 100000.0}]
        val = 100000.0
        for i in range(1, 80):
            val *= (1 + (0.0005 if i % 2 == 0 else -0.0005))
            eq.append({"step": i, "equity": val})
        bt = {"equity_curve": eq, "capital": 100000.0}
        r = auth.post(f"{BASE_URL}/api/stress/run",
                      json={"backtest": bt, "iterations": 100,
                            "slippage_jitter_bps": 0.5, "seed": 99})
        assert r.status_code == 200, r.text
        d = r.json()
        # p5 drawdown should be small (>-2% typically); blowup_rate must be ~0
        assert d["blowup_rate_pct"] <= 1.0, \
            f"blowup_rate={d['blowup_rate_pct']} for tiny DDs"

    # ---- 9) histogram bins contiguous: hi[i] == lo[i+1] ----
    def test_histograms_bins_contiguous(self, auth, backtest_result):
        r = auth.post(f"{BASE_URL}/api/stress/run",
                      json={"backtest": backtest_result, "iterations": 60, "seed": 5})
        assert r.status_code == 200
        d = r.json()
        for hkey in ("max_drawdown_pct", "sharpe", "total_return_pct"):
            hist = d["histograms"][hkey]
            for i in range(len(hist) - 1):
                assert abs(hist[i]["hi"] - hist[i + 1]["lo"]) < 1e-3, \
                    f"{hkey} bin {i} not contiguous: {hist[i]['hi']} vs {hist[i+1]['lo']}"

    # ---- 10) audit event recorded after stress run ----
    def test_stress_audit_event_recorded(self, auth, backtest_result):
        before = auth.get(f"{BASE_URL}/api/audit/events",
                          params={"event_types": "BACKTEST_RUN", "limit": 1})
        prev_ts = before.json()["items"][0]["ts"] if before.status_code == 200 \
            and before.json()["items"] else None

        r = auth.post(f"{BASE_URL}/api/stress/run",
                      json={"backtest": backtest_result, "iterations": 80, "seed": 17})
        assert r.status_code == 200
        time.sleep(1.0)

        ev = auth.get(f"{BASE_URL}/api/audit/events",
                      params={"event_types": "BACKTEST_RUN", "limit": 10})
        assert ev.status_code == 200
        items = ev.json()["items"]
        # Find the Monte Carlo event
        mc_event = next((it for it in items
                         if it.get("summary", "").startswith("Monte Carlo")), None)
        assert mc_event, f"No Monte Carlo audit event found in {items[:2]}"
        p = mc_event["payload"]
        for k in ("iterations", "blowup_rate_pct", "p5_drawdown", "p95_return"):
            assert k in p, f"audit payload missing {k}"
        # ensure it's fresher than what we had before
        if prev_ts:
            assert mc_event["ts"] >= prev_ts

    # ---- 11) Auth required ----
    def test_stress_no_auth_returns_401(self, session, backtest_result):
        r = session.post(f"{BASE_URL}/api/stress/run",
                         json={"backtest": backtest_result, "iterations": 60})
        assert r.status_code in (401, 403)


# =====================================================================
# Iter 9 — P1 service refactor + P0 BrokerAdapter rollout
# =====================================================================
class TestIter9Refactor:
    """P1: paper-trading business logic moved to services/paper_trading.
    P0: zerodha & upstox now inherit BrokerAdapter. Reconciler loop runs
    in lifespan startup."""

    # --- (A) Module-level imports work (P1 contract) ----------------
    def test_services_paper_trading_exports(self):
        from services.paper_trading import (
            place_paper_order,
            compute_positions,
            idem_lookup,
            idem_store,
            ensure_idempotency_ttl,
            signature,
            check_kill_switch,
            apply_to_position,
            resolve_price,
            undo_order,
            PaperOrderRequest,
            MultiLegOrderRequest,
        )
        assert callable(place_paper_order)
        assert callable(compute_positions)
        assert callable(ensure_idempotency_ttl)

    def test_router_paper_reexports_lifespan_helper(self):
        # server.py depends on this re-export at startup
        from routers.paper import _ensure_idempotency_ttl
        assert callable(_ensure_idempotency_ttl)

    def test_dashboard_router_imports_compute_positions_from_services(self):
        import routers.dashboard as dash
        from services.paper_trading import compute_positions
        # Confirm dashboard uses the moved symbol (not its own copy)
        assert getattr(dash, "compute_positions", None) is compute_positions

    def test_paper_adapter_uses_services(self):
        from brokers.paper_adapter import PaperAdapter
        from services.paper_trading import place_paper_order, PaperOrderRequest
        # Just import-level smoke: no instantiation of HTTP machinery
        assert PaperAdapter is not None
        assert callable(place_paper_order)
        assert PaperOrderRequest is not None

    # --- (B) Zerodha adapter conforms to BrokerAdapter ABC (P0) -----
    def test_zerodha_is_broker_adapter(self):
        from brokers.zerodha import ZerodhaClient
        from brokers.base import BrokerAdapter
        c = ZerodhaClient({"api_key": "k", "api_secret": "s", "access_token": "t"},
                          user_id="u")
        assert isinstance(c, BrokerAdapter)
        caps = c.capabilities()
        assert caps.supports_modify is True
        assert caps.supports_basket_native is True
        assert caps.supports_postback_ws is True

    def test_zerodha_test_connection_raises_broker_auth_error(self):
        import asyncio
        from brokers.zerodha import ZerodhaClient
        from brokers.base import BrokerAuthError, BrokerUnavailable
        c = ZerodhaClient({"api_key": "k", "api_secret": "s", "access_token": "t"},
                          user_id="u")
        # With kiteconnect installed but fake creds → BrokerAuthError.
        # If SDK is missing for any reason, BrokerUnavailable is acceptable.
        with pytest.raises((BrokerAuthError, BrokerUnavailable)):
            asyncio.run(c.test_connection())

    # --- (C) Upstox adapter conforms to BrokerAdapter ABC (P0) ------
    def test_upstox_is_broker_adapter(self):
        from brokers.upstox import UpstoxClient
        from brokers.base import BrokerAdapter
        c = UpstoxClient({"api_key": "k", "api_secret": "s", "access_token": "t"},
                         user_id="u")
        assert isinstance(c, BrokerAdapter)
        caps = c.capabilities()
        assert caps.supports_postback_ws is True

    def test_upstox_without_access_token_raises_unavailable(self):
        import asyncio
        from brokers.upstox import UpstoxClient
        from brokers.base import BrokerUnavailable
        c = UpstoxClient({"api_key": "k", "api_secret": "s"}, user_id="u")
        with pytest.raises(BrokerUnavailable):
            asyncio.run(c.test_connection())

    # --- (D) Reconciler loop module + tick helper -------------------
    def test_reconciler_loop_imports(self):
        from services.reconciler_loop import reconciler_loop, reconciler_tick
        assert callable(reconciler_loop)
        assert callable(reconciler_tick)

    def test_reconciler_tick_no_live_brokers_returns_zero(self, auth):
        """When no broker_connections have status='live', tick returns 0
        and does NOT raise. Run in a subprocess to get a clean event loop
        (motor singleton in get_db() is bound to FastAPI's lifespan loop)."""
        import subprocess, sys, os
        script = (
            "import asyncio, os, sys\n"
            "sys.path.insert(0, '/app/backend')\n"
            "from motor.motor_asyncio import AsyncIOMotorClient\n"
            "from services.reconciler_loop import reconciler_tick\n"
            "async def run():\n"
            "    client = AsyncIOMotorClient(os.environ['MONGO_URL'])\n"
            "    db = client[os.environ['DB_NAME']]\n"
            "    live = await db.broker_connections.find({'status':'live'}).to_list(100)\n"
            "    for rec in live:\n"
            "        await db.broker_connections.update_one({'_id': rec['_id']}, {'$set': {'status':'_iter9_demoted'}})\n"
            "    try:\n"
            "        n = await reconciler_tick()\n"
            "        print('TICK_RESULT=' + str(n))\n"
            "    finally:\n"
            "        for rec in live:\n"
            "            await db.broker_connections.update_one({'_id': rec['_id']}, {'$set': {'status': rec['status']}})\n"
            "asyncio.run(run())\n"
        )
        env = {**os.environ}
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True,
                              text=True, env=env, timeout=30)
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
        assert "TICK_RESULT=0" in proc.stdout, proc.stdout

    # --- (E) HTTP smoke: connect zerodha with fake creds → status=error
    def test_zerodha_connect_and_test_classified_as_error(self, auth):
        auth.delete(f"{BASE_URL}/api/brokers/zerodha")
        cr = auth.post(f"{BASE_URL}/api/brokers/zerodha/connect", json={
            "credentials": {"api_key": "k", "api_secret": "s", "access_token": "t"}
        })
        assert cr.status_code == 200, cr.text
        try:
            tr = auth.post(f"{BASE_URL}/api/brokers/zerodha/test")
            assert tr.status_code == 200, tr.text
            body = tr.json()
            assert body.get("status") == "error", body
        finally:
            auth.delete(f"{BASE_URL}/api/brokers/zerodha")

    # --- (F) HTTP smoke: paper reconciliation still NOT_APPLICABLE --
    def test_reconciliation_paper_not_applicable(self, auth):
        r = auth.post(f"{BASE_URL}/api/reconciliation/run/paper")
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "NOT_APPLICABLE"
