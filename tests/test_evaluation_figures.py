"""P6-4 — the evaluation figures render from synthetic outputs.

The real inputs come from a one-shot test-split run, so a figure that crashes on
them would force a second run. These tests exercise every figure on data shaped
exactly like ``episode_metrics.parquet`` and ``latencies.parquet``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from batcher.eval.plots import figure_f5, figure_f6, figure_f8

POLICIES = [
    "null",
    "e1(M=16)",
    "e2(T=20)",
    "e3(greedy)",
    "p2(D=120,N=1)",
    "p2(D=120,N=4)",
    "p3(dqn)",
    "oracle(D=120,N=4)",
]


def points(rate: str = "matched") -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for index, policy in enumerate(POLICIES):
        l_p95 = 120 + 10 * index
        c_user = 150_000 - 8_000 * index
        rows.append(
            {
                "policy": policy,
                "rate": rate,
                "l_p95": l_p95,
                "l_p95_lo": l_p95 - rng.uniform(1, 5),
                "l_p95_hi": l_p95 + rng.uniform(1, 5),
                "c_user": c_user,
                "c_user_lo": c_user - rng.uniform(500, 2000),
                "c_user_hi": c_user + rng.uniform(500, 2000),
            }
        )
    return pd.DataFrame(rows)


def test_f5_renders_and_ships_a_table(tmp_path):
    paths = figure_f5(points(), tmp_path / "figures", "synthetic")
    assert paths["figure"].stat().st_size > 0
    assert len(pd.read_csv(paths["table"])) == len(POLICIES)


def test_f5_survives_policies_that_coincide(tmp_path):
    """p2 at N_MIN=1 lands exactly on greedy; the figure must not break on that."""
    data = points()
    greedy = data.loc[data["policy"] == "e3(greedy)"].iloc[0]
    for column in ("l_p95", "l_p95_lo", "l_p95_hi", "c_user", "c_user_lo", "c_user_hi"):
        data.loc[data["policy"] == "p2(D=120,N=1)", column] = greedy[column]

    paths = figure_f5(data, tmp_path / "figures", "synthetic")
    assert paths["figure"].exists()


def test_f6_renders_quantiles(tmp_path):
    rng = np.random.default_rng(1)
    latencies = pd.DataFrame(
        [(p, float(v)) for p in POLICIES for v in rng.gamma(4, 15, 400)],
        columns=["policy", "latency"],
    )
    paths = figure_f6(latencies, tmp_path / "figures", "synthetic")
    quantiles = pd.read_csv(paths["table"], index_col=0)
    assert paths["figure"].exists()
    assert (quantiles["0.95"] >= quantiles["0.5"]).all()


def test_f6_tolerates_a_missing_series(tmp_path):
    latencies = pd.DataFrame({"policy": ["e3(greedy)"] * 50, "latency": np.arange(50.0)})
    assert figure_f6(latencies, tmp_path / "figures", "synthetic")["figure"].exists()


def test_f8_uses_one_shared_scale_across_rates(tmp_path):
    summary = pd.concat([points(rate) for rate in ("light", "matched", "heavy")])
    paths = figure_f8(summary, tmp_path / "figures", "synthetic")
    assert paths["figure"].exists()
    assert set(pd.read_csv(paths["table"])["rate"]) == {"light", "matched", "heavy"}
