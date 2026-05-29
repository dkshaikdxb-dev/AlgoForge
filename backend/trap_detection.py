"""Option Writers' Trap Detection.

Heuristic: detects strikes with heavy OI buildup (writers piling in) that are at
risk of being squeezed by a price breakout. Returns per-strike trap probability
and aggregated zones with hedging suggestions.
"""
from __future__ import annotations

from market_data import get_ohlcv, get_options_chain


def _recent_range(symbol: str) -> dict:
    candles = get_ohlcv(symbol, days=20)
    if not candles:
        return {"high20": 0, "low20": 0, "close": 0, "atr": 0}
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    trs = []
    for i in range(1, len(candles)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    atr = sum(trs) / len(trs) if trs else 0
    return {
        "high20": max(highs),
        "low20": min(lows),
        "close": closes[-1],
        "atr": atr,
    }


def scan_traps(symbol: str, expiry_days: int = 7) -> dict:
    chain = get_options_chain(symbol, expiry_days=expiry_days)
    if not chain.get("rows"):
        return {"symbol": symbol, "error": "no chain data"}

    rng = _recent_range(symbol)
    spot = chain["spot"]
    atm = chain["atm"]

    # baseline OI to normalise
    max_ce_oi = max(r["ce"]["oi"] for r in chain["rows"]) or 1
    max_pe_oi = max(r["pe"]["oi"] for r in chain["rows"]) or 1

    rows = []
    for r in chain["rows"]:
        K = r["strike"]
        # Call-writer trap: heavy CE OI buildup ABOVE spot, price approaching from below
        ce_buildup = r["ce"]["oi"] / max_ce_oi
        ce_change_score = max(0.0, r["ce"]["oi_change"]) / (max_ce_oi * 0.5)
        proximity_above = max(0.0, 1 - abs(K - spot) / max(rng["atr"] * 3, 1))
        ce_breakout_pressure = 1.0 if spot >= rng["high20"] * 0.985 and K >= spot else 0.6
        ce_trap = min(1.0, (0.45 * ce_buildup + 0.35 * ce_change_score + 0.20 * proximity_above) * ce_breakout_pressure)
        ce_trap = round(ce_trap if K >= atm else ce_trap * 0.4, 3)

        # Put-writer trap: heavy PE OI BELOW spot, price approaching from above
        pe_buildup = r["pe"]["oi"] / max_pe_oi
        pe_change_score = max(0.0, r["pe"]["oi_change"]) / (max_pe_oi * 0.5)
        proximity_below = max(0.0, 1 - abs(spot - K) / max(rng["atr"] * 3, 1))
        pe_breakdown_pressure = 1.0 if spot <= rng["low20"] * 1.015 and K <= spot else 0.6
        pe_trap = min(1.0, (0.45 * pe_buildup + 0.35 * pe_change_score + 0.20 * proximity_below) * pe_breakdown_pressure)
        pe_trap = round(pe_trap if K <= atm else pe_trap * 0.4, 3)

        rows.append({
            "strike": K,
            "ce_oi": r["ce"]["oi"],
            "ce_oi_change": r["ce"]["oi_change"],
            "ce_iv": r["ce"]["iv"],
            "ce_trap": ce_trap,
            "pe_oi": r["pe"]["oi"],
            "pe_oi_change": r["pe"]["oi_change"],
            "pe_iv": r["pe"]["iv"],
            "pe_trap": pe_trap,
            "combined": round(max(ce_trap, pe_trap), 3),
        })

    top_ce = sorted([r for r in rows if r["strike"] >= atm], key=lambda x: -x["ce_trap"])[:3]
    top_pe = sorted([r for r in rows if r["strike"] <= atm], key=lambda x: -x["pe_trap"])[:3]

    suggestions = []
    if top_ce and top_ce[0]["ce_trap"] > 0.55:
        s = top_ce[0]["strike"]
        suggestions.append({
            "side": "CE",
            "level": "HIGH" if top_ce[0]["ce_trap"] > 0.75 else "MEDIUM",
            "strike": s,
            "headline": f"Call-writer squeeze risk at {s}",
            "action": (
                f"If long the underlying, hedge with a long {s} CE or a {s}/{s + chain['step']} bull call spread. "
                f"Avoid naked short {s} CEs — breakout above {rng['high20']:.0f} could force-cover writers."
            ),
        })
    if top_pe and top_pe[0]["pe_trap"] > 0.55:
        s = top_pe[0]["strike"]
        suggestions.append({
            "side": "PE",
            "level": "HIGH" if top_pe[0]["pe_trap"] > 0.75 else "MEDIUM",
            "strike": s,
            "headline": f"Put-writer squeeze risk at {s}",
            "action": (
                f"If short the underlying, hedge with a long {s} PE or a {s}/{s - chain['step']} bear put spread. "
                f"Breakdown below {rng['low20']:.0f} could trigger panic unwinds."
            ),
        })

    overall = max([r["combined"] for r in rows], default=0.0)
    return {
        "symbol": symbol,
        "spot": spot,
        "atm": atm,
        "expiry": chain["expiry"],
        "step": chain["step"],
        "range_20d": {"high": rng["high20"], "low": rng["low20"], "atr": round(rng["atr"], 2)},
        "overall_trap_score": round(overall, 3),
        "rows": rows,
        "top_call_traps": top_ce,
        "top_put_traps": top_pe,
        "suggestions": suggestions,
    }
