"""Backtest run + history."""
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from backtest_engine import run_backtest
from db import get_db, now_iso
from services.audit import AuditEventType, record_event

router = APIRouter(tags=["backtest"])
logger = logging.getLogger("algoforge.backtest")


class BacktestRequest(BaseModel):
    dsl: dict
    capital: float = 500000.0
    slippage_bps: float = 5.0
    fee_bps: float = 2.0
    days: int = 180
    save: bool = True
    strategy_id: Optional[str] = None


@router.post("/backtest/run")
async def backtest_run(req: BacktestRequest, user: dict = Depends(get_current_user)):
    result: dict | None = None
    try:
        result = run_backtest(
            req.dsl,
            capital=req.capital,
            slippage_bps=req.slippage_bps,
            fee_bps=req.fee_bps,
            days=req.days,
        )
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        # Log with stack so genuine engine bugs aren't silently masked as "bad DSL".
        logger.warning("Backtest rejected for user=%s: %s", user.get("id"), e, exc_info=True)
        raise HTTPException(400, f"Invalid strategy DSL: {e}")
    if not result or result.get("error"):
        raise HTTPException(400, (result or {}).get("error", "Backtest produced no result"))
    if req.save:
        db = get_db()
        bid = str(uuid.uuid4())
        await db.backtests.insert_one({
            "_id": bid,
            "user_id": user["id"],
            "strategy_id": req.strategy_id,
            "strategy_name": req.dsl.get("name", "Untitled"),
            "symbol": result["symbol"],
            "summary": {
                k: result[k]
                for k in (
                    "final_equity", "total_return_pct", "sharpe", "sortino",
                    "max_drawdown_pct", "win_rate_pct", "total_trades", "profit_factor",
                )
            },
            "created_at": now_iso(),
        })
        result["backtest_id"] = bid
    await record_event(
        user["id"], AuditEventType.BACKTEST_RUN, actor="user",
        summary=f"Backtest {req.dsl.get('name', 'untitled')} on {result.get('symbol')} "
                f"→ ret={result.get('total_return_pct')}%, sharpe={result.get('sharpe')}",
        payload={
            "symbol": result.get("symbol"),
            "sharpe": result.get("sharpe"),
            "max_drawdown_pct": result.get("max_drawdown_pct"),
        },
    )
    return result


@router.get("/backtests")
async def list_backtests(user: dict = Depends(get_current_user)):
    db = get_db()
    docs = await db.backtests.find({"user_id": user["id"]}).sort("created_at", -1).to_list(50)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {"items": docs}
