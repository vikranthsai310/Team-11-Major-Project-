"""M2 · Forecaster contract.

Every backend returns the same :class:`Forecast`, so the policy cannot tell which
model produced it and the ORACLE ablation can be swapped in unchanged.

Predictions are **clipped to [0, 1]** at this boundary rather than inside each
model: a fill fraction outside that range is meaningless, and an unclipped
regressor extrapolating to 1.4 would silently disable Gate B (T-P5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from batcher.config.params import FORECAST_HORIZON
from batcher.config.protocol import MAX_BLOCK_EX_MEM, MAX_BLOCK_EX_STEPS


@dataclass(frozen=True)
class Forecast:
    fill_hat: tuple[float, ...]
    mem_headroom: int
    step_headroom: int
    model: str


def clip(values) -> tuple[float, ...]:
    return tuple(float(min(max(v, 0.0), 1.0)) for v in values)


def to_forecast(fill_hat, model: str) -> Forecast:
    """Build a Forecast from raw predictions, clipping and deriving headroom."""
    clipped = clip(fill_hat)
    next_fill = clipped[0] if clipped else 0.0
    return Forecast(
        fill_hat=clipped,
        mem_headroom=int((1.0 - next_fill) * MAX_BLOCK_EX_MEM),
        step_headroom=int((1.0 - next_fill) * MAX_BLOCK_EX_STEPS),
        model=model,
    )


@runtime_checkable
class Forecaster(Protocol):
    name: str

    def predict_frame(self, frame: pd.DataFrame) -> np.ndarray:
        """Predictions for every row, shape (len(frame), horizon)."""


class CachedForecaster:
    """Precomputes an episode's forecasts, then serves them by slot.

    The forecast does not depend on the policy, so computing it once per window
    rather than once per policy per step keeps a full paired evaluation to
    minutes. Features are causal, so a vectorised pass over the window gives
    exactly the values a step-by-step pass would (asserted in the tests).
    """

    def __init__(self, forecaster: Forecaster, horizon: int = FORECAST_HORIZON):
        self.forecaster = forecaster
        self.horizon = horizon
        self._by_slot: dict[int, Forecast] = {}

    @property
    def name(self) -> str:
        return self.forecaster.name

    def prepare(self, frame: pd.DataFrame) -> CachedForecaster:
        predictions = self.forecaster.predict_frame(frame)
        self._by_slot = {
            int(slot): to_forecast(row, self.forecaster.name)
            for slot, row in zip(frame["abs_slot"], predictions, strict=True)
        }
        return self

    def predict(self, block) -> tuple[float, ...]:
        forecast = self._by_slot.get(int(block.abs_slot))
        if forecast is None:
            return tuple([0.0] * self.horizon)
        return forecast.fill_hat
