"""Dashboard summary endpoint."""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from auth import get_current_user
from brokers import decrypt_credentials
from brokers.base import BrokerError
from brokers.registry import make_client
from db import get_db
from services.paper_trading import compute_positions

logger = logging.getLogger("algoforge.dashboard")
router = APIRouter(prefix="/dashboard", tags=["dashboard"])

CACHE_MAX_AGE_SECONDS = 120  # 2× reconciler interval — safe margin


async def _live_positions_summary(user_id: str) -> dict:
    """Prefer the reconciler-populated `live_positions_cache`. Fall back to a
    live broker call only when the cache is missing or stale (>2 min)."""
    db = get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=CACHE_MAX_AGE_SECONDS)
    cached = await db.live_positions_cache.find(
        {"user_id": user_id, "ts": {"$gte": cutoff}}
    ).to_list(20)

    conns = await db.broker_connections.find(
        {"user_id": user_id, "status": "live"},
    ).to_list(20)

    fresh_brokers = {c["broker"] for c in cached}
    stale_brokers = [c for c in conns if c["broker"] not in fresh_brokers]

    positions: list[dict] = []
    total_pnl = 0.0
    exposure = 0.0
    sources: list[dict] = []

    for row in cached:
        positions.extend(row.get("positions", []))
        total_pnl += row.get("total_pnl", 0) or 0
        exposure += row.get("exposure", 0) or 0
        sources.append({"broker": row["broker"], "source": "cache", "ts": row["ts"].isoformat()})

    for conn in stale_brokers:
        broker_name = conn["broker"]
        try:
            creds = decrypt_credentials(conn["credentials_enc"])
            adapter = make_client(broker_name, creds, user_id=user_id)
            rows = await adapter.get_positions()
        except BrokerError as e:
            logger.info("live positions skipped for %s: %s", broker_name, e)
            sources.append({"broker": broker_name, "source": "skipped", "error": str(e)})
            continue
        except Exception as e:
            logger.warning("live positions error for %s: %s", broker_name, e)
            sources.append({"broker": broker_name, "source": "error", "error": str(e)})
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
        sources.append({"broker": broker_name, "source": "fresh"})

    return {
        "positions": positions,
        "total_pnl": round(total_pnl, 2),
        "exposure": round(exposure, 2),
        "broker_count": len(conns),
        "sources": sources,
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
