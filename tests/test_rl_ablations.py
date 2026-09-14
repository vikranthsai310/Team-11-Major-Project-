"""T-L5 and the switches ablations A3/A4 depend on.

T-L5: reloading a checkpoint must reproduce its evaluation exactly, or a reported
P3 number cannot be regenerated from the committed model. A4 changes only the
latency term of the reward, so it must not alter the environment's dynamics.
"""

from __future__ import annotations

import numpy as np
import pytest

from batcher.data.collector import collect_blocks
from batcher.data.features import preprocess
from batcher.eval import metrics
from batcher.sim.gym_env import BatchingEnv, calibrate_weights
from batcher.sim.orders import ArrivalProcess
from conftest import BASE_HEIGHT, FakeSource, make_records

FLAT = tuple([1.0] * 24)


@pytest.fixture(scope="module")
def blocks(tmp_path_factory):
    source = FakeSource(make_records(400, seed=43))
    frame = collect_blocks(
        source,
        start_height=BASE_HEIGHT,
        end_height=source.tip_height(),
        staging_dir=tmp_path_factory.mktemp("staging"),
        page_size=200,
    )
    return preprocess(frame)


def make_env(blocks, **kwargs) -> BatchingEnv:
    process = ArrivalProcess(base_per_slot=0.1, diurnal=FLAT, bursts_per_day=0.0)
    return BatchingEnv(blocks, process, seed=3, **kwargs)


def greedy_by_mask_rewards(env):
    env.reset(seed=0)
    rewards, terminated = [], False
    while not terminated:
        _, reward, terminated, _, _ = env.step(int(np.argmax(env.action_masks())))
        rewards.append(reward)
    return np.array(rewards), env.to_episode_result()


def test_a4_linear_penalty_changes_the_reward_not_the_dynamics(blocks):
    quadratic, quad_result = greedy_by_mask_rewards(make_env(blocks))
    linear, lin_result = greedy_by_mask_rewards(make_env(blocks, latency_power=1))

    # Same actions, same trajectory: the penalty never feeds back into the episode.
    assert len(quad_result.settled) == len(lin_result.settled)
    assert quad_result.submissions == lin_result.submissions
    # With unit weights, latency >= latency ** 2 never holds for waits above one slot.
    assert (linear >= quadratic).all()
    assert (linear > quadratic).any()


def test_latency_power_is_restricted_to_the_two_specified_forms(blocks):
    with pytest.raises(ValueError):
        make_env(blocks, latency_power=3)


def test_calibration_normalises_the_penalty_the_env_actually_charges(blocks):
    quadratic = calibrate_weights(lambda seed: make_env(blocks), episodes=1, seed=0)
    linear = calibrate_weights(lambda seed: make_env(blocks, latency_power=1), episodes=1, seed=0)
    assert linear.latency_norm < quadratic.latency_norm


def test_a3_agent_sees_no_forecast(blocks):
    env = make_env(blocks, forecaster=None)
    state, _ = env.reset(seed=0)
    assert state[3:6].tolist() == [0.0, 0.0, 0.0]


def _score(model, blocks):
    env = make_env(blocks)
    obs, _ = env.reset(seed=3)
    terminated = False
    while not terminated:
        action, _ = model.predict(obs, deterministic=True)
        obs, _, terminated, _, _ = env.step(int(action))
    return env.actions_taken, metrics.compute(env.to_episode_result()).as_dict()


def test_a_reloaded_checkpoint_reproduces_its_evaluation(blocks, tmp_path):
    """T-L5."""
    from stable_baselines3 import DQN

    model = DQN(
        "MlpPolicy", make_env(blocks), seed=0, learning_starts=50, buffer_size=1_000, verbose=0
    )
    model.learn(total_timesteps=300)

    actions_before, metrics_before = _score(model, blocks)
    model.save(tmp_path / "dqn")
    actions_after, metrics_after = _score(DQN.load(tmp_path / "dqn.zip"), blocks)

    assert actions_before == actions_after
    np.testing.assert_equal(metrics_before, metrics_after)
