"""T-L5 · Do the committed P3 checkpoints reproduce their recorded evaluation?

    python scripts/check_checkpoints.py --data data/processed/d1_*.parquet \
        --models experiments/phase3-forecaster/models

Reloads each ``phase5-dqn-seed*`` checkpoint, re-scores it on exactly the episodes
``evaluate_rl.py`` used, and compares every metric against
``experiments/phase5-evaluation/rl_evaluation.json`` for **exact** equality. The
unit test covers the save/load path on a toy model; this covers the real models a
reported number came from. A mismatch is a defect to report, not to round away.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd

from batcher.config.params import DEFAULT_SEED, FORECAST_HORIZON
from batcher.data.collector import sha256_of
from batcher.data.features import build_features, chronological_split, preprocess
from batcher.eval.manifest import write_manifest
from batcher.forecast.baseline import MovingAverage
from batcher.forecast.lgbm import load as lgbm_load
from batcher.sim.episodes import build_episodes
from batcher.sim.orders import fit_arrival_process

COMPARED = [
    "l_mean",
    "l_p95",
    "c_user",
    "x_rate",
    "batch_n",
    "lock",
    "violations",
    "action_entropy",
]


def _evaluate_rl():
    path = Path(__file__).with_name("evaluate_rl.py")
    spec = importlib.util.spec_from_file_location("evaluate_rl", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--models", type=Path, default=None)
    parser.add_argument("--recorded", type=Path, default=Path("experiments/phase5-evaluation"))
    args = parser.parse_args(argv)

    from stable_baselines3 import DQN

    recorded_manifest = json.loads((args.recorded / "manifest.json").read_text())
    recorded = json.loads((args.recorded / "rl_evaluation.json").read_text())["per_seed"]

    frame = build_features(preprocess(pd.read_parquet(args.data)))
    process = fit_arrival_process(frame)
    episodes = build_episodes(
        frame,
        chronological_split(frame),
        which=recorded_manifest["split"],
        count=recorded_manifest["episodes"],
        seed=DEFAULT_SEED,
        blocks_per_episode=1_000,
    )
    forecaster = (
        lgbm_load(args.models, horizon=FORECAST_HORIZON) if args.models else MovingAverage()
    )
    score_agent = _evaluate_rl().score_agent

    results, mismatches = {}, []
    for seed, expected in sorted(recorded.items()):
        checkpoint = Path("experiments") / f"phase5-dqn-seed{seed}" / "models" / "dqn.zip"
        model = DQN.load(checkpoint)
        actual = score_agent(model, frame, episodes, process, forecaster)
        diffs = {
            key: (expected[key], actual[key]) for key in COMPARED if expected[key] != actual[key]
        }
        results[seed] = {"identical": not diffs, "differences": diffs}
        mismatches += [f"seed {seed} {key}: {a} -> {b}" for key, (a, b) in diffs.items()]
        print(f"  seed {seed}: {'identical' if not diffs else f'{len(diffs)} metric(s) differ'}")

    manifest = write_manifest(
        "phase6-checkpoint-reproducibility",
        seed=DEFAULT_SEED,
        dataset_checksum=sha256_of(args.data),
        recorded_from=str(args.recorded),
        recorded_git=recorded_manifest.get("git"),
        compared_metrics=COMPARED,
        results=results,
        passed=not mismatches,
    )
    if mismatches:
        print("\nT-L5 FAILED:")
        for line in mismatches:
            print(f"  {line}")
    else:
        print(f"\nT-L5 passed: {len(results)} checkpoints reproduce every recorded metric exactly")
    print(f"manifest {manifest}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
