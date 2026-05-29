"""Backend regression tests for AlgoForge MVP."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://quant-hybrid-trade.preview.emergentagent.com").rstrip("/")
DEMO_EMAIL = "demo@algoforge.io"
DEMO_PASSWORD = "Demo@123"


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
        r = auth.post(f"{BASE_URL}/api/paper/order", json={
            "symbol": "NIFTY", "side": "BUY", "qty": 50, "instrument_type": "EQ"})
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
        r = auth.post(f"{BASE_URL}/api/paper/order/multi-leg", json=payload)
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

