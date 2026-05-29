"""Broker connections: encrypted vault, connect/test/disconnect."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from brokers import BrokerUnavailable, decrypt_credentials, encrypt_credentials
from brokers.registry import list_brokers, make_client
from db import get_db, now_iso
from services.audit import AuditEventType, AuditSeverity, record_event

router = APIRouter(prefix="/brokers", tags=["brokers"])


class BrokerConnectRequest(BaseModel):
    credentials: dict


@router.get("")
async def brokers_list(user: dict = Depends(get_current_user)):
    db = get_db()
    connected = await db.broker_connections.find(
        {"user_id": user["id"]},
        {"_id": 0, "credentials_enc": 0},
    ).to_list(20)
    by_name = {c["broker"]: c for c in connected}
    items = []
    for b in list_brokers():
        c = by_name.get(b["name"])
        items.append({
            **b,
            "connected": bool(c),
            "last_test": c.get("last_test") if c else None,
            "status": c.get("status") if c else "disconnected",
        })
    return {"items": items}


@router.post("/{name}/connect")
async def broker_connect(name: str, req: BrokerConnectRequest, user: dict = Depends(get_current_user)):
    if name not in {b["name"] for b in list_brokers()}:
        raise HTTPException(404, f"Unknown broker {name}")
    db = get_db()
    enc = encrypt_credentials(req.credentials)
    doc = {
        "user_id": user["id"],
        "broker": name,
        "credentials_enc": enc,
        "status": "saved",
        "updated_at": now_iso(),
    }
    await db.broker_connections.update_one(
        {"user_id": user["id"], "broker": name},
        {"$set": doc, "$setOnInsert": {"created_at": now_iso()}},
        upsert=True,
    )
    await record_event(user["id"], AuditEventType.BROKER_CONNECT, severity=AuditSeverity.WARN,
                       actor="user", summary=f"Saved credentials for {name}",
                       payload={"broker": name, "fields": list(req.credentials.keys())})
    return {"ok": True, "broker": name, "status": "saved"}


@router.post("/{name}/test")
async def broker_test(name: str, user: dict = Depends(get_current_user)):
    db = get_db()
    rec = await db.broker_connections.find_one({"user_id": user["id"], "broker": name})
    if not rec:
        raise HTTPException(404, "Broker not connected")
    creds = decrypt_credentials(rec["credentials_enc"])
    try:
        client = make_client(name, creds)
        info = client.test_connection()
        status = "live"
        message = info.get("name") or info.get("user_id") or "OK"
    except BrokerUnavailable as e:
        status = "error"
        message = str(e)
        info = {"ok": False, "error": message}
    await db.broker_connections.update_one(
        {"user_id": user["id"], "broker": name},
        {"$set": {"status": status, "last_test": now_iso(), "last_message": message}},
    )
    await record_event(user["id"], AuditEventType.BROKER_TEST,
                       severity=AuditSeverity.INFO if status == "live" else AuditSeverity.WARN,
                       actor="user", summary=f"Broker test {name}: {status} — {message}",
                       payload={"broker": name, "status": status})
    return {"broker": name, "status": status, "message": message, "info": info}


@router.delete("/{name}")
async def broker_disconnect(name: str, user: dict = Depends(get_current_user)):
    db = get_db()
    res = await db.broker_connections.delete_one({"user_id": user["id"], "broker": name})
    if res.deleted_count:
        await record_event(user["id"], AuditEventType.BROKER_DISCONNECT,
                           severity=AuditSeverity.WARN, actor="user",
                           summary=f"Disconnected {name}", payload={"broker": name})
    return {"deleted": res.deleted_count}
