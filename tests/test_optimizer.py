"""P4-1 — the constrained optimizer, branch by branch.

P2 must be deterministic given identical observations, and every branch of the
pseudocode in ``docs/06-ML-SPEC.md`` §4 is exercised here. It is the policy a
review panel will be walked through, so its behaviour is pinned rather than
assumed.
"""

from __future__ import annotations

import pytest

from batcher.build.estimator import ORDER_MEM, ORDER_SIZE_B, ORDER_STEPS, max_n_satisfying_gate_a
from batcher.config.params import D_MAX, N_MIN
from batcher.policy.base import Observation
from batcher.policy.optimizer import ConstrainedOptimizer, OracleOptimizer

GATE_A_MAX = max_n_satisfying_gate_a(limit=200)


def observation(
    depth: int = 20,
    oldest_wait: int = 0,
    fill_hat: tuple[float, ...] = (0.0, 0.0, 0.0),
    pool_locked: bool = False,
) -> Observation:
    return Observation(
        slot=1_000,
        queue_depth=depth,
        oldest_wait=oldest_wait,
        queue_sizes=tuple([ORDER_SIZE_B] * depth),
        queue_mem=tuple([ORDER_MEM] * depth),
        queue_steps=tuple([ORDER_STEPS] * depth),
        fill_hat=fill_hat,
        mem_headroom=0,
        step_headroom=0,
        pool_locked=pool_locked,
        slots_in_flight=0,
        gate_a_max_n=min(depth, GATE_A_MAX),
    )


def test_waits_while_the_pool_is_locked():
    assert not ConstrainedOptimizer().decide(observation(pool_locked=True)).submit


def test_waits_on_an_empty_queue():
    assert not ConstrainedOptimizer().decide(observation(depth=0)).submit


def test_submits_a_full_feasible_batch_into_an_empty_block():
    action = ConstrainedOptimizer().decide(observation(depth=100, fill_hat=(0.0, 0.0, 0.0)))
    assert action.submit
    assert action.n == GATE_A_MAX


def test_never_proposes_more_than_gate_a_allows():
    """S2 by construction: the proposal itself is already feasible."""
    for depth in (1, 10, 40, 200):
        action = ConstrainedOptimizer().decide(observation(depth=depth))
        assert action.n <= min(depth, GATE_A_MAX)


def test_the_deadline_overrides_every_cost_consideration():
    """Past D_MAX the policy submits regardless of fill or batch size."""
    action = ConstrainedOptimizer().decide(
        observation(depth=2, oldest_wait=D_MAX, fill_hat=(0.95, 0.1, 0.1))
    )
    assert action.submit
    assert action.n > 0


def test_a_full_block_prediction_makes_it_wait():
    """Gate B predicts no room, so submitting would only hold the pool."""
    assert not ConstrainedOptimizer().decide(observation(fill_hat=(1.0, 1.0, 1.0))).submit


def test_waits_below_n_min_when_a_quieter_block_is_coming():
    small = observation(depth=N_MIN - 1, fill_hat=(0.5, 0.1, 0.1))
    assert not ConstrainedOptimizer().decide(small).submit


def test_submits_below_n_min_when_no_quieter_block_is_coming():
    """Waiting only pays if the wait buys something; a rising forecast means it does not."""
    small = observation(depth=N_MIN - 1, fill_hat=(0.1, 0.5, 0.6))
    action = ConstrainedOptimizer().decide(small)
    assert action.submit
    assert action.n == N_MIN - 1


def test_submits_at_or_above_n_min_regardless_of_the_forecast():
    action = ConstrainedOptimizer().decide(observation(depth=N_MIN, fill_hat=(0.5, 0.1, 0.1)))
    assert action.submit


def test_gate_b_tightens_the_batch_as_the_forecast_fills():
    empty = ConstrainedOptimizer().decide(observation(depth=100, fill_hat=(0.0, 0.0, 0.0)))
    busy = ConstrainedOptimizer().decide(observation(depth=100, fill_hat=(0.93, 0.93, 0.93)))
    assert busy.n <= empty.n


def test_is_deterministic_given_identical_observations():
    policy = ConstrainedOptimizer()
    obs = observation(depth=17, oldest_wait=40, fill_hat=(0.3, 0.4, 0.2))
    assert [policy.decide(obs) for _ in range(10)].count(policy.decide(obs)) == 10


def test_no_forecast_degenerates_to_gate_a_only():
    """Missing forecast must not disable the policy — it removes only Gate B."""
    action = ConstrainedOptimizer().decide(observation(depth=100, fill_hat=()))
    assert action.submit
    assert action.n == GATE_A_MAX


def test_a_single_step_horizon_never_predicts_a_quieter_block():
    action = ConstrainedOptimizer().decide(observation(depth=N_MIN - 1, fill_hat=(0.5,)))
    assert action.submit


def test_tuned_parameters_appear_in_the_policy_name():
    """Tuned values must be disclosed in the results table; the name carries them."""
    assert "D=90" in ConstrainedOptimizer(d_max=90, n_min=4).name
    assert "N=4" in ConstrainedOptimizer(d_max=90, n_min=4).name


def test_oracle_is_the_same_policy_under_a_different_forecast():
    """A1 measures forecast error, so the decision logic must be identical."""
    assert issubclass(OracleOptimizer, ConstrainedOptimizer)
    obs = observation(depth=30, fill_hat=(0.4, 0.4, 0.4))
    assert ConstrainedOptimizer().decide(obs) == OracleOptimizer().decide(obs)
    assert OracleOptimizer().name.startswith("oracle")


@pytest.mark.parametrize("fill", [0.0, 0.25, 0.5, 0.75, 0.9, 1.0])
def test_every_proposal_is_gate_a_feasible_at_any_congestion(fill):
    """T-P1 at policy level — the ADR-002 error is not expressible here either."""
    action = ConstrainedOptimizer().decide(observation(depth=200, fill_hat=(fill, fill, fill)))
    assert action.n <= GATE_A_MAX
