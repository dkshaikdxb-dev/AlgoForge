"""Zerodha Kite Connect adapter — implements BrokerAdapter ABC.

When live: actual order placement and order-book reads via kiteconnect.
When the SDK is missing or keys absent: BrokerUnavailable is raised cleanly so
the reconciler tags the broker PENDING_RECONCILE rather than crashing.

All blocking kiteconnect calls are dispatched via asyncio.to_thread so the
FastAPI event loop is never stalled during real-account wiring.
"""
from __future__ import annotations

import asyncio

from .base import BrokerAdapter, BrokerAuthError, BrokerOrderRejected, BrokerUnavailable
from .schemas import (
    BrokerCapabilities,
    NormalizedOrder,
    NormalizedOrderRequest,
    NormalizedPosition,
    OrderStatus,
    ReconciliationState,
)


def _kite_status_to_normalized(s: str) -> OrderStatus:
    s = (s or "").upper()
    return {
        "COMPLETE": OrderStatus.FILLED,
        "OPEN": OrderStatus.OPEN,
        "PENDING": OrderStatus.PLACED,
        "REJECTED": OrderStatus.REJECTED,
        "CANCELLED": OrderStatus.CANCELLED,
        "TRIGGER PENDING": OrderStatus.OPEN,
    }.get(s, OrderStatus.UNKNOWN)


class ZerodhaClient(BrokerAdapter):
    name = "zerodha"

    def __init__(self, credentials: dict, *, user_id: str = "anonymous"):
        super().__init__(credentials, user_id=user_id)
        self.api_key = credentials.get("api_key", "")
        self.api_secret = credentials.get("api_secret", "")
        self.access_token = credentials.get("access_token", "")
        self._kite = None

    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            supports_modify=True, supports_amo=True, supports_iceberg=True,
            supports_basket_native=True, supports_postback_ws=True,
            supports_options=True, supports_options_multi_leg=True,
        )

    def _client(self):
        if self._kite is not None:
            return self._kite
        try:
            from kiteconnect import KiteConnect  # type: ignore
        except ImportError as e:
            raise BrokerUnavailable("kiteconnect SDK not installed. Run: pip install kiteconnect") from e
        if not self.api_key or not self.access_token:
            raise BrokerUnavailable("Zerodha api_key / access_token missing.")
        kite = KiteConnect(api_key=self.api_key)
        kite.set_access_token(self.access_token)
        self._kite = kite
        return kite

    async def test_connection(self) -> dict:
        try:
            kite = self._client()
            profile = await asyncio.to_thread(kite.profile)
        except BrokerUnavailable:
            raise
        except Exception as e:
            raise BrokerAuthError(str(e)) from e
        return {"ok": True, "user_id": profile.get("user_id"), "name": profile.get("user_name")}

    async def place_order(self, req: NormalizedOrderRequest) -> NormalizedOrder:
        kite = self._client()
        side_map = {"BUY": "BUY", "SELL": "SELL"}
        try:
            order_id = await asyncio.to_thread(
                kite.place_order,
                variety="regular",
                tradingsymbol=req.symbol,
                exchange=req.exchange,
                transaction_type=side_map[req.side],
                quantity=req.qty,
                product=req.product,
                order_type=req.order_type,
                price=req.price,
                trigger_price=req.trigger_price,
                validity=req.validity,
                tag=req.tag[:20] if req.tag else None,
            )
        except Exception as e:
            raise BrokerOrderRejected(str(e)) from e
        return NormalizedOrder(
            id=str(order_id), user_id=self.user_id, broker="zerodha",
            broker_order_id=str(order_id),
            symbol=req.symbol, exchange=req.exchange, instrument_type=req.instrument_type,
            option_strike=req.option_strike, option_kind=req.option_kind,
            side=req.side, qty=req.qty, pending_qty=req.qty,
            price=req.price, order_type=req.order_type, product=req.product,
            status=OrderStatus.PLACED,
            reconciliation_state=ReconciliationState.PENDING_RECONCILE,
            idempotency_key=req.idempotency_key, tag=req.tag,
        )

    async def cancel_order(self, broker_order_id: str) -> NormalizedOrder:
        kite = self._client()
        try:
            await asyncio.to_thread(kite.cancel_order, variety="regular", order_id=broker_order_id)
        except Exception as e:
            raise BrokerOrderRejected(str(e)) from e
        return NormalizedOrder(
            id=broker_order_id, user_id=self.user_id, broker="zerodha",
            broker_order_id=broker_order_id,
            symbol="-", side="BUY", qty=0,
            status=OrderStatus.CANCELLED,
        )

    async def modify_order(self, broker_order_id: str, *, qty=None, price=None) -> NormalizedOrder:
        kite = self._client()
        kwargs = {"variety": "regular", "order_id": broker_order_id}
        if qty is not None:
            kwargs["quantity"] = qty
        if price is not None:
            kwargs["price"] = price
        try:
            await asyncio.to_thread(lambda: kite.modify_order(**kwargs))
        except Exception as e:
            raise BrokerOrderRejected(str(e)) from e
        return NormalizedOrder(
            id=broker_order_id, user_id=self.user_id, broker="zerodha",
            broker_order_id=broker_order_id, symbol="-", side="BUY",
            qty=qty or 0, price=price, status=OrderStatus.OPEN,
        )

    async def get_orders(self) -> list[NormalizedOrder]:
        kite = self._client()
        try:
            raw_orders = await asyncio.to_thread(kite.orders) or []
        except Exception as e:
            raise BrokerAuthError(str(e)) from e
        out = []
        for o in raw_orders:
            out.append(NormalizedOrder(
                id=str(o.get("order_id")),
                user_id=self.user_id, broker="zerodha",
                broker_order_id=str(o.get("order_id")),
                symbol=o.get("tradingsymbol", "-"),
                exchange=o.get("exchange", "NSE"),
                side=o.get("transaction_type", "BUY"),
                qty=int(o.get("quantity", 0)),
                filled_qty=int(o.get("filled_quantity", 0)),
                pending_qty=int(o.get("pending_quantity", 0)),
                price=o.get("price"),
                avg_fill_price=o.get("average_price"),
                order_type=o.get("order_type", "MARKET"),
                product=o.get("product", "MIS"),
                status=_kite_status_to_normalized(o.get("status", "")),
                placed_at=str(o.get("order_timestamp", "")),
                raw=o,
            ))
        return out

    async def get_positions(self) -> list[NormalizedPosition]:
        kite = self._client()
        try:
            data = await asyncio.to_thread(kite.positions) or {}
        except Exception as e:
            raise BrokerAuthError(str(e)) from e
        net = data.get("net") or []
        return [
            NormalizedPosition(
                user_id=self.user_id, broker="zerodha",
                symbol=p.get("tradingsymbol", "-"),
                exchange=p.get("exchange", "NSE"),
                product=p.get("product", "MIS"),
                qty=int(p.get("quantity", 0)),
                avg_price=float(p.get("average_price", 0)),
                last_price=float(p.get("last_price", 0)),
                pnl=float(p.get("pnl", 0)),
            )
            for p in net if p.get("quantity")
        ]

    async def get_quote(self, symbol: str, exchange: str = "NSE") -> float:
        """Live LTP via Kite quote API. Used for live-order notional checks."""
        kite = self._client()
        key = f"{exchange}:{symbol.upper()}"
        try:
            data = await asyncio.to_thread(kite.ltp, [key])
        except Exception as e:
            raise BrokerAuthError(str(e)) from e
        row = (data or {}).get(key) or {}
        return float(row.get("last_price") or 0.0)
