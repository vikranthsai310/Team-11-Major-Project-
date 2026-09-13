"""Forecaster scoring (P3-7) and the leakage check (P3-6).

**DIR matters more than MAE here.** The policy makes a threshold comparison —
will the next block have room — not a use of the exact value, so predicting the
*direction* of a change is worth more than shaving error off the level
(``docs/06-ML-SPEC.md`` §3).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def score(actual: np.ndarray, predicted: np.ndarray, previous: np.ndarray) -> dict:
    """MAE, RMSE and directional accuracy against the value known at decision time."""
    actual = np.asarray(actual, dtype="float64")
    predicted = np.asarray(predicted, dtype="float64")
    previous = np.asarray(previous, dtype="float64")

    errors = actual - predicted
    true_direction = np.sign(actual - previous)
    predicted_direction = np.sign(predicted - previous)

    moved = true_direction != 0
    directional = (
        float(np.mean(true_direction[moved] == predicted_direction[moved])) if moved.any() else 0.0
    )

    return {
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors**2))),
        "dir": directional,
        "n": int(len(actual)),
    }


def score_frame(frame: pd.DataFrame, predictions: np.ndarray, step: int = 1) -> dict:
    """Score one horizon step over a frame carrying the matching target column."""
    target = f"target_fill_t{step}"
    usable = frame[target].notna().to_numpy()

    return score(
        actual=frame.loc[usable, target].to_numpy(),
        predicted=predictions[usable, step - 1],
        previous=frame.loc[usable, "fill_pct"].to_numpy(),
    )


def leakage_check(chronological: dict, shuffled: dict) -> dict:
    """T-L1 — shuffling the split must *improve* the apparent test score.

    Shuffled training sees rows adjacent in time to the test rows, so a working
    pipeline scores better that way. If shuffling does **not** help, the
    chronological pipeline is already leaking future information and every
    forecaster number in the report is worthless.
    """
    improvement = (chronological["mae"] - shuffled["mae"]) / chronological["mae"]
    return {
        "chronological_mae": chronological["mae"],
        "shuffled_mae": shuffled["mae"],
        "shuffled_improvement": improvement,
        "leaking": bool(improvement <= 0),
    }
