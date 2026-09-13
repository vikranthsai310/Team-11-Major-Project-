"""E4 · Moving-average forecaster, and the reference predictors it is scored against.

E4 is naive but **strong on an autocorrelated series**, and Phase 1 measured
exactly that: over 92 days a rolling mean beat a global mean by 15.0 % MAE while
lag-1 persistence tied it. Success metric S1 therefore asks P1 to beat *E4*, not
to beat a constant — a much harder and more honest bar (`adr/ADR-008`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from batcher.config.params import FORECAST_HORIZON, FORECAST_WINDOW_K


class MovingAverage:
    """E4 — ``fill_hat(t+1) = mean(fill(t-k+1 .. t))``, repeated across the horizon."""

    name = "ma"

    def __init__(self, k: int = FORECAST_WINDOW_K, horizon: int = FORECAST_HORIZON):
        self.k = k
        self.horizon = horizon

    def predict_frame(self, frame: pd.DataFrame) -> np.ndarray:
        # min_periods=1 so the first rows of a window still produce a usable
        # value; a forecaster that returned NaN would stall the decision loop.
        rolling = frame["fill_pct"].rolling(self.k, min_periods=1).mean().to_numpy()
        return np.repeat(rolling[:, None], self.horizon, axis=1)


class Persistence:
    """Lag-1: predict that the next block looks like this one.

    Kept because it is the predictor the roadmap's R4 decision rule is written
    around, and reporting it alongside E4 is what makes the Phase 1 finding
    legible: it ties a global mean here, while smoothing does not.
    """

    name = "lag1"

    def __init__(self, horizon: int = FORECAST_HORIZON):
        self.horizon = horizon

    def predict_frame(self, frame: pd.DataFrame) -> np.ndarray:
        last = frame["fill_pct"].to_numpy()
        return np.repeat(last[:, None], self.horizon, axis=1)


class GlobalMean:
    """The constant predictor E4 must beat (T-L2). Fitted on train only."""

    name = "mean"

    def __init__(self, value: float = 0.0, horizon: int = FORECAST_HORIZON):
        self.value = value
        self.horizon = horizon

    def fit(self, frame: pd.DataFrame) -> GlobalMean:
        self.value = float(frame["fill_pct"].mean())
        return self

    def predict_frame(self, frame: pd.DataFrame) -> np.ndarray:
        return np.full((len(frame), self.horizon), self.value)


class Oracle:
    """The true next-block fill. Not a forecaster — an upper bound.

    The P2→ORACLE gap is the honest measure of what forecast error costs the
    *policy*, which is more informative than MAE alone (ablation A1).
    """

    name = "oracle"

    def __init__(self, horizon: int = FORECAST_HORIZON):
        self.horizon = horizon

    def predict_frame(self, frame: pd.DataFrame) -> np.ndarray:
        fill = frame["fill_pct"].to_numpy()
        columns = []
        for step in range(1, self.horizon + 1):
            shifted = np.roll(fill, -step)
            shifted[-step:] = fill[-1]
            columns.append(shifted)
        return np.column_stack(columns)
