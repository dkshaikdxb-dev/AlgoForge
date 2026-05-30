"""Dhan adapter — implements BrokerAdapter ABC.

Test/read paths are wired against the dhanhq SDK; mutating paths
(place/cancel/modify) raise BrokerUnavailable until production wiring is
verified against a real account.
"""
from __future__ import annotations

from .base import BrokerAdapter, BrokerAuthError, BrokerUnavailable
from .schemas import (
    BrokerCapabilities,
    NormalizedOrder,
    NormalizedOrderRequest,
    NormalizedPosition,
    OrderStatus,
)


def _dhan_status_to_normalized(s: str) -> OrderStatus:
    s = (s or "").upper()
    return {
        "TRADED": OrderStatus.FILLED,
        "PENDING": OrderStatus.PLACED,
        "TRANSIT": OrderStatus.PLACED,
        "OPEN": OrderStatus.OPEN,
        "REJECTED": OrderStatus.REJECTED,
        "CANCELLED": OrderStatus.CANCELLED,
        "EXPIRED": OrderStatus.CANCELLED,
    }.get(s, OrderStatus.UNKNOWN)


class DhanClient(BrokerAdapter):
    name = "dhan"

    def __init__(self, credentials: dict, *, user_id: str = "anonymous"):
        super().__init__(credentials, user_id=user_id)
        self.client_id = credentials.get("client_id", "")
        self.access_token = credentials.get("access_token", "")
        self._sdk = None

    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            supports_modify=True, supports_amo=True, supports_iceberg=False,
            supports_basket_native=False, supports_postback_ws=True,
            supports_options=True, supports_options_multi_leg=True,
        )

    def _client(self):
        if self._sdk is not None:
            return self._sdk
        try:
            from dhanhq import dhanhq  # type: ignore
        except ImportError as e:
            raise BrokerUnavailable("dhanhq SDK not installed. Run: pip install dhanhq") from e
        if not self.client_id or not self.access_token:
            raise BrokerUnavailable("Dhan client_id / access_token missing.")
        self._sdk = dhanhq(self.client_id, self.access_token)
        return self._sdk

    async def test_connection(self) -> dict:
        try:
            sdk = self._client()
            data = sdk.get_fund_limits()
        except BrokerUnavailable:
            raise
        except Exception as e:
            raise BrokerAuthError(str(e)) from e
        return {"ok": True, "name": "Dhan", "user_id": self.client_id, "data": data}

    async def place_order(self, req: NormalizedOrderRequest) -> NormalizedOrder:
        # Mutating paths not wired in MVP scaffold — surface clearly.
        raise BrokerUnavailable("Dhan place_order not wired yet — pending production verification.")

    async def cancel_order(self, broker_order_id: str) -> NormalizedOrder:
        raise BrokerUnavailable("Dhan cancel_order not wired yet.")

    async def modify_order(self, broker_order_id: str, *, qty=None, price=None) -> NormalizedOrder:
        raise BrokerUnavailable("Dhan modify_order not wired yet.")

    async def get_orders(self) -> list[NormalizedOrder]:
        try:
            sdk = self._client()
            raw = sdk.get_order_list()
        except BrokerUnavailable:
            raise
        except Exception as e:
            raise BrokerAuthError(str(e)) from e
        items = raw.get("data", []) if isinstance(raw, dict) else raw or []
        out: list[NormalizedOrder] = []
        for o in items:
            out.append(NormalizedOrder(
                id=str(o.get("orderId") or o.get("order_id") or ""),
                user_id=self.user_id, broker="dhan",
                broker_order_id=str(o.get("orderId") or o.get("order_id") or ""),
                symbol=o.get("tradingSymbol") or o.get("symbol") or "-",
                exchange=o.get("exchangeSegment") or o.get("exchange") or "NSE",
                side=(o.get("transactionType") or o.get("side") or "BUY").upper(),
                qty=int(o.get("quantity", 0)),
                filled_qty=int(o.get("filledQty", o.get("filled_quantity", 0))),
                pending_qty=int(o.get("remainingQuantity", 0)),
                price=o.get("price"),
                avg_fill_price=o.get("averageTradedPrice"),
                order_type=o.get("orderType", "MARKET"),
                product=o.get("productType", "INTRADAY"),
                status=_dhan_status_to_normalized(o.get("orderStatus", "")),
                raw=o,
            ))
        return out

    async def get_positions(self) -> list[NormalizedPosition]:
        try:
            sdk = self._client()
            raw = sdk.get_positions()
        except BrokerUnavailable:
            raise
        except Exception as e:
            raise BrokerAuthError(str(e)) from e
        items = raw.get("data", []) if isinstance(raw, dict) else raw or []
        out: list[NormalizedPosition] = []
        for p in items:
            qty = int(p.get("netQty", p.get("quantity", 0)) or 0)
            if not qty:
                continue
            out.append(NormalizedPosition(
                user_id=self.user_id, broker="dhan",
                symbol=p.get("tradingSymbol") or p.get("symbol") or "-",
                exchange=p.get("exchangeSegment") or p.get("exchange") or "NSE",
                product=p.get("productType", "INTRADAY"),
                qty=qty,
                avg_price=float(p.get("averagePrice", 0) or 0),
                last_price=float(p.get("ltp", p.get("last_price", 0)) or 0),
                pnl=float(p.get("unrealizedProfit", p.get("pnl", 0)) or 0),
            ))
        return out
