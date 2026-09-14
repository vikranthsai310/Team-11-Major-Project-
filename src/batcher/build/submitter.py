"""M5 · Submitter — the impure half, starting from its pure core (P7-7).

A live batch is planned here before anything touches the chain: which queued
orders can actually be executed, what each user must be paid, and what the pool
looks like afterwards. Planning is pure, so every rule the validators enforce is
checked in unit tests first, and a batch that would fail on preprod is caught on
the laptop instead.

Three properties matter:

* **Gate A is re-checked and raises.** The policy already clamps ``n``; a
  violation reaching this point is a defect, so it is never silently truncated.
* **Same estimator as the simulator (T-N6).** ``gate_a`` and ``fee_lovelace`` are
  imported from ``build.estimator``, not re-implemented, so a number in the
  report and a live transaction come from identical code.
* **Users are paid what ``order.ak`` requires, and no less.** Each order is
  charged ``fee // n + margin`` (ADR-006), with ``n`` the orders actually
  executed. An order the pool cannot fill at its ``min_out`` is left out, and the
  fee share is recomputed for the smaller batch.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from batcher.build.estimator import (
    ORDER_MEM,
    ORDER_SIZE_B,
    ORDER_STEPS,
    fee_lovelace,
    gate_a,
    tx_mem,
    tx_size,
    tx_steps,
)

BPS = 10_000

# Planning floor for a payout's lovelace. The live builder enforces the exact
# min-ADA for the final output; planning conservatively keeps an order out rather
# than discovering an unfundable payout after the transaction is built.
PAYOUT_MIN_LOVELACE = 2_000_000

A_TO_B = "AtoB"  # sell lovelace for the pool token
B_TO_A = "BtoA"  # sell the pool token for lovelace


class GateAViolation(RuntimeError):
    """A batch that exceeds per-transaction limits reached the submitter."""


@dataclass(frozen=True)
class OrderUtxo:
    """One order at the order script, as read from the chain."""

    tx_hash: str
    index: int
    lovelace: int
    direction: str
    amount_in: int
    min_out: int
    margin: int
    return_address: str
    size_bytes: int = ORDER_SIZE_B
    mem_exunits: int = ORDER_MEM
    step_exunits: int = ORDER_STEPS


@dataclass(frozen=True)
class Payout:
    order: OrderUtxo
    lovelace: int
    tokens: int
    received: int


@dataclass(frozen=True)
class BatchPlan:
    payouts: tuple[Payout, ...]
    skipped: tuple[OrderUtxo, ...]
    network_fee: int
    pool_lovelace: int
    pool_tokens: int

    @property
    def n(self) -> int:
        return len(self.payouts)


def quote(reserve_in: int, reserve_out: int, amount_in: int, fee_bps: int) -> int:
    """Constant-product output for ``amount_in``, fee taken on the input, floored."""
    if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
        return 0
    effective = amount_in * (BPS - fee_bps)
    return (reserve_out * effective) // (reserve_in * BPS + effective)


def pool_invariant_holds(x: int, y: int, x_new: int, y_new: int, fee_bps: int) -> bool:
    """``pool.ak``'s ``invariant_holds``, line for line (T-O4)."""
    inflow_x = max(x_new - x, 0)
    inflow_y = max(y_new - y, 0)
    adjusted_x = x_new * BPS - inflow_x * fee_bps
    adjusted_y = y_new * BPS - inflow_y * fee_bps
    return adjusted_x * adjusted_y >= x * y * BPS * BPS


def estimated_network_fee(orders: Sequence[OrderUtxo]) -> int:
    n = len(orders)
    return fee_lovelace(
        tx_size(n, [o.size_bytes for o in orders]),
        tx_mem(n, [o.mem_exunits for o in orders]),
        tx_steps(n, [o.step_exunits for o in orders]),
    )


def plan_batch(
    orders: Iterable[OrderUtxo],
    pool_lovelace: int,
    pool_tokens: int,
    fee_bps: int,
    network_fee: int | None = None,
) -> BatchPlan:
    """Plan a batch over ``orders`` in FIFO order against the pool's reserves.

    ``network_fee`` is the fee the built transaction will carry. When omitted it is
    estimated with the simulator's fee model. The live builder must not let the
    final fee fall **below** the value planned with, or users would be charged
    more than ``order.ak`` allows; a fee buffer on the builder guarantees that.
    """
    candidates = list(orders)
    _require_gate_a(candidates)

    skipped: list[OrderUtxo] = []
    while candidates:
        fee = network_fee if network_fee is not None else estimated_network_fee(candidates)
        share = fee // len(candidates)
        payouts, unfillable, x, y = _execute(candidates, pool_lovelace, pool_tokens, fee_bps, share)
        if not unfillable:
            return BatchPlan(tuple(payouts), tuple(skipped), fee, x, y)
        # Dropping an order raises everyone else's fee share, so replan from scratch.
        skipped += unfillable
        candidates = [o for o in candidates if o not in unfillable]

    return BatchPlan((), tuple(skipped), 0, pool_lovelace, pool_tokens)


def _require_gate_a(orders: Sequence[OrderUtxo]) -> None:
    n = len(orders)
    if n and not gate_a(
        n,
        [o.size_bytes for o in orders],
        [o.mem_exunits for o in orders],
        [o.step_exunits for o in orders],
    ):
        raise GateAViolation(
            f"a batch of {n} orders exceeds per-transaction limits; the policy must "
            "clamp n before the submitter is reached"
        )


def _execute(orders, x, y, fee_bps, share):
    payouts, unfillable = [], []
    for order in orders:
        charge = share + order.margin
        if order.direction == A_TO_B:
            received = quote(x, y, order.amount_in, fee_bps)
            lovelace = order.lovelace - order.amount_in - charge
            tokens = received
        elif order.direction == B_TO_A:
            received = quote(y, x, order.amount_in, fee_bps)
            lovelace = order.lovelace + received - charge
            tokens = 0
        else:
            raise ValueError(f"unknown direction {order.direction!r}")

        if received < order.min_out or lovelace < PAYOUT_MIN_LOVELACE:
            unfillable.append(order)
            continue

        if order.direction == A_TO_B:
            x, y = x + order.amount_in, y - received
        else:
            x, y = x - received, y + order.amount_in
        payouts.append(Payout(order, lovelace, tokens, received))
    return payouts, unfillable, x, y
