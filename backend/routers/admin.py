"""Platform super-admin endpoints. role=='admin' required.

Panels:
- /api/admin/audit       — global user-audit feed across all users
- /api/admin/health      — Mongo ping, reconciler liveness, LLM key presence
- /api/admin/risk/users  — every user with risk policy + open P&L + kill state
- /api/admin/risk/kill   — force a user's kill switch (writes admin_events)
- /api/admin/brokers/map — every broker connection across users with status
- /api/admin/events      — read the admin_events collection
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import get_current_user
from db import get_db, now_iso
from services.admin_audit import list_admin_events, record_admin_event
from services.audit import query_events as query_user_events
from services.paper_trading import compute_positions

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin role required")
    return user


@router.get("/audit")
async def admin_audit_feed(
    event_types: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
    admin: dict = Depends(require_admin),
):
    db = get_db()
    q: dict = {}
    if event_types:
        q["event_type"] = {"$in": [t.strip() for t in event_types.split(",") if t.strip()]}
    if cursor:
        if "|" in cursor:
            cts, cid = cursor.split("|", 1)
            q["$or"] = [{"ts": {"$lt": cts}}, {"ts": cts, "_id": {"$lt": cid}}]
        else:
            q["ts"] = {"$lt": cursor}
    docs = await db.audit_events.find(q).sort([("ts", -1), ("_id", -1)]).limit(limit + 1).to_list(limit + 1)
    has_more = len(docs) > limit
    docs = docs[:limit]
    for d in docs:
        d["id"] = str(d.pop("_id"))
    next_cursor = f"{docs[-1]['ts']}|{docs[-1]['id']}" if has_more and docs else None
    return {"items": docs, "next_cursor": next_cursor, "has_more": has_more}


@router.get("/health")
async def admin_health(admin: dict = Depends(require_admin)):
    db = get_db()
    health = {"ts": now_iso()}
    # Mongo ping
    try:
        await db.command("ping")
        health["mongo"] = "ok"
    except Exception as e:
        health["mongo"] = f"error: {e}"
    # Reconciler — module exposes a constant; reaching here means lifespan task started
    from services import reconciler_loop  # noqa: F401
    health["reconciler"] = "running"
    # LLM key
    health["emergent_llm_key"] = "configured" if os.environ.get("EMERGENT_LLM_KEY") else "missing"
    # LLM provider mode + per-provider key status (works for both emergent + direct).
    from llm_provider import status as _llm_status
    health["llm"] = _llm_status()
    # Counts
    health["users"] = await db.users.count_documents({})
    health["audit_events"] = await db.audit_events.count_documents({})
    health["paper_orders"] = await db.paper_orders.count_documents({})
    health["live_brokers"] = await db.broker_connections.count_documents({"status": "live"})
    health["broker_connections"] = await db.broker_connections.count_documents({})
    # Alert transport configuration
    from services.alerts import transport_status
    health["alerts"] = transport_status()
    return health


@router.get("/risk/users")
async def admin_risk_users(admin: dict = Depends(require_admin)):
    db = get_db()
    users = await db.users.find({}, {"_id": 1, "email": 1, "name": 1, "role": 1, "created_at": 1}).to_list(500)
    rows = []
    for u in users:
        uid = str(u["_id"])
        risk = await db.risk_limits.find_one({"user_id": uid}) or {}
        positions = await compute_positions({"id": uid})
        rows.append({
            "id": uid,
            "email": u["email"],
            "name": u.get("name"),
            "role": u.get("role", "trader"),
            "created_at": u.get("created_at"),
            "kill_switch": bool(risk.get("kill_switch")),
            "max_drawdown_pct": risk.get("max_drawdown_pct"),
            "daily_loss_cap": risk.get("daily_loss_cap"),
            "position_limit": risk.get("position_limit"),
            "open_positions": len(positions["positions"]),
            "total_pnl": positions["total_pnl"],
            "exposure": positions["exposure"],
        })
    return {"items": rows}


class KillRequest(BaseModel):
    user_id: str
    kill_switch: bool
    reason: str | None = None


@router.post("/risk/kill")
async def admin_force_kill(req: KillRequest, admin: dict = Depends(require_admin)):
    db = get_db()
    user = await db.users.find_one({"_id": req.user_id})
    if not user:
        raise HTTPException(404, "User not found")
    await db.risk_limits.update_one(
        {"user_id": req.user_id},
        {"$set": {"kill_switch": req.kill_switch, "updated_at": now_iso()}},
        upsert=True,
    )
    await record_admin_event(
        admin["id"],
        "FORCE_KILL_SWITCH",
        target_user_id=req.user_id,
        payload={"kill_switch": req.kill_switch, "reason": req.reason},
        summary=f"{'ARMED' if req.kill_switch else 'RELEASED'} kill switch on {user['email']}"
                + (f" — {req.reason}" if req.reason else ""),
    )
    return {"ok": True, "user_id": req.user_id, "kill_switch": req.kill_switch}


@router.get("/brokers/map")
async def admin_broker_map(admin: dict = Depends(require_admin)):
    db = get_db()
    conns = await db.broker_connections.find(
        {}, {"credentials_enc": 0},
    ).sort("updated_at", -1).to_list(500)
    # enrich with user email
    user_ids = list({c["user_id"] for c in conns})
    users = await db.users.find({"_id": {"$in": user_ids}}, {"email": 1}).to_list(len(user_ids))
    email_map = {str(u["_id"]): u["email"] for u in users}
    out = []
    for c in conns:
        c.pop("_id", None)
        c["user_email"] = email_map.get(c["user_id"], "unknown")
        out.append(c)
    # stats per broker
    by_broker: dict = {}
    for c in out:
        b = c["broker"]
        stats = by_broker.setdefault(b, {"total": 0, "live": 0, "error": 0, "saved": 0})
        stats["total"] += 1
        s = c.get("status", "saved")
        if s in stats:
            stats[s] += 1
    return {"connections": out, "by_broker": by_broker}


@router.get("/events")
async def admin_events_feed(limit: int = 100, cursor: str | None = None, admin: dict = Depends(require_admin)):
    return await list_admin_events(limit=limit, cursor=cursor)


@router.post("/promote")
async def admin_promote(target_email: str, admin: dict = Depends(require_admin)):
    """Promote another user to admin."""
    db = get_db()
    target = await db.users.find_one({"email": target_email.lower()})
    if not target:
        raise HTTPException(404, "User not found")
    await db.users.update_one({"_id": target["_id"]}, {"$set": {"role": "admin"}})
    await record_admin_event(
        admin["id"], "PROMOTE_ROLE",
        target_user_id=str(target["_id"]),
        payload={"new_role": "admin"},
        summary=f"Promoted {target_email} to admin",
    )
    return {"ok": True, "email": target_email, "role": "admin"}
