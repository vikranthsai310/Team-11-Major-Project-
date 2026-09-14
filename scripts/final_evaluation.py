"""P6-1 · The full paired evaluation — and the single permitted touch of the test split.

    python scripts/final_evaluation.py --data data/processed/d1_*.parquet \
        --models experiments/phase3-forecaster/models --episodes 100

Every policy sees the identical D1 window and the identical order stream in each
episode, at each of the three arrival rates. Every configuration was fixed on the
validation split before this runs; nothing here is tuned.

Writes two artifacts that every downstream table, test and figure reads:

``episode_metrics.parquet``  one row per (policy, rate, episode[, seed])
``latencies.parquet``        settled-order latencies at the matched rate, for F6

**Running this twice defeats its purpose.** The manifest records the first run,
and a second run against the test split refuses unless ``--force-rerun`` is
passed — which is itself recorded.
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
from batcher.forecast.base import CachedForecaster
from batcher.forecast.baseline import Oracle
from batcher.forecast.lgbm import load as lgbm_load
from batcher.policy.optimizer import ConstrainedOptimizer, OracleOptimizer
from batcher.policy.static import FixedInterval, FixedSize, Greedy, Null
from batcher.sim.env import run_episode
from batcher.sim.episodes import build_episodes
from batcher.sim.gym_env import BatchingEnv
from batcher.sim.orders import ARRIVAL_RATES, fit_arrival_process

EXPERIMENT = "phase6-final-evaluation"
LATENCY_SAMPLE = 20_000

# Fixed on validation before the test split is opened:
#   E1 M=16, E2 T=20       — phase2-tuning sweep, selected on L-p95
#   p2(N=1)                — the same rule applied to P2; byte-identical to greedy
#   p2(N=4)                — the validation frontier point that dominated tuned E2
# Both P2 rows are reported: the rule's selection, and the point the frontier
# analysis identified. Reporting only the flattering one would be selection.
FAMILY = {
    "null": "reference",
    "e1(M=16)": "static",
    "e2(T=20)": "static",
    "e3(greedy)": "static",
    "p2(D=120,N=1)": "proposed",
    "p2(D=120,N=4)": "proposed",
    "p3(dqn)": "proposed",
    "oracle(D=120,N=4)": "reference",
}


def simulator_policies():
    return [
        (Null(), "lgbm"),
        (FixedSize(m=16), "lgbm"),
        (FixedInterval(t=20), "lgbm"),
        (Greedy(), "lgbm"),
        (ConstrainedOptimizer(n_min=1), "lgbm"),
        (ConstrainedOptimizer(n_min=4), "lgbm"),
        (OracleOptimizer(n_min=4), "oracle"),
    ]


def row(policy_name, rate, episode, result, seed=-1):
    return {
        "policy": policy_name,
        "family": FAMILY.get(policy_name, "proposed"),
        "rate": rate,
        "episode_id": episode.episode_id,
        "seed": seed,
        "congested_share": np.nan,
        **metrics.compute(result).as_dict(),
    }


def run_p3(model, blocks, episode, process, forecaster, rate):
    """P3 on exactly the episode the simulator policies saw.

    The Gym env seeds its order stream from ``episode.seed`` and takes the same
    rate multiplier, so arrivals are identical to ``episode.stream(...)``; only
    the order-id strings differ, which no metric reads.
    """
    env = BatchingEnv(
        blocks,
        process,
        forecaster=forecaster,
        rate_multiplier=ARRIVAL_RATES[rate],
        seed=episode.seed,
    )
    obs, _ = env.reset(seed=episode.seed)
    terminated = False
    while not terminated:
        action, _ = model.predict(obs, deterministic=True)
        obs, _, terminated, _, _ = env.step(int(action))
    return env.to_episode_result()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--episodes", type=int, default=100)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    parser.add_argument("--split", default="test")
    parser.add_argument("--out", default=EXPERIMENT)
    parser.add_argument("--force-rerun", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path("experiments") / args.out
    if args.split == "test" and (out_dir / "manifest.json").exists() and not args.force_rerun:
        print(f"{out_dir} already holds a test-split evaluation. The test split is used once.")
        print("Pass --force-rerun to override; the override is recorded in the manifest.")
        return 2

    from stable_baselines3 import DQN

    frame = build_features(preprocess(pd.read_parquet(args.data)))
    process = fit_arrival_process(frame)
    episodes = build_episodes(
        frame, chronological_split(frame), which=args.split, count=args.episodes, seed=DEFAULT_SEED
    )
    lgbm = lgbm_load(args.models, horizon=FORECAST_HORIZON)
    if lgbm.name != "lgbm":
        raise RuntimeError("the trained forecaster failed to load; refusing to evaluate on E4")

    agents = {}
    for seed in args.seeds:
        checkpoint = Path("experiments") / f"phase5-dqn-seed{seed}" / "models" / "dqn.zip"
        if checkpoint.exists():
            agents[seed] = DQN.load(checkpoint)
    print(f"{len(episodes)} episodes x {len(ARRIVAL_RATES)} rates · P3 seeds {sorted(agents)}")

    rows, latencies = [], []
    for index, episode in enumerate(episodes):
        blocks = episode.blocks(frame)
        congested = float((blocks["fill_pct"] > 0.80).mean())
        forecasters = {
            "lgbm": CachedForecaster(lgbm).prepare(blocks),
            "oracle": CachedForecaster(Oracle(horizon=FORECAST_HORIZON)).prepare(blocks),
        }

        for rate in ARRIVAL_RATES:
            for policy, kind in simulator_policies():
                if hasattr(policy, "reset"):
                    policy.reset()
                result = run_episode(
                    blocks,
                    policy,
                    episode.stream(process, rate),
                    episode.rng(),
                    forecaster=forecasters[kind],
                    episode_id=episode.episode_id,
                    policy_name=policy.name,
                )
                if not metrics.conserved(result):
                    raise AssertionError(f"conservation failed: {policy.name} {episode.episode_id}")
                rows.append(
                    {**row(policy.name, rate, episode, result), "congested_share": congested}
                )
                if rate == "matched":
                    latencies += [(policy.name, o.latency) for o in result.settled]

            for seed, model in agents.items():
                result = run_p3(model, blocks, episode, process, forecasters["lgbm"], rate)
                if not metrics.conserved(result):
                    raise AssertionError(
                        f"conservation failed: p3 seed {seed} {episode.episode_id}"
                    )
                rows.append(
                    {
                        **row("p3(dqn)", rate, episode, result, seed=seed),
                        "congested_share": congested,
                    }
                )
                if rate == "matched":
                    latencies += [("p3(dqn)", o.latency) for o in result.settled]

        if (index + 1) % 5 == 0 or index == 0:
            print(f"  episode {index + 1}/{len(episodes)}", flush=True)

    results = pd.DataFrame(rows)
    lat = pd.DataFrame(latencies, columns=["policy", "latency"])
    lat = (
        lat.groupby("policy", group_keys=False)
        .apply(lambda g: g.sample(min(len(g), LATENCY_SAMPLE), random_state=DEFAULT_SEED))
        .reset_index(drop=True)
    )

    manifest = write_manifest(
        args.out,
        seed=DEFAULT_SEED,
        dataset_checksum=sha256_of(args.data),
        split=args.split,
        episodes=len(episodes),
        rates=list(ARRIVAL_RATES),
        p3_seeds=sorted(agents),
        p3_training_steps=200_000,
        forced_rerun=bool(args.force_rerun),
        arrival_process=process.to_manifest(),
        configurations_fixed_on="validation",
        gate_a_violations=int(results["gate_a_violations"].sum()),
        known_asymmetry=(
            "P3 runs through the Gym env, which does not model rollbacks "
            "(p=0.0005/block in the simulator); every other policy does"
        ),
    )
    results.to_parquet(manifest.parent / "episode_metrics.parquet", index=False)
    lat.to_parquet(manifest.parent / "latencies.parquet", index=False)
    (manifest.parent / "summary.json").write_text(
        json.dumps(
            results.groupby(["rate", "policy"])[["l_p95", "c_user"]]
            .median()
            .reset_index()
            .to_dict("records"),
            indent=2,
        )
        + "\n"
    )
    print(f"\nGate A violations across every run: {int(results['gate_a_violations'].sum())}")
    print(f"manifest {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
