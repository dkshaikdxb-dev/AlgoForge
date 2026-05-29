"""ICICI Direct Breeze adapter stub."""
from __future__ import annotations

from . import BrokerUnavailable


class ICICIDirectClient:
    name = "icici"

    def __init__(self, credentials: dict):
        self.api_key = credentials.get("api_key", "")
        self.api_secret = credentials.get("api_secret", "")
        self.session_token = credentials.get("session_token", "")
        self._sdk = None

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

    def test_connection(self) -> dict:
        sdk = self._client()
        return {"ok": True, "data": sdk.get_customer_details()}

    def is_connected(self) -> bool:
        try:
            self.test_connection()
            return True
        except Exception:
            return False

    def place_order(self, **kwargs):
        raise BrokerUnavailable("ICICI Direct place_order not wired in MVP scaffold.")

    def cancel_order(self, order_id: str):
        raise BrokerUnavailable("ICICI Direct cancel_order not wired in MVP scaffold.")

    def get_positions(self):
        return self._client().get_portfolio_positions()

    def get_orders(self):
        return self._client().get_order_list()

    def get_quote(self, symbol: str):
        raise BrokerUnavailable("ICICI Direct quote not wired.")
