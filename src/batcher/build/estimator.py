"""Transaction size, execution unit and fee estimation — the pure half of M5.

Used identically by the simulator and by live submission (T-N6), so a number
that appears in the report was produced by the same code that would build a real
transaction.

``fee_lovelace`` deliberately takes **no block or congestion argument**. Cardano
fees are demand-independent; a signature that admitted congestion would make the
ADR-001 error expressible, so the type system forbids it (T-F3).
"""

from __future__ import annotations

from collections.abc import Sequence

from batcher.config.protocol import (
    MAX_BLOCK_EX_MEM,
    MAX_BLOCK_EX_STEPS,
    MAX_BLOCK_SIZE,
    MAX_TX_EX_MEM,
    MAX_TX_EX_STEPS,
    MAX_TX_SIZE,
    MIN_FEE_A,
    MIN_FEE_B,
    PRICE_MEM,
    PRICE_STEPS,
)

# --- Per-order marginal costs (docs/07-CONSTRAINTS-COST-MODEL.md §4) ---
# Input reference ~40 B + redeemer ~60 B + user output ~150 B.
ORDER_SIZE_B = 300  # ESTIMATE — recalibrate in P7-9
ORDER_MEM = 500_000  # ESTIMATE — recalibrate in P7-9
ORDER_STEPS = 200_000_000  # ESTIMATE — recalibrate in P7-9

# --- Fixed cost of the batch transaction itself, paid regardless of n ---
POOL_TX_OVERHEAD_B = 500  # ESTIMATE — recalibrate in P7-9
POOL_VALIDATOR_MEM = 2_000_000  # ESTIMATE — recalibrate in P7-9
POOL_VALIDATOR_STEPS = 800_000_000  # ESTIMATE — recalibrate in P7-9

LOVELACE_PER_ADA = 1_000_000


def tx_size(n: int, sizes: Sequence[int] | None = None) -> int:
    """Serialized bytes of a batch of ``n`` orders."""
    return POOL_TX_OVERHEAD_B + _sum_or_default(n, sizes, ORDER_SIZE_B)


def tx_mem(n: int, mems: Sequence[int] | None = None) -> int:
    return POOL_VALIDATOR_MEM + _sum_or_default(n, mems, ORDER_MEM)


def tx_steps(n: int, steps: Sequence[int] | None = None) -> int:
    return POOL_VALIDATOR_STEPS + _sum_or_default(n, steps, ORDER_STEPS)


def _sum_or_default(n: int, values: Sequence[int] | None, default: int) -> int:
    if values is None:
        return n * default
    return sum(values[:n])


def fee_lovelace(size: int, mem: int, steps: int) -> int:
    """The Cardano fee formula (docs/07 §5). Deterministic; no congestion term."""
    return int(MIN_FEE_A * size + MIN_FEE_B + PRICE_MEM * mem + PRICE_STEPS * steps)


def batch_fee_lovelace(n: int) -> int:
    """Total fee for a batch of ``n`` orders, using the default cost estimates."""
    return fee_lovelace(tx_size(n), tx_mem(n), tx_steps(n))


def flat_component_lovelace() -> int:
    """The part of the fee that does not scale with ``n`` — the only part that amortizes."""
    return fee_lovelace(POOL_TX_OVERHEAD_B, POOL_VALIDATOR_MEM, POOL_VALIDATOR_STEPS)


def marginal_component_lovelace() -> int:
    """The per-order cost. It never amortizes: every order runs the order validator."""
    return int(MIN_FEE_A * ORDER_SIZE_B + PRICE_MEM * ORDER_MEM + PRICE_STEPS * ORDER_STEPS)


def cost_per_user_lovelace(n: int) -> float:
    """``FLAT / n + MARGINAL`` — the amortization curve of docs/07 §5."""
    if n < 1:
        raise ValueError("batch size must be at least 1")
    return batch_fee_lovelace(n) / n


def cost_per_user_ada(n: int) -> float:
    return cost_per_user_lovelace(n) / LOVELACE_PER_ADA


# --- The two gates (docs/07-CONSTRAINTS-COST-MODEL.md §3) ---------------------
#
# Gate A is feasibility: a violation is an invalid transaction, on an empty chain
# or a full one. Gate B is inclusion: a violation just means waiting for a later
# block. Conflating them is the single most consequential error available in this
# design, and is what ADR-002 corrected. The two functions below therefore take
# different arguments *by construction* — gate_a cannot see a block at all.


def gate_a(
    n: int,
    sizes: Sequence[int] | None = None,
    mems: Sequence[int] | None = None,
    steps: Sequence[int] | None = None,
) -> bool:
    """Feasibility. Always binding, and independent of congestion."""
    return (
        tx_size(n, sizes) <= MAX_TX_SIZE
        and tx_mem(n, mems) <= MAX_TX_EX_MEM
        and tx_steps(n, steps) <= MAX_TX_EX_STEPS
    )


def gate_b(
    n: int,
    block_size: int,
    block_mem: int,
    block_steps: int,
    sizes: Sequence[int] | None = None,
    mems: Sequence[int] | None = None,
    steps: Sequence[int] | None = None,
) -> bool:
    """Inclusion. Congestion dependent; evaluated against a forecast or a block."""
    return (
        block_size + tx_size(n, sizes) <= MAX_BLOCK_SIZE
        and block_mem + tx_mem(n, mems) <= MAX_BLOCK_EX_MEM
        and block_steps + tx_steps(n, steps) <= MAX_BLOCK_EX_STEPS
    )


def max_n_satisfying_gate_a(
    sizes: Sequence[int] | None = None,
    mems: Sequence[int] | None = None,
    steps: Sequence[int] | None = None,
    limit: int | None = None,
) -> int:
    """Largest feasible batch size. **An empty block does not raise this** (T-G5)."""
    ceiling = len(sizes) if sizes is not None else limit
    if ceiling is None:
        raise ValueError("need per-order dimensions or an explicit limit")

    n = 0
    while n < ceiling and gate_a(n + 1, sizes, mems, steps):
        n += 1
    return n


def max_n_satisfying_gate_b(
    block_size: int,
    block_mem: int,
    block_steps: int,
    sizes: Sequence[int] | None = None,
    mems: Sequence[int] | None = None,
    steps: Sequence[int] | None = None,
    limit: int | None = None,
) -> int:
    """Largest batch that would fit into a block with the given usage."""
    ceiling = len(sizes) if sizes is not None else limit
    if ceiling is None:
        raise ValueError("need per-order dimensions or an explicit limit")

    n = 0
    while n < ceiling and gate_b(n + 1, block_size, block_mem, block_steps, sizes, mems, steps):
        n += 1
    return n


def block_usage_from_fill(fill: float) -> tuple[int, int, int]:
    """Convert a predicted fill fraction into block usage for a Gate B check.

    Execution dimensions are scaled by the same fraction. Phase 1 measured a
    size↔execution correlation of 0.912 in the congested regime, with steps never
    exceeding 49.9 % of budget, so this is conservative on the dimensions that do
    not bind (`adr/ADR-005` §Result).
    """
    fill = min(max(fill, 0.0), 1.0)
    return (
        int(fill * MAX_BLOCK_SIZE),
        int(fill * MAX_BLOCK_EX_MEM),
        int(fill * MAX_BLOCK_EX_STEPS),
    )
