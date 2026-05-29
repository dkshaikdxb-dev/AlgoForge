"""Dashboard summary endpoint."""
from fastapi import APIRouter, Depends

from auth import get_current_user
from db import get_db
from services.paper_trading import compute_positions

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
async def dashboard_summary(user: dict = Depends(get_current_user)):
    db = get_db()
    strats = await db.strategies.count_documents({"user_id": user["id"]})
    backtests = await db.backtests.count_documents({"user_id": user["id"]})
    positions = await db.paper_positions.count_documents({"user_id": user["id"]})
    risk = await db.risk_limits.find_one({"user_id": user["id"]}) or {}
    risk.pop("_id", None)
    pos_resp = await compute_positions(user)
    return {
        "strategies": strats,
        "backtests": backtests,
        "open_positions": positions,
        "total_pnl": pos_resp["total_pnl"],
        "exposure": pos_resp["exposure"],
        "kill_switch": risk.get("kill_switch", False),
        "risk_limits": risk,
    }
