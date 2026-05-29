"""Trade journal with AI commentary."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ai_service import journal_commentary
from auth import get_current_user
from db import get_db, now_iso

router = APIRouter(prefix="/journal", tags=["journal"])


class JournalEntryRequest(BaseModel):
    symbol: str
    side: str
    qty: int
    entry_price: float
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    rationale: str = ""
    request_ai: bool = True


@router.post("")
async def journal_create(req: JournalEntryRequest, user: dict = Depends(get_current_user)):
    db = get_db()
    ai = {"tags": [], "commentary": ""}
    if req.request_ai:
        ai = await journal_commentary(req.model_dump())
    entry = {
        "_id": str(uuid.uuid4()),
        "user_id": user["id"],
        **req.model_dump(),
        "ai_tags": ai.get("tags", []),
        "ai_commentary": ai.get("commentary", ""),
        "created_at": now_iso(),
    }
    await db.journal_entries.insert_one(entry)
    entry["id"] = str(entry.pop("_id"))
    return entry


@router.get("")
async def journal_list(user: dict = Depends(get_current_user)):
    db = get_db()
    docs = await db.journal_entries.find({"user_id": user["id"]}).sort("created_at", -1).to_list(200)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {"items": docs}
