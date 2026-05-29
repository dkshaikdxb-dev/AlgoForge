"""WebSocket tick feed — deterministic mock until real broker WS is wired.

Streams JSON ticks every ~700ms for subscribed symbols. Frontend connects via
`/api/ws/ticks?symbols=NIFTY,BANKNIFTY` and receives:
  {"symbol":"NIFTY","ltp":22150.4,"change":-12.3,"change_pct":-0.05,"ts": "..."}
"""
from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from market_data import get_last_price, SYMBOLS

router = APIRouter()

# track simulated price state per symbol so movements feel continuous
_state: dict[str, float] = {}
_open: dict[str, float] = {s: get_last_price(s) for s in SYMBOLS}


def _next_tick(symbol: str) -> dict:
    s = symbol.upper()
    base = _state.get(s) or get_last_price(s)
    vol = SYMBOLS.get(s, {}).get("vol", 0.01)
    # small per-tick move
    move = random.gauss(0, base * vol * 0.05)
    new = max(0.01, base + move)
    _state[s] = new
    open_p = _open.get(s, new)
    chg = new - open_p
    return {
        "symbol": s,
        "ltp": round(new, 2),
        "open": round(open_p, 2),
        "change": round(chg, 2),
        "change_pct": round((chg / open_p) * 100, 3) if open_p else 0,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@router.websocket("/ws/ticks")
async def ws_ticks(ws: WebSocket, symbols: str = "NIFTY,BANKNIFTY"):
    await ws.accept()
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    syms = [s for s in syms if s in SYMBOLS] or ["NIFTY"]
    try:
        # Send initial snapshot
        snapshot = [_next_tick(s) for s in syms]
        await ws.send_text(json.dumps({"type": "snapshot", "ticks": snapshot}))
        while True:
            await asyncio.sleep(0.75)
            ticks = [_next_tick(s) for s in syms]
            await ws.send_text(json.dumps({"type": "tick", "ticks": ticks}))
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass
