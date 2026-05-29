"""Dhan adapter stub — lazy-imports dhanhq SDK."""
from __future__ import annotations

from . import BrokerUnavailable


class DhanClient:
    name = "dhan"

    def __init__(self, credentials: dict):
        self.client_id = credentials.get("client_id", "")
        self.access_token = credentials.get("access_token", "")
        self._sdk = None

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

    def test_connection(self) -> dict:
        sdk = self._client()
        resp = sdk.get_fund_limits()
        return {"ok": True, "data": resp}

    def is_connected(self) -> bool:
        try:
            self.test_connection()
            return True
        except Exception:
            return False

    def place_order(self, **kwargs):  # noqa: D401
        raise BrokerUnavailable("Dhan place_order not wired in MVP scaffold.")

    def cancel_order(self, order_id: str):
        raise BrokerUnavailable("Dhan cancel_order not wired in MVP scaffold.")

    def get_positions(self):
        return self._client().get_positions()

    def get_orders(self):
        return self._client().get_order_list()

    def get_quote(self, symbol: str):
        raise BrokerUnavailable("Dhan quote not wired.")
