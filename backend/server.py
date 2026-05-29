"""Main FastAPI app — thin composition layer.

All domain logic lives in routers/*. This file only wires routers, middleware
and lifecycle hooks. Keep it boring.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from auth import router as auth_router
from db import close_db, get_db
from routers import (
    audit as audit_router,
    backtest as backtest_router,
    brokers as brokers_router,
    dashboard as dashboard_router,
    health as health_router,
    journal as journal_router,
    market as market_router,
    paper as paper_router,
    reconciliation as reconciliation_router,
    risk as risk_router,
    strategies as strategies_router,
    stress as stress_router,
    trap as trap_router,
)
from services.audit import _ensure_indexes as _audit_ensure_indexes
from ws_feed import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("algoforge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_db()
    await paper_router._ensure_idempotency_ttl()
    await _audit_ensure_indexes()
    logger.info("AlgoForge backend started (modular routers, idempotency TTL ready, audit indexed)")
    yield
    close_db()


app = FastAPI(title="AlgoForge — AI Trading Platform", lifespan=lifespan)

# All HTTP REST routes mounted under /api
api = APIRouter(prefix="/api")
api.include_router(health_router.router)
api.include_router(auth_router)
api.include_router(market_router.router)
api.include_router(strategies_router.router)
api.include_router(backtest_router.router)
api.include_router(stress_router.router)
api.include_router(risk_router.router)
api.include_router(trap_router.router)
api.include_router(paper_router.router)
api.include_router(journal_router.router)
api.include_router(brokers_router.router)
api.include_router(reconciliation_router.router)
api.include_router(audit_router.router)
api.include_router(dashboard_router.router)
app.include_router(api)

# WebSocket router mounted under /api (ingress routes /api/* to backend)
api_ws = APIRouter(prefix="/api")
api_ws.include_router(ws_router)
app.include_router(api_ws)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
