"""Tune E1 and E2 on the validation split (P2-18).

    python scripts/tune_baselines.py --data data/processed/d1_*.parquet

An untuned baseline is a straw man and invalidates the entire comparison, so the
sweep runs before any proposed policy is evaluated and the selected values are
recorded in the manifest and disclosed in the results table.

**Validation only.** The test split is not touched here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from batcher.config.params import DEFAULT_SEED
from batcher.data.collector import sha256_of
from batcher.data.features import chronological_split, preprocess
from batcher.eval import metrics
from batcher.eval.manifest import write_manifest
from batcher.policy.static import FixedInterval, FixedSize
from batcher.sim.env import run_episode
from batcher.sim.episodes import build_episodes
from batcher.sim.orders import fit_arrival_process

M_GRID = [4, 8, 12, 16, 20, 25, 30, 40]
T_GRID = [20, 40, 60, 90, 120, 180, 240, 360]

# L-p95 is the headline metric: mean latency can be improved by favouring easy
# periods, while the tail is where a badly timed batcher actually hurts users
# (docs/09-EVALUATION-PROTOCOL.md §2).
SELECTION_METRIC = "l_p95"


def score(frame, episodes, policy, process, rate: str) -> dict:
    rows = []
    for episode in episodes:
        if hasattr(policy, "reset"):
            policy.reset()
        result = run_episode(
            episode.blocks(frame),
            policy,
            episode.stream(process, rate),
            episode.rng(),
            episode_id=episode.episode_id,
            policy_name=policy.name,
        )
        rows.append(metrics.compute(result).as_dict())

    table = pd.DataFrame(rows)
    return {
        "policy": policy.name,
        "l_mean": float(table["l_mean"].median()),
        "l_p95": float(table["l_p95"].median()),
        "c_user": float(table["c_user"].median()),
        "x_rate": float(table["x_rate"].median()),
        "violations": int(table["gate_a_violations"].sum()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--rate", default="matched")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)

    frame = preprocess(pd.read_parquet(args.data))
    split = chronological_split(frame)
    process = fit_arrival_process(frame)
    episodes = build_episodes(frame, split, which="val", count=args.episodes, seed=args.seed)

    print(f"tuning on the VALIDATION split · {len(episodes)} episodes · rate {args.rate}")
    print(f"selection metric: {SELECTION_METRIC} (lower is better)\n")

    sweeps = {
        "e1": [score(frame, episodes, FixedSize(m=m), process, args.rate) for m in M_GRID],
        "e2": [score(frame, episodes, FixedInterval(t=t), process, args.rate) for t in T_GRID],
    }

    tuned = {}
    for name, rows in sweeps.items():
        table = pd.DataFrame(rows).sort_values(SELECTION_METRIC)
        print(f"=== {name.upper()} sweep ===")
        print(table.round(3).to_string(index=False))

        best = table.iloc[0]
        tuned[name] = {
            "policy": best["policy"],
            SELECTION_METRIC: float(best[SELECTION_METRIC]),
        }
        print(f"  selected: {best['policy']}\n")

    manifest = write_manifest(
        "phase2-tuning",
        seed=args.seed,
        dataset_checksum=sha256_of(args.data),
        split="val",
        rate=args.rate,
        episodes=len(episodes),
        selection_metric=SELECTION_METRIC,
        grids={"M": M_GRID, "T": T_GRID},
        tuned=tuned,
    )
    (manifest.parent / "sweeps.json").write_text(json.dumps(sweeps, indent=2) + "\n")

    print("tuned baselines (disclose these in the results table):")
    for name, value in tuned.items():
        print(f"  {name}: {value['policy']}")
    print(f"\nmanifest {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
