"""A5 — estimation error against Gate A.

Perfect estimation (assumption A4) is what makes S2's zero exact. These tests pin
the direction and size of the effect when that assumption is relaxed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from batcher.build.estimator import max_n_satisfying_gate_a

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "ablation_a5", REPO_ROOT / "scripts" / "ablation_a5.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


a5 = _load()
NOMINAL = max_n_satisfying_gate_a(limit=200)


def test_perfect_estimation_invalidates_nothing():
    assert a5.violating_sizes(0.0) == []


def test_over_estimation_is_safe():
    """If true costs are lower than estimated, every estimated-feasible batch is valid."""
    assert a5.violating_sizes(-0.10) == []


def test_under_estimation_invalidates_the_largest_batches():
    """The dangerous direction: true costs above the estimate shrink the real cap."""
    bad = a5.violating_sizes(0.10)
    assert bad, "a 10 % under-estimate should invalidate some estimated-feasible sizes"
    assert max(bad) == NOMINAL
    assert bad == list(range(min(bad), NOMINAL + 1)), "violations sit contiguously at the top"


def test_larger_error_invalidates_more_sizes():
    assert len(a5.violating_sizes(0.10)) >= len(a5.violating_sizes(0.05))
