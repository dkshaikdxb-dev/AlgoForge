"""Paper trading: single + multi-leg orders, positions, flatten.

Includes:
- Pydantic Literal-validated enums (BUY/SELL, EQ/OPT, CE/PE, MARKET/LIMIT).
- Idempotency keys (header `Idempotency-Key` or auto-derived server hash)
  cached in `idempotency_keys` (24h TTL) so retries return the original response.
- Duplicate-order prevention (5s sliding window per user × instrument × side × qty)
  → returns 409 unless caller sets `?force=true`.
- Multi-leg basket: pre-flight validation of every leg, snapshot-based rollback
  if mid-loop failure (best-effort atomicity on standalone Mongo).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_user
from db import get_db, now_iso
from market_data import get_last_price, get_options_chain
from services.audit import AuditEventType, AuditSeverity, record_event

router = APIRouter(prefix="/paper", tags=["paper"])

Side = Literal["BUY", "SELL"]
InstrumentType = Literal["EQ", "OPT"]
OptionKind = Literal["CE", "PE"]
OrderType = Literal["MARKET", "LIMIT"]


# --- Schemas -----------------------------------------------------------------

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


# --- Idempotency & dedup helpers --------------------------------------------

DUP_WINDOW_SECONDS = 5
IDEMPOTENCY_TTL_HOURS = 24


def _hash_payload(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def _signature(user_id: str, req: PaperOrderRequest) -> str:
    """Stable signature used both as auto-idempotency key and dup-detection key."""
    return _hash_payload({
        "u": user_id, "s": req.symbol.upper(), "side": req.side, "qty": req.qty,
        "t": req.instrument_type, "k": req.option_strike, "kind": req.option_kind,
    })


async def _idem_lookup(user_id: str, key: str) -> Optional[dict]:
    db = get_db()
    return await db.idempotency_keys.find_one({"user_id": user_id, "key": key})


async def _idem_store(user_id: str, key: str, response: dict) -> None:
    db = get_db()
    await db.idempotency_keys.update_one(
        {"user_id": user_id, "key": key},
        {"$set": {
            "user_id": user_id,
            "key": key,
            "response": response,
            "created_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


async def _ensure_idempotency_ttl() -> None:
    """Create TTL index (idempotent; safe to call multiple times)."""
    db = get_db()
    await db.idempotency_keys.create_index(
        "created_at",
        expireAfterSeconds=IDEMPOTENCY_TTL_HOURS * 3600,
    )


async def _check_duplicate(user_id: str, req: PaperOrderRequest) -> Optional[dict]:
    """Return the most recent matching order within the dup window, or None."""
    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=DUP_WINDOW_SECONDS)).isoformat()
    query = {
        "user_id": user_id,
        "symbol": req.symbol.upper(),
        "side": req.side,
        "qty": req.qty,
        "instrument_type": req.instrument_type,
        "option_strike": req.option_strike,
        "option_kind": req.option_kind,
        "created_at": {"$gte": cutoff},
    }
    return await db.paper_orders.find_one(query, sort=[("created_at", -1)])


# --- Validation helpers ------------------------------------------------------

def _resolve_price(req: PaperOrderRequest) -> float:
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


async def _check_kill_switch(user_id: str) -> None:
    db = get_db()
    risk = await db.risk_limits.find_one({"user_id": user_id}) or {}
    if risk.get("kill_switch"):
        raise HTTPException(423, "Kill switch is active. Disable it before placing orders.")


# --- Core placement / rollback ----------------------------------------------

def _position_key(req: PaperOrderRequest) -> str:
    parts = [req.symbol.upper(), req.instrument_type]
    if req.instrument_type == "OPT":
        parts += [str(req.option_strike), req.option_kind]
    return "|".join(parts)


async def _apply_to_position(user_id: str, req: PaperOrderRequest, price: float) -> dict:
    """Apply order to positions collection. Returns snapshot for rollback."""
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
            "user_id": user_id,
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
    return snapshot


async def _restore_position(user_id: str, snapshot: dict) -> None:
    db = get_db()
    pos_key = snapshot["pos_key"]
    before = snapshot["before"]
    if before is None:
        await db.paper_positions.delete_one({"user_id": user_id, "key": pos_key})
    else:
        await db.paper_positions.replace_one(
            {"user_id": user_id, "key": pos_key},
            before,
            upsert=True,
        )


async def place_paper_order(
    req: PaperOrderRequest,
    user: dict,
    *,
    check_kill_switch: bool = True,
    check_duplicate: bool = True,
) -> dict:
    """Core paper-order logic. Used by /paper/order and multi-leg.

    Validates inputs, checks kill switch, optionally rejects duplicates, applies
    to position and inserts the order doc. Returns the order dict.
    """
    db = get_db()
    if check_kill_switch:
        await _check_kill_switch(user["id"])
    if check_duplicate:
        dup = await _check_duplicate(user["id"], req)
        if dup:
            await record_event(
                user["id"], AuditEventType.DUPLICATE_BLOCKED, severity=AuditSeverity.WARN,
                actor="system",
                summary=f"Duplicate {req.side} {req.qty} {req.symbol} blocked",
                payload={"req": req.model_dump(), "dup_id": str(dup.get("_id"))},
            )
            raise HTTPException(
                409,
                f"Duplicate order detected within {DUP_WINDOW_SECONDS}s. "
                "Resubmit with ?force=true to override.",
            )
    price = _resolve_price(req)

    await _apply_to_position(user["id"], req, price)

    oid = str(uuid.uuid4())
    order = {
        "_id": oid,
        "user_id": user["id"],
        "symbol": req.symbol.upper(),
        "side": req.side,
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
    order["id"] = oid
    order.pop("_id")
    # SEBI trace: REQUEST → FILL on paper happens atomically
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


async def _undo_order(order: dict, snapshot: dict, user_id: str) -> None:
    db = get_db()
    await db.paper_orders.delete_one({"_id": order["id"]})
    await _restore_position(user_id, snapshot)


# --- Positions helper (used by dashboard too) -------------------------------

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


# --- HTTP Endpoints ----------------------------------------------------------

@router.post("/order")
async def paper_order(
    req: PaperOrderRequest,
    user: dict = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    force: bool = Query(default=False, description="Bypass duplicate-order detection."),
):
    key = idempotency_key or _signature(user["id"], req)
    cached = await _idem_lookup(user["id"], key)
    if cached:
        return {**cached["response"], "idempotent_replay": True}

    if force:
        await record_event(
            user["id"], AuditEventType.OVERRIDE, severity=AuditSeverity.HIGH,
            actor="user",
            summary=f"FORCE override on {req.side} {req.qty} {req.symbol}",
            payload={"req": req.model_dump()},
        )
    order = await place_paper_order(req, user, check_duplicate=not force)
    response = {**order, "idempotency_key": key}
    await _idem_store(user["id"], key, response)
    return response


@router.post("/order/multi-leg")
async def paper_multi_leg(
    req: MultiLegOrderRequest,
    user: dict = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    force: bool = Query(default=False),
):
    if not req.legs:
        raise HTTPException(400, "At least one leg required")
    await _check_kill_switch(user["id"])

    payload_sig = _hash_payload({
        "u": user["id"], "name": req.name,
        "legs": [leg.model_dump() for leg in req.legs],
    })
    key = idempotency_key or payload_sig
    cached = await _idem_lookup(user["id"], key)
    if cached:
        return {**cached["response"], "idempotent_replay": True}

    # Pre-flight validation: ensure every leg can be priced before any placement.
    for i, leg in enumerate(req.legs):
        pre = PaperOrderRequest(
            symbol=leg.symbol, side=leg.side, qty=leg.qty, order_type="MARKET",
            instrument_type=leg.instrument_type,
            option_strike=leg.option_strike, option_kind=leg.option_kind,
        )
        try:
            _resolve_price(pre)
        except HTTPException as e:
            raise HTTPException(e.status_code, f"Leg {i}: {e.detail}")

    # Place legs with snapshot-based rollback on mid-loop failure.
    placed: list[dict] = []
    snapshots: list[dict] = []
    db = get_db()
    try:
        for leg in req.legs:
            single = PaperOrderRequest(
                symbol=leg.symbol, side=leg.side, qty=leg.qty, order_type="MARKET",
                instrument_type=leg.instrument_type,
                option_strike=leg.option_strike, option_kind=leg.option_kind,
            )
            price = _resolve_price(single)
            snapshot = await _apply_to_position(user["id"], single, price)
            oid = str(uuid.uuid4())
            order = {
                "_id": oid, "user_id": user["id"],
                "symbol": single.symbol.upper(), "side": single.side, "qty": single.qty,
                "price": round(price, 2),
                "instrument_type": single.instrument_type,
                "option_strike": single.option_strike, "option_kind": single.option_kind,
                "status": "FILLED", "mode": "PAPER",
                "basket_pending": True,
                "created_at": now_iso(),
            }
            await db.paper_orders.insert_one(order)
            order["id"] = oid
            order.pop("_id")
            placed.append(order)
            snapshots.append(snapshot)
    except Exception as e:
        # Rollback all placed legs (in reverse) to restore consistency.
        for order, snapshot in reversed(list(zip(placed, snapshots))):
            try:
                await _undo_order(order, snapshot, user["id"])
            except Exception:
                pass  # best-effort
        await record_event(
            user["id"], AuditEventType.BASKET_ROLLBACK, severity=AuditSeverity.HIGH,
            actor="system",
            summary=f"Basket '{req.name}' rolled back: {e}",
            payload={"name": req.name, "legs": len(req.legs), "rolled_back": len(placed)},
        )
        raise HTTPException(500, f"Basket rolled back due to leg failure: {e}") from e

    bid = str(uuid.uuid4())
    await db.baskets.insert_one({
        "_id": bid, "user_id": user["id"], "name": req.name,
        "legs": [leg.model_dump() for leg in req.legs],
        "order_ids": [o["id"] for o in placed],
        "created_at": now_iso(),
    })
    # Clear the basket_pending flag now that the basket is committed.
    await db.paper_orders.update_many(
        {"_id": {"$in": [o["id"] for o in placed]}},
        {"$set": {"basket_pending": False, "basket_id": bid}},
    )

    response = {"basket_id": bid, "orders": placed, "idempotency_key": key}
    await _idem_store(user["id"], key, response)
    return response


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
