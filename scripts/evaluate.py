"""Run policies over paired episodes (P4-5, used from Phase 2 onward).

    python scripts/evaluate.py --policy all --episodes 20 --rate matched --seed 42

Every policy sees an identical D1 window and an identical order stream per
episode, so differences are attributable to the decision logic and the paired
statistics are valid.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from batcher.config.params import DEFAULT_SEED
from batcher.data.collector import sha256_of
from batcher.data.features import chronological_split, preprocess
from batcher.eval import metrics
from batcher.eval.manifest import write_manifest
from batcher.policy.static import FixedInterval, FixedSize, Greedy, Null
from batcher.sim.env import run_episode
from batcher.sim.episodes import build_episodes
from batcher.sim.orders import ARRIVAL_RATES, fit_arrival_process

BASELINES = {
    "e1": lambda **kw: FixedSize(m=kw.get("m", 20)),
    "e2": lambda **kw: FixedInterval(t=kw.get("t", 60)),
    "e3": lambda **kw: Greedy(),
    "null": lambda **kw: Null(),
}

_TUNED_VALUE = re.compile(r"\((\w)=(\d+)\)")


def load_tuned(path: Path | None) -> dict:
    """Read the values chosen by the validation sweep (P2-18).

    Comparing against an untuned baseline is a straw man, so the tuned values are
    loaded from the tuning manifest rather than retyped, and are reported.
    """
    if path is None:
        return {}
    manifest = json.loads(path.read_text())
    tuned = {}
    for name, chosen in manifest.get("tuned", {}).items():
        match = _TUNED_VALUE.search(chosen["policy"])
        if match:
            tuned[name] = {match.group(1).lower(): int(match.group(2))}
    return tuned


def build_policies(which: str, tuned: dict) -> list:
    names = list(BASELINES) if which == "all" else [which]
    return [BASELINES[name](**tuned.get(name, {})) for name in names]


def run(
    frame: pd.DataFrame,
    policies: list,
    episodes: list,
    rate: str,
    process,
) -> pd.DataFrame:
    rows = []
    for episode in episodes:
        blocks = episode.blocks(frame)
        for policy in policies:
            if hasattr(policy, "reset"):
                policy.reset()
            result = run_episode(
                blocks,
                policy,
                episode.stream(process, rate),
                episode.rng(),
                episode_id=episode.episode_id,
                policy_name=policy.name,
            )
            if not metrics.conserved(result):
                raise AssertionError(f"order conservation failed in {episode.episode_id}")

            rows.append(
                {
                    "episode_id": episode.episode_id,
                    "policy": policy.name,
                    "rate": rate,
                    "congested_share": float((blocks["fill_pct"] > 0.80).mean()),
                    **metrics.compute(result).as_dict(),
                }
            )
    return pd.DataFrame(rows)


def summarise(results: pd.DataFrame) -> pd.DataFrame:
    return (
        results.groupby("policy")
        .agg(
            l_mean=("l_mean", "median"),
            l_p95=("l_p95", "median"),
            c_user=("c_user", "median"),
            x_rate=("x_rate", "median"),
            throughput=("throughput", "median"),
            f_jain=("f_jain", "median"),
            lock=("lock_occupancy", "median"),
            batch_n=("batch_n", "median"),
            violations=("gate_a_violations", "sum"),
        )
        .sort_values("l_p95")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--policy", default="all", choices=[*BASELINES, "all"])
    parser.add_argument("--episodes", type=int, default=20)
    parser.add_argument("--rate", default="matched", choices=[*ARRIVAL_RATES, "all"])
    parser.add_argument("--split", default="val", choices=["train", "val", "test"])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--experiment", default="phase2-baselines")
    parser.add_argument(
        "--tuned-from",
        type=Path,
        default=None,
        help="tuning manifest whose selected M and T should be used",
    )
    args = parser.parse_args(argv)

    frame = preprocess(pd.read_parquet(args.data))
    split = chronological_split(frame)
    process = fit_arrival_process(frame)
    episodes = build_episodes(frame, split, which=args.split, count=args.episodes, seed=args.seed)

    rates = list(ARRIVAL_RATES) if args.rate == "all" else [args.rate]
    tuned = load_tuned(args.tuned_from)
    policies = build_policies(args.policy, tuned)
    if tuned:
        print(f"tuned baselines in use: {tuned}")

    frames = [run(frame, policies, episodes, rate, process) for rate in rates]
    results = pd.concat(frames, ignore_index=True)

    for rate in rates:
        print(f"\n=== rate: {rate} · split: {args.split} · {len(episodes)} episodes ===")
        print(summarise(results[results["rate"] == rate]).round(4).to_string())

    manifest = write_manifest(
        args.experiment,
        seed=args.seed,
        dataset_checksum=sha256_of(args.data),
        split=args.split,
        rates=rates,
        episodes=len(episodes),
        arrival_process=process.to_manifest(),
        tuned_baselines=tuned,
        policies=[policy.name for policy in policies],
    )
    results.to_parquet(manifest.parent / "episode_metrics.parquet", index=False)
    print(f"\nmanifest {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
