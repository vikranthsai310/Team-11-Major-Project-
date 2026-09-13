"""P1-12 … P1-16 — figures F1–F3 and the predictability decision rule."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from batcher.data.collector import finalise, records_to_frame
from batcher.data.features import preprocess
from batcher.eval.plots import (
    congestion_episodes,
    congestion_shares,
    figure_f1,
    figure_f2,
    figure_f3,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_analysis():
    spec = importlib.util.spec_from_file_location(
        "analyze_congestion", REPO_ROOT / "scripts" / "analyze_congestion.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


analysis = _load_analysis()


def synthetic(fills: np.ndarray) -> pd.DataFrame:
    """A D1 frame whose fill sequence is exactly ``fills``."""
    from batcher.config.protocol import MAX_BLOCK_SIZE
    from batcher.data.sources import BlockRecord

    records = [
        BlockRecord(
            block_height=13_900_000 + index,
            abs_slot=197_600_000 + index * 20,
            block_time=1_789_000_000 + index * 20,
            block_size=int(fill * MAX_BLOCK_SIZE),
            tx_count=int(fill * 60),
            epoch_no=655,
            block_hash=f"{index:064x}",
        )
        for index, fill in enumerate(fills)
    ]
    return preprocess(finalise(records_to_frame(records)))


@pytest.fixture
def autocorrelated() -> pd.DataFrame:
    """An AR(1) series — congestion as the project hopes it behaves."""
    rng = np.random.default_rng(0)
    fills = np.zeros(3_000)
    for index in range(1, len(fills)):
        fills[index] = np.clip(0.95 * fills[index - 1] + rng.normal(0, 0.03) + 0.025, 0, 1)
    return synthetic(fills)


@pytest.fixture
def white_noise() -> pd.DataFrame:
    """Independent draws — congestion as the R4 risk fears it behaves."""
    rng = np.random.default_rng(1)
    return synthetic(np.clip(rng.uniform(0, 1, 3_000), 0, 1))


def test_congestion_shares_count_the_band_correctly():
    frame = synthetic(np.array([0.10, 0.50, 0.85, 0.95, 0.99]))
    shares = congestion_shares(frame)

    assert shares["share_above_80"] == pytest.approx(0.6)
    assert shares["share_above_90"] == pytest.approx(0.4)
    assert shares["share_in_band"] == pytest.approx(0.2)
    assert shares["max_fill"] == pytest.approx(0.99, abs=1e-4)


def test_episode_structure_separates_sustained_from_interleaved():
    """Two series with identical share-above-threshold but opposite structure.

    The share statistic cannot tell them apart; a batcher very much can.
    """
    interleaved = synthetic(np.array([0.95, 0.05] * 10))
    sustained = synthetic(np.array([0.95] * 10 + [0.05] * 10))

    assert congestion_shares(interleaved)["share_above_80"] == pytest.approx(
        congestion_shares(sustained)["share_above_80"]
    )

    assert congestion_episodes(interleaved)["longest_run_blocks"] == 1
    assert congestion_episodes(interleaved)["episodes"] == 10
    assert congestion_episodes(sustained)["longest_run_blocks"] == 10
    assert congestion_episodes(sustained)["episodes"] == 1


def test_episode_structure_on_an_uncongested_series():
    quiet = synthetic(np.full(100, 0.05))
    episodes = congestion_episodes(quiet)
    assert episodes["congested_blocks"] == 0
    assert episodes["episodes"] == 0
    assert episodes["longest_run_blocks"] == 0


def test_an_autocorrelated_series_is_judged_predictable(autocorrelated):
    result = analysis.predictability(autocorrelated)

    assert result["mae_lag1_persistence"] < result["mae_global_mean"]
    assert result["lag1_improvement_over_mean"] > analysis.CLEARLY_BETTER
    assert result["verdict"] == "predictable"


def test_white_noise_triggers_the_r4_fallback(white_noise):
    """The decision rule must be capable of returning the bad answer."""
    result = analysis.predictability(white_noise)

    assert result["lag1_improvement_over_mean"] < analysis.BARELY_BETTER
    assert "random walk" in result["verdict"]


def test_predictability_uses_the_chronological_test_split_only(autocorrelated):
    result = analysis.predictability(autocorrelated)
    assert result["split"]["train_end_slot"] < result["split"]["val_end_slot"]
    assert result["split"]["test_rows"] == pytest.approx(len(autocorrelated) * 0.15, rel=0.1)


def test_autocorrelation_is_reported_out_to_lag_20(autocorrelated):
    result = analysis.predictability(autocorrelated)
    assert set(result["autocorrelation"]) == {str(lag) for lag in range(1, 21)}
    assert result["autocorrelation"]["1"] > result["autocorrelation"]["20"]


def test_exunit_proxy_reports_not_collected_when_absent(autocorrelated):
    proxy = analysis.exunit_proxy_correlation(autocorrelated)
    assert proxy["sampled_rows"] == 0
    assert "not collected" in proxy["status"]


def test_proxy_is_reported_per_contiguous_window():
    """A pooled correlation hides which regime each window was drawn from."""
    rng = np.random.default_rng(9)
    frame = synthetic(rng.uniform(0.1, 0.9, 600))
    frame["exunits_source"] = "per_tx"
    frame["mem_pct"] = np.clip(frame["fill_pct"] + rng.normal(0, 0.02, len(frame)), 0, 1)
    frame["step_pct"] = frame["mem_pct"] / 2
    frame["mem_exunits"] = 1

    # Two sampled windows separated by an unsampled gap.
    gap = frame.index[250:350]
    frame.loc[gap, "exunits_source"] = "absent"

    proxy = analysis.exunit_proxy_correlation(frame)
    assert len(proxy["windows"]) == 2
    assert all(window["blocks"] >= 100 for window in proxy["windows"])
    assert proxy["pooled"]["blocks"] == 500


def test_window_description_reports_dominance_not_only_correlation():
    """Size can be the binding dimension even when the correlation is poor."""
    n = 200
    fills = np.linspace(0.2, 0.99, n)
    frame = synthetic(fills)
    frame["exunits_source"] = "per_tx"
    frame["mem_exunits"] = 1
    # Memory is unrelated to size, and always far below its cap.
    frame["mem_pct"] = 0.05
    frame["step_pct"] = 0.01

    window = analysis.describe_window(frame)

    assert abs(window["corr_size_vs_mem"]) < 0.7 or np.isnan(window["corr_size_vs_mem"])
    assert window["share_size_binds_first"] == 1.0
    assert window["blocks_where_only_memory_binds"] == 0


def test_memory_binding_alone_is_counted():
    frame = synthetic(np.array([0.10] * 50))
    frame["exunits_source"] = "per_tx"
    frame["mem_exunits"] = 1
    frame["mem_pct"] = 0.95  # memory full while size is nearly empty
    frame["step_pct"] = 0.01

    window = analysis.describe_window(frame)
    assert window["blocks_where_only_memory_binds"] == 50
    assert window["share_size_binds_first"] == 0.0


def test_exunit_proxy_flags_a_weak_proxy():
    """R1 trigger: if size fill does not track execution fill, the proxy is invalid."""
    rng = np.random.default_rng(3)
    frame = synthetic(rng.uniform(0, 1, 500))
    frame["exunits_source"] = "per_tx"
    frame["mem_exunits"] = 1
    frame["step_exunits"] = 1
    frame["mem_pct"] = rng.uniform(0, 1, len(frame))  # deliberately unrelated
    frame["step_pct"] = rng.uniform(0, 1, len(frame))

    proxy = analysis.exunit_proxy_correlation(frame)
    assert "R1 TRIGGER" in proxy["status"]


def test_exunit_proxy_accepts_a_strong_proxy():
    rng = np.random.default_rng(4)
    fills = rng.uniform(0.1, 0.9, 500)
    frame = synthetic(fills)
    frame["exunits_source"] = "per_tx"
    frame["mem_exunits"] = 1
    frame["step_exunits"] = 1
    frame["mem_pct"] = np.clip(frame["fill_pct"] + rng.normal(0, 0.02, len(frame)), 0, 1)
    frame["step_pct"] = np.clip(frame["fill_pct"] + rng.normal(0, 0.02, len(frame)), 0, 1)

    assert analysis.exunit_proxy_correlation(frame)["status"] == "ok"


def test_figures_are_written_with_a_table_view(autocorrelated, tmp_path):
    """Every figure ships a table view (docs/17-UI-SPEC.md B1)."""
    figures = tmp_path / "figures"
    for paths in (
        figure_f1(autocorrelated, figures, "test"),
        figure_f2(autocorrelated, figures, "test"),
        figure_f3(figures, 30, "test"),
    ):
        assert paths["figure"].exists() and paths["figure"].stat().st_size > 0
        assert paths["table"].exists()
        assert len(pd.read_csv(paths["table"])) > 0


def test_f2_histogram_table_accounts_for_every_block(autocorrelated, tmp_path):
    paths = figure_f2(autocorrelated, tmp_path / "figures", "test")
    table = pd.read_csv(paths["table"])
    assert table["blocks"].sum() == len(autocorrelated)
    assert len(table) == 50  # 2-point bins across 0-100 %


def test_f3_is_analytic_and_needs_no_data(tmp_path):
    paths = figure_f3(tmp_path / "figures", 30, "analytic")
    table = pd.read_csv(paths["table"])
    assert table["cost_per_user_ada"].is_monotonic_decreasing
    assert table["n"].max() > 30  # the infeasible region is drawn, then shaded
