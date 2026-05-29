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
