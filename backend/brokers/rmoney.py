"""Rmoney adapter stub — no official SDK; thin REST client placeholder."""
from __future__ import annotations

import requests

from . import BrokerUnavailable

BASE_URL = "https://rmoneyindia.com/api"  # placeholder; replace with real endpoint when keys arrive


class RmoneyClient:
    name = "rmoney"

    def __init__(self, credentials: dict):
        self.user_id = credentials.get("user_id", "")
        self.api_key = credentials.get("api_key", "")
        self.password = credentials.get("password", "")

    def _headers(self):
        if not self.api_key:
            raise BrokerUnavailable("Rmoney api_key missing.")
        return {"Authorization": f"Bearer {self.api_key}", "X-User-Id": self.user_id}

    def test_connection(self) -> dict:
        # REST endpoint placeholder. Real spec from Rmoney support is required.
        try:
            response = requests.get(f"{BASE_URL}/profile", headers=self._headers(), timeout=8)
        except requests.RequestException as e:
            raise BrokerUnavailable(f"Rmoney network error: {e}") from e
        if response.status_code >= 400:
            raise BrokerUnavailable(f"Rmoney auth failed ({response.status_code})")
        return {"ok": True, "data": response.json()}

    def is_connected(self) -> bool:
        try:
            self.test_connection()
            return True
        except Exception:
            return False

    def place_order(self, **kwargs):
        raise BrokerUnavailable("Rmoney place_order not wired — awaiting official API doc.")

    def cancel_order(self, order_id: str):
        raise BrokerUnavailable("Rmoney cancel_order not wired.")

    def get_positions(self):
        raise BrokerUnavailable("Rmoney positions not wired.")

    def get_orders(self):
        raise BrokerUnavailable("Rmoney orders not wired.")

    def get_quote(self, symbol: str):
        raise BrokerUnavailable("Rmoney quote not wired.")
