"""Report figures. Script-generated only — a hand-edited figure cannot be reproduced.

Conventions from ``docs/17-UI-SPEC.md`` Part B: fixed series colours, recessive
chrome, one y-axis per figure, direct labels rather than colour-alone identity,
and a table view shipped beside every figure.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from batcher.build.estimator import (  # noqa: E402
    cost_per_user_ada,
    flat_component_lovelace,
    marginal_component_lovelace,
)

SERIES_BLUE = "#2a78d6"
SERIES_BLUE_MUTED = "#a9c8ee"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"

BAND_LOW, BAND_HIGH = 0.80, 0.90


def apply_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK_SECONDARY,
            "axes.titlecolor": INK,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.dpi": 150,
        }
    )


def _provenance(figure, text: str) -> None:
    figure.text(0.01, 0.01, text, fontsize=6.5, color=MUTED, ha="left", va="bottom")


def _shade_band(axis, label: bool = True, side: str = "right") -> None:
    axis.axhspan(BAND_LOW, BAND_HIGH, color=MUTED, alpha=0.13, linewidth=0, zorder=0)
    if label:
        axis.text(
            0.995 if side == "right" else 0.005,
            (BAND_LOW + BAND_HIGH) / 2,
            "inclusion-risk band",
            transform=axis.get_yaxis_transform(),
            ha=side,
            va="center",
            fontsize=7.5,
            color=INK_SECONDARY,
        )


def congestion_shares(frame: pd.DataFrame) -> dict[str, float]:
    """The numbers F1 and F2 exist to produce; F2's >80 % share goes in the abstract."""
    fill = frame["fill_pct"]
    return {
        "mean_fill": float(fill.mean()),
        "median_fill": float(fill.median()),
        "p95_fill": float(fill.quantile(0.95)),
        "max_fill": float(fill.max()),
        "share_above_80": float((fill > BAND_LOW).mean()),
        "share_above_90": float((fill > BAND_HIGH).mean()),
        "share_in_band": float(fill.between(BAND_LOW, BAND_HIGH).mean()),
    }


def congestion_episodes(frame: pd.DataFrame, threshold: float = BAND_LOW) -> dict[str, float]:
    """Is congestion sustained, or interleaved with empty blocks?

    The distinction decides whether a batcher ever faces a *run* of blocks it
    cannot fit into, or only isolated ones it can wait out — and it is invisible
    in the share-above-threshold statistic, which counts blocks without regard to
    whether they are adjacent.
    """
    congested = frame["fill_pct"] > threshold
    if not congested.any():
        return {"congested_blocks": 0, "episodes": 0, "longest_run_blocks": 0}

    runs = congested.groupby((congested != congested.shift()).cumsum()).sum()
    runs = runs[runs > 0]

    by_day = frame.set_index("block_time")["fill_pct"].resample("1D")
    daily = by_day.apply(lambda series: (series > threshold).sum())
    blocks_per_day = by_day.size()
    top_five = daily.nlargest(5).sum()

    return {
        "congested_blocks": int(congested.sum()),
        "episodes": int(len(runs)),
        "mean_run_blocks": float(runs.mean()),
        "longest_run_blocks": int(runs.max()),
        "days_with_any": int((daily > 0).sum()),
        "days_total": int(len(daily)),
        "share_in_top_five_days": float(top_five / congested.sum()),
        "busiest_day_share": float(daily.max() / blocks_per_day.max()),
    }


def figure_f1(frame: pd.DataFrame, out_dir: Path, provenance: str = "") -> dict[str, Path]:
    """F1 · Congestion over time — is the problem real, and when does it bite?"""
    apply_style()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Drawing 168,000 blocks over 90 days produces a solid mass, not a line: at
    # this density every pixel column spans ~300 blocks. Aggregating to the hour
    # and showing the range plus the median keeps both the typical level and the
    # spikes — and the spikes are the entire argument.
    hourly = (
        frame.set_index("block_time")["fill_pct"]
        .resample("1h")
        .agg(["min", "median", "max"])
        .dropna()
    )

    # The 48-hour detail is a stacked panel rather than the inset the UI spec
    # sketches: at this fill level the band region is the only clear space on the
    # main panel, so an inset placed there covers the band it is meant to explain.
    figure, (axis, detail_axis) = plt.subplots(
        2, 1, figsize=(9, 5.6), height_ratios=[2, 1], gridspec_kw={"hspace": 0.45}
    )

    axis.fill_between(
        hourly.index, hourly["min"], hourly["max"], color=SERIES_BLUE, alpha=0.28, linewidth=0
    )
    axis.plot(hourly.index, hourly["median"], lw=1.4, color=SERIES_BLUE)
    _shade_band(axis, side="left")

    axis.set_ylim(0, 1)
    axis.set_ylabel("block fill (hourly range, median)")
    axis.set_title("F1 · Cardano block fill over the collected window", loc="left")
    axis.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")

    peak = frame.loc[frame["fill_pct"].idxmax()]
    axis.annotate(
        f"peak {peak['fill_pct']:.0%} · {peak['block_time']:%Y-%m-%d}",
        xy=(peak["block_time"], peak["fill_pct"]),
        xytext=(-14, -30),
        textcoords="offset points",
        ha="right",
        fontsize=7.5,
        color=INK_SECONDARY,
        arrowprops={"arrowstyle": "-", "color": MUTED, "lw": 0.8},
    )

    # Range *and* median, not maxima alone. A maxima-only line puts the series at
    # 100 % for any window containing a single full block, which reads as hours of
    # sustained saturation when the truth is congested blocks interleaved with
    # empty ones — the precise overstatement ADR-008 was written to correct.
    window = frame[
        (frame["block_time"] >= peak["block_time"] - pd.Timedelta(hours=24))
        & (frame["block_time"] <= peak["block_time"] + pd.Timedelta(hours=24))
    ]
    detail = (
        window.set_index("block_time")["fill_pct"].resample("5min").agg(["min", "median", "max"])
    ).dropna()
    detail_axis.fill_between(
        detail.index, detail["min"], detail["max"], color=SERIES_BLUE, alpha=0.28, linewidth=0
    )
    detail_axis.plot(detail.index, detail["median"], lw=1.2, color=SERIES_BLUE)
    _shade_band(detail_axis, side="left")
    detail_axis.set_ylim(0, 1)
    detail_axis.set_ylabel("block fill")
    detail_axis.set_xlabel("block time (UTC)")
    detail_axis.set_title(
        "48 h around the peak — 5-minute range and median",
        fontsize=8,
        color=INK_SECONDARY,
        loc="left",
    )
    detail_axis.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")

    _provenance(figure, provenance)

    paths = {"figure": out_dir / "F1_congestion_over_time.png"}
    figure.savefig(paths["figure"], bbox_inches="tight")
    plt.close(figure)

    daily = (
        frame.set_index("block_time")["fill_pct"]
        .resample("1D")
        .agg(["mean", "max", "count"])
        .rename(columns={"mean": "mean_fill", "max": "max_fill", "count": "blocks"})
    )
    paths["table"] = out_dir.parent / "tables" / "F1_daily_fill.csv"
    paths["table"].parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(paths["table"])
    return paths


def figure_f2(frame: pd.DataFrame, out_dir: Path, provenance: str = "") -> dict[str, Path]:
    """F2 · Distribution of block fill — how often does congestion actually bind?"""
    apply_style()
    out_dir.mkdir(parents=True, exist_ok=True)

    shares = congestion_shares(frame)
    edges = np.arange(0, 1.02, 0.02)  # 2-point bins
    counts, _ = np.histogram(frame["fill_pct"], bins=edges)

    figure, axis = plt.subplots(figsize=(8, 4.2))
    centres = edges[:-1]
    colours = [SERIES_BLUE if edge >= BAND_LOW else SERIES_BLUE_MUTED for edge in centres]
    axis.bar(centres, counts, width=0.018, align="edge", color=colours, linewidth=0)

    axis.axvspan(BAND_LOW, BAND_HIGH, color=MUTED, alpha=0.13, linewidth=0, zorder=0)
    axis.set_xlabel("block fill")
    axis.set_ylabel("blocks (log scale)")
    axis.set_xlim(0, 1)
    axis.set_title("F2 · Distribution of block fill", loc="left")
    axis.xaxis.set_major_formatter(lambda value, _: f"{value:.0%}")

    # The tail is the subject of this figure, and on a linear count axis it is
    # invisible: the first bin holds ~73,000 blocks and the whole region above
    # 80 % holds ~200. A log count axis shows both, and is why the full-chroma
    # bars above 80 % can be seen at all.
    axis.set_yscale("log")
    axis.set_ylim(bottom=0.7)

    axis.annotate(
        f"above 80 %: {shares['share_above_80']:.2%}\nabove 90 %: {shares['share_above_90']:.2%}",
        xy=(0.40, 0.86),
        xycoords="axes fraction",
        fontsize=8.5,
        color=INK,
        bbox={"boxstyle": "round,pad=0.4", "facecolor": SURFACE, "edgecolor": GRID},
    )

    _provenance(figure, provenance)
    figure.tight_layout()

    paths = {"figure": out_dir / "F2_fill_distribution.png"}
    figure.savefig(paths["figure"], bbox_inches="tight")
    plt.close(figure)

    paths["table"] = out_dir.parent / "tables" / "F2_fill_histogram.csv"
    paths["table"].parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"bin_low": edges[:-1], "bin_high": edges[1:], "blocks": counts}).to_csv(
        paths["table"], index=False
    )
    return paths


def anticipation_diagnostic(actual, predicted) -> dict:
    """Has the forecaster anticipated, or has it just learned persistence?

    F4's stated failure signature is a forecast that is a smoothed lag of the
    actual series. That is invisible by eye on a busy chart, so it is measured:
    if the prediction correlates best with the *previous* actual value rather
    than the one it is predicting, the model has learned to copy.
    """
    actual = np.asarray(actual, dtype="float64")
    predicted = np.asarray(predicted, dtype="float64")

    with_target = float(np.corrcoef(predicted[:-1], actual[1:])[0, 1])
    with_previous = float(np.corrcoef(predicted[1:], actual[:-1])[0, 1])

    return {
        "corr_with_target": with_target,
        "corr_with_previous": with_previous,
        "anticipates": bool(with_target >= with_previous),
    }


def figure_f4(
    frame: pd.DataFrame,
    predicted,
    out_dir: Path,
    provenance: str = "",
    window: int = 500,
    start: int | None = None,
) -> dict[str, Path]:
    """F4 · Forecast against actual over a representative test window."""
    apply_style()
    out_dir.mkdir(parents=True, exist_ok=True)

    predicted = np.asarray(predicted, dtype="float64")
    if start is None:
        # Centre on the busiest stretch: a quiet window shows two flat lines and
        # settles nothing.
        rolling = pd.Series(frame["fill_pct"].to_numpy()).rolling(window).mean()
        start = max(0, int(rolling.idxmax()) - window)

    stop = min(start + window, len(frame))
    slice_ = frame.iloc[start:stop]
    actual = slice_["fill_pct"].to_numpy()
    forecast = predicted[start:stop]
    x = np.arange(len(actual))

    figure, axis = plt.subplots(figsize=(9, 4.2))
    axis.plot(x, actual, lw=1.4, color=SERIES_BLUE, label="actual")
    axis.plot(x, forecast, lw=1.4, ls="--", color=SERIES_BLUE, alpha=0.65, label="forecast")
    _shade_band(axis, side="left")

    for label, series, offset in (("actual", actual, 6), ("forecast", forecast, -12)):
        axis.annotate(
            label,
            xy=(len(actual) - 1, series[-1]),
            xytext=(8, offset),
            textcoords="offset points",
            fontsize=8,
            color=INK_SECONDARY,
        )

    diagnostic = anticipation_diagnostic(actual, forecast)
    axis.set_ylim(0, 1)
    axis.set_xlabel(f"block index within the window ({len(actual)} blocks)")
    axis.set_ylabel("block fill")
    axis.set_title("F4 · Forecast against actual", loc="left")
    axis.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    axis.legend(loc="upper right", frameon=False, fontsize=8)

    verdict = "anticipates" if diagnostic["anticipates"] else "LAGS — learned persistence"
    axis.annotate(
        f"corr with next actual      {diagnostic['corr_with_target']:.3f}\n"
        f"corr with previous actual  {diagnostic['corr_with_previous']:.3f}\n"
        f"{verdict}",
        xy=(0.015, 0.70),
        xycoords="axes fraction",
        fontsize=7.5,
        family="monospace",
        color=INK,
        bbox={"boxstyle": "round,pad=0.4", "facecolor": SURFACE, "edgecolor": GRID},
    )
    _provenance(figure, provenance)
    figure.tight_layout()

    paths = {"figure": out_dir / "F4_forecast_vs_actual.png"}
    figure.savefig(paths["figure"], bbox_inches="tight")
    plt.close(figure)

    paths["table"] = out_dir.parent / "tables" / "F4_forecast_window.csv"
    paths["table"].parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {"abs_slot": slice_["abs_slot"].to_numpy(), "actual": actual, "forecast": forecast}
    ).to_csv(paths["table"], index=False)
    return paths


SUBMIT_GREEN = "#0ca30c"


def figure_f7(profile: dict, out_dir: Path, provenance: str = "") -> dict[str, Path]:
    """F7 · Action distribution over congestion deciles.

    **This is the figure that distinguishes a learned policy from a lucky one.**
    A flat profile means the agent ignores congestion however good F5 looks, and
    should be cross-checked against ablation A3.

    WAIT carries no colour — it is the common case, and colouring it would drown
    the state that matters (``docs/17-UI-SPEC.md`` A8).
    """
    apply_style()
    out_dir.mkdir(parents=True, exist_ok=True)

    deciles = sorted(profile, key=int)
    submit = np.array([profile[key]["submit_rate"] for key in deciles])
    wait = 1.0 - submit
    x = np.arange(len(deciles))

    figure, axis = plt.subplots(figsize=(8.5, 4.4))
    axis.bar(x, submit, color=SUBMIT_GREEN, width=0.74, label="SUBMIT")
    axis.bar(x, wait, bottom=submit, color=MUTED, alpha=0.35, width=0.74, label="WAIT")

    # Mean batch size as direct-labelled numerals, never a second y-axis.
    for index, key in enumerate(deciles):
        batch = profile[key].get("mean_batch_n")
        if batch:
            axis.text(
                index,
                1.02,
                f"{batch:.0f}",
                ha="center",
                fontsize=7.5,
                color=INK_SECONDARY,
            )

    axis.set_ylim(0, 1.10)
    axis.set_xticks(x)
    axis.set_xticklabels([str(int(key) + 1) for key in deciles])
    axis.set_xlabel("block fill decile (1 = emptiest)")
    axis.set_ylabel("share of decisions")
    axis.set_title("F7 · Action distribution over congestion deciles", loc="left")
    axis.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    axis.legend(loc="lower center", bbox_to_anchor=(0.5, -0.28), frameon=False, fontsize=8, ncol=2)
    axis.text(
        0, 1.06, "mean batch size", fontsize=7, color=MUTED, ha="left", transform=axis.transData
    )

    _provenance(figure, provenance)
    figure.tight_layout()

    paths = {"figure": out_dir / "F7_action_distribution.png"}
    figure.savefig(paths["figure"], bbox_inches="tight")
    plt.close(figure)

    paths["table"] = out_dir.parent / "tables" / "F7_action_distribution.csv"
    paths["table"].parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"decile": int(key) + 1, **profile[key]} for key in deciles]).to_csv(
        paths["table"], index=False
    )
    return paths


def figure_f3(out_dir: Path, n_max: int = 30, provenance: str = "") -> dict[str, Path]:
    """F3 · Amortization curve — why not simply always batch the maximum?

    Analytic, from the cost model; no experimental results required. Built early
    because it sharpens the objective before any policy is written.
    """
    apply_style()
    out_dir.mkdir(parents=True, exist_ok=True)

    sizes = np.arange(1, n_max + 11)
    cost = np.array([cost_per_user_ada(int(n)) for n in sizes])
    marginal_ada = marginal_component_lovelace() / 1_000_000

    figure, axis = plt.subplots(figsize=(7.5, 4.2))
    axis.plot(sizes, cost, lw=2, color=SERIES_BLUE)
    for mark in (1, 5, 10, 20, 30):
        if mark <= sizes.max():
            axis.plot(mark, cost_per_user_ada(mark), "o", ms=5, color=SERIES_BLUE)

    axis.axhline(marginal_ada, color=MUTED, lw=1, ls="--")
    axis.text(
        sizes.max(),
        marginal_ada,
        "  marginal cost asymptote",
        fontsize=7.5,
        color=INK_SECONDARY,
        va="bottom",
        ha="right",
    )
    axis.axvspan(n_max, sizes.max(), color=MUTED, alpha=0.13, linewidth=0)
    axis.text(
        n_max + 0.4,
        axis.get_ylim()[1] * 0.92,
        "infeasible (Gate A)",
        fontsize=7.5,
        color=INK_SECONDARY,
    )

    knee = 10
    axis.annotate(
        f"knee near n ≈ {knee}\n{cost_per_user_ada(knee):.3f} ADA/user",
        xy=(knee, cost_per_user_ada(knee)),
        xytext=(30, 34),
        textcoords="offset points",
        fontsize=8,
        color=INK_SECONDARY,
        arrowprops={"arrowstyle": "-", "color": MUTED, "lw": 0.8},
    )

    axis.set_xlabel("batch size n (orders)")
    axis.set_ylabel("per-user cost (ADA)")
    axis.set_title("F3 · Fee amortization across batch size", loc="left")

    _provenance(figure, provenance or f"flat={flat_component_lovelace():,} lovelace")
    figure.tight_layout()

    paths = {"figure": out_dir / "F3_amortization_curve.png"}
    figure.savefig(paths["figure"], bbox_inches="tight")
    plt.close(figure)

    paths["table"] = out_dir.parent / "tables" / "F3_amortization.csv"
    paths["table"].parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "n": sizes,
            "total_fee_ada": [cost_per_user_ada(int(n)) * int(n) for n in sizes],
            "cost_per_user_ada": cost,
        }
    ).to_csv(paths["table"], index=False)
    return paths
