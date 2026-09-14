"""P6-2, P6-3, P6-10 · Paired statistics, the main results table, and the S1–S6 verdicts.

    python scripts/run_stats.py --experiment phase6-final-evaluation

Reads ``episode_metrics.parquet`` from the one-shot test evaluation. Nothing here
re-runs a policy, so it can be re-run freely without touching the test split
again.

**P3 is seed-averaged per episode before pairing.** Each episode then has one P3
value, paired against one value per baseline, which keeps the Wilcoxon test's
unit of analysis the episode. Across-seed spread is reported separately.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from batcher.eval.stats import holm_bonferroni, median_ci, paired_test

PRIMARY = ["l_mean", "l_p95", "c_user"]
TABLE_METRICS = ["l_mean", "l_p95", "c_user", "x_rate", "throughput", "f_jain"]
LOWER_IS_BETTER = {"l_mean", "l_p95", "c_user", "x_rate", "w_max"}
STATIC = ["e1(M=16)", "e2(T=20)", "e3(greedy)"]
PROPOSED = ["p2(D=120,N=1)", "p2(D=120,N=4)", "p3(dqn)"]
ORDER = ["null", *STATIC, *PROPOSED, "oracle(D=120,N=4)"]


def per_episode(results: pd.DataFrame) -> pd.DataFrame:
    """One row per (policy, rate, episode). P3's five seeds collapse to their mean."""
    numeric = [c for c in results.columns if results[c].dtype.kind in "fiu" and c != "seed"]
    return (
        results.groupby(["policy", "rate", "episode_id"], as_index=False)[numeric]
        .mean()
        .sort_values(["policy", "rate", "episode_id"])
    )


def best_static(episodes: pd.DataFrame, rate: str, metric: str) -> str:
    """The strongest static baseline on this metric at this rate — the comparator
    S3 names. Chosen by median, so one outlier episode cannot decide it."""
    subset = episodes[(episodes["rate"] == rate) & (episodes["policy"].isin(STATIC))]
    medians = subset.groupby("policy")[metric].median()
    return medians.idxmin() if metric in LOWER_IS_BETTER else medians.idxmax()


def aligned(episodes, rate, policy, metric):
    subset = episodes[(episodes["rate"] == rate) & (episodes["policy"] == policy)]
    return subset.set_index("episode_id")[metric].sort_index()


def paired_family(episodes: pd.DataFrame, rate: str) -> list:
    """Every proposed policy against the best static baseline, per primary metric,
    with Holm–Bonferroni applied across the whole family at this rate."""
    results = []
    for metric in PRIMARY:
        reference = best_static(episodes, rate, metric)
        ref = aligned(episodes, rate, reference, metric)
        for policy in PROPOSED:
            cand = aligned(episodes, rate, policy, metric)
            common = ref.index.intersection(cand.index)
            results.append(
                paired_test(
                    cand.loc[common].to_numpy(),
                    ref.loc[common].to_numpy(),
                    metric=metric,
                    candidate_name=policy,
                    reference_name=reference,
                )
            )
    return holm_bonferroni(results)


def main_table(episodes: pd.DataFrame, rate: str) -> pd.DataFrame:
    rows = []
    for policy in ORDER:
        subset = episodes[(episodes["rate"] == rate) & (episodes["policy"] == policy)]
        if subset.empty:
            continue
        cells = {"policy": policy}
        for metric in TABLE_METRICS:
            median, low, high = median_ci(subset[metric].to_numpy())
            cells[metric] = median
            cells[f"{metric}_ci"] = f"[{low:,.2f}, {high:,.2f}]"
        rows.append(cells)
    return pd.DataFrame(rows)


def to_markdown(table: pd.DataFrame, tests: list, rate: str) -> str:
    significant = {
        (r.candidate, r.metric) for r in tests if r.significant and r.median_difference < 0
    }
    header = "| Policy | " + " | ".join(TABLE_METRICS) + " |"
    lines = [f"### Rate: {rate}", "", header, "|" + "---|" * (len(TABLE_METRICS) + 1)]

    best = {}
    for metric in TABLE_METRICS:
        candidates = table[~table["policy"].isin(["null", "oracle(D=120,N=4)"])]
        column = candidates[metric]
        best[metric] = column.min() if metric in LOWER_IS_BETTER else column.max()

    for record in table.to_dict("records"):
        cells = []
        for metric in TABLE_METRICS:
            text = f"{record[metric]:,.2f} {record[f'{metric}_ci']}"
            if np.isclose(record[metric], best[metric]) and record["policy"] not in (
                "null",
                "oracle(D=120,N=4)",
            ):
                text = f"**{text}**"
            if (record["policy"], metric) in significant:
                text += " †"
            cells.append(text)
        lines.append(f"| {record['policy']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Median [95 % bootstrap CI]. **Bold** best non-reference value. "
        "† significant improvement over the best static baseline "
        "(Wilcoxon, Holm–Bonferroni, CI excluding zero).",
        "",
    ]
    return "\n".join(lines)


def verdicts(results: pd.DataFrame, episodes: pd.DataFrame, tests_by_rate: dict) -> list[dict]:
    """S2–S6 from the evaluation. S1 is the forecaster's and comes from Phase 3."""
    out = []
    violations = int(results["gate_a_violations"].sum())
    out.append(
        {
            "id": "S2",
            "criterion": "Gate A violations exactly zero",
            "measured": violations,
            "pass": violations == 0,
        }
    )

    for rate, tests in tests_by_rate.items():
        best_p95 = [
            r for r in tests if r.metric == "l_p95" and r.significant and r.median_difference < 0
        ]
        out.append(
            {
                "id": "S3",
                "rate": rate,
                "criterion": "L-p95 significantly below best static, CI excluding zero",
                "measured": [
                    f"{r.candidate}: {r.median_difference:+.1f} [{r.ci_low:+.1f}, {r.ci_high:+.1f}]"
                    for r in tests
                    if r.metric == "l_p95"
                ],
                "pass": bool(best_p95),
            }
        )

        for policy in PROPOSED:
            ref_x = best_static(episodes, rate, "x_rate")
            _, lo, hi = median_ci(aligned(episodes, rate, policy, "x_rate").to_numpy())
            ref_med, rlo, rhi = median_ci(aligned(episodes, rate, ref_x, "x_rate").to_numpy())
            out.append(
                {
                    "id": "S4",
                    "rate": rate,
                    "policy": policy,
                    "criterion": "X-rate not worse than best static (CI overlapping or lower)",
                    "measured": f"[{lo:.4f}, {hi:.4f}] vs [{rlo:.4f}, {rhi:.4f}]",
                    "pass": bool(lo <= rhi),
                }
            )

            ref_f = best_static(episodes, rate, "f_jain")
            _, flo, fhi = median_ci(aligned(episodes, rate, policy, "f_jain").to_numpy())
            _, frlo, frhi = median_ci(aligned(episodes, rate, ref_f, "f_jain").to_numpy())
            out.append(
                {
                    "id": "S6",
                    "rate": rate,
                    "policy": policy,
                    "criterion": "F-jain not worse than best static (CI overlapping or higher)",
                    "measured": f"[{flo:.3f}, {fhi:.3f}] vs [{frlo:.3f}, {frhi:.3f}]",
                    "pass": bool(fhi >= frlo),
                }
            )

        points = episodes[episodes["rate"] == rate].groupby("policy")[["l_p95", "c_user"]].median()
        statics = points.loc[points.index.intersection(STATIC)]
        dominating = []
        for policy in PROPOSED:
            if policy not in points.index:
                continue
            p = points.loc[policy]
            for name, s in statics.iterrows():
                if (
                    p.l_p95 <= s.l_p95
                    and p.c_user <= s.c_user
                    and (p.l_p95 < s.l_p95 or p.c_user < s.c_user)
                ):
                    dominating.append(f"{policy} > {name}")
        out.append(
            {
                "id": "S5",
                "rate": rate,
                "criterion": "a proposed policy Pareto-dominates a static baseline (medians)",
                "measured": dominating or "none",
                "pass": bool(dominating),
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", default="phase6-final-evaluation")
    args = parser.parse_args(argv)

    root = Path("experiments") / args.experiment
    results = pd.read_parquet(root / "episode_metrics.parquet")
    episodes = per_episode(results)

    tests_by_rate, markdown = {}, ["# Results — test split, paired episodes", ""]
    for rate in ["light", "matched", "heavy"]:
        tests = paired_family(episodes, rate)
        tests_by_rate[rate] = tests
        markdown.append(to_markdown(main_table(episodes, rate), tests, rate))

        print(f"\n=== {rate} · proposed vs best static (Holm-adjusted) ===")
        for r in tests:
            flag = "SIGNIFICANT" if r.significant else ""
            print(
                f"  {r.metric:<7} {r.candidate:<15} vs {r.reference:<11} "
                f"diff {r.median_difference:+11.2f} [{r.ci_low:+.2f}, {r.ci_high:+.2f}] "
                f"p_adj {r.p_adjusted if r.p_adjusted is not None else float('nan'):.4f} {flag}"
            )

    seed_spread = (
        results[results["policy"] == "p3(dqn)"]
        .groupby(["rate", "seed"])[["l_p95", "c_user"]]
        .median()
        .groupby("rate")
        .agg(["mean", "std"])
    )
    print("\n=== P3 across seeds (median per seed, then mean ± sd) ===")
    print(seed_spread.round(2).to_string())

    verdict = verdicts(results, episodes, tests_by_rate)
    print("\n=== verdicts ===")
    for v in verdict:
        where = f"[{v.get('rate', '')}{' ' + v['policy'] if 'policy' in v else ''}]"
        print(f"  {v['id']} {where:<28} {'PASS' if v['pass'] else 'FAIL'}  {v['measured']}")

    # The table always lands beside its own evaluation. Only the final test-split
    # run is copied into tables/, which is what the report reads — a smoke run on
    # validation once overwrote it with numbers that looked like real results.
    (root / "main_results.md").write_text("\n".join(markdown), encoding="utf-8")
    if args.experiment == "phase6-final-evaluation":
        Path("tables").mkdir(exist_ok=True)
        (Path("tables") / "main_results.md").write_text("\n".join(markdown), encoding="utf-8")
    (root / "stats.json").write_text(
        json.dumps(
            {
                "tests": {
                    rate: [t.as_dict() for t in tests] for rate, tests in tests_by_rate.items()
                },
                "verdicts": verdict,
                "p3_seed_spread": json.loads(seed_spread.to_json()),
            },
            indent=2,
            default=str,
        )
        + "\n"
    )
    print(f"\ntables/main_results.md and {root / 'stats.json'} written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
