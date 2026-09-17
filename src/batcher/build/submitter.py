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

Clearing is a uniform-price batch auction by default. Every order selling the
same asset in a batch gets the same price, opposing orders trade with each other
first, and only the net imbalance meets the pool, so neither queue position nor
the batcher's choice of order can move one user's price at another's expense.
``clearing="sequential"`` keeps the original FIFO execution for comparison.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction

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

SEQUENTIAL = "sequential"  # FIFO: each order moves the reserves the next one sees
UNIFORM = "uniform"  # batch auction: one price per direction, opposing flow netted
CLEARINGS = (SEQUENTIAL, UNIFORM)


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
    clearing: str = UNIFORM,
) -> BatchPlan:
    """Plan a batch over ``orders`` against the pool's reserves.

    ``clearing`` is ``"uniform"`` (a batch auction, see ``clearing_prices``) or
    ``"sequential"`` (FIFO, each order priced after the ones before it). Under
    uniform clearing an unfillable order is dropped one at a time, worst shortfall
    first, because removing any order changes the price everyone else gets.

    ``network_fee`` is the fee the built transaction will carry. When omitted it is
    estimated with the simulator's fee model. The live builder must not let the
    final fee fall **below** the value planned with, or users would be charged
    more than ``order.ak`` allows; a fee buffer on the builder guarantees that.
    """
    if clearing not in CLEARINGS:
        raise ValueError(f"unknown clearing {clearing!r}; expected one of {CLEARINGS}")
    execute = _execute if clearing == SEQUENTIAL else _execute_uniform
    candidates = list(orders)
    _require_gate_a(candidates)

    skipped: list[OrderUtxo] = []
    while candidates:
        fee = network_fee if network_fee is not None else estimated_network_fee(candidates)
        share = fee // len(candidates)
        payouts, unfillable, x, y = execute(candidates, pool_lovelace, pool_tokens, fee_bps, share)
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


# --- uniform clearing ----------------------------------------------------------------------------


def clearing_prices(
    sold_lovelace: int, sold_tokens: int, reserve_lovelace: int, reserve_tokens: int, fee_bps: int
) -> tuple[tuple[int, int], tuple[int, int]]:
    """The batch's single clearing price, as ``(AtoB, BtoA)`` integer fractions.

    ``AtoB`` is tokens paid per lovelace sold, ``BtoA`` lovelace paid per token
    sold; each is the other's reciprocal. With ``a`` lovelace and ``b`` tokens
    sold, reserves ``x, y`` and ``g = 1 - fee``, the pool supplies only the
    imbalance, at the same price ``P`` (tokens per lovelace) everyone gets::

        P·dA = quote(x, y, dA),  dA = a - b/P   =>   P = g(y + b) / (x + g·a)

    valid while lovelace is in excess (``g·a·y > b·x``); the mirror image holds
    for excess tokens (``g·b·x > a·y``). Between the two the flows cancel inside
    the fee band and clear against each other at ``P = b / a``, pool untouched.
    A lone order gets exactly ``quote``.
    """
    g = BPS - fee_bps
    a, b, x, y = sold_lovelace, sold_tokens, reserve_lovelace, reserve_tokens
    if g * a * y > BPS * b * x:
        num, den = g * (y + b), x * BPS + g * a
        return (num, den), (den, num)
    if g * b * x > BPS * a * y:
        num, den = g * (x + a), y * BPS + g * b
        return (den, num), (num, den)
    return (b, a), (a, b)


def uniform_fills(
    orders: Sequence[OrderUtxo], reserve_lovelace: int, reserve_tokens: int, fee_bps: int
) -> tuple[list[int], int, int]:
    """What each order receives under uniform clearing, and the pool afterwards.

    Each fill is floored on its own, so a side is never paid more than it is owed
    in total; the rounding dust stays in the pool, which only strengthens
    ``pool.ak``'s invariant.
    """
    sold = {A_TO_B: 0, B_TO_A: 0}
    for order in orders:
        if order.direction not in sold:
            raise ValueError(f"unknown direction {order.direction!r}")
        sold[order.direction] += order.amount_in
    to_tokens, to_lovelace = clearing_prices(
        sold[A_TO_B], sold[B_TO_A], reserve_lovelace, reserve_tokens, fee_bps
    )
    prices = {A_TO_B: to_tokens, B_TO_A: to_lovelace}

    fills, paid = [], {A_TO_B: 0, B_TO_A: 0}
    for order in orders:
        num, den = prices[order.direction]
        received = order.amount_in * num // den if order.amount_in > 0 else 0
        fills.append(received)
        paid[order.direction] += received
    pool_lovelace = reserve_lovelace + sold[A_TO_B] - paid[B_TO_A]
    pool_tokens = reserve_tokens + sold[B_TO_A] - paid[A_TO_B]
    return fills, pool_lovelace, pool_tokens


def effective_prices(
    orders: Sequence[OrderUtxo],
    reserve_lovelace: int,
    reserve_tokens: int,
    fee_bps: int,
    clearing: str = UNIFORM,
) -> list[Fraction]:
    """Per-order execution price, ``received / amount_in``, in input order.

    Units follow the direction: tokens per lovelace for ``AtoB``, lovelace per
    token for ``BtoA``. Fee shares, margins and ``min_out`` are ignored, so the
    number isolates what the clearing rule does to each user's price.
    """
    if clearing == UNIFORM:
        fills, _, _ = uniform_fills(orders, reserve_lovelace, reserve_tokens, fee_bps)
    elif clearing == SEQUENTIAL:
        fills, x, y = [], reserve_lovelace, reserve_tokens
        for order in orders:
            if order.direction == A_TO_B:
                received = quote(x, y, order.amount_in, fee_bps)
                x, y = x + order.amount_in, y - received
            elif order.direction == B_TO_A:
                received = quote(y, x, order.amount_in, fee_bps)
                x, y = x - received, y + order.amount_in
            else:
                raise ValueError(f"unknown direction {order.direction!r}")
            fills.append(received)
    else:
        raise ValueError(f"unknown clearing {clearing!r}; expected one of {CLEARINGS}")
    return [
        Fraction(received, order.amount_in) if order.amount_in > 0 else Fraction(0)
        for order, received in zip(orders, fills, strict=True)
    ]


def _execute_uniform(orders, x, y, fee_bps, share):
    fills, x_new, y_new = uniform_fills(orders, x, y, fee_bps)
    if not pool_invariant_holds(x, y, x_new, y_new, fee_bps):
        raise AssertionError("uniform clearing broke the pool invariant; this is a defect")

    payouts, shortfalls = [], []
    for order, received in zip(orders, fills, strict=True):
        charge = share + order.margin
        if order.direction == A_TO_B:
            payout = Payout(order, order.lovelace - order.amount_in - charge, received, received)
        else:
            payout = Payout(order, order.lovelace + received - charge, 0, received)
        slippage = Fraction(order.min_out - received, order.min_out) if order.min_out > 0 else 0
        min_ada = Fraction(PAYOUT_MIN_LOVELACE - payout.lovelace, PAYOUT_MIN_LOVELACE)
        shortfall = max(slippage, min_ada)
        if shortfall > 0:
            shortfalls.append((-shortfall, order.tx_hash, order.index, order))
        payouts.append(payout)

    if shortfalls:
        # Every fill depends on the whole batch, so drop only the worst and re-solve.
        # The key ignores queue position, so the outcome does too.
        worst = min(shortfalls, key=lambda s: s[:3])[3]
        return [], [worst], x, y
    return payouts, [], x_new, y_new
