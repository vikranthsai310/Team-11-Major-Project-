"""Score the trained P3 agents in the project's own metrics (P5-10, P5-11, P5-13).

    python scripts/evaluate_rl.py --data data/processed/d1_*.parquet \
        --models experiments/phase3-forecaster/models --seeds 0 1 2 3 4

The RL return is a weighted penalty in reward units and is **not** comparable to
P2's numbers. This runs each seed's checkpoint through the same metric path the
simulator uses, so L-p95 and C-user mean the same thing for every policy.

Reports mean and standard deviation across seeds. A single-seed RL result is not
a result, and a collapsed seed is a training failure rather than a data point.
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
from batcher.eval import metrics
from batcher.eval.manifest import write_manifest
from batcher.eval.plots import figure_f7
from batcher.eval.rl_diagnostics import (
    action_entropy,
    has_collapsed,
    profile_by_congestion,
    profile_trend,
)
from batcher.forecast.base import CachedForecaster
from batcher.forecast.baseline import MovingAverage
from batcher.forecast.lgbm import load as lgbm_load
from batcher.policy.optimizer import ConstrainedOptimizer
from batcher.policy.static import Greedy
from batcher.sim.env import run_episode
from batcher.sim.episodes import build_episodes
from batcher.sim.gym_env import BatchingEnv
from batcher.sim.orders import fit_arrival_process


def score_agent(model, frame, episodes, process, forecaster, weights=None) -> dict:
    rows, actions, fills, batch_sizes = [], [], [], []

    for episode in episodes:
        blocks = episode.blocks(frame)
        prepared = CachedForecaster(forecaster).prepare(blocks) if forecaster else None
        env = BatchingEnv(blocks, process, forecaster=prepared, weights=weights, seed=episode.seed)

        obs, _ = env.reset(seed=episode.seed)
        terminated = False
        while not terminated:
            action, _ = model.predict(obs, deterministic=True)
            obs, _, terminated, _, _ = env.step(int(action))

        result = env.to_episode_result()
        if not metrics.conserved(result):
            raise AssertionError(f"order conservation failed in {episode.episode_id}")

        rows.append(metrics.compute(result).as_dict())
        actions += env.actions_taken
        fills += env.fills[: len(env.actions_taken)]
        batch_sizes += [env._buckets()[a - 1] if a else 0 for a in env.actions_taken]

    table = pd.DataFrame(rows)
    return {
        "l_mean": float(table["l_mean"].median()),
        "l_p95": float(table["l_p95"].median()),
        "c_user": float(table["c_user"].median()),
        "x_rate": float(table["x_rate"].median()),
        "batch_n": float(table["batch_n"].median()),
        "lock": float(table["lock_occupancy"].median()),
        "violations": int(table["gate_a_violations"].sum()),
        "action_entropy": action_entropy(actions),
        "collapsed": has_collapsed(actions),
        "congestion_profile": profile_by_congestion(actions, fills, batch_sizes),
    }


def score_policy(policy, frame, episodes, process, forecaster) -> dict:
    rows = []
    for episode in episodes:
        if hasattr(policy, "reset"):
            policy.reset()
        blocks = episode.blocks(frame)
        prepared = CachedForecaster(forecaster).prepare(blocks) if forecaster else None
        result = run_episode(
            blocks,
            policy,
            episode.stream(process, "matched"),
            episode.rng(),
            forecaster=prepared,
            episode_id=episode.episode_id,
            policy_name=policy.name,
        )
        rows.append(metrics.compute(result).as_dict())

    table = pd.DataFrame(rows)
    return {
        "l_mean": float(table["l_mean"].median()),
        "l_p95": float(table["l_p95"].median()),
        "c_user": float(table["c_user"].median()),
        "x_rate": float(table["x_rate"].median()),
        "batch_n": float(table["batch_n"].median()),
        "lock": float(table["lock_occupancy"].median()),
        "violations": int(table["gate_a_violations"].sum()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--models", type=Path, default=None)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    parser.add_argument("--episodes", type=int, default=4)
    parser.add_argument("--blocks-per-episode", type=int, default=1_000)
    parser.add_argument("--split", default="val")
    # Ablations A3/A4 score their own checkpoints on the same episodes. The P2
    # comparators and F7 belong to the main Phase 5 evaluation, so an ablation run
    # neither recomputes nor overwrites them.
    parser.add_argument("--checkpoints", default="phase5-dqn-seed", help="experiment prefix")
    parser.add_argument("--no-forecast", action="store_true", help="score A3 agents")
    parser.add_argument("--experiment", default="phase5-evaluation")
    args = parser.parse_args(argv)
    main_run = args.experiment == "phase5-evaluation"

    from stable_baselines3 import DQN

    frame = build_features(preprocess(pd.read_parquet(args.data)))
    process = fit_arrival_process(frame)
    episodes = build_episodes(
        frame,
        chronological_split(frame),
        which=args.split,
        count=args.episodes,
        seed=DEFAULT_SEED,
        blocks_per_episode=args.blocks_per_episode,
    )
    forecaster = (
        lgbm_load(args.models, horizon=FORECAST_HORIZON) if args.models else MovingAverage()
    )
    agent_forecaster = None if args.no_forecast else forecaster

    print(
        f"scoring {args.checkpoints}* on the {args.split} split · {len(episodes)} episodes · "
        f"agent forecaster {agent_forecaster.name if agent_forecaster else 'none'}\n"
    )

    per_seed = {}
    for seed in args.seeds:
        checkpoint = Path("experiments") / f"{args.checkpoints}{seed}" / "models" / "dqn.zip"
        if not checkpoint.exists():
            print(f"  seed {seed}: no checkpoint at {checkpoint}, skipped")
            continue
        model = DQN.load(checkpoint)
        per_seed[seed] = score_agent(model, frame, episodes, process, agent_forecaster)
        row = per_seed[seed]
        print(
            f"  seed {seed}: L-p95 {row['l_p95']:7.1f}  C-user {row['c_user']:11.1f}  "
            f"batch_n {row['batch_n']:5.2f}  entropy {row['action_entropy']:.3f}  "
            f"collapsed {row['collapsed']}"
        )

    if not per_seed:
        print("no checkpoints found")
        return 1

    summary = {}
    for key in ("l_mean", "l_p95", "c_user", "batch_n", "lock", "x_rate"):
        values = [row[key] for row in per_seed.values()]
        summary[key] = {"mean": float(np.mean(values)), "std": float(np.std(values))}

    print("\n=== P3 across seeds (mean ± sd) ===")
    for key, value in summary.items():
        print(f"  {key:<10} {value['mean']:12.2f} ± {value['std']:.2f}")
    print(f"  violations {sum(row['violations'] for row in per_seed.values()):>11}   <- S2")
    collapsed = sum(row["collapsed"] for row in per_seed.values())
    print(f"  collapsed  {collapsed:>11} of {len(per_seed)}")

    if not main_run:
        manifest = write_manifest(
            args.experiment,
            seed=DEFAULT_SEED,
            dataset_checksum=sha256_of(args.data),
            split=args.split,
            episodes=len(episodes),
            checkpoints=args.checkpoints,
            agent_forecaster=agent_forecaster.name if agent_forecaster else "none",
            per_seed={str(k): v for k, v in per_seed.items()},
            summary=summary,
        )
        (manifest.parent / "rl_evaluation.json").write_text(
            json.dumps(
                {"per_seed": {str(k): v for k, v in per_seed.items()}, "summary": summary},
                indent=2,
                default=str,
            )
            + "\n"
        )
        print(f"\nmanifest {manifest}")
        return 0

    # The whole P2 frontier, not one config. Comparing a learned policy against a
    # single hand-picked N_MIN would let the choice of comparator decide the
    # verdict — P2 spans a trade-off curve, and P3 lands somewhere on that plane.
    print("\n=== comparators on the same episodes and metrics ===")
    comparators = {}
    candidates = [(f"p2(N={n})", ConstrainedOptimizer(n_min=n)) for n in (1, 4, 8, 12, 20)]
    candidates.append(("e3(greedy)", Greedy()))

    for label, policy in candidates:
        comparators[label] = score_policy(policy, frame, episodes, process, forecaster)
        row = comparators[label]
        print(
            f"  {label:<12} L-p95 {row['l_p95']:7.1f}  C-user {row['c_user']:11.1f}  "
            f"batch_n {row['batch_n']:5.2f}"
        )

    p3 = (summary["l_p95"]["mean"], summary["c_user"]["mean"])
    dominates = [
        label
        for label, row in comparators.items()
        if p3[0] <= row["l_p95"]
        and p3[1] <= row["c_user"]
        and (p3[0] < row["l_p95"] or p3[1] < row["c_user"])
    ]
    dominated_by = [
        label
        for label, row in comparators.items()
        if row["l_p95"] <= p3[0]
        and row["c_user"] <= p3[1]
        and (row["l_p95"] < p3[0] or row["c_user"] < p3[1])
    ]

    print(f"\n  P3 (mean) L-p95 {p3[0]:.1f}  C-user {p3[1]:.1f}")
    print(f"  P3 dominates:    {dominates or 'none'}")
    print(f"  P3 dominated by: {dominated_by or 'none'}")
    print("  (P3 beating P2 is not an exit gate either way)")
    summary["dominates"] = dominates
    summary["dominated_by"] = dominated_by

    # F7 from the median-entropy seed, so the figure shows typical behaviour
    # rather than the best or worst run.
    typical = sorted(per_seed, key=lambda s: per_seed[s]["action_entropy"])[len(per_seed) // 2]
    profile = per_seed[typical]["congestion_profile"]
    trend = profile_trend(profile)
    figure_f7(
        profile,
        Path("figures"),
        provenance=f"DQN seed {typical} · {args.split} split · 200k steps (a tenth of spec)",
    )
    print(f"\n  F7 from seed {typical}: {trend['direction']}, ratio {trend['ratio']:.2f}")
    if trend["flat"]:
        print("  FLAT profile — the agent ignores congestion. Cross-check with A3.")

    manifest = write_manifest(
        "phase5-evaluation",
        seed=DEFAULT_SEED,
        dataset_checksum=sha256_of(args.data),
        split=args.split,
        episodes=len(episodes),
        steps_per_seed=200_000,
        budget_note="a tenth of the 2M the ML spec sets; results are a lower bound",
        per_seed={str(k): v for k, v in per_seed.items()},
        summary=summary,
        comparators=comparators,
        f7_trend=trend,
        f7_seed=typical,
    )
    (manifest.parent / "rl_evaluation.json").write_text(
        json.dumps(
            {
                "per_seed": {str(k): v for k, v in per_seed.items()},
                "summary": summary,
                "comparators": comparators,
            },
            indent=2,
            default=str,
        )
        + "\n"
    )
    print(f"\nmanifest {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
