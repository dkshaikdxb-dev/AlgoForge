"""Main FastAPI app for the AI-First Hybrid Algo Trading Platform."""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from ai_service import (
    analyse_strategy_risk,
    explain_trap,
    generate_strategy_from_nl,
    journal_commentary,
)
from auth import get_current_user, router as auth_router
from backtest_engine import run_backtest
from db import close_db, get_db, now_iso
from market_data import get_ohlcv, get_options_chain, get_symbols
from trap_detection import scan_traps

app = FastAPI(title="AlgoForge — AI Trading Platform")
api = APIRouter(prefix="/api")

# ---------- Health ----------

@api.get("/")
async def root():
    return {"service": "algoforge", "status": "ok"}


@api.get("/health")
async def health():
    return {"status": "ok", "ts": now_iso()}


# ---------- Market data ----------

@api.get("/market/symbols")
async def market_symbols():
    return {"symbols": get_symbols()}


@api.get("/market/ohlcv")
async def market_ohlcv(symbol: str, days: int = 180):
    data = get_ohlcv(symbol, days=days)
    if not data:
        raise HTTPException(404, f"Unknown symbol {symbol}")
    return {"symbol": symbol.upper(), "candles": data}


@api.get("/market/options-chain")
async def market_options_chain(symbol: str, expiry_days: int = 7):
    chain = get_options_chain(symbol, expiry_days=expiry_days)
    if not chain.get("rows"):
        raise HTTPException(404, f"No options chain for {symbol}")
    return chain


# ---------- Strategies ----------

class StrategyGenRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)


class StrategySaveRequest(BaseModel):
    name: str
    description: str | None = None
    dsl: dict


@api.post("/strategies/generate")
async def strategies_generate(req: StrategyGenRequest, user: dict = Depends(get_current_user)):
    dsl = await generate_strategy_from_nl(req.prompt)
    return {"dsl": dsl}


@api.get("/strategies")
async def list_strategies(user: dict = Depends(get_current_user)):
    db = get_db()
    docs = await db.strategies.find({"user_id": user["id"]}, {"_id": 1, "name": 1, "description": 1, "dsl": 1, "created_at": 1, "updated_at": 1}).to_list(500)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {"items": docs}


@api.post("/strategies")
async def save_strategy(req: StrategySaveRequest, user: dict = Depends(get_current_user)):
    db = get_db()
    sid = str(uuid.uuid4())
    doc = {
        "_id": sid,
        "user_id": user["id"],
        "name": req.name,
        "description": req.description or req.dsl.get("description", ""),
        "dsl": req.dsl,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.strategies.insert_one(doc)
    return {"id": sid, "name": req.name, "dsl": req.dsl}


@api.delete("/strategies/{sid}")
async def delete_strategy(sid: str, user: dict = Depends(get_current_user)):
    db = get_db()
    res = await db.strategies.delete_one({"_id": sid, "user_id": user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(404, "Strategy not found")
    return {"deleted": sid}


# ---------- Backtest ----------

class BacktestRequest(BaseModel):
    dsl: dict
    capital: float = 500000.0
    slippage_bps: float = 5.0
    fee_bps: float = 2.0
    days: int = 180
    save: bool = True
    strategy_id: Optional[str] = None


@api.post("/backtest/run")
async def backtest_run(req: BacktestRequest, user: dict = Depends(get_current_user)):
    result = run_backtest(
        req.dsl,
        capital=req.capital,
        slippage_bps=req.slippage_bps,
        fee_bps=req.fee_bps,
        days=req.days,
    )
    if result.get("error"):
        raise HTTPException(400, result["error"])
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
    return result


@api.get("/backtests")
async def list_backtests(user: dict = Depends(get_current_user)):
    db = get_db()
    docs = await db.backtests.find({"user_id": user["id"]}).sort("created_at", -1).to_list(50)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {"items": docs}


# ---------- Risk analysis (Claude) ----------

class RiskAnalyseRequest(BaseModel):
    dsl: dict
    backtest: dict | None = None


@api.post("/risk/analyse")
async def risk_analyse(req: RiskAnalyseRequest, user: dict = Depends(get_current_user)):
    return await analyse_strategy_risk(req.dsl, req.backtest)


# ---------- Trap detection ----------

@api.get("/trap/scan")
async def trap_scan(symbol: str, expiry_days: int = 7, user: dict = Depends(get_current_user)):
    scan = scan_traps(symbol, expiry_days=expiry_days)
    if scan.get("error"):
        raise HTTPException(404, scan["error"])
    return scan


class TrapExplainRequest(BaseModel):
    scan: dict


@api.post("/trap/explain")
async def trap_explain(req: TrapExplainRequest, user: dict = Depends(get_current_user)):
    return await explain_trap(req.scan)


# ---------- Paper trading ----------

class PaperOrderRequest(BaseModel):
    symbol: str
    side: str  # BUY / SELL
    qty: int = Field(gt=0)
    order_type: str = "MARKET"
    price: Optional[float] = None
    instrument_type: str = "EQ"  # EQ / OPT
    option_strike: Optional[int] = None
    option_kind: Optional[str] = None  # CE / PE


@api.post("/paper/order")
async def paper_order(req: PaperOrderRequest, user: dict = Depends(get_current_user)):
    db = get_db()
    risk = await db.risk_limits.find_one({"user_id": user["id"]}) or {}
    if risk.get("kill_switch"):
        raise HTTPException(423, "Kill switch is active. Disable it before placing orders.")

    # Resolve price
    from market_data import get_last_price
    spot = get_last_price(req.symbol)
    if req.instrument_type == "OPT":
        # rough premium via options chain
        chain = get_options_chain(req.symbol)
        row = next((r for r in chain["rows"] if r["strike"] == req.option_strike), None)
        if not row or req.option_kind not in ("CE", "PE"):
            raise HTTPException(400, "Invalid option strike/kind for symbol")
        price = row[req.option_kind.lower()]["price"]
    else:
        price = req.price if req.order_type == "LIMIT" and req.price else spot

    oid = str(uuid.uuid4())
    order = {
        "_id": oid,
        "user_id": user["id"],
        "symbol": req.symbol.upper(),
        "side": req.side.upper(),
        "qty": req.qty,
        "price": round(price, 2),
        "instrument_type": req.instrument_type,
        "option_strike": req.option_strike,
        "option_kind": req.option_kind,
        "status": "FILLED",
        "mode": "PAPER",
        "created_at": now_iso(),
    }
    await db.paper_orders.insert_one(order)

    # update positions
    key_parts = [req.symbol.upper(), req.instrument_type]
    if req.instrument_type == "OPT":
        key_parts += [str(req.option_strike), req.option_kind]
    pos_key = "|".join(key_parts)
    existing = await db.paper_positions.find_one({"user_id": user["id"], "key": pos_key})
    direction = 1 if req.side.upper() == "BUY" else -1
    if existing:
        new_qty = existing["qty"] + direction * req.qty
        if new_qty == 0:
            await db.paper_positions.delete_one({"_id": existing["_id"]})
        else:
            # weighted avg if adding to same side, else keep entry on side flip
            same_side = (existing["qty"] > 0) == (direction > 0)
            if same_side:
                total = abs(existing["qty"]) + req.qty
                new_avg = (abs(existing["qty"]) * existing["avg_price"] + req.qty * price) / total
            else:
                new_avg = price if abs(new_qty) > abs(existing["qty"]) else existing["avg_price"]
            await db.paper_positions.update_one(
                {"_id": existing["_id"]},
                {"$set": {"qty": new_qty, "avg_price": round(new_avg, 2), "updated_at": now_iso()}},
            )
    else:
        await db.paper_positions.insert_one({
            "_id": str(uuid.uuid4()),
            "user_id": user["id"],
            "key": pos_key,
            "symbol": req.symbol.upper(),
            "instrument_type": req.instrument_type,
            "option_strike": req.option_strike,
            "option_kind": req.option_kind,
            "qty": direction * req.qty,
            "avg_price": round(price, 2),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })

    order["id"] = oid
    order.pop("_id")
    return order


@api.get("/paper/positions")
async def paper_positions(user: dict = Depends(get_current_user)):
    from market_data import get_last_price
    db = get_db()
    docs = await db.paper_positions.find({"user_id": user["id"]}).to_list(200)
    out = []
    total_pnl = 0.0
    exposure = 0.0
    for d in docs:
        ltp = get_last_price(d["symbol"]) if d["instrument_type"] == "EQ" else None
        if d["instrument_type"] == "OPT":
            chain = get_options_chain(d["symbol"])
            row = next((r for r in chain["rows"] if r["strike"] == d["option_strike"]), None)
            ltp = row[d["option_kind"].lower()]["price"] if row else d["avg_price"]
        pnl = (ltp - d["avg_price"]) * d["qty"]
        total_pnl += pnl
        exposure += abs(d["qty"] * ltp)
        out.append({
            "id": str(d["_id"]),
            "symbol": d["symbol"],
            "instrument_type": d["instrument_type"],
            "option_strike": d.get("option_strike"),
            "option_kind": d.get("option_kind"),
            "qty": d["qty"],
            "avg_price": d["avg_price"],
            "ltp": round(ltp, 2),
            "pnl": round(pnl, 2),
        })
    return {"positions": out, "total_pnl": round(total_pnl, 2), "exposure": round(exposure, 2)}


@api.get("/paper/orders")
async def paper_orders_list(user: dict = Depends(get_current_user)):
    db = get_db()
    docs = await db.paper_orders.find({"user_id": user["id"]}).sort("created_at", -1).to_list(100)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {"orders": docs}


@api.post("/paper/flatten")
async def paper_flatten(user: dict = Depends(get_current_user)):
    db = get_db()
    res = await db.paper_positions.delete_many({"user_id": user["id"]})
    return {"closed": res.deleted_count}


# ---------- Risk limits + kill switch ----------

class RiskLimitsRequest(BaseModel):
    max_drawdown_pct: float = Field(ge=0, le=100)
    daily_loss_cap: float = Field(ge=0)
    position_limit: int = Field(ge=0)
    kill_switch: bool


@api.get("/risk/limits")
async def get_risk_limits(user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await db.risk_limits.find_one({"user_id": user["id"]})
    if not doc:
        doc = {"user_id": user["id"], "max_drawdown_pct": 15.0, "daily_loss_cap": 25000.0,
               "position_limit": 5, "kill_switch": False}
        await db.risk_limits.insert_one({**doc, "updated_at": now_iso()})
    doc.pop("_id", None)
    return doc


@api.put("/risk/limits")
async def update_risk_limits(req: RiskLimitsRequest, user: dict = Depends(get_current_user)):
    db = get_db()
    await db.risk_limits.update_one(
        {"user_id": user["id"]},
        {"$set": {**req.model_dump(), "updated_at": now_iso()}},
        upsert=True,
    )
    return {"ok": True, **req.model_dump()}


# ---------- Journal ----------

class JournalEntryRequest(BaseModel):
    symbol: str
    side: str
    qty: int
    entry_price: float
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    rationale: str = ""
    request_ai: bool = True


@api.post("/journal")
async def journal_create(req: JournalEntryRequest, user: dict = Depends(get_current_user)):
    db = get_db()
    ai = {"tags": [], "commentary": ""}
    if req.request_ai:
        ai = await journal_commentary(req.model_dump())
    entry = {
        "_id": str(uuid.uuid4()),
        "user_id": user["id"],
        **req.model_dump(),
        "ai_tags": ai.get("tags", []),
        "ai_commentary": ai.get("commentary", ""),
        "created_at": now_iso(),
    }
    await db.journal_entries.insert_one(entry)
    entry["id"] = str(entry.pop("_id"))
    return entry


@api.get("/journal")
async def journal_list(user: dict = Depends(get_current_user)):
    db = get_db()
    docs = await db.journal_entries.find({"user_id": user["id"]}).sort("created_at", -1).to_list(200)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {"items": docs}


# ---------- Dashboard summary ----------

@api.get("/dashboard/summary")
async def dashboard_summary(user: dict = Depends(get_current_user)):
    db = get_db()
    strats = await db.strategies.count_documents({"user_id": user["id"]})
    backtests = await db.backtests.count_documents({"user_id": user["id"]})
    positions = await db.paper_positions.count_documents({"user_id": user["id"]})
    risk = await db.risk_limits.find_one({"user_id": user["id"]}) or {}
    risk.pop("_id", None)
    # P&L via positions endpoint logic
    pos_resp = await paper_positions(user)
    return {
        "strategies": strats,
        "backtests": backtests,
        "open_positions": positions,
        "total_pnl": pos_resp["total_pnl"],
        "exposure": pos_resp["exposure"],
        "kill_switch": risk.get("kill_switch", False),
        "risk_limits": risk,
    }


# ---------- mount ----------

api.include_router(auth_router)
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("algoforge")


@app.on_event("startup")
async def on_startup():
    get_db()  # eagerly init
    logger.info("AlgoForge backend started")


@app.on_event("shutdown")
async def on_shutdown():
    close_db()
