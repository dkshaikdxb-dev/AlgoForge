"""Lightweight backtest engine. Supports a tiny strategy DSL.

DSL schema (produced by GPT-5.2):
{
  "name": "string",
  "symbol": "NIFTY",
  "indicators": [
    {"id":"sma_fast","type":"sma","period":10,"source":"close"},
    {"id":"sma_slow","type":"sma","period":30,"source":"close"},
    {"id":"rsi14","type":"rsi","period":14,"source":"close"}
  ],
  "entry":  {"op":"and","rules":[{"left":"sma_fast","cmp":">","right":"sma_slow"}]},
  "exit":   {"op":"or", "rules":[{"left":"sma_fast","cmp":"<","right":"sma_slow"}]},
  "size":   {"type":"fixed_qty","value":1},
  "stop_loss_pct": 2.0,
  "take_profit_pct": 5.0
}
"""
from __future__ import annotations

import math
from typing import Any

from market_data import get_ohlcv


# ---- indicators ----

def _sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= period:
            s -= values[i - period]
        out.append(s / period if i >= period - 1 else None)
    return out


def _ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    k = 2 / (period + 1)
    ema = None
    for i, v in enumerate(values):
        if i < period - 1:
            out.append(None)
            continue
        if ema is None:
            ema = sum(values[: period]) / period
        else:
            ema = v * k + ema * (1 - k)
        out.append(ema)
    return out


def _rsi(values: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    avg_g = gains / period
    avg_l = losses / period
    rs = avg_g / avg_l if avg_l else 100
    out[period] = 100 - 100 / (1 + rs)
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        gain = max(d, 0)
        loss = max(-d, 0)
        avg_g = (avg_g * (period - 1) + gain) / period
        avg_l = (avg_l * (period - 1) + loss) / period
        rs = avg_g / avg_l if avg_l else 100
        out[i] = 100 - 100 / (1 + rs)
    return out


def _compute_indicators(dsl: dict, closes: list[float]) -> dict[str, list]:
    result: dict[str, list] = {"close": closes}
    for idx, ind in enumerate(dsl.get("indicators", [])):
        t = (ind.get("type") or "").lower()
        period = int(ind.get("period", 14))
        ind_id = ind.get("id") or ind.get("name") or f"{t}_{period}_{idx}"
        if t == "sma":
            result[ind_id] = _sma(closes, period)
        elif t == "ema":
            result[ind_id] = _ema(closes, period)
        elif t == "rsi":
            result[ind_id] = _rsi(closes, period)
    return result


def _val(token: Any, series: dict, i: int):
    if isinstance(token, (int, float)):
        return float(token)
    if isinstance(token, str):
        s = series.get(token)
        if s is None:
            try:
                return float(token)
            except ValueError:
                return None
        return s[i]
    return None


def _eval_rule(rule: dict, series: dict, i: int) -> bool:
    if "op" in rule:
        op = rule["op"].lower()
        results = [_eval_rule(r, series, i) for r in rule.get("rules", [])]
        return all(results) if op == "and" else any(results)
    left = _val(rule.get("left"), series, i)
    right = _val(rule.get("right"), series, i)
    if left is None or right is None:
        return False
    cmp = rule.get("cmp", ">")
    if cmp == ">":
        return left > right
    if cmp == "<":
        return left < right
    if cmp == ">=":
        return left >= right
    if cmp == "<=":
        return left <= right
    if cmp in ("==", "="):
        return abs(left - right) < 1e-9
    return False


# ---- engine ----

def run_backtest(dsl: dict, *, capital: float = 500000.0, slippage_bps: float = 5.0,
                 fee_bps: float = 2.0, days: int = 180) -> dict:
    symbol = dsl.get("symbol", "NIFTY")
    candles = get_ohlcv(symbol, days=days)
    if not candles:
        return {"error": f"No data for {symbol}"}

    closes = [c["close"] for c in candles]
    series = _compute_indicators(dsl, closes)
    qty = int(dsl.get("size", {}).get("value", 1))
    sl_pct = float(dsl.get("stop_loss_pct") or 0)
    tp_pct = float(dsl.get("take_profit_pct") or 0)

    equity = capital
    cash = capital
    position = 0  # qty held
    entry_price = 0.0
    trades = []
    equity_curve = []
    peak = capital

    slip = slippage_bps / 10000.0
    fee = fee_bps / 10000.0

    entry_rule = dsl.get("entry") or {"op": "and", "rules": []}
    exit_rule = dsl.get("exit") or {"op": "or", "rules": []}

    for i, candle in enumerate(candles):
        price = candle["close"]

        # Mark-to-market equity
        mtm = cash + position * price
        equity = mtm
        peak = max(peak, equity)
        equity_curve.append({"date": candle["date"], "equity": round(equity, 2), "close": price})

        if position == 0:
            if _eval_rule(entry_rule, series, i):
                exec_price = price * (1 + slip)
                cost = exec_price * qty * (1 + fee)
                if cost <= cash:
                    cash -= cost
                    position = qty
                    entry_price = exec_price
                    trades.append({
                        "date": candle["date"],
                        "side": "BUY",
                        "qty": qty,
                        "price": round(exec_price, 2),
                        "pnl": None,
                    })
        else:
            should_exit = _eval_rule(exit_rule, series, i)
            ret = (price - entry_price) / entry_price * 100
            if sl_pct and ret <= -sl_pct:
                should_exit = True
            if tp_pct and ret >= tp_pct:
                should_exit = True
            if should_exit:
                exec_price = price * (1 - slip)
                proceeds = exec_price * position * (1 - fee)
                pnl = (exec_price - entry_price) * position - (exec_price + entry_price) * position * fee
                cash += proceeds
                trades.append({
                    "date": candle["date"],
                    "side": "SELL",
                    "qty": position,
                    "price": round(exec_price, 2),
                    "pnl": round(pnl, 2),
                })
                position = 0
                entry_price = 0.0

    # close any open position at last price
    if position > 0:
        last = closes[-1]
        exec_price = last * (1 - slip)
        proceeds = exec_price * position * (1 - fee)
        pnl = (exec_price - entry_price) * position - (exec_price + entry_price) * position * fee
        cash += proceeds
        trades.append({
            "date": candles[-1]["date"], "side": "SELL", "qty": position,
            "price": round(exec_price, 2), "pnl": round(pnl, 2),
        })
        position = 0

    final_equity = cash
    pnl_trades = [t["pnl"] for t in trades if t.get("pnl") is not None]
    wins = [p for p in pnl_trades if p > 0]
    losses = [p for p in pnl_trades if p <= 0]

    returns = []
    for i in range(1, len(equity_curve)):
        a, b = equity_curve[i - 1]["equity"], equity_curve[i]["equity"]
        returns.append((b - a) / a if a else 0.0)

    mean_r = sum(returns) / len(returns) if returns else 0.0
    var = sum((r - mean_r) ** 2 for r in returns) / len(returns) if returns else 0.0
    std = math.sqrt(var)
    downside = [r for r in returns if r < 0]
    dn_std = math.sqrt(sum(r * r for r in downside) / len(downside)) if downside else 0.0
    sharpe = (mean_r / std) * math.sqrt(252) if std else 0.0
    sortino = (mean_r / dn_std) * math.sqrt(252) if dn_std else 0.0

    # max drawdown
    pk = equity_curve[0]["equity"] if equity_curve else capital
    max_dd = 0.0
    for pt in equity_curve:
        pk = max(pk, pt["equity"])
        dd = (pt["equity"] - pk) / pk * 100
        max_dd = min(max_dd, dd)

    return {
        "symbol": symbol,
        "capital": capital,
        "final_equity": round(final_equity, 2),
        "total_return_pct": round((final_equity - capital) / capital * 100, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "total_trades": len(pnl_trades),
        "win_rate_pct": round(len(wins) / len(pnl_trades) * 100, 2) if pnl_trades else 0.0,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else 0.0,
        "equity_curve": equity_curve,
        "trades": trades,
    }
