"""Registry of supported brokers + factory."""
from __future__ import annotations

from . import BrokerInfo, BrokerUnavailable
from .zerodha import ZerodhaClient
from .upstox import UpstoxClient
from .dhan import DhanClient
from .icici import ICICIDirectClient
from .rmoney import RmoneyClient


SUPPORTED: dict[str, dict] = {
    "zerodha": {
        "client": ZerodhaClient,
        "capabilities": {
            "supports_modify": True, "supports_amo": True, "supports_iceberg": True,
            "supports_basket_native": True, "supports_postback_ws": True,
            "supports_options": True, "supports_options_multi_leg": True,
        },
        "info": BrokerInfo(
            name="zerodha",
            label="Zerodha Kite",
            description="Connect via Kite Connect API (requires app + redirect login).",
            fields=[
                {"key": "api_key", "label": "API Key", "secret": False},
                {"key": "api_secret", "label": "API Secret", "secret": True},
                {"key": "access_token", "label": "Access Token (from daily login flow)", "secret": True},
            ],
            sdk_package="kiteconnect",
            docs_url="https://kite.trade/docs/connect/v3/",
        ),
    },
    "upstox": {
        "client": UpstoxClient,
        "capabilities": {
            "supports_modify": True, "supports_amo": True, "supports_iceberg": True,
            "supports_basket_native": False, "supports_postback_ws": True,
            "supports_options": True, "supports_options_multi_leg": True,
        },
        "info": BrokerInfo(
            name="upstox",
            label="Upstox",
            description="OAuth2-based REST + WebSocket access via Upstox API v2.",
            fields=[
                {"key": "api_key", "label": "API Key", "secret": False},
                {"key": "api_secret", "label": "API Secret", "secret": True},
                {"key": "access_token", "label": "Access Token", "secret": True},
            ],
            sdk_package="upstox-python-sdk",
            docs_url="https://upstox.com/developer/api-documentation/",
        ),
    },
    "dhan": {
        "client": DhanClient,
        "info": BrokerInfo(
            name="dhan",
            label="Dhan",
            description="REST API with client_id + access_token issued from Dhan dashboard.",
            fields=[
                {"key": "client_id", "label": "Client ID", "secret": False},
                {"key": "access_token", "label": "Access Token", "secret": True},
            ],
            sdk_package="dhanhq",
            docs_url="https://dhanhq.co/docs/",
        ),
    },
    "icici": {
        "client": ICICIDirectClient,
        "capabilities": {
            "supports_modify": True, "supports_amo": False, "supports_iceberg": False,
            "supports_basket_native": False, "supports_postback_ws": False,
            "supports_options": True, "supports_options_multi_leg": True,
        },
        "info": BrokerInfo(
            name="icici",
            label="ICICI Direct Breeze",
            description="Breeze Connect API. Requires login to generate session token daily.",
            fields=[
                {"key": "api_key", "label": "API Key", "secret": False},
                {"key": "api_secret", "label": "API Secret", "secret": True},
                {"key": "session_token", "label": "Session Token", "secret": True},
            ],
            sdk_package="breeze-connect",
            docs_url="https://api.icicidirect.com/breezeapi/documents/index.html",
        ),
    },
    "rmoney": {
        "client": RmoneyClient,
        "capabilities": {
            "supports_modify": False, "supports_amo": False, "supports_iceberg": False,
            "supports_basket_native": False, "supports_postback_ws": False,
            "supports_options": True, "supports_options_multi_leg": False,
        },
        "info": BrokerInfo(
            name="rmoney",
            label="Rmoney (R-Money Plus)",
            description="REST API connection via Rmoney's official endpoints.",
            fields=[
                {"key": "user_id", "label": "User ID", "secret": False},
                {"key": "api_key", "label": "API Key", "secret": True},
                {"key": "password", "label": "Password / Token", "secret": True},
            ],
            sdk_package=None,
            docs_url="https://www.rmoneyindia.com",
        ),
    },
}


def list_brokers() -> list[dict]:
    out = []
    for key, entry in SUPPORTED.items():
        info: BrokerInfo = entry["info"]
        out.append({
            "name": info.name,
            "label": info.label,
            "description": info.description,
            "fields": info.fields,
            "sdk_package": info.sdk_package,
            "docs_url": info.docs_url,
            "capabilities": entry.get("capabilities", {}),
        })
    return out


def make_client(name: str, credentials: dict):
    if name not in SUPPORTED:
        raise BrokerUnavailable(f"Unknown broker: {name}")
    return SUPPORTED[name]["client"](credentials)
