"""Rmoney adapter — implements BrokerAdapter ABC.

No official Python SDK exists; this adapter is a thin REST client placeholder.
test_connection hits a profile endpoint; all mutating paths are not wired in
the MVP scaffold and raise BrokerUnavailable. Network errors map to
BrokerNetworkError so the reconciler retries with backoff.
"""
from __future__ import annotations

import httpx

from .base import (
    BrokerAdapter,
    BrokerAuthError,
    BrokerNetworkError,
    BrokerUnavailable,
)
from .schemas import (
    BrokerCapabilities,
    NormalizedOrder,
    NormalizedOrderRequest,
    NormalizedPosition,
)

BASE_URL = "https://rmoneyindia.com/api"  # placeholder; replace with real endpoint when keys arrive


class RmoneyClient(BrokerAdapter):
    name = "rmoney"

    def __init__(self, credentials: dict, *, user_id: str = "anonymous"):
        super().__init__(credentials, user_id=user_id)
        self.account_user_id = credentials.get("user_id", "")
        self.api_key = credentials.get("api_key", "")
        self.password = credentials.get("password", "")

    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            supports_modify=False, supports_amo=False, supports_iceberg=False,
            supports_basket_native=False, supports_postback_ws=False,
            supports_options=True, supports_options_multi_leg=False,
        )

    def _headers(self):
        if not self.api_key:
            raise BrokerUnavailable("Rmoney api_key missing.")
        return {"Authorization": f"Bearer {self.api_key}", "X-User-Id": self.account_user_id}

    async def test_connection(self) -> dict:
        headers = self._headers()
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{BASE_URL}/profile", headers=headers)
        except httpx.RequestError as e:
            raise BrokerNetworkError(f"Rmoney network error: {e}") from e
        if r.status_code in (401, 403):
            raise BrokerAuthError(f"Rmoney auth failed ({r.status_code})")
        if r.status_code >= 400:
            raise BrokerUnavailable(f"Rmoney returned {r.status_code}")
        try:
            data = r.json()
        except Exception:
            data = {}
        return {"ok": True, "name": "Rmoney", "user_id": self.account_user_id, "data": data}

    async def place_order(self, req: NormalizedOrderRequest) -> NormalizedOrder:
        raise BrokerUnavailable("Rmoney place_order not wired — awaiting official API spec.")

    async def cancel_order(self, broker_order_id: str) -> NormalizedOrder:
        raise BrokerUnavailable("Rmoney cancel_order not wired.")

    async def modify_order(self, broker_order_id: str, *, qty=None, price=None) -> NormalizedOrder:
        raise BrokerUnavailable("Rmoney modify_order not wired.")

    async def get_orders(self) -> list[NormalizedOrder]:
        raise BrokerUnavailable("Rmoney orders not wired.")

    async def get_positions(self) -> list[NormalizedPosition]:
        raise BrokerUnavailable("Rmoney positions not wired.")
