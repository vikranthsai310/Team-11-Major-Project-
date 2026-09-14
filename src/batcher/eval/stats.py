"""Paired statistics (P6-2, ``docs/09-EVALUATION-PROTOCOL.md`` §5).

The design is paired — every policy sees the identical episode — so the tests are
paired too. Three rules shape everything here:

- **Non-parametric throughout.** Latency is heavy-tailed; a t-test would assume a
  normality the data does not have.
- **An effect size and a CI travel with every p-value.** A significant but
  negligible improvement is reported as negligible, which a bare p-value hides.
- **Holm–Bonferroni across the primary metrics**, so testing several metrics does
  not manufacture a significant one by chance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy.stats import wilcoxon

ALPHA = 0.05
BOOTSTRAP_RESAMPLES = 10_000


@dataclass(frozen=True)
class PairedResult:
    metric: str
    candidate: str
    reference: str
    n: int
    median_difference: float  # candidate minus reference; negative is lower
    ci_low: float
    ci_high: float
    p_value: float | None
    p_adjusted: float | None = None
    significant: bool = False

    @property
    def ci_excludes_zero(self) -> bool:
        return self.ci_low > 0 or self.ci_high < 0

    def as_dict(self) -> dict:
        return {**asdict(self), "ci_excludes_zero": self.ci_excludes_zero}


def bootstrap_median_ci(
    differences, resamples: int = BOOTSTRAP_RESAMPLES, level: float = 0.95, seed: int = 0
) -> tuple[float, float]:
    """Percentile bootstrap CI for the median paired difference. Seeded, so the
    interval is reproducible to the digit (NFR-3)."""
    values = np.asarray(differences, dtype="float64")
    if values.size == 0:
        return (float("nan"), float("nan"))

    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=(resamples, values.size), replace=True)
    medians = np.median(samples, axis=1)
    tail = (1 - level) / 2 * 100
    low, high = np.percentile(medians, [tail, 100 - tail])
    return float(low), float(high)


def paired_test(
    candidate, reference, *, metric: str, candidate_name: str, reference_name: str, seed: int = 0
) -> PairedResult:
    """Wilcoxon signed-rank on per-episode differences, plus a bootstrap CI.

    Episodes where either policy produced no value for the metric are dropped
    pairwise, never imputed — imputing a latency for an episode that settled
    nothing would invent the very number under test.
    """
    a = np.asarray(candidate, dtype="float64")
    b = np.asarray(reference, dtype="float64")
    if a.shape != b.shape:
        raise ValueError("paired samples must have the same length")

    keep = ~(np.isnan(a) | np.isnan(b))
    differences = a[keep] - b[keep]
    low, high = bootstrap_median_ci(differences, seed=seed)

    # Wilcoxon is undefined when every difference is zero — two identical
    # policies. That is a genuine "no difference", not an error.
    if differences.size == 0 or np.all(differences == 0):
        p_value = None if differences.size == 0 else 1.0
    else:
        p_value = float(wilcoxon(differences, zero_method="wilcox").pvalue)

    return PairedResult(
        metric=metric,
        candidate=candidate_name,
        reference=reference_name,
        n=int(differences.size),
        median_difference=float(np.median(differences)) if differences.size else float("nan"),
        ci_low=low,
        ci_high=high,
        p_value=p_value,
    )


def holm_bonferroni(results: list[PairedResult], alpha: float = ALPHA) -> list[PairedResult]:
    """Adjust a family of p-values, preserving input order in the output.

    Step-down: sort ascending, multiply the i-th smallest by (m - i), enforce
    monotonicity, cap at 1. A result is significant only if its adjusted p-value
    clears alpha **and** its CI excludes zero — the two must agree.
    """
    tested = [(index, r) for index, r in enumerate(results) if r.p_value is not None]
    m = len(tested)
    adjusted: dict[int, float] = {}

    running = 0.0
    for rank, (index, result) in enumerate(sorted(tested, key=lambda item: item[1].p_value)):
        value = min(1.0, (m - rank) * result.p_value)
        running = max(running, value)
        adjusted[index] = running

    out = []
    for index, result in enumerate(results):
        p_adj = adjusted.get(index)
        significant = p_adj is not None and p_adj < alpha and result.ci_excludes_zero
        out.append(
            PairedResult(**{**asdict(result), "p_adjusted": p_adj, "significant": significant})
        )
    return out


def median_ci(values, seed: int = 0) -> tuple[float, float, float]:
    """``(median, ci_low, ci_high)`` for one policy's per-episode values — the
    cell format of the main results table."""
    array = np.asarray(values, dtype="float64")
    array = array[~np.isnan(array)]
    if array.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    low, high = bootstrap_median_ci(array, seed=seed)
    return float(np.median(array)), low, high
