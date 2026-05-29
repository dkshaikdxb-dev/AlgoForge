"""Reconciliation HTTP endpoints."""
from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from brokers import decrypt_credentials
from brokers.registry import make_client
from db import get_db
from services.reconciliation import (
    get_reconciliation_log,
    get_reconciliation_summary,
    reconcile_orders,
)
from services.audit import AuditEventType, record_event

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@router.get("/summary")
async def reconciliation_summary(user: dict = Depends(get_current_user)):
    return await get_reconciliation_summary(user["id"])


@router.get("/log")
async def reconciliation_log(
    broker: str | None = None,
    limit: int = 100,
    user: dict = Depends(get_current_user),
):
    return {"items": await get_reconciliation_log(user["id"], broker, limit=limit)}


@router.post("/run/{broker}")
async def reconciliation_run(broker: str, user: dict = Depends(get_current_user)):
    db = get_db()
    rec = await db.broker_connections.find_one({"user_id": user["id"], "broker": broker})
    if not rec and broker != "paper":
        raise HTTPException(404, "Broker not connected")
    creds = decrypt_credentials(rec["credentials_enc"]) if rec else {}
    # Lazy-import to avoid the paper adapter pulling routers at module load.
    if broker == "paper":
        from brokers.paper_adapter import PaperAdapter
        adapter = PaperAdapter(creds, user_id=user["id"])
    else:
        adapter = make_client(broker, creds)
        adapter.user_id = user["id"]  # tag for breaker key
    result = await reconcile_orders(adapter, user["id"])
    await record_event(user["id"], AuditEventType.RECONCILE, actor="system",
                       summary=f"Reconcile {broker}: {result.get('state')}",
                       payload={"broker": broker, "state": result.get("state"),
                                "actions": len(result.get("actions", []))})
    return result
