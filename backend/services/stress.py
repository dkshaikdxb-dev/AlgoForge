"""Monte Carlo stress testing for a backtest result.

Given an existing backtest's equity curve + trades, we resample the bar-level
returns with replacement (block bootstrap) and apply random slippage / fee
perturbations to estimate the distribution of risk metrics under similar but
different market paths.

This answers the question: "if I ran this strategy 1000 alternate histories
that looked statistically like my backtest, how often would I have blown up?"
"""
from __future__ import annotations

import math
import random
import statistics
from typing import Any


def _block_resample(returns: list[float], rng: random.Random, block_size: int = 5) -> list[float]:
    """Block bootstrap preserves short-horizon autocorrelation."""
    if not returns:
        return []
    n = len(returns)
    out: list[float] = []
    while len(out) < n:
        start = rng.randrange(max(1, n - block_size + 1))
        out.extend(returns[start:start + block_size])
    return out[:n]


def _path_metrics(returns: list[float], capital: float) -> dict[str, float]:
    if not returns:
        return {"final_equity": capital, "max_drawdown_pct": 0.0, "sharpe": 0.0, "sortino": 0.0, "total_return_pct": 0.0}
    equity = capital
    peak = capital
    max_dd_pct = 0.0
    eq_series = [capital]
    for r in returns:
        equity *= (1 + r)
        peak = max(peak, equity)
        dd = (equity - peak) / peak * 100
        max_dd_pct = min(max_dd_pct, dd)
        eq_series.append(equity)
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std = math.sqrt(variance)
    downside = [r for r in returns if r < 0]
    dn_std = math.sqrt(sum(r * r for r in downside) / len(downside)) if downside else 0.0
    sharpe = (mean_r / std) * math.sqrt(252) if std else 0.0
    sortino = (mean_r / dn_std) * math.sqrt(252) if dn_std else 0.0
    return {
        "final_equity": round(equity, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "total_return_pct": round((equity - capital) / capital * 100, 2),
    }


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct / 100
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


def _histogram(values: list[float], bins: int = 20) -> list[dict]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        hi = lo + 1e-9
    width = (hi - lo) / bins
    edges = [lo + i * width for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / width), bins - 1)
        counts[idx] += 1
    return [
        {
            "lo": round(edges[i], 4),
            "hi": round(edges[i + 1], 4),
            "mid": round((edges[i] + edges[i + 1]) / 2, 4),
            "count": counts[i],
        }
        for i in range(bins)
    ]


def run_monte_carlo(
    backtest_result: dict,
    *,
    iterations: int = 1000,
    block_size: int = 5,
    slippage_jitter_bps: float = 3.0,
    seed: int | None = None,
) -> dict:
    """Resample the backtest's bar returns N times, compute metric distributions."""
    equity_curve = backtest_result.get("equity_curve") or []
    if len(equity_curve) < 5:
        return {"error": "Not enough data — run a backtest with ≥5 bars first."}
    capital = backtest_result.get("capital") or equity_curve[0]["equity"]

    # Bar-level returns from equity curve.
    base_returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]["equity"]
        curr = equity_curve[i]["equity"]
        if prev:
            base_returns.append((curr - prev) / prev)
    if not base_returns:
        return {"error": "Could not derive returns from equity curve."}

    rng = random.Random(seed if seed is not None else random.randrange(2**32))
    iterations = max(50, min(5000, int(iterations)))

    samples = {"final_equity": [], "max_drawdown_pct": [], "sharpe": [], "sortino": [], "total_return_pct": []}
    worst_path: tuple[float, list[float]] | None = None  # (max_dd, returns)

    jitter = slippage_jitter_bps / 10000.0
    for _ in range(iterations):
        path = _block_resample(base_returns, rng, block_size=block_size)
        # Apply random slippage perturbation per bar to simulate execution variance.
        path = [r + rng.uniform(-jitter, jitter) for r in path]
        m = _path_metrics(path, capital)
        for k, lst in samples.items():
            lst.append(m[k])
        if worst_path is None or m["max_drawdown_pct"] < worst_path[0]:
            worst_path = (m["max_drawdown_pct"], path)

    def _stats(values: list[float]) -> dict[str, float]:
        return {
            "p5": round(_percentile(values, 5), 3),
            "p25": round(_percentile(values, 25), 3),
            "p50": round(_percentile(values, 50), 3),
            "p75": round(_percentile(values, 75), 3),
            "p95": round(_percentile(values, 95), 3),
            "mean": round(statistics.fmean(values), 3),
            "std": round(statistics.pstdev(values), 3) if len(values) > 1 else 0.0,
            "min": round(min(values), 3),
            "max": round(max(values), 3),
        }

    # Reconstruct worst-case equity curve for chart overlay.
    worst_curve: list[dict[str, float]] = []
    if worst_path:
        eq = capital
        worst_curve.append({"step": 0, "equity": round(eq, 2)})
        for idx, r in enumerate(worst_path[1], start=1):
            eq *= (1 + r)
            worst_curve.append({"step": idx, "equity": round(eq, 2)})

    blowup_threshold = -25.0  # >25% drawdown = "blowup"
    blowup_rate = sum(1 for v in samples["max_drawdown_pct"] if v <= blowup_threshold) / iterations

    return {
        "iterations": iterations,
        "block_size": block_size,
        "slippage_jitter_bps": slippage_jitter_bps,
        "seed": seed,
        "bars_per_path": len(base_returns),
        "capital": capital,
        "metrics": {
            "final_equity": _stats(samples["final_equity"]),
            "max_drawdown_pct": _stats(samples["max_drawdown_pct"]),
            "sharpe": _stats(samples["sharpe"]),
            "sortino": _stats(samples["sortino"]),
            "total_return_pct": _stats(samples["total_return_pct"]),
        },
        "histograms": {
            "max_drawdown_pct": _histogram(samples["max_drawdown_pct"]),
            "sharpe": _histogram(samples["sharpe"]),
            "total_return_pct": _histogram(samples["total_return_pct"]),
        },
        "blowup_rate_pct": round(blowup_rate * 100, 2),
        "blowup_threshold_pct": blowup_threshold,
        "worst_path": {
            "max_drawdown_pct": worst_path[0] if worst_path else 0.0,
            "equity_curve": worst_curve[: min(200, len(worst_curve))],  # cap payload
        },
    }
