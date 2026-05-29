"""Audit log HTTP endpoints."""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from auth import get_current_user
from services.audit import export_events_csv, query_events, types_for_ui

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/types")
async def audit_types(user: dict = Depends(get_current_user)):
    return types_for_ui()


@router.get("/events")
async def audit_events(
    event_types: str | None = Query(default=None, description="Comma-separated"),
    severities: str | None = Query(default=None, description="Comma-separated"),
    q: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    correlation_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
    user: dict = Depends(get_current_user),
):
    return await query_events(
        user["id"],
        event_types=[t.strip() for t in event_types.split(",") if t.strip()] if event_types else None,
        severities=[s.strip() for s in severities.split(",") if s.strip()] if severities else None,
        q=q,
        from_ts=from_ts,
        to_ts=to_ts,
        correlation_id=correlation_id,
        limit=limit,
        cursor=cursor,
    )


@router.get("/export")
async def audit_export(
    event_types: str | None = None,
    severities: str | None = None,
    q: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    correlation_id: str | None = None,
    user: dict = Depends(get_current_user),
):
    csv_text = await export_events_csv(
        user["id"],
        event_types=[t.strip() for t in event_types.split(",") if t.strip()] if event_types else None,
        severities=[s.strip() for s in severities.split(",") if s.strip()] if severities else None,
        q=q,
        from_ts=from_ts,
        to_ts=to_ts,
        correlation_id=correlation_id,
    )
    from datetime import date

    fname = f"algoforge-audit-{date.today().isoformat()}.csv"
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )
