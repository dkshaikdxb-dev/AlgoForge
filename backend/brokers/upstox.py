"""Upstox v2 adapter (lazy-imports upstox-python-sdk)."""
from __future__ import annotations

from . import BrokerUnavailable


class UpstoxClient:
    name = "upstox"

    def __init__(self, credentials: dict):
        self.api_key = credentials.get("api_key", "")
        self.api_secret = credentials.get("api_secret", "")
        self.access_token = credentials.get("access_token", "")
        self._api = None

    def _client(self):
        if self._api is not None:
            return self._api
        try:
            import upstox_client  # type: ignore
        except ImportError as e:
            raise BrokerUnavailable(
                "upstox-python-sdk not installed. Run: pip install upstox-python-sdk"
            ) from e
        if not self.access_token:
            raise BrokerUnavailable("Upstox access_token missing.")
        cfg = upstox_client.Configuration()
        cfg.access_token = self.access_token
        self._api = upstox_client.UserApi(upstox_client.ApiClient(cfg))
        self._order_api = upstox_client.OrderApi(upstox_client.ApiClient(cfg))
        self._portfolio_api = upstox_client.PortfolioApi(upstox_client.ApiClient(cfg))
        return self._api

    def test_connection(self) -> dict:
        api = self._client()
        profile = api.get_profile(api_version="2.0")
        data = getattr(profile, "data", profile)
        return {"ok": True, "user_id": getattr(data, "user_id", None), "name": getattr(data, "user_name", None)}

    def is_connected(self) -> bool:
        try:
            self.test_connection()
            return True
        except Exception:
            return False

    def place_order(self, *, instrument_token: str, transaction_type: str, quantity: int,
                    product: str = "I", order_type: str = "MARKET",
                    price: float = 0.0, **kwargs) -> dict:
        self._client()
        import upstox_client  # type: ignore
        body = upstox_client.PlaceOrderRequest(
            quantity=quantity,
            product=product,
            validity="DAY",
            price=price,
            instrument_token=instrument_token,
            order_type=order_type,
            transaction_type=transaction_type,
            disclosed_quantity=0,
            trigger_price=0,
            is_amo=False,
        )
        resp = self._order_api.place_order(body=body, api_version="2.0")
        order_id = getattr(getattr(resp, "data", {}), "order_id", None)
        return {"order_id": order_id, "status": "PLACED"}

    def cancel_order(self, order_id: str) -> dict:
        self._client()
        self._order_api.cancel_order(order_id=order_id, api_version="2.0")
        return {"order_id": order_id, "status": "CANCELLED"}

    def get_positions(self) -> list[dict]:
        self._client()
        resp = self._portfolio_api.get_positions(api_version="2.0")
        return getattr(resp, "data", []) or []

    def get_orders(self) -> list[dict]:
        self._client()
        resp = self._order_api.get_order_book(api_version="2.0")
        return getattr(resp, "data", []) or []

    def get_quote(self, symbol: str) -> dict:
        raise BrokerUnavailable("Upstox quote API not wired in MVP scaffold.")
