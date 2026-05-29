"""Paper adapter — wraps the existing paper engine into the BrokerAdapter ABC.

Reuses `routers.paper.place_paper_order` so behavior is identical to direct
HTTP calls; reconciliation_state is always NOT_APPLICABLE since the paper
broker IS the source of truth.
"""
from __future__ import annotations

from db import get_db
from market_data import get_last_price, get_options_chain

from .base import BrokerAdapter, BrokerOrderRejected
from .schemas import (
    BrokerCapabilities,
    NormalizedOrder,
    NormalizedOrderRequest,
    NormalizedPosition,
    OrderStatus,
    ReconciliationState,
)


class PaperAdapter(BrokerAdapter):
    name = "paper"

    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            supports_modify=False,
            supports_amo=False,
            supports_iceberg=False,
            supports_basket_native=False,
            supports_postback_ws=False,
            supports_options=True,
            supports_options_multi_leg=True,
        )

    async def test_connection(self) -> dict:
        return {"ok": True, "user_id": self.user_id, "name": "Paper Broker"}

    async def place_order(self, req: NormalizedOrderRequest) -> NormalizedOrder:
        # Defer to existing paper logic to avoid duplicating the engine.
        from services.paper_trading import PaperOrderRequest, place_paper_order

        single = PaperOrderRequest(
            symbol=req.symbol,
            side=req.side,
            qty=req.qty,
            order_type=req.order_type if req.order_type in ("MARKET", "LIMIT") else "MARKET",
            instrument_type=req.instrument_type if req.instrument_type in ("EQ", "OPT") else "EQ",
            option_strike=req.option_strike,
            option_kind=req.option_kind,
            price=req.price,
        )
        order = await place_paper_order(single, {"id": self.user_id}, do_check_duplicate=False)
        return NormalizedOrder(
            id=order["id"],
            user_id=self.user_id,
            broker="paper",
            broker_order_id=order["id"],
            symbol=order["symbol"],
            instrument_type=order["instrument_type"],
            option_strike=order.get("option_strike"),
            option_kind=order.get("option_kind"),
            side=order["side"],
            qty=order["qty"],
            filled_qty=order["qty"],
            pending_qty=0,
            price=order["price"],
            avg_fill_price=order["price"],
            order_type="MARKET",
            status=OrderStatus.FILLED,
            reconciliation_state=ReconciliationState.NOT_APPLICABLE,
            placed_at=order["created_at"],
            updated_at=order["created_at"],
            idempotency_key=req.idempotency_key,
            tag=req.tag,
            raw=order,
        )

    async def cancel_order(self, broker_order_id: str) -> NormalizedOrder:
        raise BrokerOrderRejected("Paper orders fill instantly; nothing to cancel.")

    async def modify_order(
        self, broker_order_id: str, *, qty: int | None = None, price: float | None = None
    ) -> NormalizedOrder:
        raise BrokerOrderRejected("Paper orders are immutable post-fill.")

    async def get_orders(self) -> list[NormalizedOrder]:
        db = get_db()
        docs = await db.paper_orders.find({"user_id": self.user_id}).sort("created_at", -1).to_list(200)
        return [
            NormalizedOrder(
                id=str(d["_id"]),
                user_id=self.user_id,
                broker="paper",
                broker_order_id=str(d["_id"]),
                symbol=d["symbol"],
                instrument_type=d.get("instrument_type", "EQ"),
                option_strike=d.get("option_strike"),
                option_kind=d.get("option_kind"),
                side=d["side"],
                qty=d["qty"],
                filled_qty=d["qty"],
                price=d.get("price"),
                avg_fill_price=d.get("price"),
                status=OrderStatus.FILLED,
                reconciliation_state=ReconciliationState.NOT_APPLICABLE,
                placed_at=d["created_at"],
                updated_at=d["created_at"],
                basket_id=d.get("basket_id"),
                raw=d,
            )
            for d in docs
        ]

    async def get_positions(self) -> list[NormalizedPosition]:
        db = get_db()
        docs = await db.paper_positions.find({"user_id": self.user_id}).to_list(200)
        out: list[NormalizedPosition] = []
        for d in docs:
            if d["instrument_type"] == "OPT":
                chain = get_options_chain(d["symbol"])
                row = next((r for r in chain["rows"] if r["strike"] == d["option_strike"]), None)
                ltp = row[d["option_kind"].lower()]["price"] if row else d["avg_price"]
            else:
                ltp = get_last_price(d["symbol"])
            out.append(NormalizedPosition(
                user_id=self.user_id,
                broker="paper",
                symbol=d["symbol"],
                instrument_type=d["instrument_type"],
                option_strike=d.get("option_strike"),
                option_kind=d.get("option_kind"),
                qty=d["qty"],
                avg_price=d["avg_price"],
                last_price=round(ltp, 2),
                pnl=round((ltp - d["avg_price"]) * d["qty"], 2),
                reconciliation_state=ReconciliationState.NOT_APPLICABLE,
            ))
        return out
