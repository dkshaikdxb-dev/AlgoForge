"""Risk: AI risk review + risk limits / kill switch."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ai_service import analyse_strategy_risk
from auth import get_current_user
from db import get_db, now_iso
from services.audit import AuditEventType, AuditSeverity, record_event

router = APIRouter(prefix="/risk", tags=["risk"])


class RiskAnalyseRequest(BaseModel):
    dsl: dict
    backtest: dict | None = None


class RiskLimitsRequest(BaseModel):
    max_drawdown_pct: float = Field(ge=0, le=100)
    daily_loss_cap: float = Field(ge=0)
    position_limit: int = Field(ge=0)
    kill_switch: bool


@router.post("/analyse")
async def risk_analyse(req: RiskAnalyseRequest, user: dict = Depends(get_current_user)):
    return await analyse_strategy_risk(req.dsl, req.backtest)


@router.get("/limits")
async def get_risk_limits(user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await db.risk_limits.find_one({"user_id": user["id"]})
    if not doc:
        doc = {
            "user_id": user["id"],
            "max_drawdown_pct": 15.0,
            "daily_loss_cap": 25000.0,
            "position_limit": 5,
            "kill_switch": False,
        }
        await db.risk_limits.insert_one({**doc, "updated_at": now_iso()})
    doc.pop("_id", None)
    return doc


@router.put("/limits")
async def update_risk_limits(req: RiskLimitsRequest, user: dict = Depends(get_current_user)):
    db = get_db()
    prev = await db.risk_limits.find_one({"user_id": user["id"]}) or {}
    await db.risk_limits.update_one(
        {"user_id": user["id"]},
        {"$set": {**req.model_dump(), "updated_at": now_iso()}},
        upsert=True,
    )
    if prev.get("kill_switch") != req.kill_switch:
        await record_event(
            user["id"], AuditEventType.KILL_SWITCH,
            severity=AuditSeverity.HIGH,
            actor="user",
            summary=f"Kill switch {'ARMED' if req.kill_switch else 'RELEASED'}",
            payload={"from": prev.get("kill_switch"), "to": req.kill_switch},
        )
    diffs = {k: (prev.get(k), getattr(req, k)) for k in ("max_drawdown_pct", "daily_loss_cap", "position_limit")
             if prev.get(k) != getattr(req, k)}
    if diffs:
        await record_event(
            user["id"], AuditEventType.RISK_POLICY_CHANGE,
            severity=AuditSeverity.WARN, actor="user",
            summary=f"Risk policy updated: {', '.join(diffs)}",
            payload={"diffs": {k: {"from": a, "to": b} for k, (a, b) in diffs.items()}},
        )
    return {"ok": True, **req.model_dump()}
