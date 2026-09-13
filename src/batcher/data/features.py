"""D1 preprocessing, feature engineering and the chronological split.

The whole file exists to serve one rule: **every feature at slot t must be
computable from data at or before t**. A rolling window that quietly includes
t+1 inflates every forecasting number in the report and is invisible in the
output, so the rule is enforced by :func:`assert_no_lookahead`, which recomputes
features on truncated prefixes and compares — not by a comment asserting care
was taken.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from batcher.config.params import FORECAST_HORIZON, FORECAST_WINDOW_K

LAGS_FILL = range(1, FORECAST_WINDOW_K + 1)
LAGS_TX = range(1, 6)
ROLLING_WINDOWS = (5, 10, 20)

SECONDS_PER_DAY = 24 * 60 * 60


def preprocess(frame: pd.DataFrame) -> pd.DataFrame:
    """Order, clean and segment D1 (``docs/05-DATA-SPEC.md`` §Preprocessing).

    Adds three bookkeeping columns:

    ``segment``    feature windows never span a hole of two or more missing blocks
    ``is_imputed`` a single missing block was forward-filled into this row
    ``is_epoch_boundary`` block production behaves differently here; excluded from training
    """
    frame = frame.sort_values("block_height").reset_index(drop=True)

    heights = frame["block_height"]
    if not heights.is_unique or not heights.is_monotonic_increasing:
        raise ValueError("block_height must be unique and strictly increasing")

    frame = _fill_single_block_gaps(frame)

    gap = frame["block_height"].diff()
    frame["segment"] = (gap > 1).cumsum().astype("int32")

    epoch = _epoch_number(frame)
    frame["is_epoch_boundary"] = epoch.ne(epoch.shift(1)).fillna(False)

    for column in ("fill_pct", "mem_pct", "step_pct"):
        if column in frame:
            frame[column] = frame[column].clip(0.0, 1.0)

    # Recompute within segment: a gap's slot_gap is the width of the hole, which
    # is not a block cadence observation.
    frame["slot_gap"] = frame.groupby("segment")["abs_slot"].diff().fillna(0).astype("int32")
    return frame


def _fill_single_block_gaps(frame: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill exactly one missing block; leave wider holes as holes."""
    gap = frame["block_height"].diff()
    single = gap[gap == 2].index
    if len(single) == 0:
        frame["is_imputed"] = False
        return frame

    frame["is_imputed"] = False
    filled = []
    for index in single:
        previous = frame.loc[index - 1].copy()
        previous["block_height"] = frame.loc[index, "block_height"] - 1
        before = frame.loc[index - 1, "abs_slot"]
        after = frame.loc[index, "abs_slot"]
        previous["abs_slot"] = (before + after) // 2
        previous["is_imputed"] = True
        filled.append(previous)

    frame = pd.concat([frame, pd.DataFrame(filled)], ignore_index=True)
    return frame.sort_values("block_height").reset_index(drop=True)


def _epoch_number(frame: pd.DataFrame) -> pd.Series:
    if "epoch_no" in frame:
        return frame["epoch_no"]
    # D1 does not carry epoch_no; Shelley epochs are 432,000 slots.
    return frame["abs_slot"] // 432_000


def build_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the P1 feature set and the t+1..t+3 targets (``docs/06-ML-SPEC.md`` §3).

    Queue features (``queue_depth``, ``oldest_wait``) are deliberately *not*
    here: they are injected at decision time by the policy, not stored in D1.
    """
    frame = frame.copy()
    grouped = frame.groupby("segment", group_keys=False)

    for lag in LAGS_FILL:
        frame[f"fill_lag_{lag}"] = grouped["fill_pct"].shift(lag)

    for lag in LAGS_TX:
        frame[f"tx_count_lag_{lag}"] = grouped["tx_count"].shift(lag)

    for window in ROLLING_WINDOWS:
        # min_periods=window: a partially-filled window at a segment start is a
        # different quantity from a full one, and reporting it as equivalent
        # would smuggle in a lower-variance feature exactly where data is thin.
        frame[f"fill_roll_mean_{window}"] = grouped["fill_pct"].transform(
            lambda series, w=window: series.rolling(w, min_periods=w).mean()
        )
        frame[f"fill_roll_std_{window}"] = grouped["fill_pct"].transform(
            lambda series, w=window: series.rolling(w, min_periods=w).std()
        )
        frame[f"slot_gap_roll_mean_{window}"] = grouped["slot_gap"].transform(
            lambda series, w=window: series.rolling(w, min_periods=w).mean()
        )

    seconds = frame["block_time"].dt.hour * 3600 + frame["block_time"].dt.minute * 60
    angle = 2 * np.pi * seconds / SECONDS_PER_DAY
    frame["hour_sin"] = np.sin(angle)
    frame["hour_cos"] = np.cos(angle)
    frame["day_of_week"] = frame["block_time"].dt.dayofweek.astype("int8")

    for step in range(1, FORECAST_HORIZON + 1):
        frame[f"target_fill_t{step}"] = grouped["fill_pct"].shift(-step)

    return frame


def feature_columns(frame: pd.DataFrame) -> list[str]:
    """The model input columns — everything engineered, no targets, no bookkeeping."""
    excluded = {
        "block_height",
        "abs_slot",
        "block_time",
        "block_size",
        "fill_pct",
        "tx_count",
        "mem_exunits",
        "step_exunits",
        "mem_pct",
        "step_pct",
        "slot_gap",
        "exunits_source",
        "epoch_no",
        "segment",
        "is_imputed",
        "is_epoch_boundary",
    }
    return [
        column
        for column in frame.columns
        if column not in excluded and not column.startswith("target_")
    ]


def modelling_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows usable for training: complete features, a target, no epoch boundary."""
    features = feature_columns(frame)
    targets = [column for column in frame.columns if column.startswith("target_")]
    usable = frame.dropna(subset=features + targets)
    return usable[~usable["is_epoch_boundary"]].reset_index(drop=True)


def assert_no_lookahead(frame: pd.DataFrame, sample: int = 12, seed: int = 0) -> None:
    """T-N3 — verify every feature at row t depends only on rows at or before t.

    Recomputes the feature set on the truncated prefix ``frame[:t+1]`` and
    requires the row-t values to be identical to those computed with the whole
    frame in view. A window that reaches forward cannot survive this.
    """
    engineered = build_features(frame)
    columns = feature_columns(engineered)

    rng = np.random.default_rng(seed)
    candidates = np.arange(max(ROLLING_WINDOWS) + 1, len(frame))
    if len(candidates) == 0:
        raise ValueError("frame too short to check for look-ahead")
    indices = rng.choice(candidates, size=min(sample, len(candidates)), replace=False)

    for index in sorted(int(i) for i in indices):
        prefix = build_features(frame.iloc[: index + 1].copy())
        full_row = engineered.iloc[index][columns]
        prefix_row = prefix.iloc[-1][columns]

        mismatched = [
            column
            for column in columns
            if not _equal_or_both_nan(full_row[column], prefix_row[column])
        ]
        if mismatched:
            raise AssertionError(
                f"look-ahead at row {index}: {mismatched} differ when later rows are hidden"
            )


def _equal_or_both_nan(a, b) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    return bool(np.isclose(a, b, rtol=1e-9, atol=1e-12, equal_nan=True))


@dataclass(frozen=True)
class Split:
    """Chronological split boundaries, shared by the forecaster, simulator and RL trainer."""

    train_end_slot: int
    val_end_slot: int

    def label(self, abs_slot: pd.Series) -> pd.Series:
        return pd.Series(
            np.where(
                abs_slot <= self.train_end_slot,
                "train",
                np.where(abs_slot <= self.val_end_slot, "val", "test"),
            ),
            index=abs_slot.index,
        )


def chronological_split(frame: pd.DataFrame, train: float = 0.70, val: float = 0.15) -> Split:
    """70/15/15 by time, **never shuffled** (``docs/05-DATA-SPEC.md`` §Splits).

    Boundaries are returned rather than applied so that every consumer splits at
    exactly the same slots; a shuffle would leak future congestion into training
    and inflate every reported number.
    """
    slots = frame["abs_slot"].sort_values().to_numpy()
    if len(slots) < 3:
        raise ValueError("need at least three rows to split")

    train_end = slots[min(int(len(slots) * train), len(slots) - 3)]
    val_end = slots[min(int(len(slots) * (train + val)), len(slots) - 2)]
    return Split(train_end_slot=int(train_end), val_end_slot=int(val_end))
