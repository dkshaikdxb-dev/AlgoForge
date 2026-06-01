"""LLM wrappers via the llm_provider abstraction.

- GPT-5.2 → translates natural-language strategy into DSL JSON.
- Claude Sonnet 4.5 → risk analysis, trap commentary, trade journal AI tags.

Set LLM_PROVIDER=emergent (default) for hosted Emergent dev, or
LLM_PROVIDER=direct with OPENAI_API_KEY + ANTHROPIC_API_KEY for self-hosted.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from llm_provider import chat as llm_chat

GPT_MODEL = "gpt-5.2"
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"


def _has_provider_key(provider: str) -> bool:
    mode = os.environ.get("LLM_PROVIDER", "emergent").strip().lower()
    if mode == "direct":
        if provider == "openai":
            return bool(os.environ.get("OPENAI_API_KEY"))
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    return bool(os.environ.get("EMERGENT_LLM_KEY"))


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


STRATEGY_SYSTEM = """You are a senior quant who converts plain-English trading ideas into a strict JSON strategy DSL.

OUTPUT RULES:
- Return ONLY valid JSON. No prose, no markdown fences.
- Schema:
{
  "name": "short title",
  "description": "1-2 sentence description",
  "symbol": "NIFTY|BANKNIFTY|RELIANCE|TCS|HDFCBANK|INFY",
  "timeframe": "1d",
  "indicators": [{"id":"sma_fast","type":"sma|ema|rsi","period":<int>,"source":"close"}],
  "entry": {"op":"and|or","rules":[{"left":"<id|number>","cmp":">|<|>=|<=|==","right":"<id|number>"}]},
  "exit":  {"op":"and|or","rules":[...]},
  "size":  {"type":"fixed_qty","value":<int>},
  "stop_loss_pct": <number>,
  "take_profit_pct": <number>
}
- Pick reasonable defaults if the user is vague.
- Always include at least one indicator and rules in entry+exit.
- Default symbol = NIFTY if not specified.
"""


async def generate_strategy_from_nl(nl_text: str) -> dict:
    if not _has_provider_key("openai"):
        return _fallback_strategy(nl_text)
    try:
        resp = await llm_chat("openai", GPT_MODEL, STRATEGY_SYSTEM, nl_text)
        dsl = _extract_json(resp)
        if not dsl:
            return _fallback_strategy(nl_text, raw=resp)
        return dsl
    except Exception as e:
        return _fallback_strategy(nl_text, error=str(e))


def _fallback_strategy(nl_text: str, raw: str | None = None, error: str | None = None) -> dict:
    return {
        "name": "Auto: SMA Crossover (fallback)",
        "description": "Fallback strategy. " + (error or "AI unavailable; using SMA 10/30 crossover on NIFTY."),
        "symbol": "NIFTY",
        "timeframe": "1d",
        "indicators": [
            {"id": "sma_fast", "type": "sma", "period": 10, "source": "close"},
            {"id": "sma_slow", "type": "sma", "period": 30, "source": "close"},
        ],
        "entry": {"op": "and", "rules": [{"left": "sma_fast", "cmp": ">", "right": "sma_slow"}]},
        "exit": {"op": "and", "rules": [{"left": "sma_fast", "cmp": "<", "right": "sma_slow"}]},
        "size": {"type": "fixed_qty", "value": 1},
        "stop_loss_pct": 3.0,
        "take_profit_pct": 8.0,
        "_user_prompt": nl_text,
        "_raw": raw,
    }


RISK_SYSTEM = """You are a senior risk analyst at an Indian options trading desk.
Given a JSON strategy DSL and backtest stats, produce a concise, structured risk review.
Return STRICT JSON only with this shape:
{
  "risk_score": <0-100 integer where 100 = highest risk>,
  "verdict": "LOW|MEDIUM|HIGH",
  "summary": "1-2 sentence overview",
  "strengths": ["..."],
  "concerns": ["..."],
  "suggestions": ["..."]
}
"""


async def analyse_strategy_risk(dsl: dict, backtest: dict | None = None) -> dict:
    if not _has_provider_key("anthropic"):
        return _fallback_risk(dsl, backtest)
    payload = {
        "strategy": dsl,
        "backtest_metrics": {
            k: backtest.get(k)
            for k in (
                "sharpe", "sortino", "max_drawdown_pct", "win_rate_pct",
                "total_trades", "total_return_pct", "profit_factor",
            )
        } if backtest else None,
    }
    try:
        resp = await llm_chat("anthropic", CLAUDE_MODEL, RISK_SYSTEM, json.dumps(payload))
        return _extract_json(resp) or _fallback_risk(dsl, backtest, raw=resp)
    except Exception as e:
        return _fallback_risk(dsl, backtest, error=str(e))


def _fallback_risk(dsl: dict, backtest: dict | None, raw: str | None = None, error: str | None = None) -> dict:
    dd = abs((backtest or {}).get("max_drawdown_pct", 0))
    sharpe = (backtest or {}).get("sharpe", 0)
    score = int(min(100, max(0, 50 + dd * 1.5 - sharpe * 8)))
    verdict = "HIGH" if score > 70 else ("MEDIUM" if score > 40 else "LOW")
    return {
        "risk_score": score,
        "verdict": verdict,
        "summary": f"Heuristic risk review. {error or 'AI unavailable; using fallback scoring.'}",
        "strengths": ["Backtest available" if backtest else "Strategy has defined entry/exit rules"],
        "concerns": [f"Max drawdown {dd:.1f}%", f"Sharpe {sharpe}"],
        "suggestions": ["Add stop-loss", "Run forward test before going live"],
        "_raw": raw,
    }


TRAP_SYSTEM = """You are an options strategist explaining option-writer trap risks in plain English.
Given trap scan data, produce STRICT JSON only:
{
  "headline": "1 sentence summary",
  "explanation": "2-3 sentences explaining the setup, OI dynamics, and why a squeeze is possible",
  "hedging_playbook": ["actionable bullet 1", "bullet 2", "bullet 3"]
}
"""


async def explain_trap(scan: dict) -> dict:
    if not _has_provider_key("anthropic"):
        return _fallback_trap_explain(scan)
    body = {
        "symbol": scan.get("symbol"),
        "spot": scan.get("spot"),
        "overall_trap_score": scan.get("overall_trap_score"),
        "top_call_traps": scan.get("top_call_traps"),
        "top_put_traps": scan.get("top_put_traps"),
        "range_20d": scan.get("range_20d"),
        "suggestions": scan.get("suggestions"),
    }
    try:
        resp = await llm_chat("anthropic", CLAUDE_MODEL, TRAP_SYSTEM, json.dumps(body))
        return _extract_json(resp) or _fallback_trap_explain(scan, raw=resp)
    except Exception as e:
        return _fallback_trap_explain(scan, error=str(e))


def _fallback_trap_explain(scan: dict, raw: str | None = None, error: str | None = None) -> dict:
    return {
        "headline": f"Trap score {scan.get('overall_trap_score', 0):.2f} for {scan.get('symbol')}.",
        "explanation": error or "Heuristic-only output; AI commentary unavailable.",
        "hedging_playbook": [s.get("action", "") for s in (scan.get("suggestions") or [])[:3]],
        "_raw": raw,
    }


JOURNAL_SYSTEM = """You are a trading coach. Given a journal entry (rationale, instrument, side, P&L outcome),
return STRICT JSON:
{
  "tags": ["FOMO","trend-follow","mean-reversion","news-driven","disciplined"...],
  "commentary": "2-3 sentence honest feedback in second person"
}
"""


async def journal_commentary(entry: dict) -> dict:
    if not _has_provider_key("anthropic"):
        return {"tags": [], "commentary": "AI commentary unavailable."}
    try:
        resp = await llm_chat("anthropic", CLAUDE_MODEL, JOURNAL_SYSTEM, json.dumps(entry))
        return _extract_json(resp) or {"tags": [], "commentary": (resp or "")[:400]}
    except Exception as e:
        return {"tags": [], "commentary": f"AI error: {e}"}
