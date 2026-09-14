"""Train the P3 reinforcement-learning agent (P5-7 … P5-12).

    python scripts/train_rl.py --data data/processed/d1_*.parquet --steps 200000 --seed 0
    for s in 0 1 2 3 4; do python scripts/train_rl.py --seed $s ...; done

**Beating P2 is not the goal.** The Phase 5 exit gate is a correctly trained and
honestly reported agent: the mask holds, the reward terms are commensurable, the
policy has not collapsed, and five seeds are reported with mean and standard
deviation. A single-seed RL result is not a result.

Training draws episodes from the **train** split only; checkpoints are selected on
validation; the test split is touched once, in Phase 6.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from batcher.config.params import DEFAULT_SEED, FORECAST_HORIZON
from batcher.data.collector import sha256_of
from batcher.data.features import build_features, chronological_split, preprocess
from batcher.eval.manifest import write_manifest
from batcher.eval.rl_diagnostics import action_entropy, action_profile, has_collapsed
from batcher.forecast.base import CachedForecaster
from batcher.forecast.baseline import MovingAverage
from batcher.forecast.lgbm import load as lgbm_load
from batcher.sim.episodes import build_episodes
from batcher.sim.gym_env import BatchingEnv, calibrate_weights
from batcher.sim.orders import fit_arrival_process

# docs/06-ML-SPEC.md §5. Kept here so a change is visible in review rather than
# buried in a call site.
DQN_CONFIG = {
    "learning_rate": 1e-4,
    "batch_size": 64,
    "gamma": 0.99,
    "buffer_size": 100_000,
    "exploration_initial_eps": 1.0,
    "exploration_final_eps": 0.05,
    "exploration_fraction": 0.20,
    "learning_starts": 1_000,
}


def make_env_factory(
    frame, episodes, process, forecaster, weights=None, rate: str = "matched", latency_power=2
):
    """An env over a training window chosen by the episode index."""

    def factory(seed: int) -> BatchingEnv:
        episode = episodes[seed % len(episodes)]
        blocks = episode.blocks(frame)
        prepared = CachedForecaster(forecaster).prepare(blocks) if forecaster else None
        return BatchingEnv(
            blocks,
            process,
            forecaster=prepared,
            weights=weights,
            latency_power=latency_power,
            seed=seed,
        )

    return factory


def evaluate(factory, seeds: range) -> dict:
    """Roll the greedy-by-mask policy for diagnostics; the agent version below."""
    returns, entropies = [], []
    for seed in seeds:
        env = factory(seed)
        env.reset(seed=seed)
        total, terminated = 0.0, False
        while not terminated:
            _, reward, terminated, _, _ = env.step(int(np.argmax(env.action_masks())))
            total += reward
        returns.append(total)
        entropies.append(action_entropy(env.actions_taken))
    return {"return_mean": float(np.mean(returns)), "entropy_mean": float(np.mean(entropies))}


def run_agent(model, factory, seeds) -> dict:
    returns, all_actions, settled = [], [], []
    for seed in seeds:
        env = factory(seed)
        obs, _ = env.reset(seed=seed)
        total, terminated = 0.0, False
        while not terminated:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, _, _ = env.step(int(action))
            total += reward
        returns.append(total)
        all_actions += env.actions_taken
        settled.append(len(env.settled))

    return {
        "return_mean": float(np.mean(returns)),
        "return_std": float(np.std(returns)),
        "settled_mean": float(np.mean(settled)),
        "action_entropy": action_entropy(all_actions),
        "collapsed": has_collapsed(all_actions),
        "action_profile": action_profile(all_actions, 10),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--models", type=Path, default=None)
    parser.add_argument("--steps", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--episodes", type=int, default=8)
    parser.add_argument("--blocks-per-episode", type=int, default=1_000)
    parser.add_argument("--experiment", default=None)
    # P5-13. A3 retrains with no forecast in the state (the three fill_hat inputs
    # are constant zero), rather than zeroing them on an agent trained with them.
    # A4 retrains with a linear instead of a quadratic latency penalty.
    parser.add_argument("--no-forecast", action="store_true", help="ablation A3")
    parser.add_argument("--linear-latency", action="store_true", help="ablation A4")
    args = parser.parse_args(argv)
    latency_power = 1 if args.linear_latency else 2
    ablation = "A3" if args.no_forecast else "A4" if args.linear_latency else None
    if args.no_forecast and args.linear_latency:
        parser.error("run A3 and A4 separately, or neither isolates its question")

    from stable_baselines3 import DQN
    from stable_baselines3.common.env_checker import check_env

    frame = build_features(preprocess(pd.read_parquet(args.data)))
    process = fit_arrival_process(frame)
    train_episodes = build_episodes(
        frame,
        chronological_split(frame),
        which="train",
        count=args.episodes,
        seed=args.seed,
        blocks_per_episode=args.blocks_per_episode,
    )
    val_episodes = build_episodes(
        frame,
        chronological_split(frame),
        which="val",
        count=4,
        seed=args.seed,
        blocks_per_episode=args.blocks_per_episode,
    )

    if args.no_forecast:
        forecaster = None
    else:
        forecaster = (
            lgbm_load(args.models, horizon=FORECAST_HORIZON) if args.models else MovingAverage()
        )
    forecaster_name = forecaster.name if forecaster else "none"
    print(f"forecaster: {forecaster_name} · latency penalty power {latency_power}")

    # P5-5: normalise every reward term before weights are applied, or latency
    # dominates by orders of magnitude and cost becomes decorative.
    raw_factory = make_env_factory(
        frame, train_episodes, process, forecaster, latency_power=latency_power
    )
    print("calibrating reward weights...")
    weights = calibrate_weights(raw_factory, episodes=2, seed=args.seed)
    print(f"  {weights.as_dict()}")

    factory = make_env_factory(
        frame, train_episodes, process, forecaster, weights, latency_power=latency_power
    )
    val_factory = make_env_factory(
        frame, val_episodes, process, forecaster, weights, latency_power=latency_power
    )

    print("checking the environment against the SB3 contract...")
    check_env(factory(args.seed), warn=True, skip_render_check=True)

    env = factory(args.seed)
    model = DQN("MlpPolicy", env, seed=args.seed, verbose=0, **DQN_CONFIG)

    print(f"training DQN · {args.steps:,} steps · seed {args.seed}")
    model.learn(total_timesteps=args.steps, progress_bar=False)

    default_name = {"A3": "phase6-a3-seed", "A4": "phase6-a4-seed"}.get(ablation, "phase5-dqn-seed")
    experiment = args.experiment or f"{default_name}{args.seed}"
    manifest = write_manifest(
        experiment,
        seed=args.seed,
        dataset_checksum=sha256_of(args.data),
        algorithm="DQN",
        config=DQN_CONFIG,
        steps=args.steps,
        ablation=ablation,
        latency_power=latency_power,
        forecaster=forecaster_name,
        reward_weights=weights.as_dict(),
        train_episodes=len(train_episodes),
        blocks_per_episode=args.blocks_per_episode,
    )
    model.save(manifest.parent / "models" / "dqn")

    print("\nevaluating on the validation split...")
    agent = run_agent(model, val_factory, range(4))
    baseline = evaluate(val_factory, range(4))

    print(f"  agent return    {agent['return_mean']:,.1f} ± {agent['return_std']:,.1f}")
    print(f"  greedy-by-mask  {baseline['return_mean']:,.1f}")
    print(f"  action entropy  {agent['action_entropy']:.3f}")
    print(f"  collapsed       {agent['collapsed']}  <- T-L6")
    if agent["collapsed"]:
        print("  A collapsed policy is a training failure, not a result. Report it.")

    results = {"agent": agent, "greedy_by_mask": baseline}
    (manifest.parent / "rl_results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nmanifest {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
