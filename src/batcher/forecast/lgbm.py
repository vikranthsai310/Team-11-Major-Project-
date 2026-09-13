"""P1a · LightGBM congestion forecaster.

Tabular lag features suit gradient boosting, and it trains on a laptop CPU in
minutes. One model per horizon step, each predicting ``fill_pct`` at t+k from
features that are all computable at t (enforced by
``batcher.data.features.assert_no_lookahead``).

**Failure is not allowed to block the decision loop.** If an artifact is missing
or corrupt, :func:`load` returns the E4 moving average tagged ``model="ma"``
rather than raising (T-N4) — a batcher that stops deciding because a model file
went bad is worse than one that decides with a weaker forecast.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from batcher.config.params import FORECAST_HORIZON
from batcher.data.features import feature_columns
from batcher.forecast.baseline import MovingAverage

DEFAULT_PARAMS = {
    "objective": "regression_l1",  # L1 matches MAE, the reported metric
    "n_estimators": 500,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_child_samples": 40,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "verbose": -1,
}


class LightGBMForecaster:
    name = "lgbm"

    def __init__(self, horizon: int = FORECAST_HORIZON, params: dict | None = None):
        self.horizon = horizon
        self.params = {**DEFAULT_PARAMS, **(params or {})}
        self.models: list = []
        self.features: list[str] = []

    def fit(self, train: pd.DataFrame, validation: pd.DataFrame | None = None):
        """Fit one regressor per horizon step, early-stopping on validation MAE."""
        import lightgbm as lgb

        self.features = feature_columns(train)
        self.models = []

        for step in range(1, self.horizon + 1):
            target = f"target_fill_t{step}"
            usable = train.dropna(subset=[*self.features, target])
            model = lgb.LGBMRegressor(**self.params)

            kwargs = {}
            if validation is not None:
                held = validation.dropna(subset=[*self.features, target])
                if len(held):
                    kwargs = {
                        "eval_set": [(held[self.features], held[target])],
                        "eval_metric": "l1",
                        "callbacks": [lgb.early_stopping(50, verbose=False)],
                    }

            model.fit(usable[self.features], usable[target], **kwargs)
            self.models.append(model)
        return self

    def predict_frame(self, frame: pd.DataFrame) -> np.ndarray:
        if not self.models:
            raise RuntimeError("forecaster is not fitted")

        # Two very different situations look alike here, and conflating them cost
        # a full evaluation run: a frame that was never passed through
        # build_features has *no* feature columns and silently degraded to the
        # moving average for every row, so "P2 on LightGBM" was really P2 on E4.
        # A missing column is a caller error and is loud; NaNs within present
        # columns are the legitimate window-start case and stay silent.
        missing = [column for column in self.features if column not in frame.columns]
        if missing:
            raise KeyError(
                f"frame is missing {len(missing)} feature column(s) this forecaster needs "
                f"(e.g. {missing[:3]}). Pass it through batcher.data.features.build_features."
            )

        # A window can begin before its rolling features are complete. Those rows
        # get the moving-average value rather than a prediction from NaNs.
        features = frame.reindex(columns=self.features)
        complete = features.notna().all(axis=1).to_numpy()
        fallback = MovingAverage(horizon=self.horizon).predict_frame(frame)

        predictions = fallback.copy()
        if complete.any():
            usable = features[complete]
            for step, model in enumerate(self.models):
                predictions[complete, step] = model.predict(usable)
        return predictions

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        for step, model in enumerate(self.models, start=1):
            model.booster_.save_model(str(directory / f"lgbm_t{step}.txt"))
        (directory / "features.json").write_text(
            json.dumps({"features": self.features, "horizon": self.horizon}, indent=2)
        )
        return directory


def load(directory: Path, horizon: int = FORECAST_HORIZON):
    """Load a saved forecaster, or fall back to E4 if anything is wrong (T-N4)."""
    try:
        import lightgbm as lgb

        meta = json.loads((Path(directory) / "features.json").read_text())
        forecaster = LightGBMForecaster(horizon=meta["horizon"])
        forecaster.features = meta["features"]
        forecaster.models = [
            lgb.Booster(model_file=str(Path(directory) / f"lgbm_t{step}.txt"))
            for step in range(1, meta["horizon"] + 1)
        ]
        return forecaster
    except Exception:
        return MovingAverage(horizon=horizon)
