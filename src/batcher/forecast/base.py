"""M2 · Forecaster contract.

Every backend returns the same :class:`Forecast`, so the policy cannot tell which
model produced it and the ORACLE ablation can be swapped in unchanged.

Predictions are **clipped to [0, 1]** at this boundary rather than inside each
model: a fill fraction outside that range is meaningless, and an unclipped
regressor extrapolating to 1.4 would silently disable Gate B (T-P5).

**A missing forecast is not an empty block.** Reading 0.0 for a slot the cache
does not hold tells every policy the next block has room, so Gate B never binds
exactly when the forecaster knows least. So by default a miss returns a
conservative estimate instead and is recorded as a fallback; ``on_missing="empty"``
restores the old 0.0 reading. Recorded evaluations are unaffected either way: each
cache is prepared on the very window it serves, so none of them ever misses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from batcher.config.params import FORECAST_HORIZON, FORECAST_WINDOW_K
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


# A cache miss serves this quantile of the fills recorded *before* the missing
# slot, over this many blocks; with no history at all it serves a full block.
FALLBACK_QUANTILE = 0.9
FALLBACK_HISTORY = 5 * FORECAST_WINDOW_K
NO_HISTORY_FILL = 1.0
MISSING_MODES = ("empty", "conservative")


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

    def __init__(
        self,
        forecaster: Forecaster,
        horizon: int = FORECAST_HORIZON,
        on_missing: str = "conservative",
    ):
        if on_missing not in MISSING_MODES:
            raise ValueError(f"on_missing must be one of {MISSING_MODES}")
        self.forecaster = forecaster
        self.horizon = horizon
        self.on_missing = on_missing
        self._by_slot: dict[int, Forecast] = {}
        self._known_slots = np.empty(0, dtype="int64")
        self._known_fills = np.empty(0, dtype="float64")
        self.fallback_slots: list[int] = []
        self.last_was_fallback = False

    @property
    def name(self) -> str:
        return self.forecaster.name

    def prepare(self, frame: pd.DataFrame) -> CachedForecaster:
        predictions = self.forecaster.predict_frame(frame)
        self._by_slot = {
            int(slot): to_forecast(row, self.forecaster.name)
            for slot, row in zip(frame["abs_slot"], predictions, strict=True)
        }
        if "fill_pct" in frame:
            known = frame[["abs_slot", "fill_pct"]].dropna().sort_values("abs_slot")
            self._known_slots = known["abs_slot"].to_numpy(dtype="int64")
            self._known_fills = known["fill_pct"].to_numpy(dtype="float64")
        self.fallback_slots = []
        self.last_was_fallback = False
        return self

    def predict(self, block) -> tuple[float, ...]:
        slot = int(block.abs_slot)
        forecast = self._by_slot.get(slot)
        self.last_was_fallback = forecast is None
        if forecast is None:
            self.fallback_slots.append(slot)
            if self.on_missing == "empty":
                return tuple([0.0] * self.horizon)
            return tuple([self.fallback_fill(slot)] * self.horizon)
        return forecast.fill_hat

    def fallback_fill(self, slot: int) -> float:
        """Conservative fill for a slot with no forecast, from strictly earlier fills.

        The recent high quantile of recorded fills, or a full block when nothing
        earlier is known. Only past slots are read, so no future data leaks in.
        """
        end = int(np.searchsorted(self._known_slots, slot, side="left"))
        recent = self._known_fills[max(0, end - FALLBACK_HISTORY) : end]
        if recent.size == 0:
            return NO_HISTORY_FILL
        return clip([np.quantile(recent, FALLBACK_QUANTILE)])[0]
