"""Phase 8 — a forecast that is missing must not read as an empty block."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from batcher.dashboard.data import forecaster_label
from batcher.forecast.base import FALLBACK_QUANTILE, NO_HISTORY_FILL, CachedForecaster
from batcher.forecast.baseline import MovingAverage
from batcher.forecast.lgbm import LightGBMForecaster, MovingAverageFallback, load


def window(n: int = 50, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {"abs_slot": 1_000 + 20 * np.arange(n), "fill_pct": rng.uniform(0.1, 0.9, n)}
    )


def block(slot: int):
    return SimpleNamespace(abs_slot=slot)


def test_a_cached_slot_is_served_unchanged():
    frame = window()
    cache = CachedForecaster(MovingAverage(horizon=3)).prepare(frame)
    expected = MovingAverage(horizon=3).predict_frame(frame)[10]
    assert cache.predict(block(int(frame["abs_slot"][10]))) == pytest.approx(tuple(expected))
    assert not cache.last_was_fallback
    assert cache.fallback_slots == []


def test_a_missing_slot_serves_a_high_quantile_of_earlier_fills_not_zero():
    frame = window()
    cache = CachedForecaster(MovingAverage(horizon=3), on_missing="conservative").prepare(frame)
    missing = int(frame["abs_slot"][30]) + 7  # between two recorded blocks

    values = cache.predict(block(missing))
    earlier = frame["fill_pct"][:31].to_numpy()
    assert values == pytest.approx((np.quantile(earlier, FALLBACK_QUANTILE),) * 3)
    assert min(values) > 0.0
    assert cache.last_was_fallback
    assert cache.fallback_slots == [missing]


def test_the_fallback_never_reads_fills_after_the_missing_slot():
    frame = window()
    frame.loc[40:, "fill_pct"] = 0.0  # a quiet future must not lower the estimate
    cache = CachedForecaster(MovingAverage(), on_missing="conservative").prepare(frame)
    before = cache.predict(block(int(frame["abs_slot"][39]) + 1))
    assert before[0] == pytest.approx(np.quantile(frame["fill_pct"][:40], FALLBACK_QUANTILE))


def test_with_no_history_a_missing_slot_is_a_full_block():
    cache = CachedForecaster(MovingAverage(horizon=3), on_missing="conservative")
    assert cache.predict(block(5)) == (NO_HISTORY_FILL,) * 3
    prepared = CachedForecaster(MovingAverage(), on_missing="conservative").prepare(window())
    assert prepared.predict(block(1))[0] == NO_HISTORY_FILL  # before the window starts


def test_the_empty_mode_reads_a_miss_as_empty_but_still_records_it():
    cache = CachedForecaster(MovingAverage(horizon=3), on_missing="empty").prepare(window())
    assert cache.predict(block(1_007)) == (0.0, 0.0, 0.0)
    assert cache.last_was_fallback
    assert cache.fallback_slots == [1_007]


def test_the_default_never_reads_a_miss_as_an_empty_block():
    cache = CachedForecaster(MovingAverage(horizon=3)).prepare(window())
    assert all(fill > 0.0 for fill in cache.predict(block(1_007)))
    assert cache.fallback_slots == [1_007]


def test_an_unknown_missing_mode_is_rejected():
    with pytest.raises(ValueError, match="on_missing"):
        CachedForecaster(MovingAverage(), on_missing="zero")


def test_a_missing_model_is_an_explicit_logged_fallback(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="batcher.forecast.lgbm"):
        forecaster = load(tmp_path / "nothing-here", horizon=3)

    assert isinstance(forecaster, MovingAverageFallback)
    assert forecaster.is_fallback
    assert forecaster.name == "ma"  # the Phase 6 guard still refuses it
    assert forecaster.name != "lgbm"
    assert forecaster.label == "moving average (LightGBM model files not found)"
    assert "falling back to the moving average" in caplog.text


def test_a_corrupt_model_says_so(tmp_path):
    (tmp_path / "features.json").write_text("{ not json")
    forecaster = load(tmp_path)
    assert forecaster.is_fallback
    assert "could not be loaded" in forecaster.label


def test_the_fallback_predicts_exactly_what_e4_predicts(tmp_path):
    frame = window(200, seed=4)
    fallback = load(tmp_path / "absent", horizon=3)
    assert np.array_equal(
        fallback.predict_frame(frame), MovingAverage(horizon=3).predict_frame(frame)
    )


def test_the_dashboard_labels_the_forecaster_that_actually_ran(tmp_path):
    assert forecaster_label(load(tmp_path / "absent")) == (
        "moving average (LightGBM model files not found)"
    )
    assert forecaster_label(LightGBMForecaster()) == "LightGBM"
    assert forecaster_label(MovingAverage()) == "ma"
    assert forecaster_label(None) == "none"
