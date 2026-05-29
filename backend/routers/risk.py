"""Risk: AI risk review + risk limits / kill switch."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ai_service import analyse_strategy_risk
from auth import get_current_user
from db import get_db, now_iso

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
    await db.risk_limits.update_one(
        {"user_id": user["id"]},
        {"$set": {**req.model_dump(), "updated_at": now_iso()}},
        upsert=True,
    )
    return {"ok": True, **req.model_dump()}
