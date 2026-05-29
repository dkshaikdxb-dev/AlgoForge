"""Monte Carlo stress-test endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
from backtest_engine import run_backtest
from services.audit import AuditEventType, record_event
from services.stress import run_monte_carlo

router = APIRouter(prefix="/stress", tags=["stress"])


class StressRunRequest(BaseModel):
    # Pass either an already-computed backtest result OR a DSL to backtest first.
    backtest: Optional[dict] = None
    dsl: Optional[dict] = None
    capital: float = 500000.0
    slippage_bps: float = 5.0
    fee_bps: float = 2.0
    days: int = 180
    iterations: int = Field(default=1000, ge=50, le=5000)
    block_size: int = Field(default=5, ge=1, le=30)
    slippage_jitter_bps: float = Field(default=3.0, ge=0, le=50)
    seed: Optional[int] = None


@router.post("/run")
async def stress_run(req: StressRunRequest, user: dict = Depends(get_current_user)):
    bt = req.backtest
    if not bt:
        if not req.dsl:
            raise HTTPException(400, "Either `backtest` or `dsl` must be provided.")
        try:
            bt = run_backtest(
                req.dsl,
                capital=req.capital,
                slippage_bps=req.slippage_bps,
                fee_bps=req.fee_bps,
                days=req.days,
            )
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            raise HTTPException(400, f"Invalid strategy DSL: {e}")

    result = run_monte_carlo(
        bt,
        iterations=req.iterations,
        block_size=req.block_size,
        slippage_jitter_bps=req.slippage_jitter_bps,
        seed=req.seed,
    )
    if result.get("error"):
        raise HTTPException(400, result["error"])

    blow = result["blowup_rate_pct"]
    await record_event(
        user["id"], AuditEventType.BACKTEST_RUN, actor="user",
        summary=f"Monte Carlo × {result['iterations']} → blowup_rate {blow:.1f}% "
                f"(P5 DD {result['metrics']['max_drawdown_pct']['p5']}%)",
        payload={
            "iterations": result["iterations"],
            "block_size": result["block_size"],
            "blowup_rate_pct": blow,
            "p5_drawdown": result["metrics"]["max_drawdown_pct"]["p5"],
            "p95_return": result["metrics"]["total_return_pct"]["p95"],
        },
    )
    return result
