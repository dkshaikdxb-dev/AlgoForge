"""Mock market data: OHLCV history + live tick + options chain with Greeks.

Deterministic per-symbol seed so charts and chains are stable across reloads.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import List

SYMBOLS = {
    "NIFTY": {"name": "NIFTY 50", "base": 22150.0, "vol": 0.011, "lot": 50, "step": 50},
    "BANKNIFTY": {"name": "BANK NIFTY", "base": 47200.0, "vol": 0.015, "lot": 15, "step": 100},
    "RELIANCE": {"name": "Reliance Industries", "base": 2890.0, "vol": 0.014, "lot": 250, "step": 20},
    "TCS": {"name": "Tata Consultancy", "base": 3940.0, "vol": 0.010, "lot": 175, "step": 20},
    "HDFCBANK": {"name": "HDFC Bank", "base": 1510.0, "vol": 0.012, "lot": 550, "step": 10},
    "INFY": {"name": "Infosys", "base": 1750.0, "vol": 0.013, "lot": 300, "step": 10},
}


def _seed(symbol: str) -> int:
    return sum(ord(c) for c in symbol) * 7919


def get_symbols() -> list[dict]:
    return [
        {"symbol": s, "name": v["name"], "ltp": round(v["base"], 2)}
        for s, v in SYMBOLS.items()
    ]


def get_ohlcv(symbol: str, days: int = 180) -> List[dict]:
    cfg = SYMBOLS.get(symbol.upper())
    if not cfg:
        return []
    rng = random.Random(_seed(symbol))
    price = cfg["base"]
    vol = cfg["vol"]
    out = []
    today = datetime.now(timezone.utc).date()
    # walk backwards then forwards
    start = today - timedelta(days=days)
    p = price * (1 - vol * 4)  # start lower so we drift up
    for i in range(days):
        d = start + timedelta(days=i)
        drift = rng.gauss(0.0006, vol)
        o = p
        c = max(o * (1 + drift), 0.01)
        h = max(o, c) * (1 + abs(rng.gauss(0, vol * 0.4)))
        low = min(o, c) * (1 - abs(rng.gauss(0, vol * 0.4)))
        v = int(rng.uniform(500_000, 5_000_000))
        out.append(
            {
                "date": d.isoformat(),
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(low, 2),
                "close": round(c, 2),
                "volume": v,
            }
        )
        p = c
    return out


def get_last_price(symbol: str) -> float:
    series = get_ohlcv(symbol, days=30)
    return series[-1]["close"] if series else 0.0


# --- Options chain (Black-Scholes-lite) ---

def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _bs_price_greeks(S: float, K: float, T: float, r: float, sigma: float, kind: str):
    if T <= 0 or sigma <= 0:
        intrinsic = max(0.0, (S - K) if kind == "CE" else (K - S))
        return {"price": intrinsic, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "iv": sigma}
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    pdf = math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi)
    if kind == "CE":
        price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        theta = (-S * pdf * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * _norm_cdf(d2)) / 365
    else:
        price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1
        theta = (-S * pdf * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * _norm_cdf(-d2)) / 365
    gamma = pdf / (S * sigma * math.sqrt(T))
    vega = S * pdf * math.sqrt(T) / 100
    return {
        "price": round(price, 2),
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 3),
        "vega": round(vega, 3),
        "iv": round(sigma * 100, 2),
    }


def get_options_chain(symbol: str, expiry_days: int = 7) -> dict:
    """Return strikes around spot with CE/PE OI, IV, Greeks (mocked deterministically)."""
    symbol = symbol.upper()
    cfg = SYMBOLS.get(symbol)
    if not cfg:
        return {"symbol": symbol, "spot": 0.0, "expiry": None, "rows": []}
    spot = get_last_price(symbol)
    step = cfg["step"]
    atm = round(spot / step) * step
    rng = random.Random(_seed(symbol) + expiry_days)
    T = expiry_days / 365.0
    r = 0.065
    base_iv = 0.18 + rng.uniform(-0.03, 0.05)

    rows = []
    for k_off in range(-7, 8):
        K = atm + k_off * step
        # IV smile
        smile = 0.0008 * (k_off ** 2)
        iv_ce = max(0.05, base_iv + smile + rng.uniform(-0.01, 0.01))
        iv_pe = max(0.05, base_iv + smile + rng.uniform(-0.01, 0.01))
        ce = _bs_price_greeks(spot, K, T, r, iv_ce, "CE")
        pe = _bs_price_greeks(spot, K, T, r, iv_pe, "PE")
        # Mock OI: piles near ATM, heavier on OTM calls/puts depending on regime
        ce_oi = int(max(0, rng.gauss(80000, 30000)) * math.exp(-(k_off ** 2) / 20)) + rng.randint(0, 50000)
        pe_oi = int(max(0, rng.gauss(80000, 30000)) * math.exp(-(k_off ** 2) / 20)) + rng.randint(0, 50000)
        # induce writer buildup on a couple of OTM strikes
        if k_off in (2, 3):
            ce_oi = int(ce_oi * 2.4)
        if k_off in (-2, -3):
            pe_oi = int(pe_oi * 2.1)
        ce_chg = int(rng.gauss(0, ce_oi * 0.15))
        pe_chg = int(rng.gauss(0, pe_oi * 0.15))
        # If buildup strikes, force positive OI change (writers piling in)
        if k_off in (2, 3):
            ce_chg = abs(ce_chg) + int(ce_oi * 0.25)
        if k_off in (-2, -3):
            pe_chg = abs(pe_chg) + int(pe_oi * 0.22)

        rows.append(
            {
                "strike": int(K),
                "ce": {**ce, "oi": ce_oi, "oi_change": ce_chg, "volume": rng.randint(5000, 80000)},
                "pe": {**pe, "oi": pe_oi, "oi_change": pe_chg, "volume": rng.randint(5000, 80000)},
            }
        )

    expiry = (datetime.now(timezone.utc) + timedelta(days=expiry_days)).date().isoformat()
    return {
        "symbol": symbol,
        "name": cfg["name"],
        "spot": round(spot, 2),
        "atm": int(atm),
        "step": step,
        "expiry": expiry,
        "rows": rows,
    }
