"""Zerodha Kite Connect adapter (lazy-imports kiteconnect)."""
from __future__ import annotations

from . import BrokerUnavailable


class ZerodhaClient:
    name = "zerodha"

    def __init__(self, credentials: dict):
        self.api_key = credentials.get("api_key", "")
        self.api_secret = credentials.get("api_secret", "")
        self.access_token = credentials.get("access_token", "")
        self._kite = None

    def _client(self):
        if self._kite is not None:
            return self._kite
        try:
            from kiteconnect import KiteConnect  # type: ignore
        except ImportError as e:
            raise BrokerUnavailable(
                "kiteconnect SDK not installed. Run: pip install kiteconnect"
            ) from e
        if not self.api_key or not self.access_token:
            raise BrokerUnavailable("Zerodha api_key / access_token missing.")
        kite = KiteConnect(api_key=self.api_key)
        kite.set_access_token(self.access_token)
        self._kite = kite
        return kite

    def test_connection(self) -> dict:
        kite = self._client()
        profile = kite.profile()
        return {"ok": True, "user_id": profile.get("user_id"), "name": profile.get("user_name")}

    def is_connected(self) -> bool:
        try:
            self.test_connection()
            return True
        except Exception:
            return False

    def place_order(self, *, tradingsymbol: str, exchange: str, transaction_type: str,
                    quantity: int, product: str = "MIS", order_type: str = "MARKET",
                    price: float | None = None, **kwargs) -> dict:
        kite = self._client()
        order_id = kite.place_order(
            variety="regular",
            tradingsymbol=tradingsymbol,
            exchange=exchange,
            transaction_type=transaction_type,
            quantity=quantity,
            product=product,
            order_type=order_type,
            price=price,
        )
        return {"order_id": str(order_id), "status": "PLACED"}

    def cancel_order(self, order_id: str) -> dict:
        kite = self._client()
        kite.cancel_order(variety="regular", order_id=order_id)
        return {"order_id": order_id, "status": "CANCELLED"}

    def get_positions(self) -> list[dict]:
        kite = self._client()
        pos = kite.positions()
        return pos.get("net", [])

    def get_orders(self) -> list[dict]:
        return self._client().orders()

    def get_quote(self, symbol: str) -> dict:
        return self._client().quote([symbol]).get(symbol, {})
