"""T-N3 and T-I4 — feature-level and split-level leakage guards."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from batcher.data.collector import collect_blocks, finalise, records_to_frame
from batcher.data.features import (
    assert_no_lookahead,
    build_features,
    chronological_split,
    feature_columns,
    modelling_frame,
    preprocess,
)
from conftest import BASE_HEIGHT, FakeSource, make_records


@pytest.fixture
def prepared(tmp_path):
    source = FakeSource(make_records(400, seed=7))
    frame = collect_blocks(
        source,
        start_height=BASE_HEIGHT,
        end_height=source.tip_height(),
        staging_dir=tmp_path / "staging",
        page_size=100,
    )
    return preprocess(frame)


def test_preprocessing_orders_clips_and_segments(prepared):
    assert prepared["block_height"].is_monotonic_increasing
    assert prepared["fill_pct"].between(0, 1).all()
    assert "segment" in prepared
    assert "is_epoch_boundary" in prepared


def test_a_single_missing_block_is_forward_filled():
    records = make_records(60, skip={BASE_HEIGHT + 30})
    prepared = preprocess(finalise(records_to_frame(records)))

    assert BASE_HEIGHT + 30 in set(prepared["block_height"])
    assert prepared.loc[prepared["block_height"] == BASE_HEIGHT + 30, "is_imputed"].all()
    assert prepared["is_imputed"].sum() == 1


def test_a_wider_hole_becomes_a_segment_boundary():
    """Two or more missing blocks is a hole; feature windows must not span it."""
    missing = {BASE_HEIGHT + 30, BASE_HEIGHT + 31, BASE_HEIGHT + 32}
    prepared = preprocess(finalise(records_to_frame(make_records(60, skip=missing))))

    assert prepared["segment"].nunique() == 2
    assert not prepared["is_imputed"].any()


def test_features_do_not_span_a_hole():
    missing = {BASE_HEIGHT + 30, BASE_HEIGHT + 31, BASE_HEIGHT + 32}
    prepared = preprocess(finalise(records_to_frame(make_records(80, skip=missing))))
    engineered = build_features(prepared)

    first_of_second_segment = engineered[engineered["segment"] == 1].iloc[0]
    assert pd.isna(first_of_second_segment["fill_lag_1"])
    assert pd.isna(first_of_second_segment["fill_roll_mean_5"])


def test_no_nan_in_the_modelling_frame(prepared):
    """T-N3, first half — no NaN in feature columns after preprocessing."""
    usable = modelling_frame(build_features(prepared))
    assert len(usable) > 0
    assert not usable[feature_columns(usable)].isna().any().any()


def test_every_feature_is_computable_from_the_past(prepared):
    """T-N3 — the look-ahead guard, asserted rather than assumed."""
    assert_no_lookahead(prepared, sample=10)


def test_the_lookahead_guard_catches_a_planted_future_feature(prepared, monkeypatch):
    """The guard must fail when it should, or it is decoration."""
    import batcher.data.features as features

    original = features.build_features

    def leaky(frame):
        engineered = original(frame)
        engineered["fill_next_leak"] = engineered.groupby("segment")["fill_pct"].shift(-1)
        return engineered

    monkeypatch.setattr(features, "build_features", leaky)

    with pytest.raises(AssertionError, match="look-ahead"):
        features.assert_no_lookahead(prepared, sample=6)


def test_targets_look_forward_and_features_do_not(prepared):
    engineered = build_features(prepared)
    row = 100
    assert engineered["target_fill_t1"].iloc[row] == pytest.approx(
        engineered["fill_pct"].iloc[row + 1]
    )
    assert engineered["fill_lag_1"].iloc[row] == pytest.approx(engineered["fill_pct"].iloc[row - 1])
    assert not any(column.startswith("target_") for column in feature_columns(engineered))


def test_calendar_features_are_cyclic(prepared):
    engineered = build_features(prepared)
    radius = engineered["hour_sin"] ** 2 + engineered["hour_cos"] ** 2
    assert np.allclose(radius, 1.0)
    assert engineered["day_of_week"].between(0, 6).all()


def test_chronological_split_never_leaks(prepared):
    """T-I4 — max(train) < min(val) < min(test), by construction."""
    split = chronological_split(prepared)
    labels = split.label(prepared["abs_slot"])

    train = prepared.loc[labels == "train", "abs_slot"]
    val = prepared.loc[labels == "val", "abs_slot"]
    test = prepared.loc[labels == "test", "abs_slot"]

    assert len(train) and len(val) and len(test)
    assert train.max() < val.min() < test.min()
    assert val.max() < test.min()


def test_split_shares_are_roughly_seventy_fifteen_fifteen(prepared):
    labels = chronological_split(prepared).label(prepared["abs_slot"])
    shares = labels.value_counts(normalize=True)
    assert shares["train"] == pytest.approx(0.70, abs=0.02)
    assert shares["val"] == pytest.approx(0.15, abs=0.02)
    assert shares["test"] == pytest.approx(0.15, abs=0.02)


def test_split_is_a_boundary_not_a_shuffle(prepared):
    """Every consumer must be able to reproduce the same boundaries from the same data."""
    shuffled = prepared.sample(frac=1, random_state=1)
    assert chronological_split(prepared) == chronological_split(shuffled)
