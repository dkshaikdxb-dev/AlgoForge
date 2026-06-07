"""Dashboard summary endpoint."""
import logging

from fastapi import APIRouter, Depends

from auth import get_current_user
from brokers import decrypt_credentials
from brokers.base import BrokerError
from brokers.registry import make_client
from db import get_db
from services.paper_trading import compute_positions

logger = logging.getLogger("algoforge.dashboard")
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


async def _live_positions_summary(user_id: str) -> dict:
    """Merge net qty / P&L across every connected live broker. Best-effort —
    a broker error never fails the dashboard, it just shows zero for that broker."""
    db = get_db()
    conns = await db.broker_connections.find(
        {"user_id": user_id, "status": "live"}
    ).to_list(20)
    positions: list[dict] = []
    total_pnl = 0.0
    exposure = 0.0
    for conn in conns:
        broker_name = conn["broker"]
        try:
            creds = decrypt_credentials(conn["credentials_enc"])
            adapter = make_client(broker_name, creds, user_id=user_id)
            rows = await adapter.get_positions()
        except BrokerError as e:
            logger.info("live positions skipped for %s: %s", broker_name, e)
            continue
        except Exception as e:
            logger.warning("live positions error for %s: %s", broker_name, e)
            continue
        for p in rows:
            total_pnl += p.pnl or 0
            exposure += abs((p.last_price or 0) * (p.qty or 0))
            positions.append({
                "broker": broker_name,
                "symbol": p.symbol,
                "qty": p.qty,
                "avg_price": p.avg_price,
                "last_price": p.last_price,
                "pnl": p.pnl,
                "product": p.product,
            })
    return {
        "positions": positions,
        "total_pnl": round(total_pnl, 2),
        "exposure": round(exposure, 2),
        "broker_count": len(conns),
    }


@router.get("/summary")
async def dashboard_summary(user: dict = Depends(get_current_user)):
    db = get_db()
    strats = await db.strategies.count_documents({"user_id": user["id"]})
    backtests = await db.backtests.count_documents({"user_id": user["id"]})
    paper_count = await db.paper_positions.count_documents({"user_id": user["id"]})
    risk = await db.risk_limits.find_one({"user_id": user["id"]}) or {}
    risk.pop("_id", None)
    paper = await compute_positions(user)
    live = await _live_positions_summary(user["id"])
    return {
        "strategies": strats,
        "backtests": backtests,
        # Paper-only legacy fields (kept for backward compat).
        "open_positions": paper_count,
        "total_pnl": paper["total_pnl"],
        "exposure": paper["exposure"],
        # New per-mode breakdown.
        "paper": {
            "open_positions": paper_count,
            "total_pnl": paper["total_pnl"],
            "exposure": paper["exposure"],
        },
        "live": live,
        "combined": {
            "total_pnl": round(paper["total_pnl"] + live["total_pnl"], 2),
            "exposure": round(paper["exposure"] + live["exposure"], 2),
            "open_positions": paper_count + len(live["positions"]),
        },
        "kill_switch": risk.get("kill_switch", False),
        "risk_limits": risk,
    }
