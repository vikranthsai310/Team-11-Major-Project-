"""A5 · How brittle is Gate A when the estimator is wrong? (P6-9)

    python scripts/ablation_a5.py --data data/processed/d1_*.parquet

The simulator assumes perfect estimation (assumption A4): Gate A is checked
against the same per-order costs the ledger would charge. In production the
estimator can be off. This measures what happens when the **true** per-order
size, memory and steps differ from the estimate by ±5 % and ±10 %.

A batch sized from the estimate is then checked against the true costs. Any
batch the estimate called feasible but the true costs make invalid is a Gate A
violation that the ledger would reject outright. This bounds assumption A4 and
answers the question S2 cannot: S2's zero is exact only under perfect estimation.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from batcher.build.estimator import (
    ORDER_MEM,
    ORDER_SIZE_B,
    ORDER_STEPS,
    gate_a,
    max_n_satisfying_gate_a,
)
from batcher.config.params import DEFAULT_SEED
from batcher.data.features import chronological_split, preprocess
from batcher.eval.manifest import write_manifest
from batcher.policy.optimizer import ConstrainedOptimizer
from batcher.policy.static import Greedy
from batcher.sim.env import run_episode
from batcher.sim.episodes import build_episodes
from batcher.sim.orders import fit_arrival_process

ERRORS = [-0.10, -0.05, 0.0, 0.05, 0.10]
LIMIT = 200


def violating_sizes(error: float) -> list[int]:
    """Batch sizes the estimator deems feasible that the true costs make invalid.

    Positive ``error`` means the true cost is higher than estimated — the
    dangerous direction, because the estimator then under-counts.
    """
    nominal_max = max_n_satisfying_gate_a(limit=LIMIT)
    true_size = [ORDER_SIZE_B * (1 + error)] * LIMIT
    true_mem = [ORDER_MEM * (1 + error)] * LIMIT
    true_steps = [ORDER_STEPS * (1 + error)] * LIMIT
    return [n for n in range(1, nominal_max + 1) if not gate_a(n, true_size, true_mem, true_steps)]


def batch_size_distribution(frame, episodes, process, policy) -> Counter:
    sizes: Counter = Counter()
    for episode in episodes:
        if hasattr(policy, "reset"):
            policy.reset()
        result = run_episode(
            episode.blocks(frame),
            policy,
            episode.stream(process, "heavy"),
            episode.rng(),
            episode_id=episode.episode_id,
            policy_name=policy.name,
        )
        sizes.update(result.submissions)
    return sizes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--episodes", type=int, default=6)
    args = parser.parse_args(argv)

    nominal_max = max_n_satisfying_gate_a(limit=LIMIT)
    print(f"nominal Gate A cap: n_max = {nominal_max}\n")

    frame = preprocess(pd.read_parquet(args.data))
    process = fit_arrival_process(frame)
    # Validation split and the heavy arrival rate: heavy is where batches grow
    # large enough to approach the cap, which is the only place A5 can bite.
    episodes = build_episodes(
        frame, chronological_split(frame), which="val", count=args.episodes, seed=DEFAULT_SEED
    )

    distributions = {
        policy.name: batch_size_distribution(frame, episodes, process, policy)
        for policy in (Greedy(), ConstrainedOptimizer(n_min=4))
    }

    rows = []
    for error in ERRORS:
        bad = set(violating_sizes(error))
        cap = nominal_max - len(bad)
        for name, sizes in distributions.items():
            total = sum(sizes.values())
            invalid = sum(count for size, count in sizes.items() if size in bad)
            rows.append(
                {
                    "error": error,
                    "policy": name,
                    "true_cap": cap,
                    "violating_sizes": sorted(bad),
                    "batches": total,
                    "invalid_batches": invalid,
                    "invalid_share": invalid / total if total else 0.0,
                }
            )

    table = pd.DataFrame(rows)
    print(
        table[
            ["error", "policy", "true_cap", "batches", "invalid_batches", "invalid_share"]
        ].to_string(index=False, float_format=lambda v: f"{v:.4f}")
    )

    worst = table[table["error"] == max(ERRORS)]
    print(
        f"\nAt +{max(ERRORS):.0%} under-estimation the true cap falls from {nominal_max} to "
        f"{int(worst['true_cap'].iloc[0])}."
    )
    margin = len(violating_sizes(max(ERRORS)))
    print(
        f"A safety margin of {margin} order(s) below the estimated cap would have made every "
        "batch valid."
    )

    manifest = write_manifest(
        "phase6-ablation-a5",
        seed=DEFAULT_SEED,
        split="val",
        rate="heavy",
        episodes=len(episodes),
        nominal_cap=nominal_max,
        results=table.to_dict("records"),
        recommended_safety_margin=margin,
    )
    (manifest.parent / "a5.json").write_text(
        json.dumps(table.to_dict("records"), indent=2, default=str) + "\n"
    )
    print(f"\nmanifest {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
