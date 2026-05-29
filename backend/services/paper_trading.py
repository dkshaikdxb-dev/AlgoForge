"""Paper-trading business logic.

Moved out of `routers/paper.py` so it can be reused by the live broker adapter
(`brokers/paper_adapter.py`), the reconciler, and any future research tooling
without going through HTTP. The router is now a thin HTTP layer.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from db import get_db, now_iso
from market_data import get_last_price, get_options_chain

Side = Literal["BUY", "SELL"]
InstrumentType = Literal["EQ", "OPT"]
OptionKind = Literal["CE", "PE"]
OrderType = Literal["MARKET", "LIMIT"]


# --- Schemas ----------------------------------------------------------------

class PaperOrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    side: Side
    qty: int = Field(gt=0)
    order_type: OrderType = "MARKET"
    price: Optional[float] = None
    instrument_type: InstrumentType = "EQ"
    option_strike: Optional[int] = None
    option_kind: Optional[OptionKind] = None


class MultiLegLeg(BaseModel):
    side: Side
    instrument_type: InstrumentType = "OPT"
    qty: int = Field(gt=0)
    symbol: str = Field(min_length=1, max_length=20)
    option_strike: Optional[int] = None
    option_kind: Optional[OptionKind] = None


class MultiLegOrderRequest(BaseModel):
    name: str = "Basket"
    legs: list[MultiLegLeg]


# --- Constants --------------------------------------------------------------

DUP_WINDOW_SECONDS = 5
IDEMPOTENCY_TTL_HOURS = 24


# --- Idempotency + dedup ----------------------------------------------------

def _hash_payload(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def signature(user_id: str, req: PaperOrderRequest) -> str:
    return _hash_payload({
        "u": user_id, "s": req.symbol.upper(), "side": req.side, "qty": req.qty,
        "t": req.instrument_type, "k": req.option_strike, "kind": req.option_kind,
    })


async def idem_lookup(user_id: str, key: str) -> Optional[dict]:
    db = get_db()
    return await db.idempotency_keys.find_one({"user_id": user_id, "key": key})


async def idem_store(user_id: str, key: str, response: dict) -> None:
    db = get_db()
    await db.idempotency_keys.update_one(
        {"user_id": user_id, "key": key},
        {"$set": {
            "user_id": user_id, "key": key, "response": response,
            "created_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


async def ensure_idempotency_ttl() -> None:
    db = get_db()
    await db.idempotency_keys.create_index(
        "created_at", expireAfterSeconds=IDEMPOTENCY_TTL_HOURS * 3600,
    )


async def check_duplicate(user_id: str, req: PaperOrderRequest) -> Optional[dict]:
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=DUP_WINDOW_SECONDS)).isoformat()
    return await db.paper_orders.find_one(
        {
            "user_id": user_id,
            "symbol": req.symbol.upper(), "side": req.side, "qty": req.qty,
            "instrument_type": req.instrument_type,
            "option_strike": req.option_strike, "option_kind": req.option_kind,
            "created_at": {"$gte": cutoff},
        },
        sort=[("created_at", -1)],
    )


# --- Validation -------------------------------------------------------------

def resolve_price(req: PaperOrderRequest) -> float:
    if req.instrument_type == "OPT":
        if req.option_strike is None or req.option_kind is None:
            raise HTTPException(400, "Option order requires option_strike and option_kind")
        chain = get_options_chain(req.symbol)
        row = next((r for r in chain["rows"] if r["strike"] == req.option_strike), None)
        if not row:
            raise HTTPException(400, f"Strike {req.option_strike} not in {req.symbol} chain")
        return row[req.option_kind.lower()]["price"]
    spot = get_last_price(req.symbol)
    if spot <= 0:
        raise HTTPException(400, f"Unknown symbol {req.symbol}")
    return req.price if req.order_type == "LIMIT" and req.price else spot


async def check_kill_switch(user_id: str) -> None:
    db = get_db()
    risk = await db.risk_limits.find_one({"user_id": user_id}) or {}
    if risk.get("kill_switch"):
        raise HTTPException(423, "Kill switch is active. Disable it before placing orders.")


# --- Position application + rollback ----------------------------------------

def _position_key(req: PaperOrderRequest) -> str:
    parts = [req.symbol.upper(), req.instrument_type]
    if req.instrument_type == "OPT":
        parts += [str(req.option_strike), req.option_kind]
    return "|".join(parts)


async def apply_to_position(user_id: str, req: PaperOrderRequest, price: float) -> dict:
    db = get_db()
    pos_key = _position_key(req)
    before = await db.paper_positions.find_one({"user_id": user_id, "key": pos_key})
    snapshot = {"pos_key": pos_key, "before": deepcopy(before)}
    direction = 1 if req.side == "BUY" else -1
    if before:
        new_qty = before["qty"] + direction * req.qty
        if new_qty == 0:
            await db.paper_positions.delete_one({"_id": before["_id"]})
        else:
            same_side = (before["qty"] > 0) == (direction > 0)
            if same_side:
                total = abs(before["qty"]) + req.qty
                new_avg = (abs(before["qty"]) * before["avg_price"] + req.qty * price) / total
            else:
                new_avg = price if abs(new_qty) > abs(before["qty"]) else before["avg_price"]
            await db.paper_positions.update_one(
                {"_id": before["_id"]},
                {"$set": {"qty": new_qty, "avg_price": round(new_avg, 2), "updated_at": now_iso()}},
            )
    else:
        await db.paper_positions.insert_one({
            "_id": str(uuid.uuid4()),
            "user_id": user_id, "key": pos_key,
            "symbol": req.symbol.upper(), "instrument_type": req.instrument_type,
            "option_strike": req.option_strike, "option_kind": req.option_kind,
            "qty": direction * req.qty, "avg_price": round(price, 2),
            "created_at": now_iso(), "updated_at": now_iso(),
        })
    return snapshot


async def restore_position(user_id: str, snapshot: dict) -> None:
    db = get_db()
    if snapshot["before"] is None:
        await db.paper_positions.delete_one({"user_id": user_id, "key": snapshot["pos_key"]})
    else:
        await db.paper_positions.replace_one(
            {"user_id": user_id, "key": snapshot["pos_key"]}, snapshot["before"], upsert=True,
        )


async def place_paper_order(
    req: PaperOrderRequest, user: dict, *,
    do_check_kill_switch: bool = True, do_check_duplicate: bool = True,
) -> dict:
    from services.audit import AuditEventType, AuditSeverity, record_event

    db = get_db()
    if do_check_kill_switch:
        await check_kill_switch(user["id"])
    if do_check_duplicate:
        dup = await check_duplicate(user["id"], req)
        if dup:
            await record_event(
                user["id"], AuditEventType.DUPLICATE_BLOCKED, severity=AuditSeverity.WARN,
                actor="system",
                summary=f"Duplicate {req.side} {req.qty} {req.symbol} blocked",
                payload={"req": req.model_dump(), "dup_id": str(dup.get("_id"))},
            )
            raise HTTPException(409, f"Duplicate order detected within {DUP_WINDOW_SECONDS}s. Resubmit with ?force=true to override.")

    price = resolve_price(req)
    await apply_to_position(user["id"], req, price)

    oid = str(uuid.uuid4())
    order = {
        "_id": oid, "user_id": user["id"],
        "symbol": req.symbol.upper(), "side": req.side, "qty": req.qty,
        "price": round(price, 2),
        "instrument_type": req.instrument_type,
        "option_strike": req.option_strike, "option_kind": req.option_kind,
        "status": "FILLED", "mode": "PAPER",
        "created_at": now_iso(),
    }
    await db.paper_orders.insert_one(order)
    order["id"] = oid
    order.pop("_id")

    await record_event(
        user["id"], AuditEventType.REQUEST, actor="user",
        summary=f"{req.side} {req.qty} {req.symbol} ({req.instrument_type})",
        payload={"req": req.model_dump(), "price": price},
        correlation_id=oid,
    )
    await record_event(
        user["id"], AuditEventType.FILL, actor="broker",
        summary=f"FILLED {req.side} {req.qty} {req.symbol} @ {price:.2f}",
        payload={"order_id": oid, "price": price, "qty": req.qty},
        correlation_id=oid,
    )
    return order


async def undo_order(order: dict, snapshot: dict, user_id: str) -> None:
    db = get_db()
    await db.paper_orders.delete_one({"_id": order["id"]})
    await restore_position(user_id, snapshot)


async def compute_positions(user: dict) -> dict:
    db = get_db()
    docs = await db.paper_positions.find({"user_id": user["id"]}).to_list(200)
    out, total_pnl, exposure = [], 0.0, 0.0
    for d in docs:
        if d["instrument_type"] == "OPT":
            chain = get_options_chain(d["symbol"])
            row = next((r for r in chain["rows"] if r["strike"] == d["option_strike"]), None)
            ltp = row[d["option_kind"].lower()]["price"] if row else d["avg_price"]
        else:
            ltp = get_last_price(d["symbol"])
        pnl = (ltp - d["avg_price"]) * d["qty"]
        total_pnl += pnl
        exposure += abs(d["qty"] * ltp)
        out.append({
            "id": str(d["_id"]),
            "symbol": d["symbol"], "instrument_type": d["instrument_type"],
            "option_strike": d.get("option_strike"), "option_kind": d.get("option_kind"),
            "qty": d["qty"], "avg_price": d["avg_price"],
            "ltp": round(ltp, 2), "pnl": round(pnl, 2),
        })
    return {"positions": out, "total_pnl": round(total_pnl, 2), "exposure": round(exposure, 2)}
