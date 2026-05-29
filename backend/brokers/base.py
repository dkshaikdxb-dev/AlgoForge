"""Broker adapter ABC + typed error hierarchy + retry / circuit-breaker helpers.

Every concrete broker adapter (Zerodha, Upstox, Dhan, ICICI, Rmoney, Paper)
inherits from `BrokerAdapter` and implements 6 abstract methods. The platform
NEVER imports a concrete adapter directly — it always goes through the
registry, which produces a `BrokerAdapter`.

Error policy:
- All adapter methods raise subclasses of `BrokerError`.
- Network/timeout errors are retried by `call_with_retry`.
- Auth/rejected errors fail fast.
- Repeated failures (3 within 30s) trip an in-memory circuit breaker per
  (user_id, broker) tuple → calls fail fast for 60s → half-open → retry.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Awaitable, Callable, TypeVar

from .schemas import (
    BrokerCapabilities,
    NormalizedOrder,
    NormalizedOrderEvent,
    NormalizedOrderRequest,
    NormalizedPosition,
)

logger = logging.getLogger("algoforge.brokers")

T = TypeVar("T")


# --- Error hierarchy --------------------------------------------------------

class BrokerError(Exception):
    """Base broker error. Subclasses describe whether retry is meaningful."""
    retryable: bool = False


class BrokerUnavailable(BrokerError):
    """SDK missing / no keys / configuration error. Not retryable."""
    retryable = False


class BrokerAuthError(BrokerError):
    """Bad creds / expired token. Not retryable — needs user reconnect."""
    retryable = False


class BrokerRateLimited(BrokerError):
    """Broker said slow down. Retryable with backoff."""
    retryable = True


class BrokerOrderRejected(BrokerError):
    """Broker accepted the call but rejected the order. Not retryable."""
    retryable = False


class BrokerNetworkError(BrokerError):
    """Connection/DNS/TLS. Retryable."""
    retryable = True


class BrokerTimeoutError(BrokerError):
    """Broker didn't respond in time. Retryable but caller must reconcile."""
    retryable = True


class BrokerUnexpectedError(BrokerError):
    """Anything we didn't classify. Not retryable; surface to ops."""
    retryable = False


# --- Circuit breaker --------------------------------------------------------

@dataclass
class CircuitState:
    failures: list[float] = field(default_factory=list)
    open_until: float = 0.0


_breakers: dict[tuple[str, str], CircuitState] = {}

FAILURE_THRESHOLD = 3
FAILURE_WINDOW = 30.0
OPEN_DURATION = 60.0


def circuit_open(user_id: str, broker: str) -> bool:
    state = _breakers.get((user_id, broker))
    return bool(state and state.open_until > time.monotonic())


def _record_failure(user_id: str, broker: str) -> None:
    key = (user_id, broker)
    state = _breakers.setdefault(key, CircuitState())
    now = time.monotonic()
    state.failures = [t for t in state.failures if now - t < FAILURE_WINDOW]
    state.failures.append(now)
    if len(state.failures) >= FAILURE_THRESHOLD:
        state.open_until = now + OPEN_DURATION
        state.failures = []
        logger.warning("Circuit OPEN for user=%s broker=%s for %ss", user_id, broker, OPEN_DURATION)


def _record_success(user_id: str, broker: str) -> None:
    state = _breakers.get((user_id, broker))
    if state:
        state.failures = []
        state.open_until = 0.0


async def call_with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    user_id: str,
    broker: str,
    max_attempts: int = 3,
    base_delay: float = 0.3,
) -> T:
    """Execute `fn`, respecting circuit breaker + classifying & retrying errors."""
    if circuit_open(user_id, broker):
        raise BrokerUnavailable(f"Circuit OPEN for {broker}; cooling down")
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = await fn()
            _record_success(user_id, broker)
            return result
        except BrokerError as e:
            last_exc = e
            if not e.retryable or attempt == max_attempts:
                _record_failure(user_id, broker)
                raise
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, base_delay)
            logger.info("Retry %d/%d for %s in %.2fs (%s)", attempt, max_attempts, broker, delay, e)
            await asyncio.sleep(delay)
        except Exception as e:  # unexpected → classify + fail
            _record_failure(user_id, broker)
            raise BrokerUnexpectedError(str(e)) from e
    assert last_exc is not None
    raise last_exc


# --- Adapter ABC ------------------------------------------------------------

class BrokerAdapter(ABC):
    """Contract every broker adapter MUST implement.

    Concrete adapters keep their existing lazy-SDK imports inside method
    bodies so that missing SDKs raise `BrokerUnavailable` rather than break
    module imports.
    """

    name: str = "abstract"

    def __init__(self, credentials: dict, *, user_id: str = "anonymous"):
        self.credentials = credentials
        self.user_id = user_id

    # --- introspection ---
    @abstractmethod
    def capabilities(self) -> BrokerCapabilities: ...

    @abstractmethod
    async def test_connection(self) -> dict: ...

    # --- order lifecycle ---
    @abstractmethod
    async def place_order(self, req: NormalizedOrderRequest) -> NormalizedOrder: ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> NormalizedOrder: ...

    @abstractmethod
    async def modify_order(
        self, broker_order_id: str, *, qty: int | None = None, price: float | None = None
    ) -> NormalizedOrder: ...

    # --- reads (used by reconciler) ---
    @abstractmethod
    async def get_orders(self) -> list[NormalizedOrder]: ...

    @abstractmethod
    async def get_positions(self) -> list[NormalizedPosition]: ...

    # --- optional stream ---
    async def stream_order_updates(self) -> AsyncIterator[NormalizedOrderEvent]:
        """Override only if `capabilities().supports_postback_ws` is True."""
        if False:  # pragma: no cover  # makes this an async generator
            yield  # noqa
        raise BrokerUnavailable(f"{self.name} does not support push-based order updates.")
