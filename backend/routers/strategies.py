"""Strategy CRUD + NL→DSL generation."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ai_service import generate_strategy_from_nl
from auth import get_current_user
from db import get_db, now_iso

router = APIRouter(prefix="/strategies", tags=["strategies"])


class StrategyGenRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)


class StrategySaveRequest(BaseModel):
    name: str
    description: str | None = None
    dsl: dict


@router.post("/generate")
async def strategies_generate(req: StrategyGenRequest, user: dict = Depends(get_current_user)):
    dsl = await generate_strategy_from_nl(req.prompt)
    return {"dsl": dsl}


@router.get("")
async def list_strategies(user: dict = Depends(get_current_user)):
    db = get_db()
    docs = await db.strategies.find(
        {"user_id": user["id"]},
        {"_id": 1, "name": 1, "description": 1, "dsl": 1, "created_at": 1, "updated_at": 1},
    ).to_list(500)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {"items": docs}


@router.post("")
async def save_strategy(req: StrategySaveRequest, user: dict = Depends(get_current_user)):
    db = get_db()
    sid = str(uuid.uuid4())
    doc = {
        "_id": sid,
        "user_id": user["id"],
        "name": req.name,
        "description": req.description or req.dsl.get("description", ""),
        "dsl": req.dsl,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.strategies.insert_one(doc)
    return {"id": sid, "name": req.name, "dsl": req.dsl}


@router.delete("/{sid}")
async def delete_strategy(sid: str, user: dict = Depends(get_current_user)):
    db = get_db()
    res = await db.strategies.delete_one({"_id": sid, "user_id": user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(404, "Strategy not found")
    return {"deleted": sid}
