"""Broker integration scaffold.

Each broker implements the BrokerClient interface. When live keys are not
available or the SDK isn't installed, methods raise BrokerUnavailable so the
caller can gracefully fall back to the paper engine.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from cryptography.fernet import Fernet

_FERNET = Fernet(os.environ["ENCRYPTION_KEY"].encode())


def encrypt_credentials(payload: dict) -> str:
    import json
    return _FERNET.encrypt(json.dumps(payload).encode()).decode()


def decrypt_credentials(token: str) -> dict:
    import json
    return json.loads(_FERNET.decrypt(token.encode()).decode())


class BrokerUnavailable(Exception):
    """DEPRECATED legacy shim. Use brokers.base.BrokerUnavailable instead.

    Kept ONLY so older imports `from brokers import BrokerUnavailable` still
    work; this class is re-assigned below to the canonical one in
    `brokers.base` so `isinstance(e, brokers.base.BrokerUnavailable)` and
    `isinstance(e, brokers.BrokerUnavailable)` evaluate identically.
    """
    pass


# Re-export the canonical class so both imports resolve to the same object.
from .base import BrokerUnavailable as BrokerUnavailable  # noqa: F811,E402


@dataclass
class BrokerInfo:
    name: str
    label: str
    description: str
    fields: list[dict]  # [{"key":"api_key","label":"API Key","secret":True}, ...]
    sdk_package: str | None
    docs_url: str


class BrokerClient(Protocol):
    name: str

    def is_connected(self) -> bool: ...
    def test_connection(self) -> dict: ...
    def place_order(self, **kwargs) -> dict: ...
    def cancel_order(self, order_id: str) -> dict: ...
    def get_positions(self) -> list[dict]: ...
    def get_orders(self) -> list[dict]: ...
    def get_quote(self, symbol: str) -> dict: ...
