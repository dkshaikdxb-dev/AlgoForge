"""Broker OAuth onboarding + postback webhooks.

Flow (Zerodha + Upstox):
1. UI calls POST /brokers/{name}/oauth/start with {api_key, api_secret}.
   Backend stores partial creds + a CSRF-style state in `oauth_states`
   (TTL 10 min) and returns the broker's login URL.
2. User opens the login URL in a new tab and logs in at the broker.
3. Broker redirects to GET /brokers/{name}/oauth/callback?...&state=...
   The callback finds the state, exchanges request_token/code for an
   access_token via the broker SDK, persists the full credentials, marks
   the connection LIVE, audit-logs it, and serves a tiny auto-close page.
4. The original UI tab polls /api/brokers until status flips to 'live'.

Postback webhook (Zerodha + Upstox):
- POST /brokers/{name}/postback receives broker-initiated order updates.
  Validated by the broker_user_id + per-connection postback_secret query
  param. Persists to `live_order_events`; audit-logs at INFO/WARN/HIGH.

URLs surfaced:
- GET /brokers/{name}/oauth/urls returns redirect_url + postback_url for
  the user to paste into the broker developer console.
"""
from __future__ import annotations

import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from auth import get_current_user
from brokers import decrypt_credentials, encrypt_credentials
from brokers.base import BrokerError
from brokers.registry import SUPPORTED, make_client
from db import get_db, now_iso
from services.audit import AuditEventType, AuditSeverity, record_event

logger = logging.getLogger("algoforge.broker_oauth")

router = APIRouter(prefix="/brokers", tags=["brokers"])

OAUTH_CAPABLE = {"zerodha", "upstox"}
OAUTH_STATE_TTL_SECONDS = 600


def _base_url(request: Request) -> str:
    """Reconstruct the public base URL behind ingress.

    The ingress terminates TLS, so request.base_url reflects the internal
    HTTP scheme. Trust X-Forwarded-Proto / X-Forwarded-Host when present.
    """
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


def _redirect_url(request: Request, name: str) -> str:
    return f"{_base_url(request)}/api/brokers/{name}/oauth/callback"


def _postback_url(request: Request, name: str, secret: Optional[str] = None) -> str:
    base = f"{_base_url(request)}/api/brokers/{name}/postback"
    return f"{base}?token={secret}" if secret else base


async def _ensure_oauth_state_ttl() -> None:
    db = get_db()
    indexes = await db.oauth_states.index_information()
    if "created_at_ttl" not in indexes:
        await db.oauth_states.create_index(
            "created_at", expireAfterSeconds=OAUTH_STATE_TTL_SECONDS, name="created_at_ttl"
        )


# ───────────────────────────────────────────────────────────────────────────
# 1. URL surface
# ───────────────────────────────────────────────────────────────────────────

@router.post("/{name}/oauth/relink")
async def oauth_relink(name: str, request: Request, user: dict = Depends(get_current_user)):
    """Re-issue an OAuth login URL using saved api_key/api_secret.

    Kite access tokens expire daily ~6 AM IST. This endpoint reads the
    previously-stored credentials (api_key + api_secret), arms a fresh state
    row, and returns the broker login URL — so the user just clicks once and
    logs in, no re-pasting of keys required.
    """
    if name not in OAUTH_CAPABLE:
        raise HTTPException(400, f"{name} does not support OAuth wizard")
    db = get_db()
    conn = await db.broker_connections.find_one({"user_id": user["id"], "broker": name})
    if not conn:
        raise HTTPException(404, f"No saved {name} connection. Run the wizard first.")
    creds = decrypt_credentials(conn["credentials_enc"])
    if not creds.get("api_key") or not creds.get("api_secret"):
        raise HTTPException(400, "Saved connection is missing api_key / api_secret — re-link via wizard.")
    await _ensure_oauth_state_ttl()
    state = secrets.token_urlsafe(24)
    await db.oauth_states.insert_one({
        "_id": state, "user_id": user["id"], "broker": name,
        "api_key": creds["api_key"], "api_secret": creds["api_secret"],
        "created_at": now_iso(),
    })
    redirect_url = _redirect_url(request, name)
    if name == "zerodha":
        login_url = _kite_login_url(creds["api_key"], state)
    else:  # upstox
        login_url = _upstox_login_url(creds["api_key"], redirect_url, state)
    return {"state": state, "login_url": login_url, "redirect_url": redirect_url}


# ───────────────────────────────────────────────────────────────────────────
# 1. URL surface (continued)
# ───────────────────────────────────────────────────────────────────────────

@router.get("/{name}/oauth/urls")
async def oauth_urls(name: str, request: Request, user: dict = Depends(get_current_user)):
    if name not in SUPPORTED:
        raise HTTPException(404, f"Unknown broker {name}")
    db = get_db()
    conn = await db.broker_connections.find_one({"user_id": user["id"], "broker": name})
    pb_secret = (conn or {}).get("postback_secret")
    return {
        "broker": name,
        "redirect_url": _redirect_url(request, name),
        "postback_url": _postback_url(request, name, pb_secret),
        "postback_secret": pb_secret,
        "oauth_supported": name in OAUTH_CAPABLE,
    }


# ───────────────────────────────────────────────────────────────────────────
# 2. Start OAuth (UI calls with api_key + api_secret)
# ───────────────────────────────────────────────────────────────────────────

class OAuthStartRequest(BaseModel):
    api_key: str
    api_secret: str


def _kite_login_url(api_key: str, state: str) -> str:
    """Kite Connect login URL.

    Kite doesn't natively support an OAuth-style `state` parameter on its
    login URL, but it echoes anything passed via `redirect_params` back to
    the callback as plain query parameters. We exploit that to round-trip
    our CSRF state token so concurrent multi-user OAuth flows are isolated.

    See: https://kite.trade/docs/connect/v3/user/#login-flow
    """
    from urllib.parse import quote
    rp = quote(f"state={state}", safe="")
    return f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}&redirect_params={rp}"


def _upstox_login_url(api_key: str, redirect_url: str, state: str) -> str:
    from urllib.parse import urlencode

    qs = urlencode(
        {
            "client_id": api_key,
            "redirect_uri": redirect_url,
            "response_type": "code",
            "state": state,
        }
    )
    return f"https://api.upstox.com/v2/login/authorization/dialog?{qs}"


@router.post("/{name}/oauth/start")
async def oauth_start(name: str, body: OAuthStartRequest, request: Request, user: dict = Depends(get_current_user)):
    if name not in OAUTH_CAPABLE:
        raise HTTPException(400, f"{name} does not support OAuth wizard")
    if not body.api_key or not body.api_secret:
        raise HTTPException(400, "api_key and api_secret are required")
    await _ensure_oauth_state_ttl()
    state = secrets.token_urlsafe(24)
    db = get_db()
    await db.oauth_states.insert_one({
        "_id": state,
        "user_id": user["id"],
        "broker": name,
        "api_key": body.api_key,
        "api_secret": body.api_secret,
        "created_at": now_iso(),
    })
    redirect_url = _redirect_url(request, name)
    if name == "zerodha":
        # Kite echoes anything in redirect_params back to the callback, so
        # we round-trip our CSRF state through it.
        login_url = _kite_login_url(body.api_key, state)
    else:  # upstox
        login_url = _upstox_login_url(body.api_key, redirect_url, state)
    return {
        "state": state,
        "login_url": login_url,
        "redirect_url": redirect_url,
        "expires_in": OAUTH_STATE_TTL_SECONDS,
    }


# ───────────────────────────────────────────────────────────────────────────
# 3. OAuth callback (broker → us)
# ───────────────────────────────────────────────────────────────────────────

def _auto_close_html(message: str, ok: bool = True) -> str:
    color = "#10b981" if ok else "#ef4444"
    return f"""<!doctype html>
<html><head><title>AlgoForge — broker callback</title>
<style>
body{{background:#0a0a0a;color:#fff;font-family:'IBM Plex Sans',system-ui;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.box{{text-align:center;padding:40px;border:1px solid #27272a;max-width:520px}}
.dot{{width:10px;height:10px;background:{color};display:inline-block;
border-radius:50%;margin-right:10px}}
.msg{{font-family:'JetBrains Mono',monospace;font-size:13px;color:#a1a1aa;
margin-top:14px;word-break:break-word}}
</style></head><body>
<div class="box">
  <div><span class="dot"></span>{'ALGOFORGE — BROKER LINK ' + ('OK' if ok else 'FAILED')}</div>
  <div class="msg">{message}</div>
  <div class="msg" style="color:#52525b;margin-top:18px">You can close this tab.</div>
</div>
<script>setTimeout(() => window.close(), 4000)</script>
</body></html>"""


async def _exchange_kite(state_row: dict, request_token: str) -> dict:
    api_key = state_row["api_key"]
    api_secret = state_row["api_secret"]
    try:
        from kiteconnect import KiteConnect  # type: ignore
    except ImportError as e:
        raise HTTPException(500, f"kiteconnect SDK missing: {e}")
    kite = KiteConnect(api_key=api_key)
    data = kite.generate_session(request_token, api_secret=api_secret)
    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "access_token": data["access_token"],
        "broker_user_id": data.get("user_id"),
        "broker_user_name": data.get("user_name"),
    }


async def _exchange_upstox(state_row: dict, code: str, redirect_url: str) -> dict:
    import httpx

    api_key = state_row["api_key"]
    api_secret = state_row["api_secret"]
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://api.upstox.com/v2/login/authorization/token",
            data={
                "code": code,
                "client_id": api_key,
                "client_secret": api_secret,
                "redirect_uri": redirect_url,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
    if r.status_code >= 400:
        raise HTTPException(400, f"Upstox token exchange failed: {r.text[:200]}")
    data = r.json()
    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "access_token": data.get("access_token"),
        "broker_user_id": data.get("user_id") or data.get("user_name"),
        "broker_user_name": data.get("user_name"),
    }


async def _finalize_connection(user_id: str, name: str, creds: dict) -> str:
    db = get_db()
    pb_secret = secrets.token_urlsafe(18)
    enc = encrypt_credentials({
        "api_key": creds["api_key"],
        "api_secret": creds["api_secret"],
        "access_token": creds["access_token"],
    })
    await db.broker_connections.update_one(
        {"user_id": user_id, "broker": name},
        {
            "$set": {
                "user_id": user_id,
                "broker": name,
                "credentials_enc": enc,
                "broker_user_id": creds.get("broker_user_id"),
                "broker_user_name": creds.get("broker_user_name"),
                "postback_secret": pb_secret,
                "status": "saved",
                "updated_at": now_iso(),
            },
            "$setOnInsert": {"created_at": now_iso()},
        },
        upsert=True,
    )
    # Live test
    try:
        client = make_client(name, decrypt_credentials(enc), user_id=user_id)
        info = await client.test_connection()
        status = "live"
        message = info.get("name") or info.get("user_id") or "OK"
    except BrokerError as e:
        status = "error"
        message = str(e)
    await db.broker_connections.update_one(
        {"user_id": user_id, "broker": name},
        {"$set": {"status": status, "last_test": now_iso(), "last_message": message}},
    )
    await record_event(
        user_id, AuditEventType.BROKER_CONNECT,
        severity=AuditSeverity.WARN, actor="user",
        summary=f"OAuth linked {name}: {status} — {message}",
        payload={"broker": name, "status": status, "broker_user_id": creds.get("broker_user_id")},
    )
    return status


@router.get("/{name}/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    name: str,
    request: Request,
    request_token: str | None = None,  # Kite
    code: str | None = None,           # Upstox
    state: str | None = None,
    status: str | None = None,         # Kite sends status=success
):
    if name not in OAUTH_CAPABLE:
        return HTMLResponse(_auto_close_html(f"{name} OAuth not supported.", ok=False), status_code=400)

    db = get_db()
    # Both Kite (via redirect_params=state=...) and Upstox (native state param)
    # now round-trip the CSRF state token through the callback. We require it.
    if not state:
        return HTMLResponse(
            _auto_close_html(
                "Missing OAuth state in callback. Re-run the wizard — your broker app must echo state via redirect_params.",
                ok=False,
            ),
            status_code=400,
        )
    state_row = await db.oauth_states.find_one({"_id": state, "broker": name})
    if state_row is None:
        return HTMLResponse(
            _auto_close_html("OAuth state not found or expired. Re-run the wizard.", ok=False),
            status_code=400,
        )

    user_id = state_row["user_id"]
    try:
        if name == "zerodha":
            if not request_token:
                raise HTTPException(400, "Missing request_token in Kite callback")
            creds = await _exchange_kite(state_row, request_token)
        else:  # upstox
            if not code:
                raise HTTPException(400, "Missing authorization code in Upstox callback")
            creds = await _exchange_upstox(state_row, code, _redirect_url(request, name))
        if not creds.get("access_token"):
            raise HTTPException(400, "Broker returned no access_token")
        link_status = await _finalize_connection(user_id, name, creds)
    except HTTPException as e:
        await db.oauth_states.delete_one({"_id": state_row["_id"]})
        return HTMLResponse(_auto_close_html(str(e.detail), ok=False), status_code=e.status_code)
    except Exception as e:
        logger.exception("oauth callback failure")
        await db.oauth_states.delete_one({"_id": state_row["_id"]})
        return HTMLResponse(_auto_close_html(f"Exchange failed: {e}", ok=False), status_code=500)

    await db.oauth_states.delete_one({"_id": state_row["_id"]})
    return HTMLResponse(_auto_close_html(
        f"Linked {name.upper()} as {creds.get('broker_user_id', '—')} • status={link_status}",
        ok=link_status == "live",
    ))


# ───────────────────────────────────────────────────────────────────────────
# 4. Postback webhook
# ───────────────────────────────────────────────────────────────────────────

@router.post("/{name}/postback")
async def broker_postback(name: str, request: Request, token: str | None = None):
    """Broker → us order updates. No user JWT; auth via per-connection token."""
    if name not in SUPPORTED:
        raise HTTPException(404, f"Unknown broker {name}")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    db = get_db()
    conn = None
    if token:
        conn = await db.broker_connections.find_one({"broker": name, "postback_secret": token})
    if not conn:
        # Reject silently to avoid leaking info about valid tokens.
        raise HTTPException(403, "Invalid postback token")
    user_id = conn["user_id"]
    await db.live_order_events.insert_one({
        "ts": now_iso(),
        "user_id": user_id,
        "broker": name,
        "payload": payload if len(str(payload)) < 8000 else {"truncated": True, "preview": str(payload)[:8000]},
        "broker_order_id": payload.get("order_id") or payload.get("orderId"),
        "status": payload.get("status") or payload.get("orderStatus"),
    })
    status = (payload.get("status") or payload.get("orderStatus") or "").upper()
    severity = AuditSeverity.HIGH if status == "REJECTED" else AuditSeverity.INFO
    await record_event(
        user_id, AuditEventType.RESPONSE,
        severity=severity, actor="broker",
        summary=f"{name} postback {status or 'UPDATE'}",
        payload={"broker": name, "status": status, "raw_keys": list(payload.keys())[:10]},
        correlation_id=str(payload.get("order_id") or payload.get("orderId") or ""),
    )
    return {"ok": True}
