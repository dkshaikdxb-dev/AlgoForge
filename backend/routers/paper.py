"""Paper trading: single + multi-leg orders, positions, flatten."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
from db import get_db, now_iso
from market_data import get_last_price, get_options_chain

router = APIRouter(prefix="/paper", tags=["paper"])


class PaperOrderRequest(BaseModel):
    symbol: str
    side: str  # BUY / SELL
    qty: int = Field(gt=0)
    order_type: str = "MARKET"
    price: Optional[float] = None
    instrument_type: str = "EQ"  # EQ / OPT
    option_strike: Optional[int] = None
    option_kind: Optional[str] = None  # CE / PE


class MultiLegLeg(BaseModel):
    side: str
    instrument_type: str = "OPT"
    qty: int = Field(gt=0)
    symbol: str
    option_strike: Optional[int] = None
    option_kind: Optional[str] = None


class MultiLegOrderRequest(BaseModel):
    name: str = "Basket"
    legs: list[MultiLegLeg]


async def place_paper_order(req: PaperOrderRequest, user: dict) -> dict:
    """Core paper-order logic shared by /paper/order and multi-leg.

    Updates orders + positions collections, returns the order dict (with `id`).
    Raises HTTPException for invalid inputs / kill-switch.
    """
    db = get_db()
    risk = await db.risk_limits.find_one({"user_id": user["id"]}) or {}
    if risk.get("kill_switch"):
        raise HTTPException(423, "Kill switch is active. Disable it before placing orders.")

    spot = get_last_price(req.symbol)
    if req.instrument_type == "OPT":
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


async def compute_positions(user: dict) -> dict:
    """Returns {positions[], total_pnl, exposure} marked-to-market.

    Reused by /paper/positions and /dashboard/summary.
    """
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


@router.post("/order")
async def paper_order(req: PaperOrderRequest, user: dict = Depends(get_current_user)):
    return await place_paper_order(req, user)


@router.post("/order/multi-leg")
async def paper_multi_leg(req: MultiLegOrderRequest, user: dict = Depends(get_current_user)):
    db = get_db()
    risk = await db.risk_limits.find_one({"user_id": user["id"]}) or {}
    if risk.get("kill_switch"):
        raise HTTPException(423, "Kill switch is active.")
    if not req.legs:
        raise HTTPException(400, "At least one leg required")
    placed = []
    for leg in req.legs:
        payload = PaperOrderRequest(
            symbol=leg.symbol,
            side=leg.side,
            qty=leg.qty,
            order_type="MARKET",
            instrument_type=leg.instrument_type,
            option_strike=leg.option_strike,
            option_kind=leg.option_kind,
        )
        order = await place_paper_order(payload, user)
        placed.append(order)
    bid = str(uuid.uuid4())
    await db.baskets.insert_one({
        "_id": bid,
        "user_id": user["id"],
        "name": req.name,
        "legs": [leg.model_dump() for leg in req.legs],
        "order_ids": [o["id"] for o in placed],
        "created_at": now_iso(),
    })
    return {"basket_id": bid, "orders": placed}


@router.get("/positions")
async def paper_positions(user: dict = Depends(get_current_user)):
    return await compute_positions(user)


@router.get("/orders")
async def paper_orders_list(user: dict = Depends(get_current_user)):
    db = get_db()
    docs = await db.paper_orders.find({"user_id": user["id"]}).sort("created_at", -1).to_list(100)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {"orders": docs}


@router.post("/flatten")
async def paper_flatten(user: dict = Depends(get_current_user)):
    db = get_db()
    res = await db.paper_positions.delete_many({"user_id": user["id"]})
    return {"closed": res.deleted_count}
