"""Upstox v2 adapter — implements BrokerAdapter ABC.

All blocking upstox_client SDK calls are dispatched via asyncio.to_thread so
the FastAPI event loop is never stalled during real-account wiring.
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


def _upstox_status_to_normalized(s: str) -> OrderStatus:
    s = (s or "").upper()
    return {
        "COMPLETE": OrderStatus.FILLED,
        "OPEN": OrderStatus.OPEN,
        "PENDING": OrderStatus.PLACED,
        "REJECTED": OrderStatus.REJECTED,
        "CANCELLED": OrderStatus.CANCELLED,
    }.get(s, OrderStatus.UNKNOWN)


class UpstoxClient(BrokerAdapter):
    name = "upstox"

    def __init__(self, credentials: dict, *, user_id: str = "anonymous"):
        super().__init__(credentials, user_id=user_id)
        self.api_key = credentials.get("api_key", "")
        self.api_secret = credentials.get("api_secret", "")
        self.access_token = credentials.get("access_token", "")
        self._cfg = None

    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            supports_modify=True, supports_amo=True, supports_iceberg=True,
            supports_basket_native=False, supports_postback_ws=True,
            supports_options=True, supports_options_multi_leg=True,
        )

    def _apis(self):
        if self._cfg is not None:
            return self._cfg
        try:
            import upstox_client  # type: ignore
        except ImportError as e:
            raise BrokerUnavailable("upstox-python-sdk not installed. Run: pip install upstox-python-sdk") from e
        if not self.access_token:
            raise BrokerUnavailable("Upstox access_token missing.")
        cfg = upstox_client.Configuration()
        cfg.access_token = self.access_token
        api_client = upstox_client.ApiClient(cfg)
        self._cfg = {
            "user": upstox_client.UserApi(api_client),
            "order": upstox_client.OrderApi(api_client),
            "portfolio": upstox_client.PortfolioApi(api_client),
            "module": upstox_client,
        }
        return self._cfg

    async def test_connection(self) -> dict:
        try:
            apis = self._apis()
            profile = await asyncio.to_thread(apis["user"].get_profile, api_version="2.0")
        except BrokerUnavailable:
            raise
        except Exception as e:
            raise BrokerAuthError(str(e)) from e
        data = getattr(profile, "data", profile)
        return {"ok": True, "user_id": getattr(data, "user_id", None), "name": getattr(data, "user_name", None)}

    async def place_order(self, req: NormalizedOrderRequest) -> NormalizedOrder:
        apis = self._apis()
        upstox_client = apis["module"]
        body = upstox_client.PlaceOrderRequest(
            quantity=req.qty,
            product="I" if req.product == "MIS" else "D",
            validity=req.validity,
            price=req.price or 0.0,
            instrument_token=req.symbol,
            order_type=req.order_type,
            transaction_type=req.side,
            disclosed_quantity=0,
            trigger_price=req.trigger_price or 0,
            is_amo=False,
        )
        try:
            resp = await asyncio.to_thread(apis["order"].place_order, body=body, api_version="2.0")
        except Exception as e:
            raise BrokerOrderRejected(str(e)) from e
        order_id = getattr(getattr(resp, "data", None), "order_id", None)
        return NormalizedOrder(
            id=str(order_id), user_id=self.user_id, broker="upstox",
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
        apis = self._apis()
        try:
            await asyncio.to_thread(apis["order"].cancel_order, order_id=broker_order_id, api_version="2.0")
        except Exception as e:
            raise BrokerOrderRejected(str(e)) from e
        return NormalizedOrder(
            id=broker_order_id, user_id=self.user_id, broker="upstox",
            broker_order_id=broker_order_id, symbol="-", side="BUY", qty=0,
            status=OrderStatus.CANCELLED,
        )

    async def modify_order(self, broker_order_id: str, *, qty=None, price=None) -> NormalizedOrder:
        apis = self._apis()
        upstox_client = apis["module"]
        body = upstox_client.ModifyOrderRequest(
            order_id=broker_order_id,
            quantity=qty,
            price=price,
            validity="DAY",
            order_type="LIMIT" if price else "MARKET",
            disclosed_quantity=0,
            trigger_price=0,
        )
        try:
            await asyncio.to_thread(apis["order"].modify_order, body=body, api_version="2.0")
        except Exception as e:
            raise BrokerOrderRejected(str(e)) from e
        return NormalizedOrder(
            id=broker_order_id, user_id=self.user_id, broker="upstox",
            broker_order_id=broker_order_id, symbol="-", side="BUY",
            qty=qty or 0, price=price, status=OrderStatus.OPEN,
        )

    async def get_orders(self) -> list[NormalizedOrder]:
        apis = self._apis()
        try:
            resp = await asyncio.to_thread(apis["order"].get_order_book, api_version="2.0")
        except Exception as e:
            raise BrokerAuthError(str(e)) from e
        items = getattr(resp, "data", []) or []
        out = []
        for o in items:
            order_id = getattr(o, "order_id", None) or getattr(o, "exchange_order_id", None)
            out.append(NormalizedOrder(
                id=str(order_id), user_id=self.user_id, broker="upstox",
                broker_order_id=str(order_id),
                symbol=getattr(o, "trading_symbol", "-"),
                exchange=getattr(o, "exchange", "NSE"),
                side=getattr(o, "transaction_type", "BUY"),
                qty=int(getattr(o, "quantity", 0)),
                filled_qty=int(getattr(o, "filled_quantity", 0)),
                pending_qty=int(getattr(o, "pending_quantity", 0)),
                price=getattr(o, "price", None),
                avg_fill_price=getattr(o, "average_price", None),
                order_type=getattr(o, "order_type", "MARKET"),
                status=_upstox_status_to_normalized(getattr(o, "status", "")),
                raw={k: getattr(o, k) for k in dir(o) if not k.startswith("_") and not callable(getattr(o, k))},
            ))
        return out

    async def get_positions(self) -> list[NormalizedPosition]:
        apis = self._apis()
        try:
            resp = await asyncio.to_thread(apis["portfolio"].get_positions, api_version="2.0")
        except Exception as e:
            raise BrokerAuthError(str(e)) from e
        items = getattr(resp, "data", []) or []
        return [
            NormalizedPosition(
                user_id=self.user_id, broker="upstox",
                symbol=getattr(p, "trading_symbol", "-"),
                exchange=getattr(p, "exchange", "NSE"),
                qty=int(getattr(p, "quantity", 0)),
                avg_price=float(getattr(p, "average_price", 0) or 0),
                last_price=float(getattr(p, "last_price", 0) or 0),
                pnl=float(getattr(p, "pnl", 0) or 0),
            )
            for p in items if getattr(p, "quantity", 0)
        ]
