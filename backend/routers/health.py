"""Health/root endpoints."""
from fastapi import APIRouter

from db import now_iso

router = APIRouter(tags=["health"])


@router.get("/")
async def root():
    return {"service": "algoforge", "status": "ok"}


@router.get("/health")
async def health():
    return {"status": "ok", "ts": now_iso()}
