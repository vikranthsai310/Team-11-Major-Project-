"""Phase 1 exploratory analysis and the predictability decision (P1-12 … P1-16).

    python scripts/analyze_congestion.py --data data/processed/d1_*.parquet --out figures/

Produces figures F1, F2 and F3, and prints the numbers that decide whether the
project's forecasting premise survives. Read this output before building the
forecaster — it is the R4 gate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from batcher.config.params import FORECAST_WINDOW_K
from batcher.data.collector import sha256_of
from batcher.data.features import chronological_split, preprocess
from batcher.eval.manifest import write_manifest
from batcher.eval.plots import (
    BAND_LOW,
    congestion_episodes,
    congestion_shares,
    figure_f1,
    figure_f2,
    figure_f3,
)

EXPERIMENT_ID = "phase1-predictability"

# A lag-1 predictor beating the global mean by less than this is, for practical
# purposes, a random walk at this horizon: forecasting adds nothing the policy
# can act on, and the R4 fallback applies (docs/12-ROADMAP.md Phase 1).
CLEARLY_BETTER = 0.20
BARELY_BETTER = 0.05

# Below this, size-based fill is not a valid proxy for execution-based fill and
# the R1 trigger fires (docs/18-TODO.md P1-16).
PROXY_CORRELATION_FLOOR = 0.70


def autocorrelation(series: pd.Series, max_lag: int) -> dict[str, float]:
    # String keys so the value survives a JSON round-trip unchanged.
    return {str(lag): float(series.autocorr(lag)) for lag in range(1, max_lag + 1)}


def mean_absolute_error(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - predicted)))


def predictability(frame: pd.DataFrame) -> dict:
    """The five numbers of P1-16, computed on the real chronological test split."""
    split = chronological_split(frame)
    labels = split.label(frame["abs_slot"])

    train = frame[labels == "train"]
    test = frame[labels == "test"].reset_index(drop=True)

    actual = test["fill_pct"].to_numpy()[1:]
    lag1 = test["fill_pct"].to_numpy()[:-1]
    global_mean = np.full_like(actual, train["fill_pct"].mean())
    rolling = test["fill_pct"].rolling(FORECAST_WINDOW_K, min_periods=1).mean().to_numpy()[:-1]

    mae_lag1 = mean_absolute_error(actual, lag1)
    mae_mean = mean_absolute_error(actual, global_mean)
    mae_e4 = mean_absolute_error(actual, rolling)
    improvement = 1 - (mae_lag1 / mae_mean) if mae_mean else 0.0

    if improvement >= CLEARLY_BETTER:
        verdict = "predictable"
    elif improvement >= BARELY_BETTER:
        verdict = "weakly predictable"
    else:
        verdict = "close to a random walk — take the R4 fallback"

    return {
        "split": {
            "train_end_slot": split.train_end_slot,
            "val_end_slot": split.val_end_slot,
            "test_rows": int(len(test)),
        },
        "autocorrelation": autocorrelation(frame["fill_pct"], FORECAST_WINDOW_K),
        "mae_lag1_persistence": mae_lag1,
        "mae_global_mean": mae_mean,
        f"mae_rolling_mean_k{FORECAST_WINDOW_K}": mae_e4,
        "lag1_improvement_over_mean": improvement,
        "verdict": verdict,
    }


def describe_window(sampled: pd.DataFrame) -> dict:
    """Correlation *and* dominance for one sampled window.

    Correlation alone cannot answer the question ADR-005 actually asks. The proxy
    exists so that Gate B can be reasoned about from size; what matters is whether
    size is the dimension that binds first, which a correlation coefficient does
    not measure.
    """
    nearest = sampled[["fill_pct", "mem_pct", "step_pct"]].idxmax(axis=1)
    size_binds = (nearest == "fill_pct").mean()
    mem_only = ((sampled["mem_pct"] > BAND_LOW) & (sampled["fill_pct"] <= BAND_LOW)).sum()

    return {
        "blocks": int(len(sampled)),
        "start": str(sampled["block_time"].min()),
        "end": str(sampled["block_time"].max()),
        "mean_fill": float(sampled["fill_pct"].mean()),
        "share_above_80": float((sampled["fill_pct"] > BAND_LOW).mean()),
        "share_without_scripts": float((sampled["mem_exunits"] == 0).mean()),
        "corr_size_vs_mem": float(sampled["fill_pct"].corr(sampled["mem_pct"])),
        "corr_size_vs_steps": float(sampled["fill_pct"].corr(sampled["step_pct"])),
        "spearman_size_vs_mem": float(
            sampled["fill_pct"].corr(sampled["mem_pct"], method="spearman")
        ),
        "max_mem_pct": float(sampled["mem_pct"].max()),
        "max_step_pct": float(sampled["step_pct"].max()),
        "share_size_binds_first": float(size_binds),
        "blocks_where_only_memory_binds": int(mem_only),
    }


def exunit_proxy_correlation(frame: pd.DataFrame) -> dict:
    """Does size-based fill stand in for execution-based fill? (ADR-005 / R1)

    Reported per contiguous sampled window, because a single pooled correlation
    hides the regime a window was drawn from — and the regime is the point: a
    quiet window contains almost no blocks near any capacity limit.
    """
    sampled = frame[frame["exunits_source"] == "per_tx"]
    if len(sampled) < 100:
        return {
            "sampled_rows": int(len(sampled)),
            "status": "not collected — run collect.py --exunits-sample 2",
        }

    breaks = sampled["block_height"].diff() > 1
    windows = [
        describe_window(group) for _, group in sampled.groupby(breaks.cumsum()) if len(group) >= 100
    ]

    overall = describe_window(sampled)
    worst = min(overall["corr_size_vs_mem"], overall["corr_size_vs_steps"])

    return {
        "sampled_rows": int(len(sampled)),
        "windows": windows,
        "pooled": overall,
        "corr_size_vs_mem": overall["corr_size_vs_mem"],
        "corr_size_vs_steps": overall["corr_size_vs_steps"],
        "status": "ok" if worst >= PROXY_CORRELATION_FLOOR else "R1 TRIGGER — proxy invalid",
    }


def _window_lines(proxy: dict) -> list[str]:
    windows = proxy.get("windows") or []
    if not windows:
        return []

    lines = [
        "",
        f"  {'window':<12} {'blocks':>7} {'mean fill':>10} {'>80%':>7} "
        f"{'no script':>10} {'r(size,mem)':>12} {'size binds':>11} {'mem-only':>9}",
    ]
    for window in windows:
        label = window["start"][:10]
        lines.append(
            f"  {label:<12} {window['blocks']:>7,} {window['mean_fill']:>10.2%} "
            f"{window['share_above_80']:>7.2%} {window['share_without_scripts']:>10.1%} "
            f"{window['corr_size_vs_mem']:>12.3f} {window['share_size_binds_first']:>11.1%} "
            f"{window['blocks_where_only_memory_binds']:>9}"
        )
    lines.append("")
    return lines


def report(results: dict) -> str:
    shares = results["congestion"]
    episodes = results["episodes"]
    pred = results["predictability"]
    proxy = results["exunits_proxy"]
    autocorr = pred["autocorrelation"]

    lines = [
        "PHASE 1 · PREDICTABILITY REPORT",
        "=" * 62,
        "",
        f"dataset            {results['dataset']}",
        f"rows               {results['rows']:,}",
        f"window             {results['window']['start_time']} .. {results['window']['end_time']}",
        "",
        "CONGESTION (F1, F2)",
        f"  mean fill              {shares['mean_fill']:.2%}",
        f"  median fill            {shares['median_fill']:.2%}",
        f"  95th percentile        {shares['p95_fill']:.2%}",
        f"  max fill               {shares['max_fill']:.2%}",
        f"  blocks in 80-90 % band {shares['share_in_band']:.3%}",
        f"  blocks above 80 %      {shares['share_above_80']:.3%}   <- goes in the abstract",
        f"  blocks above 90 %      {shares['share_above_90']:.3%}",
        "",
        "EPISODE STRUCTURE — is congestion sustained or interleaved?",
        f"  congested blocks       {episodes['congested_blocks']:,}",
        f"  contiguous episodes    {episodes['episodes']:,}"
        f"   (mean run {episodes.get('mean_run_blocks', 0):.1f} blocks)",
        f"  longest run            {episodes['longest_run_blocks']} blocks",
        f"  days with any          {episodes.get('days_with_any', 0)}"
        f" of {episodes.get('days_total', 0)}",
        f"  in the busiest 5 days  {episodes.get('share_in_top_five_days', 0):.0%}",
        "",
        "PREDICTABILITY (the R4 gate)",
        f"  autocorrelation lag 1  {autocorr['1']:.4f}",
        f"  autocorrelation lag 5  {autocorr['5']:.4f}",
        f"  autocorrelation lag 20 {autocorr['20']:.4f}",
        f"  MAE lag-1 persistence  {pred['mae_lag1_persistence']:.5f}",
        f"  MAE global mean        {pred['mae_global_mean']:.5f}",
        f"  MAE rolling mean k=20  {pred[f'mae_rolling_mean_k{FORECAST_WINDOW_K}']:.5f}",
        f"  lag-1 improvement      {pred['lag1_improvement_over_mean']:.1%}",
        f"  VERDICT                {pred['verdict']}",
        "",
        "EXECUTION-UNIT PROXY (ADR-005 / R1)",
        f"  sampled rows           {proxy['sampled_rows']:,}",
        *_window_lines(proxy),
        f"  status                 {proxy['status']}",
        "",
        "The team must now record an explicit written decision (P1-16).",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("figures"))
    parser.add_argument("--n-max", type=int, default=30, help="Gate A batch ceiling for F3")
    args = parser.parse_args(argv)

    frame = preprocess(pd.read_parquet(args.data))
    checksum = sha256_of(args.data)
    provenance = (
        f"{args.data.name} · n={len(frame):,} · sha256 {checksum[:12]} · "
        f"chronological 70/15/15 split"
    )

    results = {
        "dataset": args.data.name,
        "dataset_checksum": checksum,
        "rows": int(len(frame)),
        "window": {
            "start_time": str(frame["block_time"].min()),
            "end_time": str(frame["block_time"].max()),
        },
        "congestion": congestion_shares(frame),
        "episodes": congestion_episodes(frame),
        "predictability": predictability(frame),
        "exunits_proxy": exunit_proxy_correlation(frame),
    }

    figures = {
        "F1": figure_f1(frame, args.out, provenance),
        "F2": figure_f2(frame, args.out, provenance),
        # F3 is analytic: it derives from the cost model, not from this dataset,
        # so citing the dataset in its provenance would misdescribe it.
        "F3": figure_f3(args.out, args.n_max, "analytic, from the cost model (docs/07 §5)"),
    }

    summary = report(results)
    print(summary)

    manifest_path = write_manifest(
        EXPERIMENT_ID,
        seed=0,
        dataset_checksum=checksum,
        results=results,
        figures={name: {k: str(v) for k, v in paths.items()} for name, paths in figures.items()},
    )
    out_dir = manifest_path.parent
    (out_dir / "predictability.json").write_text(json.dumps(results, indent=2, default=str) + "\n")
    (out_dir / "predictability.txt").write_text(summary + "\n")

    print(f"\nfigures  {args.out}")
    print(f"report   {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
