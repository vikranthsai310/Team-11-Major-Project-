"""T-F1 … T-F5 — the fee model and the amortization finding it encodes.

Built during Phase 1 because figure F3 is analytic and needs it; the Gate A and
Gate B tests that complete P2-3 arrive with the simulator.
"""

from __future__ import annotations

import inspect
from itertools import pairwise

import pytest

from batcher.build import estimator
from batcher.build.estimator import (
    ORDER_MEM,
    ORDER_SIZE_B,
    ORDER_STEPS,
    POOL_TX_OVERHEAD_B,
    POOL_VALIDATOR_MEM,
    POOL_VALIDATOR_STEPS,
    batch_fee_lovelace,
    cost_per_user_ada,
    cost_per_user_lovelace,
    fee_lovelace,
    flat_component_lovelace,
    marginal_component_lovelace,
    tx_mem,
    tx_size,
    tx_steps,
)
from batcher.config.protocol import MIN_FEE_A, MIN_FEE_B, PRICE_MEM, PRICE_STEPS


def test_empty_transaction_costs_the_flat_component():
    """T-F1 — a zero-size, zero-execution transaction costs exactly MIN_FEE_B."""
    assert fee_lovelace(0, 0, 0) == MIN_FEE_B


def test_fee_matches_a_hand_computed_value_to_the_lovelace():
    """T-F2 — 44*2000 + 155381 + 0.0577*1e6 + 0.0000721*5e8."""
    expected = int(44 * 2_000 + 155_381 + 0.0577 * 1_000_000 + 0.0000721 * 500_000_000)
    assert fee_lovelace(2_000, 1_000_000, 500_000_000) == expected
    assert expected == 88_000 + 155_381 + 57_700 + 36_050


def test_fee_is_strictly_increasing_in_every_dimension():
    """T-F3, first half — monotone in size, memory and steps."""
    base = fee_lovelace(1_000, 1_000_000, 100_000_000)
    assert fee_lovelace(1_001, 1_000_000, 100_000_000) > base
    assert fee_lovelace(1_000, 1_100_000, 100_000_000) > base
    assert fee_lovelace(1_000, 1_000_000, 110_000_000) > base


def test_the_fee_function_cannot_see_congestion():
    """T-F3 — the ADR-001 guard, enforced at the signature.

    Cardano fees are demand-independent. If ``fee_lovelace`` ever grows a block,
    fill or congestion parameter, the project has silently readopted the
    Ethereum-shaped premise that ADR-001 overturned.
    """
    parameters = set(inspect.signature(fee_lovelace).parameters)
    assert parameters == {"size", "mem", "steps"}

    # Gate B is *supposed* to depend on congestion — that is the entire
    # distinction ADR-002 draws between the two gates. The guard therefore covers
    # everything in the module except the Gate B family, so a newly added fee or
    # sizing function is policed automatically.
    congestion_dependent = {"gate_b", "max_n_satisfying_gate_b", "block_usage_from_fill"}
    forbidden = {"block", "blk", "fill", "fill_hat", "congestion", "headroom", "slot"}

    for name, function in vars(estimator).items():
        if not callable(function) or name.startswith("_") or name in congestion_dependent:
            continue
        if getattr(function, "__module__", None) != estimator.__name__:
            continue
        assert not (set(inspect.signature(function).parameters) & forbidden), (
            f"{name} accepts congestion state; fees and Gate A do not depend on it"
        )


def test_per_user_cost_decreases_with_batch_size():
    """T-F4 — amortization is real: a bigger batch is cheaper per user."""
    costs = [cost_per_user_lovelace(n) for n in range(1, 41)]
    assert all(later < earlier for earlier, later in pairwise(costs))


def test_amortization_flattens_quickly():
    """T-F5 — encodes the docs/07 §5 finding that latency, not cost, dominates.

    Most of the saving is realised by n ~ 10; going on to 30 buys little. That is
    why there is no economic reason to hoard orders, and why the objective is
    confirmation latency.
    """
    early_gain = cost_per_user_lovelace(1) - cost_per_user_lovelace(10)
    late_gain = cost_per_user_lovelace(10) - cost_per_user_lovelace(30)
    assert late_gain < early_gain
    assert late_gain < 0.35 * early_gain


def test_only_the_flat_component_amortizes():
    """Per-user cost approaches the marginal cost and never falls below it."""
    marginal = marginal_component_lovelace()
    assert cost_per_user_lovelace(1_000) > marginal
    assert cost_per_user_lovelace(1_000) == pytest.approx(marginal, rel=0.02)


def test_fee_decomposes_into_flat_plus_linear():
    for n in (1, 5, 17, 40):
        expected = flat_component_lovelace() + n * marginal_component_lovelace()
        assert batch_fee_lovelace(n) == pytest.approx(expected, abs=2)


def test_flat_and_marginal_components_are_built_from_the_protocol_constants():
    assert flat_component_lovelace() == int(
        MIN_FEE_A * POOL_TX_OVERHEAD_B
        + MIN_FEE_B
        + PRICE_MEM * POOL_VALIDATOR_MEM
        + PRICE_STEPS * POOL_VALIDATOR_STEPS
    )
    assert marginal_component_lovelace() == int(
        MIN_FEE_A * ORDER_SIZE_B + PRICE_MEM * ORDER_MEM + PRICE_STEPS * ORDER_STEPS
    )


def test_transaction_dimensions_include_the_fixed_pool_cost():
    assert tx_size(0) == POOL_TX_OVERHEAD_B
    assert tx_mem(0) == POOL_VALIDATOR_MEM
    assert tx_steps(0) == POOL_VALIDATOR_STEPS
    assert tx_size(10) == POOL_TX_OVERHEAD_B + 10 * ORDER_SIZE_B


def test_explicit_per_order_costs_override_the_defaults():
    sizes = [100, 200, 300, 400]
    assert tx_size(3, sizes) == POOL_TX_OVERHEAD_B + 600
    assert tx_size(4, sizes) == POOL_TX_OVERHEAD_B + 1000


def test_empty_batch_has_no_per_user_cost():
    with pytest.raises(ValueError):
        cost_per_user_lovelace(0)


def test_ada_conversion():
    assert cost_per_user_ada(10) == pytest.approx(cost_per_user_lovelace(10) / 1_000_000)
