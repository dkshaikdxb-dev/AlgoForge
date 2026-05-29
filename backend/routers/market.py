"""Market data endpoints."""
from fastapi import APIRouter, HTTPException

from market_data import get_ohlcv, get_options_chain, get_symbols

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/symbols")
async def market_symbols():
    return {"symbols": get_symbols()}


@router.get("/ohlcv")
async def market_ohlcv(symbol: str, days: int = 180):
    data = get_ohlcv(symbol, days=days)
    if not data:
        raise HTTPException(404, f"Unknown symbol {symbol}")
    return {"symbol": symbol.upper(), "candles": data}


@router.get("/options-chain")
async def market_options_chain(symbol: str, expiry_days: int = 7):
    chain = get_options_chain(symbol, expiry_days=expiry_days)
    if not chain.get("rows"):
        raise HTTPException(404, f"No options chain for {symbol}")
    return chain
