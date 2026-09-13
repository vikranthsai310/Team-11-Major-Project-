"""Mempool and the pool lock — the mechanism the project exists to manage.

A submitted transaction **stays in the mempool** and is retried against each
subsequent block. It is never rejected for being late. It leaves only by
inclusion, by TTL expiry, or by mempool eviction (ADR-004).

The earlier design had a batch "bouncing" off a full block, which does not
describe Cardano. There is deliberately no bounce state anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from batcher.build.estimator import fee_lovelace, tx_mem, tx_size, tx_steps
from batcher.queue.manager import Order


class Resolution(str, Enum):
    """How an in-flight batch left the mempool. Note what is absent: rejection."""

    INCLUDED = "included"
    EXPIRED = "expired"
    ROLLED_BACK = "rolled_back"


@dataclass
class InFlight:
    orders: list[Order]
    submit_slot: int
    ttl_slot: int
    size: int
    mem: int
    steps: int
    fee: int
    blocks_waited: int = field(default=0)

    @property
    def n(self) -> int:
        return len(self.orders)


def build_in_flight(orders: list[Order], slot: int, ttl_slots: int) -> InFlight:
    sizes = [order.size_bytes for order in orders]
    mems = [order.mem_exunits for order in orders]
    steps = [order.step_exunits for order in orders]
    n = len(orders)

    size = tx_size(n, sizes)
    mem = tx_mem(n, mems)
    step = tx_steps(n, steps)

    return InFlight(
        orders=list(orders),
        submit_slot=slot,
        ttl_slot=slot + ttl_slots,
        size=size,
        mem=mem,
        steps=step,
        fee=fee_lovelace(size, mem, step),
    )


class ConstantProductPool:
    """``x * y = k``. Slippage is endogenous — it measures the mechanism, not
    real-world price risk (assumption A7)."""

    def __init__(self, reserve_a: int = 10_000_000_000_000, reserve_b: int = 10_000_000_000_000):
        self.reserve_a = reserve_a
        self.reserve_b = reserve_b

    @property
    def price(self) -> float:
        return self.reserve_b / self.reserve_a

    def execute(self, amount_in: int, fee_bps: int = 30) -> int:
        """Swap ``amount_in`` of A for B, returning the amount out."""
        effective_in = amount_in * (10_000 - fee_bps) // 10_000
        out = self.reserve_b * effective_in // (self.reserve_a + effective_in)
        self.reserve_a += amount_in
        self.reserve_b -= out
        return out
