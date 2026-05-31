"""Live broker order routing.

Two-step flow with strong guardrails:

  1. POST /api/orders/live/preview
       Returns an order preview + a short-lived HMAC `confirm_token`
       (60-second TTL, includes exact order params). The frontend renders
       a "TYPE LIVE TO CONFIRM" modal.

  2. POST /api/orders/live/execute
       Re-validates the HMAC, re-runs all guardrails, places the order via
       the broker adapter, writes an audit row at severity=HIGH.

Guardrails (every preview AND execute):
  - kill_switch must be OFF
  - User must have a 'live' broker connection for the requested broker
  - Daily live-order rate limit (default 10 orders/day per user)
  - Notional cap (default ₹50,000 per order — explicitly override on the
    request if you really mean it)
  - confirm_token TTL = 60 seconds, single-use (drop into `live_used_tokens`)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
from brokers import decrypt_credentials
from brokers.base import BrokerError
from brokers.registry import make_client
from brokers.schemas import NormalizedOrderRequest
from db import get_db, now_iso
from market_data import get_last_price
from services.audit import AuditEventType, AuditSeverity, record_event
from services.paper_trading import check_kill_switch

router = APIRouter(prefix="/orders/live", tags=["orders"])

# Defaults — tunable via env later, but err on the side of safety.
DEFAULT_NOTIONAL_CAP = float(os.environ.get("LIVE_NOTIONAL_CAP", "50000"))
DEFAULT_DAILY_ORDER_LIMIT = int(os.environ.get("LIVE_DAILY_ORDER_LIMIT", "10"))
CONFIRM_TOKEN_TTL = 60  # seconds


class LiveOrderRequest(BaseModel):
    broker: Literal["zerodha", "upstox", "dhan", "icici"]
    symbol: str = Field(min_length=1, max_length=20)
    exchange: str = "NSE"
    side: Literal["BUY", "SELL"]
    qty: int = Field(gt=0, le=100000)
    order_type: Literal["MARKET", "LIMIT"] = "MARKET"
    product: Literal["MIS", "CNC", "NRML"] = "CNC"
    price: Optional[float] = None
    tag: Optional[str] = None


class LiveExecuteRequest(LiveOrderRequest):
    confirm_token: str
    typed_confirm: Literal["LIVE"]  # frontend forces user to type "LIVE"


def _hmac_payload(req: LiveOrderRequest, user_id: str, ts: int) -> str:
    payload = {
        "u": user_id, "b": req.broker, "s": req.symbol.upper(),
        "side": req.side, "qty": req.qty, "type": req.order_type,
        "px": req.price, "prod": req.product, "ts": ts,
    }
    raw = json.dumps(payload, sort_keys=True).encode()
    secret = os.environ.get("SECRET_KEY", "fallback").encode()
    return hmac.new(secret, raw, hashlib.sha256).hexdigest()


async def _ensure_indexes() -> None:
    db = get_db()
    info = await db.live_used_tokens.index_information()
    if "created_at_ttl" not in info:
        await db.live_used_tokens.create_index(
            "created_at", expireAfterSeconds=CONFIRM_TOKEN_TTL * 2,
            name="created_at_ttl",
        )


async def _broker_connection_or_404(user_id: str, broker: str) -> dict:
    db = get_db()
    conn = await db.broker_connections.find_one({"user_id": user_id, "broker": broker})
    if not conn:
        raise HTTPException(400, f"No saved broker connection for {broker}. Connect it first.")
    if conn.get("status") != "live":
        raise HTTPException(
            400,
            f"{broker} connection status={conn.get('status', 'unknown')}. Re-test or re-link the broker before placing live orders.",
        )
    return conn


async def _daily_count(user_id: str) -> int:
    db = get_db()
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return await db.live_orders.count_documents({"user_id": user_id, "created_at": {"$gte": midnight}})


async def _enforce_guardrails(req: LiveOrderRequest, user: dict) -> dict:
    """Returns dict with `estimated_price` and `notional`. Raises HTTPException on any breach.
    Called from BOTH /preview and /execute so every guardrail is re-checked at execute time."""
    await check_kill_switch(user["id"])
    await _broker_connection_or_404(user["id"], req.broker)

    # Daily rate limit.
    daily = await _daily_count(user["id"])
    if daily >= DEFAULT_DAILY_ORDER_LIMIT:
        raise HTTPException(
            429,
            f"Daily live-order limit reached ({DEFAULT_DAILY_ORDER_LIMIT}). Wait until 00:00 UTC.",
        )

    # Price estimate for notional check.
    if req.order_type == "LIMIT":
        if not req.price or req.price <= 0:
            raise HTTPException(400, "LIMIT order requires a positive price.")
        est_price = req.price
    else:
        est_price = get_last_price(req.symbol)
        if est_price <= 0:
            # Symbol not in our mock universe — query the broker for a real
            # LTP. Requires a live broker connection (already verified) and,
            # for Kite, the paid market-data add-on. Falls through to a 400
            # below if the broker returns 0 / lacks the subscription.
            db = get_db()
            conn = await db.broker_connections.find_one({"user_id": user["id"], "broker": req.broker})
            if conn:
                creds = decrypt_credentials(conn["credentials_enc"])
                adapter = make_client(req.broker, creds, user_id=user["id"])
                try:
                    est_price = await adapter.get_quote(req.symbol, req.exchange)
                except BrokerError as e:
                    # Kite returns "Insufficient permission" without the
                    # market-data add-on. Surface a clear suggestion.
                    msg = str(e)
                    if "permission" in msg.lower():
                        raise HTTPException(
                            400,
                            f"Cannot fetch live LTP for {req.symbol} (your broker's market-data plan is not active). "
                            "Use a LIMIT order with your own price for the notional check.",
                        ) from e
                    raise HTTPException(400, f"Could not fetch {req.broker} LTP for {req.symbol}: {e}") from e
        if est_price <= 0:
            raise HTTPException(
                400,
                f"Unknown symbol {req.symbol} on {req.exchange} — could not estimate notional. "
                "Switch to LIMIT and provide a price.",
            )

    notional = est_price * req.qty
    if notional > DEFAULT_NOTIONAL_CAP:
        raise HTTPException(
            400,
            f"Order notional ₹{notional:,.0f} exceeds platform cap ₹{DEFAULT_NOTIONAL_CAP:,.0f}. Lower qty/price.",
        )

    return {"estimated_price": est_price, "notional": notional, "daily_count": daily}


@router.post("/preview")
async def preview_live_order(req: LiveOrderRequest, user: dict = Depends(get_current_user)):
    guard = await _enforce_guardrails(req, user)
    ts = int(datetime.now(timezone.utc).timestamp())
    token = f"{ts}.{_hmac_payload(req, user['id'], ts)}"
    await record_event(
        user["id"], AuditEventType.REQUEST, severity=AuditSeverity.INFO, actor="user",
        summary=f"LIVE preview {req.side} {req.qty} {req.symbol} on {req.broker}",
        payload={"req": req.model_dump(), **guard},
    )
    return {
        "ok": True,
        "broker": req.broker,
        "symbol": req.symbol.upper(),
        "side": req.side,
        "qty": req.qty,
        "order_type": req.order_type,
        "estimated_price": guard["estimated_price"],
        "notional": guard["notional"],
        "notional_cap": DEFAULT_NOTIONAL_CAP,
        "daily_count": guard["daily_count"],
        "daily_limit": DEFAULT_DAILY_ORDER_LIMIT,
        "confirm_token": token,
        "expires_in": CONFIRM_TOKEN_TTL,
    }


@router.post("/execute")
async def execute_live_order(req: LiveExecuteRequest, user: dict = Depends(get_current_user)):
    # 1. Verify confirm_token format + freshness.
    try:
        ts_str, sig = req.confirm_token.split(".", 1)
        ts = int(ts_str)
    except Exception as e:
        raise HTTPException(400, "Malformed confirm_token") from e

    age = int(datetime.now(timezone.utc).timestamp()) - ts
    if age < 0 or age > CONFIRM_TOKEN_TTL:
        raise HTTPException(400, f"confirm_token expired ({age}s old). Re-preview the order.")

    expected = _hmac_payload(
        LiveOrderRequest(**req.model_dump(exclude={"confirm_token", "typed_confirm"})),
        user["id"], ts,
    )
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(400, "confirm_token does not match order params (tampered or stale).")

    # 2. Single-use enforcement: drop token into Mongo (TTL-purged).
    db = get_db()
    try:
        await db.live_used_tokens.insert_one({
            "_id": req.confirm_token,
            "user_id": user["id"],
            "created_at": datetime.now(timezone.utc),
        })
    except Exception as e:
        # DuplicateKeyError → token already used. Block replay.
        if "duplicate key" in str(e).lower():
            raise HTTPException(409, "confirm_token already used. Re-preview to get a fresh token.") from e
        raise

    # 3. Re-run ALL guardrails (kill switch could have flipped, notional could now exceed).
    base_req = LiveOrderRequest(**req.model_dump(exclude={"confirm_token", "typed_confirm"}))
    guard = await _enforce_guardrails(base_req, user)

    # 4. Load broker connection + adapter.
    conn = await _broker_connection_or_404(user["id"], req.broker)
    creds = decrypt_credentials(conn["credentials_enc"])
    adapter = make_client(req.broker, creds, user_id=user["id"])

    # 5. Audit BEFORE the call — so we have a record even on broker timeout.
    correlation_id = str(uuid.uuid4())
    await record_event(
        user["id"], AuditEventType.REQUEST, severity=AuditSeverity.HIGH, actor="user",
        summary=f"LIVE ORDER {req.side} {req.qty} {req.symbol} ({req.broker})",
        payload={"req": base_req.model_dump(), "notional": guard["notional"]},
        correlation_id=correlation_id,
    )

    # 6. Place via adapter.
    norm_req = NormalizedOrderRequest(
        symbol=req.symbol.upper(),
        exchange=req.exchange,
        side=req.side,
        qty=req.qty,
        order_type=req.order_type,
        product=req.product,
        price=req.price,
        tag=(req.tag or "live")[:20],
    )
    try:
        placed = await adapter.place_order(norm_req)
    except BrokerError as e:
        await record_event(
            user["id"], AuditEventType.REJECT, severity=AuditSeverity.HIGH, actor="broker",
            summary=f"LIVE REJECTED {req.side} {req.qty} {req.symbol} — {e}",
            payload={"req": base_req.model_dump(), "error": str(e)},
            correlation_id=correlation_id,
        )
        raise HTTPException(400, f"Broker rejected: {e}") from e

    # 7. Persist live_orders row.
    placed_dict = placed.model_dump()
    placed_dict["_id"] = placed.id
    placed_dict["user_id"] = user["id"]
    placed_dict["correlation_id"] = correlation_id
    placed_dict["created_at"] = now_iso()
    placed_dict["mode"] = "LIVE"
    await db.live_orders.update_one(
        {"_id": placed.id}, {"$set": placed_dict}, upsert=True,
    )

    await record_event(
        user["id"], AuditEventType.RESPONSE, severity=AuditSeverity.HIGH, actor="broker",
        summary=f"LIVE PLACED {req.side} {req.qty} {req.symbol} → {placed.broker_order_id} status={placed.status}",
        payload={"broker_order_id": placed.broker_order_id, "status": placed.status},
        correlation_id=correlation_id,
    )

    return {
        "ok": True,
        "broker_order_id": placed.broker_order_id,
        "status": placed.status,
        "id": placed.id,
        "correlation_id": correlation_id,
        "guardrails": guard,
    }


@router.get("/orders")
async def list_live_orders(limit: int = 50, user: dict = Depends(get_current_user)):
    db = get_db()
    docs = await db.live_orders.find({"user_id": user["id"]}).sort("created_at", -1).limit(limit).to_list(limit)
    for d in docs:
        d.pop("_id", None)
    return {"orders": docs}
