"""Admin event audit trail (separate from user-facing audit_events).

Tracks privileged actions: impersonation, force-kill, role changes,
configuration overrides. Append-only, queryable by admin only.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from db import get_db, now_iso

logger = logging.getLogger("algoforge.admin_audit")


async def ensure_indexes() -> None:
    db = get_db()
    await db.admin_events.create_index([("ts", -1)])
    await db.admin_events.create_index("admin_id")
    await db.admin_events.create_index("target_user_id")


async def record_admin_event(
    admin_id: str,
    action: str,
    *,
    target_user_id: Optional[str] = None,
    target_broker: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    summary: str = "",
) -> None:
    try:
        db = get_db()
        await db.admin_events.insert_one({
            "_id": str(uuid.uuid4()),
            "admin_id": admin_id,
            "action": action,
            "target_user_id": target_user_id,
            "target_broker": target_broker,
            "summary": summary[:500],
            "payload": payload or {},
            "ts": now_iso(),
        })
    except Exception as e:
        logger.warning("admin audit insert failed: %s", e)


async def list_admin_events(*, limit: int = 100, cursor: str | None = None) -> dict:
    db = get_db()
    q: dict = {}
    if cursor:
        q["ts"] = {"$lt": cursor}
    docs = await db.admin_events.find(q).sort("ts", -1).limit(limit + 1).to_list(limit + 1)
    has_more = len(docs) > limit
    docs = docs[:limit]
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {"items": docs, "next_cursor": docs[-1]["ts"] if has_more else None, "has_more": has_more}
