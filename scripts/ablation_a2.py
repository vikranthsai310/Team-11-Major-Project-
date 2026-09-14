"""A2, re-specified · Does the learned forecaster help the *policy*? (P4-8)

    python scripts/ablation_a2.py --data data/processed/d1_*.parquet \
        --models experiments/phase3-forecaster/models

A2 as first run compared P2 on E4 against P2 on LightGBM, and was confounded: E4
is flat across the forecast horizon, so P2's "quieter block predicted" branch
never fired and P2-on-E4 was identical to greedy at every N_MIN. That compared a
flat forecast with a varying one, not a naive forecast with a learned one.

This run replaces E4 with :class:`MeanReverting` — equally naive (a rolling mean
and one fitted coefficient) but varying across the horizon — and compares it with
LightGBM on paired validation episodes, with E4 and ORACLE kept as references.
Before any policy result, it reports how often each forecaster lets the branch
fire at all, since that is precisely what the original run got wrong.

Validation split only: the test split has been spent.
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
from batcher.eval.stats import holm_bonferroni, paired_test
from batcher.forecast.base import CachedForecaster, clip
from batcher.forecast.baseline import MeanReverting, MovingAverage, Oracle
from batcher.forecast.evaluate import score_frame
from batcher.forecast.lgbm import load as lgbm_load
from batcher.policy.optimizer import ConstrainedOptimizer
from batcher.sim.env import run_episode
from batcher.sim.episodes import build_episodes
from batcher.sim.orders import fit_arrival_process

N_MIN_FRONTIER = [1, 4, 8, 12, 20]
NAIVE, LEARNED = "meanrev (naive)", "lgbm (P1)"


def fire_rate(predictions: np.ndarray) -> float:
    """Share of blocks where P2's quieter-block test would pass, on clipped values."""
    clipped = np.array([clip(row) for row in predictions])
    return float((np.minimum(clipped[:, 1], clipped[:, 2]) < clipped[:, 0]).mean())


def per_episode(frame, episodes, n_min, process, rate, forecaster) -> pd.DataFrame:
    policy = ConstrainedOptimizer(n_min=n_min)
    rows = []
    for episode in episodes:
        blocks = episode.blocks(frame)
        result = run_episode(
            blocks,
            policy,
            episode.stream(process, rate),
            episode.rng(),
            forecaster=CachedForecaster(forecaster).prepare(blocks),
            episode_id=episode.episode_id,
            policy_name=policy.name,
        )
        if not metrics.conserved(result):
            raise AssertionError(f"order conservation failed in {episode.episode_id}")
        rows.append({"episode_id": episode.episode_id, **metrics.compute(result).as_dict()})
    return pd.DataFrame(rows).set_index("episode_id").sort_index()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--episodes", type=int, default=12)
    parser.add_argument("--rate", default="matched")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)

    frame = build_features(preprocess(pd.read_parquet(args.data)))
    split = chronological_split(frame)
    labels = split.label(frame["abs_slot"])
    train, val = frame[labels == "train"], frame[labels == "val"]
    process = fit_arrival_process(frame)
    episodes = build_episodes(frame, split, which="val", count=args.episodes, seed=args.seed)

    naive = MeanReverting(horizon=FORECAST_HORIZON).fit(train)
    learned = lgbm_load(args.models, horizon=FORECAST_HORIZON)
    if learned.name != "lgbm":
        raise SystemExit("no trained LightGBM forecaster loaded; A2 would compare naive with naive")
    forecasters = {
        NAIVE: naive,
        LEARNED: learned,
        "ma (E4, flat)": MovingAverage(horizon=FORECAST_HORIZON),
        "oracle": Oracle(horizon=FORECAST_HORIZON),
    }
    print(f"MeanReverting phi fitted on train: {naive.phi:.4f}\n")

    # --- 1. Can each forecaster make the branch fire? And how accurate is it? ---
    print("=== forecasters on the validation split ===")
    diagnostics = {}
    for label, forecaster in forecasters.items():
        predictions = forecaster.predict_frame(val)
        scored = score_frame(val, predictions, step=1)
        diagnostics[label] = {
            "quieter_branch_fire_rate": fire_rate(predictions),
            "mae_t1": scored["mae"],
            "dir_t1": scored["dir"],
        }
        d = diagnostics[label]
        print(
            f"  {label:<16} fires {d['quieter_branch_fire_rate']:6.1%}   "
            f"MAE t+1 {d['mae_t1']:.5f}   DIR {d['dir_t1']:.3f}"
        )

    # --- 2. P2 on each forecaster, paired episodes, across N_MIN ----------------
    print(f"\n=== P2 across N_MIN · {len(episodes)} paired validation episodes · {args.rate} ===")
    results: dict[tuple[str, int], pd.DataFrame] = {}
    summary = []
    for n_min in N_MIN_FRONTIER:
        for label, forecaster in forecasters.items():
            table = per_episode(frame, episodes, n_min, process, args.rate, forecaster)
            results[(label, n_min)] = table
            summary.append(
                {
                    "n_min": n_min,
                    "forecaster": label,
                    "l_p95": float(table["l_p95"].median()),
                    "c_user": float(table["c_user"].median()),
                    "batch_n": float(table["batch_n"].median()),
                    "violations": int(table["gate_a_violations"].sum()),
                }
            )
            print(
                f"  N={n_min:<3} {label:<16} L-p95 {summary[-1]['l_p95']:7.1f}   "
                f"C-user {summary[-1]['c_user']:10.0f}   batch {summary[-1]['batch_n']:5.2f}"
            )

    # --- 3. A2 proper: learned minus naive, paired, Holm across the family -------
    tests = []
    for n_min in N_MIN_FRONTIER:
        for metric in ("l_p95", "c_user"):
            a = results[(LEARNED, n_min)][metric]
            b = results[(NAIVE, n_min)][metric]
            common = a.index.intersection(b.index)
            tests.append(
                paired_test(
                    a.loc[common].to_numpy(),
                    b.loc[common].to_numpy(),
                    metric=f"{metric}@N={n_min}",
                    candidate_name=LEARNED,
                    reference_name=NAIVE,
                )
            )
    tests = holm_bonferroni(tests)

    print("\n=== A2 · LightGBM minus mean-reverting naive (negative = learned is better) ===")
    for t in tests:
        p = t.p_adjusted if t.p_adjusted is not None else float("nan")
        print(
            f"  {t.metric:<12} diff {t.median_difference:+10.2f} "
            f"[{t.ci_low:+.2f}, {t.ci_high:+.2f}]  p_adj {p:.4f}  "
            f"{'SIGNIFICANT' if t.significant else ''}"
        )

    violations = sum(row["violations"] for row in summary)
    print(f"\n  Gate A violations across the run: {violations}")

    manifest = write_manifest(
        "phase6-ablation-a2",
        seed=args.seed,
        dataset_checksum=sha256_of(args.data),
        split="val",
        rate=args.rate,
        episodes=len(episodes),
        naive_baseline="MeanReverting",
        meanrev_phi=naive.phi,
        forecaster_diagnostics=diagnostics,
        gate_a_violations=violations,
    )
    (manifest.parent / "a2.json").write_text(
        json.dumps(
            {
                "phi": naive.phi,
                "diagnostics": diagnostics,
                "summary": summary,
                "tests": [t.as_dict() for t in tests],
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
