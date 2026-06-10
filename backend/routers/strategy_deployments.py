import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from db import get_db, now_iso

router = APIRouter(
    prefix="/strategy-deployments",
    tags=["strategy-deployments"]
)


class DeployRequest(BaseModel):
    strategy_id: str
    mode: str = "paper"


@router.get("")
async def list_deployments(user: dict = Depends(get_current_user)):
    db = get_db()

    rows = await db.strategy_deployments.find(
        {"user_id": user["id"]}
    ).to_list(500)

    for r in rows:
        r["id"] = str(r.pop("_id"))

    return {"items": rows}


@router.post("/deploy")
async def deploy_strategy(
    req: DeployRequest,
    user: dict = Depends(get_current_user)
):
    db = get_db()

    strategy = await db.strategies.find_one({
        "_id": req.strategy_id,
        "user_id": user["id"]
    })

    if not strategy:
        raise HTTPException(404, "Strategy not found")

    deployment_id = str(uuid.uuid4())

    doc = {
        "_id": deployment_id,
        "user_id": user["id"],

        "strategy_id": req.strategy_id,
        "name": strategy["name"],

        "mode": req.mode,
        "status": "STOPPED",

        "symbol": strategy["dsl"].get("symbol"),
        "timeframe": strategy["dsl"].get("timeframe"),

        "last_signal": None,
        "last_execution": None,

        "created_at": now_iso(),
        "updated_at": now_iso(),
    }

    await db.strategy_deployments.insert_one(doc)

    return {
        "id": deployment_id,
        "status": "STOPPED"
    }


@router.post("/start/{deployment_id}")
async def start_deployment(
    deployment_id: str,
    user: dict = Depends(get_current_user)
):
    db = get_db()

    await db.strategy_deployments.update_one(
        {
            "_id": deployment_id,
            "user_id": user["id"]
        },
        {
            "$set": {
                "status": "RUNNING",
                "updated_at": now_iso()
            }
        }
    )

    return {"status": "RUNNING"}


@router.post("/stop/{deployment_id}")
async def stop_deployment(
    deployment_id: str,
    user: dict = Depends(get_current_user)
):
    db = get_db()

    await db.strategy_deployments.update_one(
        {
            "_id": deployment_id,
            "user_id": user["id"]
        },
        {
            "$set": {
                "status": "STOPPED",
                "updated_at": now_iso()
            }
        }
    )

    return {"status": "STOPPED"}


@router.delete("/{deployment_id}")
async def delete_deployment(
    deployment_id: str,
    user: dict = Depends(get_current_user)
):
    db = get_db()

    await db.strategy_deployments.delete_one(
        {
            "_id": deployment_id,
            "user_id": user["id"]
        }
    )

    return {"deleted": deployment_id}
