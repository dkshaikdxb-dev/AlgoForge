"""Option Writers' Trap Detection endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ai_service import explain_trap
from auth import get_current_user
from trap_detection import scan_traps

router = APIRouter(prefix="/trap", tags=["trap"])


class TrapExplainRequest(BaseModel):
    scan: dict


@router.get("/scan")
async def trap_scan(symbol: str, expiry_days: int = 7, user: dict = Depends(get_current_user)):
    scan = scan_traps(symbol, expiry_days=expiry_days)
    if scan.get("error"):
        raise HTTPException(404, scan["error"])
    return scan


@router.post("/explain")
async def trap_explain(req: TrapExplainRequest, user: dict = Depends(get_current_user)):
    return await explain_trap(req.scan)
