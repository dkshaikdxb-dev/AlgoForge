"""Reconciliation service — compares platform state with broker state.

For a real broker, this:
  1. Pulls broker's authoritative order book + positions.
  2. Diffs against `paper_orders` / `paper_positions` (we'll add `live_orders` later).
  3. Emits a `reconciliation_log` row per discrepancy with an `action_taken`.
  4. Updates the reconciliation_state on each affected order/position.

For the paper broker, reconciliation is a no-op (paper IS the source of truth)
— state is always NOT_APPLICABLE.

This iteration ships the data model + diff algorithm + endpoint. Real-broker
poll/WS wiring lands together with live broker keys.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from brokers.base import BrokerAdapter, BrokerError
from brokers.schemas import (
    NormalizedOrder,
    NormalizedPosition,
    OrderStatus,
    ReconciliationState,
)
from db import get_db, now_iso

logger = logging.getLogger("algoforge.reconciliation")


class ReconciliationAction:
    ADOPT_BROKER_ORDER = "ADOPT_BROKER_ORDER"      # broker had order we didn't
    MARK_LOST = "MARK_LOST"                        # we had order broker doesn't
    SYNC_STATUS = "SYNC_STATUS"                    # status drift (placed→filled)
    SYNC_FILL_QTY = "SYNC_FILL_QTY"                # partial fill drift
    NO_OP = "NO_OP"


async def _log(user_id: str, broker: str, entry: dict[str, Any]) -> None:
    db = get_db()
    await db.reconciliation_log.insert_one({
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "broker": broker,
        "ts": now_iso(),
        **entry,
    })


def _orders_equal(local: dict, remote: NormalizedOrder) -> bool:
    """Cheap structural equality for the reconciler diff."""
    return (
        local.get("status") == remote.status
        and int(local.get("filled_qty", 0) or 0) == remote.filled_qty
        and (local.get("avg_fill_price") or 0) == (remote.avg_fill_price or 0)
    )


async def reconcile_orders(adapter, user_id: str) -> dict:
    """Diff broker order book against our `live_orders` collection.

    The paper adapter shortcuts this (always SYNCED). For real brokers the
    `live_orders` collection (to be added when live wiring lands) carries
    `broker_order_id`. Until then this function returns an informative shape.
    """
    broker = getattr(adapter, "name", "unknown")
    if broker == "paper":
        await _log(user_id, broker, {
            "action_taken": ReconciliationAction.NO_OP,
            "reason": "paper broker is source of truth",
        })
        return {
            "broker": broker,
            "checked": 0,
            "actions": [],
            "state": ReconciliationState.NOT_APPLICABLE.value,
        }

    # Legacy adapters (zerodha/upstox/dhan/icici/rmoney) don't yet implement
    # the async `get_orders -> list[NormalizedOrder]` contract. Gate cleanly.
    if not isinstance(adapter, BrokerAdapter):
        await _log(user_id, broker, {
            "action_taken": "ADAPTER_LEGACY",
            "reason": "Adapter pre-dates BrokerAdapter ABC; reconciliation pending live wiring.",
        })
        return {
            "broker": broker,
            "checked": 0,
            "actions": [],
            "state": ReconciliationState.PENDING_RECONCILE.value,
            "note": "Awaiting live broker adapter implementation.",
        }

    try:
        remote_orders = await adapter.get_orders()
    except BrokerError as e:
        logger.warning("Reconciler could not fetch orders from %s: %s", broker, e)
        await _log(user_id, broker, {
            "action_taken": "FETCH_FAILED",
            "reason": str(e),
        })
        return {
            "broker": broker,
            "checked": 0,
            "actions": [],
            "state": ReconciliationState.FAILED.value,
            "error": str(e),
        }

    db = get_db()
    local_docs = await db.live_orders.find(
        {"user_id": user_id, "broker": broker},
    ).to_list(500)
    local_by_bid = {d["broker_order_id"]: d for d in local_docs if d.get("broker_order_id")}
    remote_by_bid = {o.broker_order_id: o for o in remote_orders if o.broker_order_id}

    actions: list[dict] = []

    # 1. Orders broker has that we don't → adopt.
    for bid, ro in remote_by_bid.items():
        if bid in local_by_bid:
            continue
        await db.live_orders.insert_one({
            "_id": str(uuid.uuid4()),
            "user_id": user_id,
            "broker": broker,
            "broker_order_id": bid,
            "reconciliation_state": ReconciliationState.RECONCILED.value,
            **ro.model_dump(exclude={"id"}),
        })
        actions.append({"action": ReconciliationAction.ADOPT_BROKER_ORDER, "broker_order_id": bid})

    # 2. Orders we have that broker doesn't → mark lost (only if status was open).
    for bid, ld in local_by_bid.items():
        if bid in remote_by_bid:
            continue
        if ld.get("status") in (OrderStatus.FILLED.value, OrderStatus.CANCELLED.value):
            continue
        await db.live_orders.update_one(
            {"_id": ld["_id"]},
            {"$set": {
                "reconciliation_state": ReconciliationState.OUT_OF_SYNC.value,
                "status": OrderStatus.UNKNOWN.value,
                "updated_at": now_iso(),
            }},
        )
        actions.append({"action": ReconciliationAction.MARK_LOST, "broker_order_id": bid})

    # 3. Status / fill_qty drift.
    for bid in set(local_by_bid) & set(remote_by_bid):
        ld = local_by_bid[bid]
        ro = remote_by_bid[bid]
        if _orders_equal(ld, ro):
            await db.live_orders.update_one(
                {"_id": ld["_id"]},
                {"$set": {"reconciliation_state": ReconciliationState.SYNCED.value}},
            )
            continue
        await db.live_orders.update_one(
            {"_id": ld["_id"]},
            {"$set": {
                "status": ro.status,
                "filled_qty": ro.filled_qty,
                "avg_fill_price": ro.avg_fill_price,
                "reconciliation_state": ReconciliationState.RECONCILED.value,
                "updated_at": now_iso(),
            }},
        )
        actions.append({
            "action": ReconciliationAction.SYNC_STATUS,
            "broker_order_id": bid,
            "from": ld.get("status"),
            "to": ro.status,
        })

    for a in actions:
        await _log(user_id, broker, a)

    return {
        "broker": broker,
        "checked": len(remote_orders),
        "actions": actions,
        "state": ReconciliationState.SYNCED.value if not actions else ReconciliationState.RECONCILED.value,
    }


async def get_reconciliation_log(user_id: str, broker: str | None, limit: int = 100) -> list[dict]:
    db = get_db()
    q: dict[str, Any] = {"user_id": user_id}
    if broker:
        q["broker"] = broker
    docs = await db.reconciliation_log.find(q).sort("ts", -1).to_list(limit)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs


async def get_reconciliation_summary(user_id: str) -> dict:
    db = get_db()
    docs = await db.broker_connections.find({"user_id": user_id}, {"_id": 0, "credentials_enc": 0}).to_list(20)
    counts = {}
    for state in ReconciliationState:
        counts[state.value] = await db.live_orders.count_documents({
            "user_id": user_id, "reconciliation_state": state.value,
        })
    return {
        "connected_brokers": [d["broker"] for d in docs],
        "counts_by_state": counts,
    }
