"""Phase 8 — runtime shields and the opt-in mask repair.

The recorded results never pass through these wrappers; the tests pin that the
wrappers keep a policy inside Gate A, submit the full feasible batch when
submission is forced, hand unfamiliar states to the fallback, and act before the
deadline rather than after it.
"""

from __future__ import annotations

import numpy as np
import pytest

from batcher.build.estimator import (
    ORDER_MEM,
    ORDER_SIZE_B,
    ORDER_STEPS,
    gate_a,
    max_n_satisfying_gate_a,
)
from batcher.config.params import D_MAX, QUEUE_CAP
from batcher.data.collector import collect_blocks
from batcher.data.features import preprocess
from batcher.policy.base import Action, Observation
from batcher.policy.optimizer import ConstrainedOptimizer
from batcher.policy.shield import DeadlineAwarePolicy, ShieldedPolicy
from batcher.policy.static import FixedSize, Greedy, Null
from batcher.sim.gym_env import WAIT_ACTION, BatchingEnv
from batcher.sim.orders import ArrivalProcess
from conftest import BASE_HEIGHT, FakeSource, make_records

GATE_A_MAX = max_n_satisfying_gate_a(limit=400)


def observation(
    depth: int = 20,
    oldest_wait: int = 0,
    slot: int = 1_000,
    fill_hat: tuple[float, ...] = (0.0, 0.0, 0.0),
) -> Observation:
    return Observation(
        slot=slot,
        queue_depth=depth,
        oldest_wait=oldest_wait,
        queue_sizes=tuple([ORDER_SIZE_B] * depth),
        queue_mem=tuple([ORDER_MEM] * depth),
        queue_steps=tuple([ORDER_STEPS] * depth),
        fill_hat=fill_hat,
        mem_headroom=0,
        step_headroom=0,
        pool_locked=False,
        slots_in_flight=0,
        gate_a_max_n=min(depth, GATE_A_MAX),
    )


class Constant:
    """A policy that always proposes the same action, and counts its calls."""

    def __init__(self, action: Action, name: str = "constant"):
        self.action = action
        self.name = name
        self.calls = 0

    def decide(self, obs: Observation) -> Action:
        self.calls += 1
        return self.action

    def observe_outcome(self, outcome) -> None:
        return None


# --- ShieldedPolicy ------------------------------------------------------------------


@pytest.mark.parametrize("inner", [Null(), Constant(Action(submit=True, n=1))])
@pytest.mark.parametrize("depth", [1, 5, 30, 150])
def test_forced_submission_always_uses_the_gate_a_maximum(inner, depth):
    shield = ShieldedPolicy(inner, fallback=Null())
    action = shield.decide(observation(depth=depth, oldest_wait=D_MAX))
    assert action == Action(submit=True, n=min(depth, GATE_A_MAX))
    assert shield.forced_overrides == 1


def test_in_distribution_states_are_decided_by_the_inner_policy():
    inner = Constant(Action(submit=True, n=3), name="inner")
    fallback = Constant(Action(submit=False), name="fallback")
    shield = ShieldedPolicy(inner, fallback)

    assert shield.decide(observation(depth=20, oldest_wait=10)) == Action(submit=True, n=3)
    assert (inner.calls, fallback.calls) == (1, 0)
    assert shield.interventions == 0


@pytest.mark.parametrize(
    ("depth", "oldest_wait"),
    [(QUEUE_CAP + 1, 0), (20, int(0.8 * D_MAX)), (20, D_MAX - 1)],
)
def test_out_of_distribution_states_are_delegated_to_the_fallback(depth, oldest_wait):
    inner = Constant(Action(submit=False), name="inner")
    shield = ShieldedPolicy(inner, fallback=Greedy())

    action = shield.decide(observation(depth=depth, oldest_wait=oldest_wait))
    assert action == Action(submit=True, n=min(depth, GATE_A_MAX))
    assert inner.calls == 0
    assert shield.counters() == {
        "decisions": 1,
        "forced_overrides": 0,
        "ood_delegations": 1,
        "interventions": 1,
    }


def test_thresholds_are_configurable():
    shield = ShieldedPolicy(Null(), fallback=Greedy(), max_queue_depth=10, max_oldest_wait=50)
    assert shield.decide(observation(depth=11)).submit
    assert not shield.decide(observation(depth=10, oldest_wait=49)).submit
    assert shield.decide(observation(depth=10, oldest_wait=50)).submit


def test_the_shield_never_passes_on_a_gate_a_violation():
    shield = ShieldedPolicy(Constant(Action(submit=True, n=10_000)), fallback=Greedy())
    for depth in (1, 40, 300):
        action = shield.decide(observation(depth=depth, oldest_wait=0))
        assert action.n <= min(depth, GATE_A_MAX)
        assert gate_a(action.n)


def test_reset_clears_the_counters():
    shield = ShieldedPolicy(Null(), fallback=Greedy())
    shield.decide(observation(oldest_wait=D_MAX))
    shield.reset()
    assert shield.interventions == 0 and shield.decisions == 0


# --- DeadlineAwarePolicy -------------------------------------------------------------


def feed_gaps(policy, gaps, depth=0, start=0):
    """Present WAIT decisions separated by ``gaps`` slots with an empty queue."""
    slot = start
    for gap in gaps:
        slot += gap
        assert not policy.decide(observation(depth=depth, slot=slot)).submit
    return slot


def test_learns_the_gap_quantile_from_observations_only():
    policy = DeadlineAwarePolicy(Null(), include_confirmation=False, min_samples=5)
    assert policy.expected_delay() == pytest.approx(46)  # prior before any data
    gaps = [10] * 90 + [40] * 10
    feed_gaps(policy, gaps)
    # The first decision has no predecessor, so its gap is not observable.
    assert policy.expected_delay() == pytest.approx(np.quantile(gaps[1:], 0.9))


def test_submits_before_the_deadline_given_a_known_gap_distribution():
    policy = DeadlineAwarePolicy(Null(), include_confirmation=False, min_samples=5)
    slot = feed_gaps(policy, [30] * 50)
    assert policy.expected_delay() == pytest.approx(30)

    # 89 + 30 < 120: another block can be waited for.
    assert not policy.decide(observation(depth=3, oldest_wait=89, slot=slot + 30)).submit
    # 90 + 30 >= 120: waiting would likely miss D_MAX, so submit now.
    action = policy.decide(observation(depth=3, oldest_wait=90, slot=slot + 60))
    assert action == Action(submit=True, n=3)
    assert policy.deadline_submissions == 1


def test_confirmation_delay_is_learned_from_the_decision_after_a_submit():
    policy = DeadlineAwarePolicy(Greedy(), min_samples=1)
    policy.decide(observation(depth=2, slot=100))  # submits
    policy.decide(observation(depth=0, slot=160))  # resolved 60 slots later
    policy.decide(observation(depth=0, slot=180))  # a plain 20-slot gap
    assert list(policy.confirmations) == [60]
    assert list(policy.gaps) == [20]
    assert policy.expected_delay() == pytest.approx(80)


def test_sizes_to_gate_b_under_deadline_pressure():
    """A nearly full block predicted: submit what fits instead of the full batch."""
    policy = DeadlineAwarePolicy(Null(), include_confirmation=False, min_samples=1)
    feed_gaps(policy, [20] * 5)
    obs = observation(depth=40, oldest_wait=D_MAX - 10, slot=500, fill_hat=(0.9, 0.9, 0.9))

    action = policy.decide(obs)
    assert action.submit
    assert 0 < action.n < obs.gate_a_max_n
    assert policy.gate_b_sized == 1

    # No room predicted at all: the feasible maximum still goes to the mempool.
    full = observation(depth=40, oldest_wait=D_MAX - 10, slot=520, fill_hat=(1.0, 1.0, 1.0))
    assert policy.decide(full) == Action(submit=True, n=full.gate_a_max_n)


@pytest.mark.parametrize("inner", [Null(), Greedy(), FixedSize(m=16), ConstrainedOptimizer()])
def test_never_exceeds_gate_a(inner):
    policy = DeadlineAwarePolicy(inner, min_samples=1)
    rng = np.random.default_rng(3)
    slot = 0
    for _ in range(300):
        slot += int(rng.integers(1, 80))
        depth = int(rng.integers(0, 400))
        fill = float(rng.random())
        obs = observation(
            depth=depth, oldest_wait=int(rng.integers(0, 200)), slot=slot, fill_hat=(fill,) * 3
        )
        action = policy.decide(obs)
        if action.submit:
            assert 0 < action.n <= obs.gate_a_max_n
            assert gate_a(action.n)


def test_is_deterministic():
    def run():
        policy = DeadlineAwarePolicy(ConstrainedOptimizer(n_min=4))
        rng = np.random.default_rng(11)
        slot, actions = 0, []
        for _ in range(200):
            slot += int(rng.integers(1, 60))
            obs = observation(
                depth=int(rng.integers(0, 30)),
                oldest_wait=int(rng.integers(0, 130)),
                slot=slot,
                fill_hat=(float(rng.random()),) * 3,
            )
            actions.append(policy.decide(obs))
        return actions

    assert run() == run()


# --- Gym env mask repair -------------------------------------------------------------


@pytest.fixture(scope="module")
def blocks(tmp_path_factory):
    source = FakeSource(make_records(600, seed=41))
    frame = collect_blocks(
        source,
        start_height=BASE_HEIGHT,
        end_height=source.tip_height(),
        staging_dir=tmp_path_factory.mktemp("staging"),
        page_size=300,
    )
    return preprocess(frame)


def make_env(blocks, **kwargs) -> BatchingEnv:
    process = ArrivalProcess(base_per_slot=0.3, diurnal=tuple([1.0] * 24), bursts_per_day=0.0)
    return BatchingEnv(blocks, process, seed=3, **kwargs)


def forced_batches(env) -> list[tuple[int, int]]:
    """Always-WAIT rollout; (gate_a_max, submitted n) at every forced submission."""
    env.reset(seed=5)
    forced = []
    terminated = False
    while not terminated:
        forced_now = not env.action_masks()[WAIT_ACTION]
        ceiling = env._gate_a_max()
        before = len(env.submissions)
        _, _, terminated, _, _ = env.step(WAIT_ACTION)
        if forced_now:
            assert len(env.submissions) == before + 1
            forced.append((ceiling, env.submissions[-1]))
    return forced


def test_the_default_repair_is_the_recorded_first_legal_index(blocks):
    forced = forced_batches(make_env(blocks))
    assert forced, "the deadline should have forced submissions"
    assert all(n == 1 for _, n in forced)


def test_the_largest_repair_submits_the_gate_a_maximum_when_forced(blocks):
    forced = forced_batches(make_env(blocks, illegal_action="largest"))
    assert forced
    assert all(n == ceiling for ceiling, n in forced)
    assert any(n > 1 for _, n in forced)


def test_the_largest_repair_picks_the_nearest_legal_batch_otherwise(blocks):
    env = make_env(blocks, illegal_action="largest")
    env.reset(seed=1)
    env._gate_a_max = lambda: 10  # buckets 1, 4, 8 and the n_max action (10) are legal
    mask = np.zeros(env.action_space.n, dtype=bool)
    mask[[0, 1, 2, 3, 9]] = True

    assert env._repair(7, mask) == 9  # n=25 requested -> 10
    assert env._repair(4, mask) == 9  # n=12 requested -> 10 (distance 2 beats 4)
    mask[WAIT_ACTION] = False
    assert env._repair(WAIT_ACTION, mask) == 9  # forced -> largest


def test_an_unknown_repair_mode_is_rejected(blocks):
    with pytest.raises(ValueError, match="illegal_action"):
        make_env(blocks, illegal_action="random")
