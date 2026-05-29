"""Background reconciler — polls live brokers periodically.

Starts on FastAPI lifespan; runs forever; sleeps ~30s between rounds. For each
user × connected-and-live broker pair, calls `reconcile_orders`. Logs
exceptions but never crashes the loop.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from brokers import decrypt_credentials
from brokers.paper_adapter import PaperAdapter
from brokers.registry import make_client
from db import get_db
from services.reconciliation import reconcile_orders

logger = logging.getLogger("algoforge.reconciler_loop")

POLL_INTERVAL_SECONDS = 30.0


async def _reconcile_one(user_id: str, broker: str, creds_enc: str | None) -> None:
    try:
        if broker == "paper":
            adapter: Any = PaperAdapter({}, user_id=user_id)
        else:
            creds = decrypt_credentials(creds_enc) if creds_enc else {}
            adapter = make_client(broker, creds)
            adapter.user_id = user_id
        await reconcile_orders(adapter, user_id)
    except Exception as e:
        logger.warning("reconciler: %s/%s failed: %s", user_id, broker, e)


async def reconciler_tick() -> int:
    db = get_db()
    cursor = db.broker_connections.find(
        {"status": "live"}, {"user_id": 1, "broker": 1, "credentials_enc": 1},
    )
    count = 0
    async for rec in cursor:
        await _reconcile_one(rec["user_id"], rec["broker"], rec.get("credentials_enc"))
        count += 1
    return count


async def reconciler_loop() -> None:
    logger.info("reconciler loop started (interval=%.0fs)", POLL_INTERVAL_SECONDS)
    while True:
        try:
            checked = await reconciler_tick()
            if checked:
                logger.info("reconciler tick: %d brokers", checked)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("reconciler tick failed: %s", e)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
