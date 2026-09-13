"""Ablations A1 and A2 (P4-8, P4-9), and the Pareto check behind S5.

    python scripts/ablations.py --data data/processed/d1_*.parquet \
        --models experiments/phase3-forecaster/models

**A1 — what does forecast error cost the policy?** P2 on its real forecast
against P2 on the true next-block fill. More informative than MAE alone, because
it is denominated in the metric the project actually claims to improve.

**A2 — does the learned forecaster help the policy, or only the MAE?** P2 on E4
against P2 on LightGBM. A reviewer will ask, and Phase 3 gives reason to expect
little: the model tracks the level rather than anticipating spikes.
"""

from __future__ import annotations

import argparse
import json
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
from batcher.policy.optimizer import ConstrainedOptimizer
from batcher.policy.static import FixedInterval, FixedSize, Greedy, Null
from batcher.sim.env import run_episode
from batcher.sim.episodes import build_episodes
from batcher.sim.orders import fit_arrival_process

# N_MIN spans the amortization curve so the frontier is visible. Selecting a
# single point on L-p95 alone collapses P2 onto greedy, which is itself the
# Phase 4 finding — the frontier is what makes that legible.
N_MIN_FRONTIER = [1, 4, 8, 12, 20]


def score(frame, episodes, policy, process, rate, forecaster) -> dict:
    rows = []
    for episode in episodes:
        if hasattr(policy, "reset"):
            policy.reset()
        blocks = episode.blocks(frame)
        prepared = CachedForecaster(forecaster).prepare(blocks) if forecaster else None
        result = run_episode(
            blocks,
            policy,
            episode.stream(process, rate),
            episode.rng(),
            forecaster=prepared,
            episode_id=episode.episode_id,
            policy_name=policy.name,
        )
        if not metrics.conserved(result):
            raise AssertionError(f"order conservation failed in {episode.episode_id}")
        rows.append(metrics.compute(result).as_dict())

    table = pd.DataFrame(rows)
    return {
        "l_mean": float(table["l_mean"].median()),
        "l_p95": float(table["l_p95"].median()),
        "c_user": float(table["c_user"].median()),
        "batch_n": float(table["batch_n"].median()),
        "lock": float(table["lock_occupancy"].median()),
        "violations": int(table["gate_a_violations"].sum()),
    }


def pareto_front(points: list[dict]) -> list[dict]:
    """Non-dominated points on (l_p95, c_user), both lower-is-better."""
    front = []
    for point in points:
        dominated = any(
            other["l_p95"] <= point["l_p95"]
            and other["c_user"] <= point["c_user"]
            and (other["l_p95"] < point["l_p95"] or other["c_user"] < point["c_user"])
            for other in points
        )
        if not dominated:
            front.append(point)
    return front


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--models", type=Path, default=None)
    parser.add_argument("--episodes", type=int, default=12)
    parser.add_argument("--rate", default="matched")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--split", default="val")
    args = parser.parse_args(argv)

    frame = build_features(preprocess(pd.read_parquet(args.data)))
    process = fit_arrival_process(frame)
    episodes = build_episodes(
        frame, chronological_split(frame), which=args.split, count=args.episodes, seed=args.seed
    )

    ma = MovingAverage(horizon=FORECAST_HORIZON)
    oracle = Oracle(horizon=FORECAST_HORIZON)
    lgbm = lgbm_load(args.models, horizon=FORECAST_HORIZON) if args.models else ma
    if lgbm.name != "lgbm":
        print("WARNING: no trained forecaster loaded; A2 compares E4 against itself")

    rows = []

    print(f"=== A1 / A2 · P2 across N_MIN, three forecasters · {args.split} split ===")
    for n_min in N_MIN_FRONTIER:
        for label, forecaster in (("ma (E4)", ma), ("lgbm (P1)", lgbm), ("oracle", oracle)):
            result = score(
                frame,
                episodes,
                ConstrainedOptimizer(n_min=n_min),
                process,
                args.rate,
                forecaster,
            )
            rows.append({"policy": f"p2(N={n_min})", "forecaster": label, **result})

    for label, policy in (
        ("—", Greedy()),
        ("—", FixedInterval(t=20)),
        ("—", FixedSize(m=16)),
        ("—", Null()),
    ):
        rows.append(
            {
                "policy": policy.name,
                "forecaster": label,
                **score(frame, episodes, policy, process, args.rate, ma),
            }
        )

    table = pd.DataFrame(rows)
    print(table.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    # --- A2: does the learned forecaster change the policy's behaviour? ---
    print("\n=== A2 · learned forecaster vs moving average, per N_MIN ===")
    a2 = []
    for n_min in N_MIN_FRONTIER:
        rows_n = table[table["policy"] == f"p2(N={n_min})"].set_index("forecaster")
        delta_p95 = rows_n.loc["lgbm (P1)", "l_p95"] - rows_n.loc["ma (E4)", "l_p95"]
        delta_cost = rows_n.loc["lgbm (P1)", "c_user"] - rows_n.loc["ma (E4)", "c_user"]
        a2.append({"n_min": n_min, "d_l_p95": delta_p95, "d_c_user": delta_cost})
        print(f"  N_MIN={n_min:<3} L-p95 {delta_p95:+7.2f}   C-user {delta_cost:+10.2f}")

    # --- S5: is any P2 point non-dominated against the static baselines? ---
    print("\n=== S5 · Pareto check on (L-p95, C-user) ===")
    front = pareto_front(table.to_dict("records"))
    for point in sorted(front, key=lambda p: p["l_p95"]):
        print(
            f"  {point['policy']:<14} {point['forecaster']:<10} "
            f"L-p95 {point['l_p95']:7.2f}   C-user {point['c_user']:10.2f}"
        )

    # S5 as written asks whether the *achievable* policy Pareto-dominates the
    # static baselines. ORACLE is an upper bound, not a competitor, so it is
    # excluded here — including it would answer a question nobody asked.
    statics = {"e3(greedy)", "e2(T=20)", "e1(M=16)", "null"}
    static_points = [p for p in table.to_dict("records") if p["policy"] in statics]
    achievable = [
        p
        for p in table.to_dict("records")
        if p["policy"].startswith("p2") and p["forecaster"] == "lgbm (P1)"
    ]

    dominates = [
        (p["policy"], s["policy"])
        for p in achievable
        for s in static_points
        if p["l_p95"] <= s["l_p95"]
        and p["c_user"] <= s["c_user"]
        and (p["l_p95"] < s["l_p95"] or p["c_user"] < s["c_user"])
    ]
    dominated_by = [
        (p["policy"], s["policy"])
        for p in achievable
        for s in static_points
        if s["l_p95"] <= p["l_p95"]
        and s["c_user"] <= p["c_user"]
        and (s["l_p95"] < p["l_p95"] or s["c_user"] < p["c_user"])
    ]
    joint_front = pareto_front(static_points + achievable)
    on_front = [p["policy"] for p in joint_front if p in achievable]

    s5 = {
        "p2_dominates_a_static": sorted({f"{a} > {b}" for a, b in dominates}),
        "p2_dominated_by_a_static": sorted({f"{b} > {a}" for a, b in dominated_by}),
        "p2_points_on_joint_frontier": sorted(set(on_front)),
        "verdict": "PASS" if dominates and not dominated_by else "FAIL — trade-off, not dominance",
    }
    print(f"\n  P2 dominates a static baseline: {s5['p2_dominates_a_static'] or 'none'}")
    print(f"  P2 dominated by a static:       {s5['p2_dominated_by_a_static'] or 'none'}")
    print(f"  P2 points on the joint frontier: {s5['p2_points_on_joint_frontier']}")
    print(f"  S5 VERDICT: {s5['verdict']}")

    manifest = write_manifest(
        "phase4-ablations",
        seed=args.seed,
        dataset_checksum=sha256_of(args.data),
        split=args.split,
        rate=args.rate,
        episodes=len(episodes),
        forecaster_used=lgbm.name,
        a2=a2,
        pareto_front=[
            {key: point[key] for key in ("policy", "forecaster", "l_p95", "c_user")}
            for point in front
        ],
        s5=s5,
    )
    table.to_parquet(manifest.parent / "ablations.parquet", index=False)
    (manifest.parent / "ablations.json").write_text(
        json.dumps(table.to_dict("records"), indent=2) + "\n"
    )
    print(f"\nmanifest {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
