"""Alert dispatcher for HIGH-severity audit events.

Transports: Telegram Bot API (HTTPS) + SMTP email (aiosmtplib).
- Fire-and-forget: any failure is logged and swallowed; never breaks trading.
- Per-user opt-in via `alert_preferences` Mongo collection.
- Global admin mirror via env (TELEGRAM_GLOBAL_CHAT_ID, SMTP_GLOBAL_RECIPIENT).
- Dedup: identical (user_id, channel, summary) within ALERT_DEDUP_SEC → drop.
- Retry: one retry on 5xx / transport error, then give up.
"""
from __future__ import annotations

import asyncio
import logging
import os
import ssl
from collections import OrderedDict
from email.message import EmailMessage
from typing import Any, Optional

import aiosmtplib
import httpx

from db import get_db, now_iso

logger = logging.getLogger("algoforge.alerts")

ALERT_DEDUP_SEC = 60
_dedup: "OrderedDict[str, float]" = OrderedDict()
_dedup_lock = asyncio.Lock()

DEFAULT_HIGH_EVENT_TYPES = [
    "KILL_SWITCH",
    "BROKER_DISCONNECT",
    "BASKET_ROLLBACK",
    "RISK_POLICY_CHANGE",
    "OVERRIDE",
]


# ─────────────────────────────────────────────────────────────────────────────
# Preferences
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_indexes() -> None:
    db = get_db()
    await db.alert_preferences.create_index("user_id", unique=True)


async def get_prefs(user_id: str) -> dict:
    db = get_db()
    row = await db.alert_preferences.find_one({"user_id": user_id})
    if not row:
        return {
            "user_id": user_id,
            "telegram_enabled": False,
            "telegram_chat_id": "",
            "email_enabled": False,
            "email_address": "",
            "event_types": DEFAULT_HIGH_EVENT_TYPES,
            "min_severity": "HIGH",
        }
    row.pop("_id", None)
    return row


async def save_prefs(user_id: str, prefs: dict) -> dict:
    db = get_db()
    # Use `is None` so user can explicitly opt out of all event types with [].
    event_types = prefs.get("event_types")
    if event_types is None:
        event_types = DEFAULT_HIGH_EVENT_TYPES
    update = {
        "user_id": user_id,
        "telegram_enabled": bool(prefs.get("telegram_enabled")),
        "telegram_chat_id": (prefs.get("telegram_chat_id") or "").strip(),
        "email_enabled": bool(prefs.get("email_enabled")),
        "email_address": (prefs.get("email_address") or "").strip(),
        "event_types": event_types,
        "min_severity": prefs.get("min_severity") or "HIGH",
        "updated_at": now_iso(),
    }
    await db.alert_preferences.update_one({"user_id": user_id}, {"$set": update}, upsert=True)
    return update


# ─────────────────────────────────────────────────────────────────────────────
# Dedup
# ─────────────────────────────────────────────────────────────────────────────

async def _should_send(key: str) -> bool:
    now = asyncio.get_event_loop().time()
    async with _dedup_lock:
        cutoff = now - ALERT_DEDUP_SEC
        # purge stale entries (keep map bounded)
        while _dedup and next(iter(_dedup.values())) < cutoff:
            _dedup.popitem(last=False)
        if key in _dedup:
            return False
        _dedup[key] = now
        if len(_dedup) > 5000:
            _dedup.popitem(last=False)
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Telegram transport
# ─────────────────────────────────────────────────────────────────────────────

def _tg_token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN") or None


async def _telegram_send(chat_id: str, text: str) -> dict:
    token = _tg_token()
    if not token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not configured"}
    if not chat_id:
        return {"ok": False, "error": "chat_id missing"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True}
    last_err = ""
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(url, json=payload)
            if r.status_code == 200:
                return {"ok": True}
            last_err = f"{r.status_code}: {r.text[:200]}"
            # 4xx (bad chat_id / token) — no point retrying
            if 400 <= r.status_code < 500:
                break
        except Exception as e:
            last_err = str(e)
        if attempt == 1:
            await asyncio.sleep(0.6)
    return {"ok": False, "error": last_err}


# ─────────────────────────────────────────────────────────────────────────────
# SMTP transport
# ─────────────────────────────────────────────────────────────────────────────

def _smtp_env() -> dict | None:
    host = os.environ.get("SMTP_HOST")
    port = os.environ.get("SMTP_PORT")
    user = os.environ.get("SMTP_USER")
    pwd = os.environ.get("SMTP_PASSWORD")
    sender = os.environ.get("SMTP_FROM") or user
    if not (host and port and user and pwd and sender):
        return None
    return {"host": host, "port": int(port), "user": user, "password": pwd, "from": sender}


async def _email_send(to_addr: str, subject: str, body: str) -> dict:
    cfg = _smtp_env()
    if not cfg:
        return {"ok": False, "error": "SMTP_* env vars not configured"}
    if not to_addr:
        return {"ok": False, "error": "to_addr missing"}
    msg = EmailMessage()
    msg["From"] = cfg["from"]
    msg["To"] = to_addr
    msg["Subject"] = subject[:200]
    msg.set_content(body)

    last_err = ""
    for attempt in (1, 2):
        try:
            tls_ctx = ssl.create_default_context()
            await aiosmtplib.send(
                msg,
                hostname=cfg["host"],
                port=cfg["port"],
                username=cfg["user"],
                password=cfg["password"],
                start_tls=cfg["port"] in (587, 25),
                use_tls=cfg["port"] == 465,
                tls_context=tls_ctx,
                timeout=15,
            )
            return {"ok": True}
        except Exception as e:
            last_err = str(e)
        if attempt == 1:
            await asyncio.sleep(0.6)
    return {"ok": False, "error": last_err}


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────────────────────────────────────

def _format_message(event: dict[str, Any]) -> tuple[str, str]:
    """Returns (subject, body) for both Telegram and Email."""
    et = event.get("event_type", "EVENT")
    sev = event.get("severity", "INFO")
    actor = event.get("actor", "system")
    summary = event.get("summary", "")
    ts = event.get("ts", now_iso())
    corr = event.get("correlation_id")
    subject = f"[AlgoForge {sev}] {et}"
    body = (
        f"AlgoForge alert\n"
        f"━━━━━━━━━━━━━━\n"
        f"Event:    {et}\n"
        f"Severity: {sev}\n"
        f"Actor:    {actor}\n"
        f"Time:     {ts}\n"
        + (f"Corr:     {corr}\n" if corr else "")
        + f"\n{summary}\n"
    )
    return subject, body


async def dispatch_event(event: dict[str, Any]) -> None:
    """Fire-and-forget. Routes to user + global admin channels."""
    try:
        sev = event.get("severity", "INFO")
        if sev != "HIGH":
            return
        user_id = event.get("user_id")
        et = event.get("event_type", "")
        subject, body = _format_message(event)

        # Per-user channels
        if user_id and user_id != "anonymous":
            prefs = await get_prefs(user_id)
            if et in (prefs.get("event_types") or []):
                if prefs.get("telegram_enabled") and prefs.get("telegram_chat_id"):
                    key = f"u:{user_id}:tg:{et}:{event.get('summary','')[:80]}"
                    if await _should_send(key):
                        res = await _telegram_send(prefs["telegram_chat_id"], body)
                        await _log("telegram", user_id, prefs["telegram_chat_id"], event, res)
                if prefs.get("email_enabled") and prefs.get("email_address"):
                    key = f"u:{user_id}:em:{et}:{event.get('summary','')[:80]}"
                    if await _should_send(key):
                        res = await _email_send(prefs["email_address"], subject, body)
                        await _log("email", user_id, prefs["email_address"], event, res)

        # Global admin mirror
        gtg = os.environ.get("TELEGRAM_GLOBAL_CHAT_ID")
        if gtg:
            key = f"g:tg:{et}:{event.get('summary','')[:80]}"
            if await _should_send(key):
                res = await _telegram_send(gtg, body)
                await _log("telegram", "global", gtg, event, res)
        gem = os.environ.get("SMTP_GLOBAL_RECIPIENT")
        if gem:
            key = f"g:em:{et}:{event.get('summary','')[:80]}"
            if await _should_send(key):
                res = await _email_send(gem, subject, body)
                await _log("email", "global", gem, event, res)
    except Exception as e:
        logger.warning("alert dispatch failed: %s", e)


async def _log(channel: str, user_id: str, dest: str, event: dict, res: dict) -> None:
    try:
        db = get_db()
        await db.alert_log.insert_one({
            "ts": now_iso(),
            "channel": channel,
            "user_id": user_id,
            "destination": dest[:200],
            "event_type": event.get("event_type"),
            "severity": event.get("severity"),
            "summary": (event.get("summary") or "")[:200],
            "ok": bool(res.get("ok")),
            "error": res.get("error"),
        })
    except Exception as e:
        logger.warning("alert log insert failed: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# Test helper (Settings UI button)
# ─────────────────────────────────────────────────────────────────────────────

async def send_test(user_id: str, channel: str) -> dict:
    prefs = await get_prefs(user_id)
    fake_event = {
        "event_type": "ALERT_TEST",
        "severity": "HIGH",
        "actor": "user",
        "summary": "AlgoForge test alert — your alerts pipeline is wired correctly.",
        "ts": now_iso(),
        "user_id": user_id,
    }
    subject, body = _format_message(fake_event)
    if channel == "telegram":
        if not prefs.get("telegram_chat_id"):
            return {"ok": False, "error": "telegram_chat_id not set"}
        res = await _telegram_send(prefs["telegram_chat_id"], body)
        await _log("telegram", user_id, prefs["telegram_chat_id"], fake_event, res)
        return res
    if channel == "email":
        if not prefs.get("email_address"):
            return {"ok": False, "error": "email_address not set"}
        res = await _email_send(prefs["email_address"], subject, body)
        await _log("email", user_id, prefs["email_address"], fake_event, res)
        return res
    return {"ok": False, "error": f"unknown channel: {channel}"}


def transport_status() -> dict:
    return {
        "telegram": "configured" if _tg_token() else "missing TELEGRAM_BOT_TOKEN",
        "email": "configured" if _smtp_env() else "missing SMTP_* env vars",
        "global_telegram": bool(os.environ.get("TELEGRAM_GLOBAL_CHAT_ID")),
        "global_email": bool(os.environ.get("SMTP_GLOBAL_RECIPIENT")),
    }
