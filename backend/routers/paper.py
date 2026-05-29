"""HTTP layer for paper trading. Business logic lives in services/paper_trading."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from auth import get_current_user
from db import get_db, now_iso
from services.audit import AuditEventType, AuditSeverity, record_event
from services.paper_trading import (
    MultiLegOrderRequest,
    PaperOrderRequest,
    apply_to_position,
    check_kill_switch,
    compute_positions,
    ensure_idempotency_ttl as _ensure_idempotency_ttl,  # re-export for server lifespan
    idem_lookup,
    idem_store,
    place_paper_order,
    resolve_price,
    signature,
    undo_order,
)

router = APIRouter(prefix="/paper", tags=["paper"])

__all__ = ["router", "_ensure_idempotency_ttl"]


@router.post("/order")
async def paper_order(
    req: PaperOrderRequest,
    user: dict = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    force: bool = Query(default=False, description="Bypass duplicate-order detection."),
):
    key = idempotency_key or signature(user["id"], req)
    cached = await idem_lookup(user["id"], key)
    if cached:
        return {**cached["response"], "idempotent_replay": True}

    if force:
        await record_event(
            user["id"], AuditEventType.OVERRIDE, severity=AuditSeverity.HIGH,
            actor="user",
            summary=f"FORCE override on {req.side} {req.qty} {req.symbol}",
            payload={"req": req.model_dump()},
        )
    order = await place_paper_order(req, user, do_check_duplicate=not force)
    response = {**order, "idempotency_key": key}
    await idem_store(user["id"], key, response)
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
    await check_kill_switch(user["id"])

    payload_sig = uuid.UUID(int=hash(tuple(
        (leg.symbol, leg.side, leg.qty, leg.option_strike, leg.option_kind, leg.instrument_type)
        for leg in req.legs
    )) & ((1 << 128) - 1)).hex
    key = idempotency_key or payload_sig
    cached = await idem_lookup(user["id"], key)
    if cached:
        return {**cached["response"], "idempotent_replay": True}

    # Pre-flight validation.
    for i, leg in enumerate(req.legs):
        pre = PaperOrderRequest(
            symbol=leg.symbol, side=leg.side, qty=leg.qty, order_type="MARKET",
            instrument_type=leg.instrument_type,
            option_strike=leg.option_strike, option_kind=leg.option_kind,
        )
        try:
            resolve_price(pre)
        except HTTPException as e:
            raise HTTPException(e.status_code, f"Leg {i}: {e.detail}")

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
            price = resolve_price(single)
            snapshot = await apply_to_position(user["id"], single, price)
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
        for order, snapshot in reversed(list(zip(placed, snapshots))):
            try:
                await undo_order(order, snapshot, user["id"])
            except Exception:
                pass
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
    await db.paper_orders.update_many(
        {"_id": {"$in": [o["id"] for o in placed]}},
        {"$set": {"basket_pending": False, "basket_id": bid}},
    )
    response = {"basket_id": bid, "orders": placed, "idempotency_key": key}
    await idem_store(user["id"], key, response)
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
