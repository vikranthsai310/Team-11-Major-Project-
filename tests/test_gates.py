"""T-G1 … T-G5 — the two gates.

T-G5 is the permanent regression guard against the ADR-002 error, in which an
empty block was thought to permit a larger batch. **It must never be deleted.**
"""

from __future__ import annotations

import pytest

from batcher.build.estimator import (
    ORDER_MEM,
    ORDER_SIZE_B,
    ORDER_STEPS,
    block_usage_from_fill,
    gate_a,
    gate_b,
    max_n_satisfying_gate_a,
    max_n_satisfying_gate_b,
    tx_mem,
    tx_size,
    tx_steps,
)
from batcher.config.protocol import (
    MAX_BLOCK_EX_MEM,
    MAX_BLOCK_EX_STEPS,
    MAX_BLOCK_SIZE,
    MAX_TX_EX_MEM,
    MAX_TX_EX_STEPS,
    MAX_TX_SIZE,
)

LIMIT = 200


def queue_of(n: int):
    return ([ORDER_SIZE_B] * n, [ORDER_MEM] * n, [ORDER_STEPS] * n)


def test_gate_a_is_independent_of_block_state():
    """T-G1 — identical for an empty and a 90 %-full block.

    Enforced by the signature: gate_a cannot accept block state at all, so the
    ADR-002 error is not merely untested but inexpressible.
    """
    import inspect

    assert "block" not in str(inspect.signature(gate_a))
    assert gate_a(20) is gate_a(20)


def test_gate_a_binds_between_fifteen_and_fifty_orders():
    """T-G2 — with calibrated per-order costs, n_max lands in [15, 50]."""
    n_max = max_n_satisfying_gate_a(limit=LIMIT)
    assert 15 <= n_max <= 50


def test_execution_memory_binds_before_size():
    """T-G3 — with the default estimates, memory is the limiting dimension."""
    n_max = max_n_satisfying_gate_a(limit=LIMIT)
    n = n_max + 1

    assert tx_mem(n) > MAX_TX_EX_MEM, "memory should be the binding dimension"
    assert tx_size(n) <= MAX_TX_SIZE
    assert tx_steps(n) <= MAX_TX_EX_STEPS


def test_gate_b_tightens_as_the_block_fills():
    """T-G4 — a fuller block admits no more than an emptier one."""
    empty = max_n_satisfying_gate_b(*block_usage_from_fill(0.1), limit=LIMIT)
    full = max_n_satisfying_gate_b(*block_usage_from_fill(0.9), limit=LIMIT)
    assert full <= empty


@pytest.mark.parametrize("fill", [0.0, 0.1, 0.5])
def test_an_empty_block_does_not_raise_the_gate_a_cap(fill):
    """T-G5 — the ADR-002 regression guard. Never delete this test.

    The original design sized batches as ``(1 - fill_hat) * 90,112``, which on an
    idle chain proposes a transaction five times the legal per-transaction size.
    The effective cap is min(Gate A, Gate B) and Gate A does not move.
    """
    gate_a_max = max_n_satisfying_gate_a(limit=LIMIT)
    gate_b_max = max_n_satisfying_gate_b(*block_usage_from_fill(fill), limit=LIMIT)
    effective = min(gate_a_max, gate_b_max)

    assert effective == gate_a_max
    assert gate_a(effective)


def test_the_discredited_block_limit_formula_would_produce_invalid_transactions():
    """Demonstrates *why* T-G5 exists, using the formula from deck slide 13."""
    proposed_bytes = (1 - 0.0) * MAX_BLOCK_SIZE
    n_from_block_limits = int(proposed_bytes // ORDER_SIZE_B)

    assert n_from_block_limits > max_n_satisfying_gate_a(limit=LIMIT)
    assert not gate_a(n_from_block_limits)


def test_gate_a_rejects_one_order_past_the_cap():
    n_max = max_n_satisfying_gate_a(limit=LIMIT)
    assert gate_a(n_max)
    assert not gate_a(n_max + 1)


def test_gate_b_rejects_when_the_block_is_nearly_full():
    assert not gate_b(30, MAX_BLOCK_SIZE - 100, 0, 0)
    assert not gate_b(30, 0, MAX_BLOCK_EX_MEM - 100, 0)
    assert not gate_b(30, 0, 0, MAX_BLOCK_EX_STEPS - 100)


def test_gate_b_accepts_a_batch_into_an_empty_block():
    assert gate_b(max_n_satisfying_gate_a(limit=LIMIT), 0, 0, 0)


def test_gates_respect_explicit_per_order_dimensions():
    sizes, mems, steps = queue_of(40)
    assert max_n_satisfying_gate_a(sizes, mems, steps) == max_n_satisfying_gate_a(limit=40)


def test_max_n_is_bounded_by_the_queue():
    sizes, mems, steps = queue_of(3)
    assert max_n_satisfying_gate_a(sizes, mems, steps) == 3


def test_fill_conversion_is_clipped():
    assert block_usage_from_fill(-1.0) == (0, 0, 0)
    assert block_usage_from_fill(2.0) == (MAX_BLOCK_SIZE, MAX_BLOCK_EX_MEM, MAX_BLOCK_EX_STEPS)


def test_max_n_requires_a_bound():
    with pytest.raises(ValueError):
        max_n_satisfying_gate_a()
    with pytest.raises(ValueError):
        max_n_satisfying_gate_b(0, 0, 0)
