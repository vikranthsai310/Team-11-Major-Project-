"""P6-2 — paired statistics. A wrong p-value or CI reaches the report unnoticed,
so each piece is checked against a case whose answer is known in advance."""

from __future__ import annotations

import numpy as np
import pytest

from batcher.eval.stats import (
    PairedResult,
    bootstrap_median_ci,
    holm_bonferroni,
    median_ci,
    paired_test,
)


def test_a_clear_improvement_is_significant_with_a_ci_below_zero():
    rng = np.random.default_rng(0)
    reference = rng.normal(150, 10, 60)
    candidate = reference - 20 + rng.normal(0, 2, 60)

    result = paired_test(
        candidate, reference, metric="l_p95", candidate_name="p2", reference_name="e2"
    )
    assert result.p_value < 0.001
    assert result.ci_high < 0
    assert result.ci_excludes_zero
    assert result.median_difference == pytest.approx(-20, abs=2)


def test_no_real_difference_is_not_significant():
    rng = np.random.default_rng(1)
    reference = rng.normal(150, 10, 60)
    candidate = reference + rng.normal(0, 5, 60)

    result = paired_test(candidate, reference, metric="m", candidate_name="a", reference_name="b")
    assert result.p_value > 0.05
    assert not result.ci_excludes_zero


def test_identical_policies_are_no_difference_rather_than_an_error():
    """P2 at N_MIN=1 is byte-identical to greedy; Wilcoxon is undefined there."""
    values = np.arange(30, dtype=float)
    result = paired_test(values, values.copy(), metric="m", candidate_name="a", reference_name="b")
    assert result.p_value == 1.0
    assert result.median_difference == 0.0


def test_pairing_is_respected_not_pooled():
    """Large between-episode spread, tiny consistent within-pair gap: only a paired
    test sees it. An unpaired comparison would drown it in the spread."""
    rng = np.random.default_rng(2)
    reference = rng.uniform(50, 500, 40)
    candidate = reference - 3

    result = paired_test(candidate, reference, metric="m", candidate_name="a", reference_name="b")
    assert result.p_value < 0.001


def test_missing_values_are_dropped_pairwise_never_imputed():
    candidate = np.array([10.0, np.nan, 12.0, 11.0, 9.0, 13.0])
    reference = np.array([12.0, 14.0, np.nan, 13.0, 11.0, 15.0])
    result = paired_test(candidate, reference, metric="m", candidate_name="a", reference_name="b")
    assert result.n == 4


def test_mismatched_lengths_are_refused():
    with pytest.raises(ValueError):
        paired_test([1, 2, 3], [1, 2], metric="m", candidate_name="a", reference_name="b")


def test_bootstrap_ci_is_reproducible_to_the_digit():
    values = np.random.default_rng(3).normal(0, 1, 50)
    assert bootstrap_median_ci(values, seed=7) == bootstrap_median_ci(values, seed=7)


def test_bootstrap_ci_contains_the_sample_median():
    values = np.random.default_rng(4).exponential(10, 200)
    low, high = bootstrap_median_ci(values)
    assert low <= np.median(values) <= high


def test_holm_matches_a_hand_computed_example():
    """p = [0.01, 0.04, 0.03], m = 3. Sorted 0.01, 0.03, 0.04 -> x3, x2, x1 ->
    0.03, 0.06, 0.04 -> monotone 0.03, 0.06, 0.06."""

    def fake(p):
        return PairedResult("m", "a", "b", 30, -1.0, -2.0, -0.5, p)

    adjusted = holm_bonferroni([fake(0.01), fake(0.04), fake(0.03)])
    assert [r.p_adjusted for r in adjusted] == pytest.approx([0.03, 0.06, 0.06])
    assert [r.significant for r in adjusted] == [True, False, False]


def test_significance_requires_the_ci_to_agree_with_the_p_value():
    """A small p with a CI straddling zero is not reported as significant."""
    straddling = PairedResult("m", "a", "b", 30, -0.1, -1.0, 0.8, 0.001)
    (result,) = holm_bonferroni([straddling])
    assert result.p_adjusted < 0.05
    assert not result.significant


def test_untestable_results_pass_through_holm():
    empty = PairedResult("m", "a", "b", 0, float("nan"), float("nan"), float("nan"), None)
    (result,) = holm_bonferroni([empty])
    assert result.p_adjusted is None and not result.significant


def test_median_ci_is_the_results_table_cell():
    median, low, high = median_ci([5.0, 6.0, 7.0, np.nan, 8.0])
    assert median == 6.5
    assert low <= median <= high
