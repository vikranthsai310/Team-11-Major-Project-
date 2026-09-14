"""P6-4 · Regenerate the evaluation figures F5, F6 and F8 from a manifest's outputs.

    python scripts/make_figures.py --experiment phase6-final-evaluation

Figures are never hand-edited. Deleting ``figures/`` and re-running this must
reproduce them exactly, which is only possible if every number comes from the
committed experiment outputs rather than from a notebook's state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from batcher.eval.plots import figure_f5, figure_f6, figure_f8
from batcher.eval.stats import median_ci


def per_episode(results: pd.DataFrame) -> pd.DataFrame:
    numeric = [c for c in results.columns if results[c].dtype.kind in "fiu" and c != "seed"]
    return results.groupby(["policy", "rate", "episode_id"], as_index=False)[numeric].mean()


def point_estimates(episodes: pd.DataFrame, rate: str) -> pd.DataFrame:
    rows = []
    for policy, group in episodes[episodes["rate"] == rate].groupby("policy"):
        l_med, l_lo, l_hi = median_ci(group["l_p95"].to_numpy())
        c_med, c_lo, c_hi = median_ci(group["c_user"].to_numpy())
        rows.append(
            {
                "policy": policy,
                "rate": rate,
                "l_p95": l_med,
                "l_p95_lo": l_lo,
                "l_p95_hi": l_hi,
                "c_user": c_med,
                "c_user_lo": c_lo,
                "c_user_hi": c_hi,
            }
        )
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", default="phase6-final-evaluation")
    parser.add_argument("--out", type=Path, default=Path("figures"))
    args = parser.parse_args(argv)

    root = Path("experiments") / args.experiment
    manifest = json.loads((root / "manifest.json").read_text())
    results = pd.read_parquet(root / "episode_metrics.parquet")
    latencies = pd.read_parquet(root / "latencies.parquet")
    episodes = per_episode(results)

    provenance = (
        f"{manifest['split']} split · {manifest['episodes']} paired episodes · "
        f"P3 seeds {manifest['p3_seeds']} at {manifest['p3_training_steps']:,} steps · "
        f"dataset {str(manifest['dataset_checksum'])[:12]}"
    )

    matched = point_estimates(episodes, "matched")
    all_rates = pd.concat([point_estimates(episodes, r) for r in ("light", "matched", "heavy")])

    written = [
        figure_f5(matched, args.out, provenance + " · matched rate"),
        figure_f6(latencies, args.out, provenance + " · matched rate"),
        figure_f8(all_rates, args.out, provenance),
    ]
    for paths in written:
        print(f"  {paths['figure']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
