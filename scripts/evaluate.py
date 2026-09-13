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

from batcher.config.params import DEFAULT_SEED, FORECAST_HORIZON
from batcher.data.collector import sha256_of
from batcher.data.features import build_features, chronological_split, preprocess
from batcher.eval import metrics
from batcher.eval.manifest import write_manifest
from batcher.forecast.base import CachedForecaster
from batcher.forecast.baseline import MovingAverage, Oracle
from batcher.forecast.lgbm import load as lgbm_load
from batcher.policy.optimizer import ConstrainedOptimizer, OracleOptimizer
from batcher.policy.static import FixedInterval, FixedSize, Greedy, Null
from batcher.sim.env import run_episode
from batcher.sim.episodes import build_episodes
from batcher.sim.orders import ARRIVAL_RATES, fit_arrival_process

POLICIES = {
    "e1": lambda **kw: FixedSize(m=kw.get("m", 20)),
    "e2": lambda **kw: FixedInterval(t=kw.get("t", 60)),
    "e3": lambda **kw: Greedy(),
    "p2": lambda **kw: ConstrainedOptimizer(**kw),
    "oracle": lambda **kw: OracleOptimizer(**kw),
    "null": lambda **kw: Null(),
}
BASELINES = POLICIES  # kept: the tuning script imports this name

# Which forecaster drives which policy. ORACLE sees the true next-block fill, so
# the P2->ORACLE gap isolates what forecast error costs the policy (ablation A1).
FORECASTER_FOR = {"oracle": "oracle"}

_TUNED_VALUE = re.compile(r"(\w+)=(\d+)")

# Policy-name letters back to constructor keywords. P2 carries two, so the
# single-letter form the baselines use is not enough.
_KEYWORD = {"m": "m", "t": "t", "d": "d_max", "n": "n_min"}


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
        found = {
            _KEYWORD[letter.lower()]: int(value)
            for letter, value in _TUNED_VALUE.findall(chosen["policy"])
            if letter.lower() in _KEYWORD
        }
        if found:
            tuned[name] = found
    return tuned


def build_policies(which: str, tuned: dict) -> list[tuple[str, object]]:
    names = list(POLICIES) if which == "all" else [which]
    return [(name, POLICIES[name](**tuned.get(name, {}))) for name in names]


def build_forecasters(frame, model_dir: Path | None, horizon: int):
    """One forecaster per kind, prepared per episode window.

    ``ma`` is the fallback everywhere: if no trained artifact is supplied, P2 runs
    on the moving average, which is the E4 baseline and a strong one.
    """
    forecasters = {"ma": MovingAverage(horizon=horizon), "oracle": Oracle(horizon=horizon)}
    if model_dir is not None:
        forecasters["lgbm"] = lgbm_load(model_dir, horizon=horizon)
    return forecasters


def run(
    frame: pd.DataFrame,
    policies: list[tuple[str, object]],
    episodes: list,
    rate: str,
    process,
    forecasters: dict,
    default_forecaster: str = "ma",
) -> pd.DataFrame:
    rows = []
    for episode in episodes:
        blocks = episode.blocks(frame)

        # Prepared once per window and shared across policies: the forecast does
        # not depend on the policy, and recomputing it per policy would make a
        # paired evaluation several times slower for identical numbers.
        prepared = {
            name: CachedForecaster(model).prepare(blocks) for name, model in forecasters.items()
        }

        for key, policy in policies:
            if hasattr(policy, "reset"):
                policy.reset()
            forecaster = prepared[FORECASTER_FOR.get(key, default_forecaster)]
            result = run_episode(
                blocks,
                policy,
                episode.stream(process, rate),
                episode.rng(),
                forecaster=forecaster,
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
    parser.add_argument("--policy", default="all", choices=[*POLICIES, "all"])
    parser.add_argument(
        "--models",
        type=Path,
        default=None,
        help="directory of a trained forecaster; omitted, P2 runs on the E4 moving average",
    )
    parser.add_argument(
        "--forecaster",
        default="ma",
        help="which forecaster drives the non-oracle policies (ma | lgbm)",
    )
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

    # build_features is not optional: a trained forecaster needs its feature
    # columns, and without them it degrades to the moving average on every row
    # while still reporting itself as "lgbm".
    frame = build_features(preprocess(pd.read_parquet(args.data)))
    split = chronological_split(frame)
    process = fit_arrival_process(frame)
    episodes = build_episodes(frame, split, which=args.split, count=args.episodes, seed=args.seed)

    rates = list(ARRIVAL_RATES) if args.rate == "all" else [args.rate]
    tuned = load_tuned(args.tuned_from)
    policies = build_policies(args.policy, tuned)
    if tuned:
        print(f"tuned baselines in use: {tuned}")

    forecasters = build_forecasters(frame, args.models, FORECAST_HORIZON)
    if args.forecaster not in forecasters:
        print(f"forecaster {args.forecaster!r} unavailable; falling back to 'ma'")
        args.forecaster = "ma"
    print(f"forecaster driving policies: {args.forecaster}")

    frames = [
        run(frame, policies, episodes, rate, process, forecasters, args.forecaster)
        for rate in rates
    ]
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
        policies=[policy.name for _, policy in policies],
        forecaster=args.forecaster,
    )
    results.to_parquet(manifest.parent / "episode_metrics.parquet", index=False)
    print(f"\nmanifest {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
