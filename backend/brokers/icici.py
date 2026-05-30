"""ICICI Direct Breeze adapter — implements BrokerAdapter ABC.

The Breeze SDK is synchronous; we wrap calls and translate errors to typed
BrokerError subclasses. Mutating paths are intentionally not wired in the MVP
scaffold and raise BrokerUnavailable.
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


def _icici_status_to_normalized(s: str) -> OrderStatus:
    s = (s or "").upper()
    return {
        "EXECUTED": OrderStatus.FILLED,
        "OPEN": OrderStatus.OPEN,
        "PENDING": OrderStatus.PLACED,
        "REJECTED": OrderStatus.REJECTED,
        "CANCELLED": OrderStatus.CANCELLED,
    }.get(s, OrderStatus.UNKNOWN)


class ICICIDirectClient(BrokerAdapter):
    name = "icici"

    def __init__(self, credentials: dict, *, user_id: str = "anonymous"):
        super().__init__(credentials, user_id=user_id)
        self.api_key = credentials.get("api_key", "")
        self.api_secret = credentials.get("api_secret", "")
        self.session_token = credentials.get("session_token", "")
        self._sdk = None

    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            supports_modify=True, supports_amo=False, supports_iceberg=False,
            supports_basket_native=False, supports_postback_ws=False,
            supports_options=True, supports_options_multi_leg=True,
        )

    def _client(self):
        if self._sdk is not None:
            return self._sdk
        try:
            from breeze_connect import BreezeConnect  # type: ignore
        except ImportError as e:
            raise BrokerUnavailable("breeze-connect not installed. Run: pip install breeze-connect") from e
        if not all([self.api_key, self.api_secret, self.session_token]):
            raise BrokerUnavailable("ICICI Direct keys missing (api_key / api_secret / session_token).")
        bc = BreezeConnect(api_key=self.api_key)
        bc.generate_session(api_secret=self.api_secret, session_token=self.session_token)
        self._sdk = bc
        return bc

    async def test_connection(self) -> dict:
        try:
            sdk = self._client()
            data = sdk.get_customer_details()
        except BrokerUnavailable:
            raise
        except Exception as e:
            raise BrokerAuthError(str(e)) from e
        d = data.get("Success") if isinstance(data, dict) else None
        return {
            "ok": True, "name": "ICICI Direct",
            "user_id": (d or {}).get("idirect_userid"),
            "data": data,
        }

    async def place_order(self, req: NormalizedOrderRequest) -> NormalizedOrder:
        raise BrokerUnavailable("ICICI Direct place_order not wired yet — pending production verification.")

    async def cancel_order(self, broker_order_id: str) -> NormalizedOrder:
        raise BrokerUnavailable("ICICI Direct cancel_order not wired yet.")

    async def modify_order(self, broker_order_id: str, *, qty=None, price=None) -> NormalizedOrder:
        raise BrokerUnavailable("ICICI Direct modify_order not wired yet.")

    async def get_orders(self) -> list[NormalizedOrder]:
        try:
            sdk = self._client()
            raw = sdk.get_order_list()
        except BrokerUnavailable:
            raise
        except Exception as e:
            raise BrokerAuthError(str(e)) from e
        items = raw.get("Success", []) if isinstance(raw, dict) else raw or []
        out: list[NormalizedOrder] = []
        for o in items:
            oid = str(o.get("order_id", ""))
            out.append(NormalizedOrder(
                id=oid, user_id=self.user_id, broker="icici",
                broker_order_id=oid,
                symbol=o.get("stock_code") or o.get("trading_symbol") or "-",
                exchange=o.get("exchange_code", "NSE"),
                side=(o.get("action") or o.get("transaction_type") or "BUY").upper(),
                qty=int(o.get("quantity", 0) or 0),
                filled_qty=int(o.get("executed_quantity", 0) or 0),
                pending_qty=int(o.get("pending_quantity", 0) or 0),
                price=o.get("price"),
                avg_fill_price=o.get("average_price"),
                order_type=o.get("order_type", "MARKET"),
                product=o.get("product", "cash"),
                status=_icici_status_to_normalized(o.get("status", "")),
                raw=o,
            ))
        return out

    async def get_positions(self) -> list[NormalizedPosition]:
        try:
            sdk = self._client()
            raw = sdk.get_portfolio_positions()
        except BrokerUnavailable:
            raise
        except Exception as e:
            raise BrokerAuthError(str(e)) from e
        items = raw.get("Success", []) if isinstance(raw, dict) else raw or []
        out: list[NormalizedPosition] = []
        for p in items:
            qty = int(p.get("quantity", 0) or 0)
            if not qty:
                continue
            out.append(NormalizedPosition(
                user_id=self.user_id, broker="icici",
                symbol=p.get("stock_code") or "-",
                exchange=p.get("exchange_code", "NSE"),
                product=p.get("product", "cash"),
                qty=qty,
                avg_price=float(p.get("average_price", 0) or 0),
                last_price=float(p.get("ltp", 0) or 0),
                pnl=float(p.get("unrealized_pnl", 0) or 0),
            ))
        return out
