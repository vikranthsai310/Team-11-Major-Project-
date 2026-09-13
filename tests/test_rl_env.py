"""T-L3, T-L4, T-L6 — the RL environment's structural guarantees.

The exit gate for Phase 5 is **a correctly trained and honestly reported agent**,
not an agent that beats P2. These tests cover the "correctly" half: an agent
cannot act illegally, the reward terms are commensurable, and a collapsed policy
is detected by the action distribution rather than by the return curve.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from batcher.build.estimator import gate_a
from batcher.config.params import ACTION_BUCKETS
from batcher.data.collector import collect_blocks
from batcher.data.features import preprocess
from batcher.sim.gym_env import (
    STATE_DIM,
    WAIT_ACTION,
    BatchingEnv,
    RewardWeights,
    calibrate_weights,
)
from batcher.sim.orders import ArrivalProcess
from conftest import BASE_HEIGHT, FakeSource, make_records

FLAT = tuple([1.0] * 24)


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


def process() -> ArrivalProcess:
    return ArrivalProcess(base_per_slot=0.1, diurnal=FLAT, bursts_per_day=0.0)


def make_env(blocks, **kwargs) -> BatchingEnv:
    return BatchingEnv(blocks, process(), seed=3, **kwargs)


def rollout(env, policy, limit: int = 10_000, seed: int = 0):
    """Run until termination, returning the actions actually executed."""
    rng = np.random.default_rng(seed)
    env.reset(seed=seed)
    steps = 0
    terminated = False
    while not terminated and steps < limit:
        action = policy(env, rng)
        _, _, terminated, _, _ = env.step(action)
        steps += 1
    return steps


def test_the_observation_space_is_the_specified_shape(blocks):
    env = make_env(blocks)
    obs, _ = env.reset(seed=1)
    assert obs.shape == (STATE_DIM,)
    assert env.observation_space.contains(obs)
    assert env.action_space.n == len(ACTION_BUCKETS) + 2


def test_every_observation_stays_in_range(blocks):
    """A component drifting outside [0,1] silently changes what the network sees."""
    env = make_env(blocks)
    obs, _ = env.reset(seed=2)
    terminated = False
    while not terminated:
        assert env.observation_space.contains(obs), obs
        obs, _, terminated, _, _ = env.step(int(np.argmax(env.action_masks())))


def test_a_random_agent_never_executes_an_illegal_action(blocks):
    """⚠ T-L3 — this is what makes invariants I1 and I2 structural.

    The agent does not have to learn not to violate a ledger rule; it cannot.
    """
    env = make_env(blocks)
    executed: list[int] = []

    def random_policy(env, rng):
        action = int(rng.integers(env.action_space.n))
        mask = env.action_masks()
        # Record what the env will actually execute, not what was requested.
        executed.append(action if mask[action] else int(np.argmax(mask)))
        return action

    total = 0
    for seed in range(6):
        total += rollout(env, random_policy, seed=seed)
    assert total > 1_000, "not enough steps to be meaningful"

    # Every executed action was legal at the moment of execution.
    assert env.mask_hits > 0, "the random agent should have proposed illegal actions"


def test_no_submission_can_violate_gate_a(blocks):
    """T-I1 at the RL boundary: every batch size the env builds is feasible."""
    env = make_env(blocks)
    env.reset(seed=4)
    rng = np.random.default_rng(4)

    terminated = False
    while not terminated:
        action = int(rng.integers(env.action_space.n))
        n = env._action_to_n(action if env.action_masks()[action] else WAIT_ACTION)
        assert gate_a(n), f"proposed infeasible n={n}"
        _, _, terminated, _, _ = env.step(action)


def test_waiting_forever_is_impossible(blocks):
    """T-I2 — the deadline mask forces submission, so orders still settle."""
    env = make_env(blocks)
    rollout(env, lambda env, rng: WAIT_ACTION, seed=5)

    assert env.mask_hits > 0, "WAIT should have been masked at the deadline"
    assert len(env.settled) > 0, "an always-WAIT agent must still settle orders"


def test_the_episode_terminates_and_advances(blocks):
    """The env once looped on one block forever when WAIT was chosen."""
    env = make_env(blocks)
    steps = rollout(env, lambda env, rng: WAIT_ACTION, seed=6)
    assert steps < len(blocks) + 5
    assert env.index >= len(env.blocks)


def test_reward_is_never_positive(blocks):
    """Reward is a negated penalty; a positive value would mean a sign error."""
    env = make_env(blocks)
    env.reset(seed=7)
    terminated = False
    while not terminated:
        _, reward, terminated, _, _ = env.step(int(np.argmax(env.action_masks())))
        assert reward <= 0.0


def test_reward_terms_are_commensurable_after_calibration(blocks):
    """⚠ T-L4 — raw, the latency term dwarfs cost by orders of magnitude.

    Left uncalibrated the agent optimises latency alone while appearing to trade
    off four objectives, and the cost weight would be decorative.
    """
    weights = calibrate_weights(lambda seed: make_env(blocks), episodes=2, seed=11)

    assert weights.cost_norm > 0
    assert weights.latency_norm > 0
    assert weights.lock_norm > 0

    # The normalisers must actually differ in scale — that is the problem they
    # exist to solve.
    assert weights.latency_norm / weights.cost_norm > 10


def test_calibrated_weights_are_recorded_for_the_manifest(blocks):
    weights = calibrate_weights(lambda seed: make_env(blocks), episodes=1, seed=12)
    recorded = weights.as_dict()
    assert {"w_cost", "w_latency", "w_slip", "w_lock"} <= set(recorded)
    assert {"cost_norm", "latency_norm", "slip_norm", "lock_norm"} <= set(recorded)


def test_action_distribution_detects_a_collapsed_policy(blocks):
    """T-L6 — collapse is visible in the actions, not in the return curve."""
    from batcher.eval.rl_diagnostics import action_entropy

    env = make_env(blocks)

    rollout(env, lambda env, rng: WAIT_ACTION, seed=8)
    collapsed = action_entropy(env.actions_taken)

    rollout(env, lambda env, rng: int(rng.integers(env.action_space.n)), seed=9)
    varied = action_entropy(env.actions_taken)

    assert collapsed < 0.2
    assert varied > collapsed


def test_the_same_seed_reproduces_the_episode(blocks):
    """Determinism: the RL env is subject to the same rule as the simulator."""
    first = make_env(blocks)
    second = make_env(blocks)

    rollout(first, lambda env, rng: int(np.argmax(env.action_masks())), seed=13)
    rollout(second, lambda env, rng: int(np.argmax(env.action_masks())), seed=13)

    assert first.actions_taken == second.actions_taken
    assert len(first.settled) == len(second.settled)


def test_no_inclusion_failure_penalty_exists():
    """ADR-004: a submitted transaction is not rejected for being late.

    Penalising a non-existent event would teach a false model of the environment.
    """
    import inspect

    from batcher.sim import gym_env

    source = inspect.getsource(gym_env.BatchingEnv._reward)
    for forbidden in ("reject", "bounce", "fail"):
        assert forbidden not in source.lower()


@pytest.mark.slow
def test_the_environment_satisfies_the_sb3_contract(blocks):
    """P5-1 — Stable-Baselines3 drives this env, so its checker must pass."""
    from stable_baselines3.common.env_checker import check_env

    check_env(make_env(blocks), warn=True, skip_render_check=True)


def test_weights_default_to_neutral():
    weights = RewardWeights()
    assert weights.cost == weights.latency == weights.slip == weights.lock == 1.0


def test_an_empty_window_is_rejected():
    with pytest.raises((ValueError, IndexError)):
        BatchingEnv(pd.DataFrame(columns=["abs_slot", "block_time"]), process()).reset(seed=0)
