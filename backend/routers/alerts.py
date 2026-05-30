"""User-facing alert preferences + test endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from db import get_db
from services.alerts import (
    DEFAULT_HIGH_EVENT_TYPES,
    get_prefs,
    save_prefs,
    send_test,
    transport_status,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertPrefs(BaseModel):
    telegram_enabled: bool = False
    telegram_chat_id: str = ""
    email_enabled: bool = False
    email_address: str = ""
    event_types: list[str] | None = None
    min_severity: str = "HIGH"


@router.get("/prefs")
async def get_alert_prefs(user: dict = Depends(get_current_user)):
    prefs = await get_prefs(user["id"])
    return {
        "prefs": prefs,
        "transports": transport_status(),
        "available_event_types": DEFAULT_HIGH_EVENT_TYPES,
    }


@router.put("/prefs")
async def update_alert_prefs(body: AlertPrefs, user: dict = Depends(get_current_user)):
    saved = await save_prefs(user["id"], body.model_dump())
    return {"ok": True, "prefs": saved}


class TestAlertReq(BaseModel):
    channel: str  # 'telegram' | 'email'


@router.post("/test")
async def test_alert(req: TestAlertReq, user: dict = Depends(get_current_user)):
    if req.channel not in ("telegram", "email"):
        raise HTTPException(400, "channel must be 'telegram' or 'email'")
    res = await send_test(user["id"], req.channel)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error") or "test failed")
    return res


@router.get("/log")
async def alert_log(limit: int = 50, user: dict = Depends(get_current_user)):
    db = get_db()
    docs = await db.alert_log.find({"user_id": user["id"]}).sort("ts", -1).limit(limit).to_list(limit)
    for d in docs:
        d.pop("_id", None)
    return {"items": docs}
