"""Does transaction chaining lift the one-batch-per-block ceiling? (validation split only)

    python scripts/chaining_eval.py
    python scripts/chaining_eval.py --episodes 10 --depths 1 2 3

Heavy-load diagnosis on validation days found no batch stuck behind a full block
(no expiries) but 7-10 % of submissions leaving a backlog beyond one Gate A batch:
the ceiling is one batch per decision point, not congestion. This script replays the
same validation episodes Phase 8 uses at chain depths 1 (the recorded simulator),
2 and 3 for P2 (N=4) and greedy, and records latency, the deadline view, cost and
expiry. The test split is never opened.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from batcher.config.params import D_MAX, DEFAULT_SEED, FORECAST_HORIZON
from batcher.eval import metrics

EXPERIMENT = "phase8-chaining"
SPLIT = "val"  # never "test"
RATES = ("matched", "heavy")
COLUMNS = ["l_p95", "l_p95_all", "late_share", "overshoot", "x_rate", "c_user", "throughput"]


def summarise(result) -> dict:
    row = metrics.compute(result).as_dict()
    latencies = [order.latency for order in result.settled]
    waits = [d["oldest_wait"] for d in result.decisions if d["action"] == "SUBMIT"]
    row.update(
        overshoot=max(0, max(waits) - D_MAX) if waits else None,
        late_share=float(np.mean([lat > D_MAX for lat in latencies])) if latencies else None,
        batches_per_decision_block=(
            float(np.mean(list(_submits_per_block(result).values())))
            if result.submissions
            else None
        ),
    )
    return row


def _submits_per_block(result) -> dict[int, int]:
    counts: dict[int, int] = {}
    for d in result.decisions:
        if d["action"] == "SUBMIT" and d["n"]:
            counts[d["abs_slot"]] = counts.get(d["abs_slot"], 0) + 1
    return counts


def fmt(value, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "–"
    return f"{value:,.{digits}f}"


def markdown(summary: list[dict], episodes: int, label: str) -> str:
    lines = [
        "# Phase 8 · Transaction chaining (validation split)",
        "",
        f"{episodes} validation episodes per rate, `build_episodes(seed={DEFAULT_SEED})`, "
        f"forecaster: {label}. Medians over episodes. Depth 1 is the recorded simulator.",
        "",
        "| rate | policy | depth | L-p95 | L-p95 all | late share | overshoot | X-rate "
        "| C-user | throughput | batches/decision block |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in summary:
        lines.append(
            f"| {row['rate']} | {row['policy']} | {row['depth']} | {fmt(row['l_p95'])} | "
            f"{fmt(row['l_p95_all'])} | {fmt(row['late_share'], 3)} | {fmt(row['overshoot'], 0)} | "
            f"{fmt(row['x_rate'], 3)} | {fmt(row['c_user'], 0)} | {fmt(row['throughput'], 1)} | "
            f"{fmt(row['batches_per_decision_block'], 2)} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=None)
    parser.add_argument("--models", type=Path, default=Path("experiments/phase3-forecaster/models"))
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--depths", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--rates", nargs="+", default=list(RATES))
    args = parser.parse_args(argv)

    from batcher.data.collector import sha256_of
    from batcher.data.features import build_features, chronological_split, preprocess
    from batcher.forecast.base import CachedForecaster
    from batcher.forecast.lgbm import load as lgbm_load
    from batcher.policy.optimizer import ConstrainedOptimizer
    from batcher.policy.static import Greedy
    from batcher.sim.env import run_episode
    from batcher.sim.episodes import build_episodes
    from batcher.sim.orders import fit_arrival_process

    data = args.data or next(iter(sorted(Path("data/processed").glob("d1_blocks_*.parquet"))), None)
    if data is None or not Path(data).exists():
        print("D1 dataset not found under data/processed/; nothing to measure.")
        return 1

    started = time.perf_counter()
    frame = build_features(preprocess(pd.read_parquet(data)))
    process = fit_arrival_process(frame)
    episodes = build_episodes(
        frame, chronological_split(frame), which=SPLIT, count=args.episodes, seed=DEFAULT_SEED
    )
    forecaster = lgbm_load(args.models, horizon=FORECAST_HORIZON)
    label = getattr(forecaster, "label", forecaster.name)
    print(f"{len(episodes)} {SPLIT} episodes · rates {args.rates} · depths {args.depths} · {label}")

    rows = []
    for index, episode in enumerate(episodes):
        blocks = episode.blocks(frame)
        prepared = CachedForecaster(forecaster).prepare(blocks)
        for rate in args.rates:
            for depth in args.depths:
                for name, policy in (
                    ("p2(N=4)", ConstrainedOptimizer(n_min=4)),
                    ("e3(greedy)", Greedy()),
                ):
                    result = run_episode(
                        blocks,
                        policy,
                        episode.stream(process, rate),
                        episode.rng(),
                        forecaster=prepared,
                        episode_id=episode.episode_id,
                        policy_name=name,
                        chain_depth=depth,
                    )
                    if not metrics.conserved(result):
                        raise AssertionError(f"conservation failed: {name} depth {depth}")
                    rows.append(
                        {
                            "episode": episode.episode_id,
                            "rate": rate,
                            "policy": name,
                            "depth": depth,
                            **summarise(result),
                        }
                    )
        print(
            f"  episode {index + 1}/{len(episodes)} done · {time.perf_counter() - started:.0f} s",
            flush=True,
        )

    table = pd.DataFrame(rows)
    summary = []
    for (rate, policy, depth), group in table.groupby(["rate", "policy", "depth"], sort=False):
        entry = {"rate": rate, "policy": policy, "depth": int(depth)}
        for column in [*COLUMNS, "batches_per_decision_block"]:
            values = pd.to_numeric(group[column], errors="coerce").dropna()
            entry[column] = float(values.median()) if len(values) else None
        summary.append(entry)

    out_dir = Path("experiments") / EXPERIMENT
    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_dir / "episode_metrics.csv", index=False)
    (out_dir / "results.json").write_text(
        json.dumps(
            {"split": SPLIT, "episodes": len(episodes), "forecaster": label, "summary": summary},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "results.md").write_text(markdown(summary, len(episodes), label), encoding="utf-8")

    from batcher.eval.manifest import write_manifest

    write_manifest(
        EXPERIMENT,
        seed=DEFAULT_SEED,
        dataset_checksum=sha256_of(Path(data)),
        split=SPLIT,
        episodes=len(episodes),
        rates=list(args.rates),
        depths=list(args.depths),
        forecaster=label,
        runtime_seconds=round(time.perf_counter() - started, 1),
    )
    print((out_dir / "results.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
