"""T-L1, T-L2, T-N4, T-P5 — the forecaster and its guards."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from batcher.config.protocol import MAX_BLOCK_EX_MEM
from batcher.data.collector import collect_blocks, finalise, records_to_frame
from batcher.data.features import build_features, preprocess
from batcher.eval.plots import anticipation_diagnostic
from batcher.forecast.base import CachedForecaster, clip, to_forecast
from batcher.forecast.baseline import GlobalMean, MovingAverage, Oracle, Persistence
from batcher.forecast.evaluate import leakage_check, score, score_frame
from batcher.forecast.lgbm import LightGBMForecaster, load
from conftest import BASE_HEIGHT, FakeSource, make_records


@pytest.fixture(scope="module")
def frame(tmp_path_factory):
    source = FakeSource(make_records(2500, seed=31))
    blocks = collect_blocks(
        source,
        start_height=BASE_HEIGHT,
        end_height=source.tip_height(),
        staging_dir=tmp_path_factory.mktemp("staging"),
        page_size=1000,
    )
    return build_features(preprocess(blocks))


def autocorrelated(n: int = 1500, seed: int = 0) -> pd.DataFrame:
    """A series with real structure, so a model can beat a constant."""
    rng = np.random.default_rng(seed)
    fills = np.zeros(n)
    for i in range(1, n):
        fills[i] = np.clip(0.9 * fills[i - 1] + rng.normal(0, 0.05) + 0.03, 0, 1)

    from batcher.config.protocol import MAX_BLOCK_SIZE
    from batcher.data.sources import BlockRecord

    records = [
        BlockRecord(
            block_height=BASE_HEIGHT + i,
            abs_slot=197_600_000 + i * 20,
            block_time=1_789_000_000 + i * 20,
            block_size=int(f * MAX_BLOCK_SIZE),
            tx_count=int(f * 50),
            epoch_no=655,
            block_hash=f"{i:064x}",
        )
        for i, f in enumerate(fills)
    ]
    return build_features(preprocess(finalise(records_to_frame(records))))


# --- baselines ---------------------------------------------------------------


def test_moving_average_beats_a_constant_predictor():
    """T-L2 — E4 must beat predicting the global mean on an autocorrelated series."""
    data = autocorrelated()
    ma = score_frame(data, MovingAverage().predict_frame(data))
    mean = score_frame(data, GlobalMean().fit(data).predict_frame(data))
    assert ma["mae"] < mean["mae"]


def test_moving_average_never_returns_nan_at_a_window_start(frame):
    """A NaN forecast would stall the decision loop."""
    predictions = MovingAverage().predict_frame(frame.head(3))
    assert not np.isnan(predictions).any()


def test_oracle_returns_the_true_next_value(frame):
    predictions = Oracle().predict_frame(frame)
    actual = frame["fill_pct"].to_numpy()
    assert np.allclose(predictions[:-1, 0], actual[1:])


def test_oracle_is_perfect_by_construction(frame):
    scored = score_frame(frame, Oracle().predict_frame(frame))
    assert scored["mae"] == pytest.approx(0.0, abs=1e-9)


def test_persistence_repeats_the_current_value(frame):
    predictions = Persistence().predict_frame(frame)
    assert np.allclose(predictions[:, 0], frame["fill_pct"].to_numpy())


# --- the Forecast contract ---------------------------------------------------


def test_predictions_are_clipped_to_the_valid_range():
    """T-P5 — an unclipped regressor extrapolating past 1.0 would disable Gate B."""
    assert clip([-0.5, 0.3, 1.8]) == (0.0, 0.3, 1.0)

    forecast = to_forecast([1.9, -2.0, 0.5], model="test")
    assert all(0.0 <= value <= 1.0 for value in forecast.fill_hat)
    assert forecast.mem_headroom == 0


def test_headroom_follows_the_next_block_prediction():
    empty = to_forecast([0.0, 0.0, 0.0], model="t")
    assert empty.mem_headroom == MAX_BLOCK_EX_MEM


def test_cached_forecaster_matches_direct_prediction(frame):
    """Precomputing per window must equal predicting per step — features are causal."""
    model = MovingAverage()
    cached = CachedForecaster(model).prepare(frame)
    direct = model.predict_frame(frame)

    for index, block in enumerate(frame.itertuples()):
        if index > 50:
            break
        assert cached.predict(block)[0] == pytest.approx(direct[index, 0], abs=1e-9)


def test_cached_forecaster_is_safe_on_an_unknown_slot(frame):
    cached = CachedForecaster(MovingAverage()).prepare(frame.head(10))
    unknown = next(iter(frame.tail(1).itertuples()))
    assert cached.predict(unknown) == (0.0, 0.0, 0.0)


# --- LightGBM and the fallback ----------------------------------------------


def test_lightgbm_beats_the_moving_average_on_a_learnable_series():
    data = autocorrelated(seed=5)
    cut = int(len(data) * 0.8)
    train, test = data.iloc[:cut], data.iloc[cut:]

    model = LightGBMForecaster(horizon=1).fit(train)
    assert (
        score_frame(test, model.predict_frame(test))["mae"]
        < score_frame(test, MovingAverage(horizon=1).predict_frame(test))["mae"]
    )


def test_an_unfitted_forecaster_refuses_to_predict(frame):
    with pytest.raises(RuntimeError, match="not fitted"):
        LightGBMForecaster().predict_frame(frame)


def test_a_corrupt_artifact_falls_back_to_the_moving_average(tmp_path):
    """T-N4 — the decision loop must never block on the forecaster."""
    broken = tmp_path / "models"
    broken.mkdir()
    (broken / "features.json").write_text("{ not json")

    recovered = load(broken)
    assert recovered.name == "ma"


def test_a_missing_artifact_falls_back_too(tmp_path):
    assert load(tmp_path / "nothing-here").name == "ma"


def test_a_saved_forecaster_round_trips(tmp_path):
    data = autocorrelated(seed=6)
    model = LightGBMForecaster(horizon=1).fit(data.iloc[:800])
    model.save(tmp_path / "models")

    reloaded = load(tmp_path / "models", horizon=1)
    assert reloaded.name == "lgbm"
    assert np.allclose(
        reloaded.predict_frame(data.iloc[800:]), model.predict_frame(data.iloc[800:]), atol=1e-6
    )


def test_a_frame_without_features_is_rejected_loudly():
    """The defect this guards against cost a whole evaluation run.

    `evaluate.py` passed a frame that had never been through `build_features`.
    Every row's features were absent, so the model degraded to the moving average
    for all of them while still calling itself "lgbm" — and P2-on-LightGBM was
    silently P2-on-E4. A missing *column* is a caller error and must raise; NaNs
    inside present columns remain the silent, legitimate case.
    """
    data = autocorrelated(seed=11)
    model = LightGBMForecaster(horizon=1).fit(data.iloc[:900])

    featureless = data[["abs_slot", "block_time", "fill_pct", "tx_count", "slot_gap", "segment"]]
    with pytest.raises(KeyError, match="build_features"):
        model.predict_frame(featureless)


def test_a_real_model_varies_across_the_horizon():
    """The moving average repeats one value; a fallback is detectable this way."""
    data = autocorrelated(seed=12)
    model = LightGBMForecaster(horizon=3).fit(data.iloc[:1000])
    predictions = model.predict_frame(data.iloc[1000:])

    assert not np.allclose(predictions[:, 0], predictions[:, 1])
    assert np.allclose(
        MovingAverage(horizon=3).predict_frame(data)[:, 0],
        MovingAverage(horizon=3).predict_frame(data)[:, 1],
    )


def test_rows_with_incomplete_features_get_the_moving_average(frame):
    """A window can start before its rolling features are complete."""
    data = autocorrelated(seed=7)
    model = LightGBMForecaster(horizon=1).fit(data.iloc[:900])

    head = data.head(3)  # lag_20 is still NaN here
    assert not np.isnan(model.predict_frame(head)).any()


# --- scoring and leakage -----------------------------------------------------


def test_directional_accuracy_rewards_predicting_the_move():
    previous = np.array([0.5, 0.5, 0.5, 0.5])
    actual = np.array([0.6, 0.4, 0.6, 0.4])

    assert score(actual, np.array([0.7, 0.3, 0.7, 0.3]), previous)["dir"] == 1.0
    assert score(actual, np.array([0.3, 0.7, 0.3, 0.7]), previous)["dir"] == 0.0


def test_a_persistence_forecast_has_no_directional_signal():
    """Predicting no change can never call a direction correctly."""
    previous = np.array([0.5, 0.5, 0.5])
    actual = np.array([0.6, 0.4, 0.7])
    assert score(actual, previous.copy(), previous)["dir"] == 0.0


def test_leakage_check_flags_a_pipeline_that_learns_nothing_from_neighbours():
    """T-L1 — if a leaky split does not score better, the honest split is leaking."""
    honest = {"mae": 0.05}
    assert leakage_check(honest, {"mae": 0.04})["leaking"] is False
    assert leakage_check(honest, {"mae": 0.06})["leaking"] is True


# --- the F4 diagnostic -------------------------------------------------------


def test_anticipation_diagnostic_detects_a_lagging_forecast():
    """F4's stated failure signature, measured rather than eyeballed."""
    rng = np.random.default_rng(3)
    actual = np.clip(rng.normal(0.3, 0.2, 500), 0, 1)

    lagging = np.roll(actual, 1)
    assert anticipation_diagnostic(actual, lagging)["anticipates"] is False

    anticipating = np.roll(actual, -1)
    assert anticipation_diagnostic(actual, anticipating)["anticipates"] is True
