"""M3 · Order queue manager.

Strict FIFO, and selection is always the prefix ``Q[0:n]`` — never a chosen
subset. That is a deliberate fairness property, not an implementation
convenience: the policy chooses *how many* orders to include and never *which*,
which removes order-selection MEV from the design space entirely
(``docs/04-MODULE-SPECS.md`` M3).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from batcher.policy.base import OrderId


@dataclass(frozen=True)
class Order:
    order_id: OrderId
    arrival_slot: int
    size_bytes: int
    mem_exunits: int
    step_exunits: int
    amount_in: int
    min_out: int
    ttl_slot: int


class OrderQueue:
    """Pending orders, oldest first.

    **Unbounded by design.** An order is a UTXO sitting at the DEX script address;
    the batcher discovers it, it does not admit it. There is no mechanism by which
    a batcher could refuse one, so a capacity limit here would model something
    that cannot happen — and would silently drop orders out of the conservation
    law that proves nothing is lost. ``QUEUE_CAP`` exists only to normalise queue
    depth in the RL state vector.
    """

    def __init__(self):
        self._orders: deque[Order] = deque()
        self.admitted = 0
        self.expired: list[Order] = []

    def __len__(self) -> int:
        return len(self._orders)

    @property
    def orders(self) -> tuple[Order, ...]:
        return tuple(self._orders)

    def admit(self, orders) -> int:
        accepted = 0
        for order in orders:
            self._orders.append(order)
            self.admitted += 1
            accepted += 1
        return accepted

    def evict_expired(self, slot: int) -> list[Order]:
        """Drop orders past their TTL. They are counted, never silently lost."""
        kept: deque[Order] = deque()
        evicted = []
        for order in self._orders:
            if order.ttl_slot < slot:
                evicted.append(order)
            else:
                kept.append(order)
        self._orders = kept
        self.expired.extend(evicted)
        return evicted

    def take(self, n: int) -> list[Order]:
        """Remove and return the ``n`` oldest orders."""
        n = min(n, len(self._orders))
        return [self._orders.popleft() for _ in range(n)]

    def give_back(self, orders) -> None:
        """Reinsert at the front, preserving original order and age.

        An order returned after a batch expired has *not* just arrived. Resetting
        its age here would hide exactly the starvation the deadline exists to
        prevent, and would make the fairness metric flatter than reality.
        """
        for order in reversed(list(orders)):
            self._orders.appendleft(order)

    def oldest_wait(self, slot: int) -> int:
        if not self._orders:
            return 0
        return slot - min(order.arrival_slot for order in self._orders)

    def waits(self, slot: int) -> list[int]:
        return [slot - order.arrival_slot for order in self._orders]

    def dimensions(self) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
        """Per-order (sizes, memory, steps) in FIFO order."""
        return (
            tuple(order.size_bytes for order in self._orders),
            tuple(order.mem_exunits for order in self._orders),
            tuple(order.step_exunits for order in self._orders),
        )
