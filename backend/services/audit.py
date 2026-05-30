"""SEBI-style audit log service.

Append-only event stream that traces every signal → decision → request →
response → fill → override interaction. Used to:
  - reconstruct any trade after the fact
  - prove compliance during a SEBI inspection
  - power the in-app audit viewer

Hooks call `record_event()` fire-and-forget — failures never break user flows.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from db import get_db, now_iso

logger = logging.getLogger("algoforge.audit")


class AuditEventType(str, Enum):
    # SEBI 6-step trace
    SIGNAL = "SIGNAL"             # AI/strategy generated a candidate signal
    DECISION = "DECISION"         # human or system decided to act (or skip)
    REQUEST = "REQUEST"           # order request sent (paper or broker)
    RESPONSE = "RESPONSE"         # broker ack
    FILL = "FILL"                 # order filled (partial / complete)
    OVERRIDE = "OVERRIDE"         # human bypassed a guard (force, kill release)
    # Operational events
    AUTH_LOGIN = "AUTH_LOGIN"
    AUTH_REGISTER = "AUTH_REGISTER"
    KILL_SWITCH = "KILL_SWITCH"
    RISK_POLICY_CHANGE = "RISK_POLICY_CHANGE"
    BROKER_CONNECT = "BROKER_CONNECT"
    BROKER_DISCONNECT = "BROKER_DISCONNECT"
    BROKER_TEST = "BROKER_TEST"
    RECONCILE = "RECONCILE"
    STRATEGY_SAVED = "STRATEGY_SAVED"
    BACKTEST_RUN = "BACKTEST_RUN"
    DUPLICATE_BLOCKED = "DUPLICATE_BLOCKED"
    BASKET_ROLLBACK = "BASKET_ROLLBACK"


class AuditSeverity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    HIGH = "HIGH"


# UI filter chips — keep order stable for deterministic rendering.
SEBI_TRACE_TYPES = [
    AuditEventType.SIGNAL,
    AuditEventType.DECISION,
    AuditEventType.REQUEST,
    AuditEventType.RESPONSE,
    AuditEventType.FILL,
    AuditEventType.OVERRIDE,
]


async def _ensure_indexes() -> None:
    db = get_db()
    await db.audit_events.create_index([("user_id", 1), ("ts", -1)])
    await db.audit_events.create_index("event_type")


async def record_event(
    user_id: str | None,
    event_type: AuditEventType,
    *,
    severity: AuditSeverity = AuditSeverity.INFO,
    actor: str = "user",                  # 'user' | 'system' | 'broker'
    summary: str = "",
    payload: Optional[dict[str, Any]] = None,
    correlation_id: Optional[str] = None,  # links related events (order, basket, signal)
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Append an immutable audit row. Best-effort: never raises."""
    try:
        db = get_db()
        row = {
            "_id": str(uuid.uuid4()),
            "user_id": user_id or "anonymous",
            "event_type": event_type.value,
            "severity": severity.value,
            "actor": actor,
            "summary": summary[:500],
            "payload": payload or {},
            "correlation_id": correlation_id,
            "ip": ip,
            "user_agent": user_agent,
            "ts": now_iso(),
        }
        await db.audit_events.insert_one(row)
        # Fire-and-forget alert dispatch on HIGH severity. Never blocks.
        if severity == AuditSeverity.HIGH:
            try:
                import asyncio as _asyncio

                from services.alerts import dispatch_event
                _asyncio.create_task(dispatch_event(row))
            except Exception as e:
                logger.warning("alert dispatch schedule failed: %s", e)
    except Exception as e:
        # Audit failures must never break trading flows.
        logger.warning("audit insert failed: %s", e)


async def query_events(
    user_id: str,
    *,
    event_types: list[str] | None = None,
    severities: list[str] | None = None,
    q: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    correlation_id: str | None = None,
    limit: int = 100,
    cursor: str | None = None,  # compound cursor "<ts>|<id>" for burst stability
) -> dict:
    db = get_db()
    query: dict[str, Any] = {"user_id": user_id}

    # Whitelist event types against the enum to fail-fast on typos.
    if event_types:
        valid = {t.value for t in AuditEventType}
        cleaned = [t for t in event_types if t in valid]
        if cleaned:
            query["event_type"] = {"$in": cleaned}
    if severities:
        query["severity"] = {"$in": severities}
    if correlation_id:
        query["correlation_id"] = correlation_id

    if from_ts or to_ts:
        ts_q: dict[str, Any] = {}
        if from_ts:
            ts_q["$gte"] = from_ts
        if to_ts:
            ts_q["$lte"] = to_ts
        query["ts"] = ts_q

    # Compound cursor: format "<ts>|<id>" — survives same-ms event bursts.
    if cursor:
        if "|" in cursor:
            cur_ts, cur_id = cursor.split("|", 1)
            query["$or"] = [
                {"ts": {"$lt": cur_ts}},
                {"ts": cur_ts, "_id": {"$lt": cur_id}},
            ]
        else:
            query.setdefault("ts", {})["$lt"] = cursor

    if q:
        # Escape user input before passing to $regex.
        query["summary"] = {"$regex": re.escape(q), "$options": "i"}

    docs = (
        await db.audit_events.find(query)
        .sort([("ts", -1), ("_id", -1)])
        .limit(limit + 1)
        .to_list(limit + 1)
    )
    has_more = len(docs) > limit
    docs = docs[:limit]
    for d in docs:
        d["id"] = str(d.pop("_id"))
    next_cursor = f"{docs[-1]['ts']}|{docs[-1]['id']}" if has_more and docs else None
    return {"items": docs, "next_cursor": next_cursor, "has_more": has_more}


async def export_events_csv(user_id: str, **kwargs) -> str:
    """Render CSV of events matching the same filters."""
    import csv
    import io

    kwargs.setdefault("limit", 5000)
    result = await query_events(user_id, **kwargs)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ts", "event_type", "severity", "actor", "summary", "correlation_id"])
    for e in result["items"]:
        writer.writerow([e["ts"], e["event_type"], e["severity"], e["actor"], e["summary"], e.get("correlation_id", "")])
    return buf.getvalue()


def types_for_ui() -> dict:
    return {
        "all": [t.value for t in AuditEventType],
        "sebi_trace": [t.value for t in SEBI_TRACE_TYPES],
        "severities": [s.value for s in AuditSeverity],
    }
