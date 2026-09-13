"""Train and evaluate the congestion forecaster (P3-3, P3-5, P3-6, P3-10).

    python scripts/train_forecaster.py --data data/processed/d1_*.parquet

Trains P1a (LightGBM) on the train split, early-stops on validation, and reports
it against E4, lag-1 persistence and a global mean. Runs the T-L1 leakage check.

**The test split is touched once**, at the end, for the reported number — and the
run manifest records that it happened (P3-12).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from batcher.config.params import DEFAULT_SEED, FORECAST_HORIZON
from batcher.data.collector import sha256_of
from batcher.data.features import (
    assert_no_lookahead,
    build_features,
    chronological_split,
    preprocess,
)
from batcher.eval.manifest import write_manifest
from batcher.eval.plots import anticipation_diagnostic, figure_f4
from batcher.forecast.baseline import GlobalMean, MovingAverage, Persistence
from batcher.forecast.evaluate import leakage_check, score_frame
from batcher.forecast.lgbm import LightGBMForecaster


def split_frames(frame: pd.DataFrame):
    split = chronological_split(frame)
    labels = split.label(frame["abs_slot"])
    return (
        frame[labels == "train"].reset_index(drop=True),
        frame[labels == "val"].reset_index(drop=True),
        frame[labels == "test"].reset_index(drop=True),
        split,
    )


def leakage_control(frame: pd.DataFrame, test: pd.DataFrame, seed: int, every: int = 5):
    """Build the T-L1 control so that **both models are scored on the same rows**.

    The obvious implementation — train a model on a shuffled 85/15 and compare
    its MAE to the chronological model's — compares scores computed on *different*
    rows. Periods differ in intrinsic difficulty (a global mean scores 0.0607 on
    the chronological test window and 0.0649 on validation), so that comparison
    measures which window is easier, not whether the pipeline leaks.

    Here the evaluation rows are fixed: a subsample of the chronological test
    split. The honest model trained strictly before them; the leaky model may
    train on everything else, **including their temporal neighbours**. If the
    pipeline is sound the leaky model wins, because it has effectively seen the
    answer next door.
    """
    evaluation = test.iloc[::every]
    leaky_train = frame.drop(index=evaluation.index, errors="ignore")
    return evaluation, leaky_train.sample(frac=1.0, random_state=seed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--horizon", type=int, default=FORECAST_HORIZON)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--experiment", default="phase3-forecaster")
    parser.add_argument("--skip-leakage-check", action="store_true")
    args = parser.parse_args(argv)

    raw = preprocess(pd.read_parquet(args.data))
    print("checking features for look-ahead (T-N3)...")
    assert_no_lookahead(raw, sample=8)

    frame = build_features(raw)
    train, val, test, split = split_frames(frame)
    print(f"train {len(train):,}  val {len(val):,}  test {len(test):,}")
    assert train["abs_slot"].max() < val["abs_slot"].min() < test["abs_slot"].min()

    print("\ntraining P1a (LightGBM)...")
    lgbm = LightGBMForecaster(horizon=args.horizon).fit(train, val)

    models = {
        "lgbm": lgbm,
        "ma": MovingAverage(horizon=args.horizon),
        "lag1": Persistence(horizon=args.horizon),
        "mean": GlobalMean(horizon=args.horizon).fit(train),
    }

    # --- validation: model selection happens here, never on test ---
    print("\n=== VALIDATION (model selection) ===")
    validation_scores = _report(models, val, args.horizon)

    # --- leakage check (T-L1) ---
    leakage = None
    if not args.skip_leakage_check:
        print("\n=== T-L1 leakage check ===")
        evaluation, leaky_train = leakage_control(frame, test, args.seed)
        leaky = LightGBMForecaster(horizon=1).fit(leaky_train)
        leakage = leakage_check(
            chronological=score_frame(evaluation, lgbm.predict_frame(evaluation), step=1),
            shuffled=score_frame(evaluation, leaky.predict_frame(evaluation), step=1),
        )
        print(f"  evaluated on      {len(evaluation):,} identical rows")
        print(f"  chronological MAE {leakage['chronological_mae']:.5f}")
        print(f"  leaky-split MAE   {leakage['shuffled_mae']:.5f}")
        print(f"  leaking helps     {leakage['shuffled_improvement']:+.1%}")
        print(f"  VERDICT           {'LEAKING — results invalid' if leakage['leaking'] else 'ok'}")

    # --- test: touched exactly once, for the reported number (P3-12) ---
    print("\n=== TEST (reported once) ===")
    test_scores = _report(models, test, args.horizon)

    s1_pass = test_scores["lgbm"]["t1"]["mae"] < test_scores["ma"]["t1"]["mae"]
    margin = 1 - test_scores["lgbm"]["t1"]["mae"] / test_scores["ma"]["t1"]["mae"]
    print(f"\nS1 · P1 beats E4 on the test split: {'PASS' if s1_pass else 'FAIL'} ({margin:+.1%})")
    if not s1_pass:
        print("  Report it and continue — a policy over a moving average is still adaptive.")

    figure = figure_f4(
        test,
        lgbm.predict_frame(test)[:, 0],
        Path("figures"),
        provenance=f"{args.data.name} · test split · lgbm vs actual",
    )
    diagnostic = anticipation_diagnostic(
        test["fill_pct"].to_numpy(), lgbm.predict_frame(test)[:, 0]
    )
    print(f"\nF4 written to {figure['figure']}")
    print(
        f"  anticipation: corr(next) {diagnostic['corr_with_target']:.3f} vs "
        f"corr(previous) {diagnostic['corr_with_previous']:.3f} — "
        f"{'anticipates' if diagnostic['anticipates'] else 'LAGS, learned persistence'}"
    )

    manifest = write_manifest(
        args.experiment,
        seed=args.seed,
        dataset_checksum=sha256_of(args.data),
        horizon=args.horizon,
        split={"train_end_slot": split.train_end_slot, "val_end_slot": split.val_end_slot},
        rows={"train": len(train), "val": len(val), "test": len(test)},
        validation=validation_scores,
        test=test_scores,
        leakage=leakage,
        anticipation=diagnostic,
        s1_pass=bool(s1_pass),
        s1_margin=float(margin),
        test_split_used="once, for the numbers under 'test' in this manifest",
    )
    lgbm.save(manifest.parent / "models")
    (manifest.parent / "forecaster_scores.json").write_text(
        json.dumps({"validation": validation_scores, "test": test_scores}, indent=2) + "\n"
    )
    print(f"\nmanifest {manifest}")
    return 0


def _report(models: dict, frame: pd.DataFrame, horizon: int) -> dict:
    scores: dict[str, dict] = {}
    rows = []
    for name, model in models.items():
        predictions = model.predict_frame(frame)
        scores[name] = {}
        for step in range(1, horizon + 1):
            scored = score_frame(frame, predictions, step=step)
            scores[name][f"t{step}"] = scored
            if step == 1:
                rows.append({"model": name, **scored})

    table = pd.DataFrame(rows).sort_values("mae")
    print(table.to_string(index=False, float_format=lambda v: f"{v:.5f}"))
    return scores


if __name__ == "__main__":
    raise SystemExit(main())
