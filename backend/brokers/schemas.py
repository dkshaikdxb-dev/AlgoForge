"""Normalized cross-broker schemas.

Every broker adapter translates its native payloads into these types so the
rest of the platform (order book, positions UI, reconciler, risk engine,
journal) is broker-agnostic.

When a real broker is wired later, the adapter must:
  1. Convert outgoing requests:  NormalizedOrderRequest -> broker-native call.
  2. Convert incoming payloads:  broker-native dict -> NormalizedOrder.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class OrderStatus(str, Enum):
    PENDING = "PENDING"          # sent locally, not yet placed at broker
    PLACED = "PLACED"            # broker acknowledged
    OPEN = "OPEN"                # working order in the book
    PARTIAL = "PARTIAL"          # partially filled
    FILLED = "FILLED"            # completely filled
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class ReconciliationState(str, Enum):
    SYNCED = "SYNCED"                       # local + broker agree
    PENDING_RECONCILE = "PENDING_RECONCILE" # haven't checked yet
    OUT_OF_SYNC = "OUT_OF_SYNC"             # disagreement detected
    RECONCILED = "RECONCILED"               # disagreement just resolved
    FAILED = "FAILED"                       # cannot reach broker / persistent
    NOT_APPLICABLE = "NOT_APPLICABLE"       # paper / synthetic


class RejectionReason(str, Enum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    PRICE_OUT_OF_RANGE = "PRICE_OUT_OF_RANGE"
    KILL_SWITCH = "KILL_SWITCH"
    DUPLICATE = "DUPLICATE"
    INVALID_INSTRUMENT = "INVALID_INSTRUMENT"
    RISK_LIMIT = "RISK_LIMIT"
    BROKER_REJECTED = "BROKER_REJECTED"
    UNKNOWN = "UNKNOWN"


Side = Literal["BUY", "SELL"]
InstrumentType = Literal["EQ", "OPT", "FUT", "CMDTY"]
OptionKind = Literal["CE", "PE"]
Product = Literal["MIS", "CNC", "NRML"]  # intraday / delivery / carry-forward
Validity = Literal["DAY", "IOC", "GTT"]
OrderType = Literal["MARKET", "LIMIT", "SL", "SL-M"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NormalizedOrderRequest(BaseModel):
    """What the platform asks a broker to do. Adapter-agnostic."""
    model_config = ConfigDict(use_enum_values=True)

    symbol: str
    exchange: str = "NSE"
    instrument_type: InstrumentType = "EQ"
    option_strike: Optional[int] = None
    option_kind: Optional[OptionKind] = None
    side: Side
    qty: int = Field(gt=0)
    order_type: OrderType = "MARKET"
    product: Product = "MIS"
    validity: Validity = "DAY"
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    idempotency_key: Optional[str] = None
    tag: Optional[str] = None  # client-side correlation (strategy id, basket id)


class NormalizedOrder(BaseModel):
    """Authoritative platform-side order record after a broker call."""
    model_config = ConfigDict(use_enum_values=True)

    id: str                              # local UUID
    user_id: str
    broker: str                          # 'paper' | 'zerodha' | 'upstox' | ...
    broker_order_id: Optional[str] = None
    symbol: str
    exchange: str = "NSE"
    instrument_type: InstrumentType = "EQ"
    option_strike: Optional[int] = None
    option_kind: Optional[OptionKind] = None
    side: Side
    qty: int
    filled_qty: int = 0
    pending_qty: int = 0
    price: Optional[float] = None
    avg_fill_price: Optional[float] = None
    order_type: OrderType = "MARKET"
    product: Product = "MIS"
    validity: Validity = "DAY"
    status: OrderStatus = OrderStatus.PENDING
    rejection_reason: Optional[RejectionReason] = None
    rejection_message: Optional[str] = None
    reconciliation_state: ReconciliationState = ReconciliationState.NOT_APPLICABLE
    placed_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)
    idempotency_key: Optional[str] = None
    basket_id: Optional[str] = None
    tag: Optional[str] = None
    raw: Optional[dict[str, Any]] = None  # original broker payload for audit


class NormalizedPosition(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    user_id: str
    broker: str
    symbol: str
    exchange: str = "NSE"
    instrument_type: InstrumentType = "EQ"
    option_strike: Optional[int] = None
    option_kind: Optional[OptionKind] = None
    product: Product = "MIS"
    qty: int                              # signed
    avg_price: float
    last_price: Optional[float] = None
    pnl: Optional[float] = None
    reconciliation_state: ReconciliationState = ReconciliationState.NOT_APPLICABLE


class NormalizedOrderEvent(BaseModel):
    """Emitted by broker stream / poller when status transitions."""
    model_config = ConfigDict(use_enum_values=True)

    order_id: str
    broker_order_id: Optional[str] = None
    previous_status: OrderStatus
    new_status: OrderStatus
    filled_qty: int = 0
    avg_fill_price: Optional[float] = None
    ts: str = Field(default_factory=_utc_now)
    raw: Optional[dict[str, Any]] = None


class BrokerCapabilities(BaseModel):
    """What the broker can do — adapters declare; UI/risk uses to gate features."""
    supports_modify: bool = False
    supports_amo: bool = False              # after-market orders
    supports_iceberg: bool = False
    supports_basket_native: bool = False    # broker-side basket (e.g. Kite GTT basket)
    supports_postback_ws: bool = False      # push-based order updates
    supports_options: bool = True
    supports_options_multi_leg: bool = True
    max_qty_per_order: Optional[int] = None
    min_qty_per_order: int = 1
