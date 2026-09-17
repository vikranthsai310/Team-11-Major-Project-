"""Capacity calibration for the live batcher: Gate A against the chain as it is.

``build.estimator`` answers Gate A with protocol limits fixed in
``config.protocol`` and a linear per-order cost model. Both are right for the
simulator, whose recorded results must stay reproducible, and both can be wrong
on a live chain:

* **Limits change by governance.** A parameter update (or Leios) can lower
  ``max_tx_size`` or the execution budget between two epochs.
* **The cost model is an estimate.** The first real batch on preprod measured
  2 682 bytes against an estimate of 800 — 3.4× larger, the unsafe direction —
  while memory and steps came in at a fifth of theirs.

:class:`CapacityCalibrator` corrects both for the live daemon only, and never
touches the estimator's constants:

1. **Effective limits.** Each limit is ``min(live, configured)``: a stricter live
   value is obeyed and warned about; a looser one is ignored until the constant
   is deliberately raised. Read at most once per ``refresh_blocks`` blocks or when
   the epoch changes.
2. **Learned correction.** Per dimension ``d``, a factor ``f_d`` multiplies the
   estimator's own ``tx_size`` / ``tx_mem`` / ``tx_steps``. An observation
   ``r = actual / estimate`` with ``r·(1 + SAFETY_MARGIN) ≥ f_d`` raises ``f_d`` to
   that value at once. Lowering needs ``MIN_SAMPLES`` consecutive observations
   that all argue for less, and then goes only to
   ``(1 + SAFETY_MARGIN) · max(max of those ratios, EWMA of all ratios)``, never
   below ``MIN_FACTOR``.
3. **Calibrated Gate A.** The largest ``n`` with ``ceil(f_d · estimate_d(n)) ≤
   limit_d`` for every dimension.
4. **Failure feedback.** A build refused for size or budget tightens the
   dimension it names (see :func:`capacity_failure`), so the retry at a smaller
   ``n`` and every later decision see the tighter model.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from batcher.build.estimator import tx_mem, tx_size, tx_steps
from batcher.config.protocol import (
    MAX_TX_EX_MEM,
    MAX_TX_EX_STEPS,
    MAX_TX_SIZE,
    MIN_FEE_A,
    MIN_FEE_B,
    PRICE_MEM,
    PRICE_STEPS,
)

SIZE, MEM, STEPS = "size", "mem", "steps"
DIMENSIONS = (SIZE, MEM, STEPS)

# Headroom added on top of every observed ratio.
SAFETY_MARGIN = 0.10
# Weight of the newest ratio in the running average.
EWMA_ALPHA = 0.3
# Consecutive observations needed before a factor may be lowered.
MIN_SAMPLES = 5
# No factor goes below this, however cheap transactions measure.
MIN_FACTOR = 0.5
# Multiplier applied on a refusal that does not say by how much a limit was missed.
FAILURE_TIGHTEN = 1.5
# Blocks between protocol parameter reads (about two hours on preprod); an epoch
# change also triggers a read.
REFRESH_BLOCKS = 360
# Warnings kept for the snapshot.
WARNINGS_KEPT = 20

# PyCardano's field for each limit, and the configured constant it is held to.
_LIMIT_PARAMS = {SIZE: "max_tx_size", MEM: "max_tx_ex_mem", STEPS: "max_tx_ex_steps"}
_FEE_PARAMS = {
    "min_fee_coefficient": MIN_FEE_A,
    "min_fee_constant": MIN_FEE_B,
    "price_mem": PRICE_MEM,
    "price_step": PRICE_STEPS,
}

_PYCARDANO_SIZE = re.compile(r"transaction size \((\d+)\) exceeds", re.IGNORECASE)


class CapacityExceeded(RuntimeError):
    """A built transaction measured above an effective per-transaction limit."""

    def __init__(self, dimensions: Sequence[str], message: str):
        super().__init__(message)
        self.dimensions = tuple(dimensions)


@dataclass(frozen=True)
class CapacityLimits:
    size: int
    mem: int
    steps: int

    def of(self, dimension: str) -> int:
        return getattr(self, dimension)


CONFIGURED_LIMITS = CapacityLimits(MAX_TX_SIZE, MAX_TX_EX_MEM, MAX_TX_EX_STEPS)


@dataclass
class DimensionCorrection:
    """The learned ``actual / estimate`` correction for one dimension."""

    factor: float = 1.0
    ratio_ewma: float | None = None
    samples: int = 0
    # Consecutive recent ratios that each argued for a lower factor.
    lower: list[float] = field(default_factory=list)

    def observe(self, ratio: float, min_samples: int, floor: float) -> None:
        self.samples += 1
        self.ratio_ewma = (
            ratio
            if self.ratio_ewma is None
            else EWMA_ALPHA * ratio + (1 - EWMA_ALPHA) * self.ratio_ewma
        )
        target = ratio * (1 + SAFETY_MARGIN)
        if target >= self.factor:
            # Under-estimation is the unsafe direction: corrected on the first sight.
            self.factor = target
            self.lower.clear()
            return
        self.lower.append(ratio)
        if len(self.lower) >= min_samples:
            window = self.lower[-min_samples:]
            evidence = (1 + SAFETY_MARGIN) * max(max(window), self.ratio_ewma)
            self.factor = max(floor, min(self.factor, evidence))
            del self.lower[: len(self.lower) - min_samples + 1]  # slide, don't restart

    def tighten(self, bound: float | None) -> None:
        """A refusal: the true ratio is at least ``bound``, or unknown but too low."""
        raised = self.factor * FAILURE_TIGHTEN
        if bound is not None:
            raised = max(raised, bound * (1 + SAFETY_MARGIN))
        self.factor = max(self.factor, raised)
        self.lower.clear()


def capacity_failure(error: BaseException) -> tuple[tuple[str, ...], int | None] | None:
    """Which limits a build or submission error says were exceeded, or ``None``.

    Returns ``(dimensions, measured_size)``. Recognised:

    * PyCardano's ``InvalidTransactionException`` "Transaction size (N) exceeds the
      max limit" — raised while balancing, it also carries the measured size;
    * the ledger's ``MaxTxSizeUTxO`` and ``ExUnitsTooBigUTxO`` rejections;
    * an evaluator reporting an overspent or exceeded execution budget. Which of
      memory or steps ran out is taken from the message only when exactly one is
      named; otherwise both are tightened.
    """
    text = f"{type(error).__name__}: {error}".lower()
    if match := _PYCARDANO_SIZE.search(text):
        return (SIZE,), int(match.group(1))
    if "maxtxsizeutxo" in text or "txtoolarge" in text:
        return (SIZE,), None
    budget = (
        "exunitstoobig" in text
        or "overspent" in text
        or "out of budget" in text
        or ("execution" in text and ("exceed" in text or "too big" in text))
    )
    if not budget:
        return None
    named_mem = "mem" in text
    named_steps = "step" in text or "cpu" in text
    if named_mem != named_steps:
        return ((MEM,) if named_mem else (STEPS,)), None
    return (MEM, STEPS), None


def read_d4_rows(path: Path) -> list[dict]:
    """D4 rows from a JSONL file; missing file or unreadable lines are skipped."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


class CapacityCalibrator:
    """Effective per-transaction limits and learned estimate corrections."""

    def __init__(
        self,
        configured: CapacityLimits = CONFIGURED_LIMITS,
        *,
        refresh_blocks: int = REFRESH_BLOCKS,
        min_samples: int = MIN_SAMPLES,
        min_factor: float = MIN_FACTOR,
    ):
        self.configured = configured
        self.limits = configured
        self.live_limits: dict[str, int | None] = dict.fromkeys(DIMENSIONS)
        self.refresh_blocks = refresh_blocks
        self.min_samples = min_samples
        self.min_factor = min_factor
        self.corrections = {d: DimensionCorrection() for d in DIMENSIONS}
        self.refreshed_height: int | None = None
        self.refreshed_epoch: int | None = None
        self.warnings: list[dict] = []
        self._unreported: list[dict] = []
        self._last_key: object = None

    # --- protocol parameters ---------------------------------------------------------------

    def refresh(self, context, height: int) -> bool:
        """Re-read live limits if due. Returns whether they were read.

        A failed read keeps the limits in force (never looser than the configured
        ones) and is retried at the next call.
        """
        try:
            epoch = context.epoch
        except Exception:
            epoch = None
        due = (
            self.refreshed_height is None
            or height - self.refreshed_height >= self.refresh_blocks
            or (epoch is not None and epoch != self.refreshed_epoch)
        )
        if not due:
            return False
        try:
            params = context.protocol_param
        except Exception as error:
            self._warn(
                height,
                f"protocol parameters unreadable ({type(error).__name__}); keeping {self.limits}",
            )
            return False
        self.apply_protocol_params(params, height)
        self.refreshed_height, self.refreshed_epoch = height, epoch
        return True

    def apply_protocol_params(self, params, height: int | None = None) -> CapacityLimits:
        """Hold each limit to ``min(live, configured)``; warn when live is stricter."""
        effective = {}
        for dimension, name in _LIMIT_PARAMS.items():
            configured = self.configured.of(dimension)
            live = _positive_int(getattr(params, name, None))
            self.live_limits[dimension] = live
            value = configured if live is None else min(live, configured)
            if value < configured and value != self.limits.of(dimension):
                self._warn(
                    height,
                    f"protocol parameter changed: {name} is {live} on chain, below the "
                    f"configured {configured}; Gate A now uses {live}",
                )
            effective[dimension] = value
        self.limits = CapacityLimits(**effective)

        for name, configured in _FEE_PARAMS.items():
            live = getattr(params, name, None)
            try:
                changed = live is not None and not math.isclose(float(live), configured)
            except (TypeError, ValueError):
                changed = False
            if changed and not any(name in w["message"] for w in self.warnings):
                self._warn(
                    height,
                    f"fee parameter changed: {name} is {live} on chain, configured "
                    f"{configured}; live fees follow the chain, the simulator's model does not",
                )
        return self.limits

    # --- learning ----------------------------------------------------------------------------

    def observe(self, dimension: str, estimate: int, actual: int) -> None:
        if estimate > 0 and actual > 0:
            self.corrections[dimension].observe(
                actual / estimate, self.min_samples, self.min_factor
            )

    def observe_measurement(
        self,
        estimates: tuple[int, int, int],
        actuals: tuple[int, int, int],
        key: object = None,
    ) -> bool:
        """Learn from one measured transaction. A repeat of ``key`` is ignored.

        Shadow mode rebuilds the same batch every block; counting each rebuild
        would let one transaction pass for ``MIN_SAMPLES`` independent ones.
        """
        if key is not None and key == self._last_key:
            return False
        self._last_key = key
        for dimension, estimate, actual in zip(DIMENSIONS, estimates, actuals, strict=True):
            self.observe(dimension, estimate, actual)
        return True

    def observe_built(self, built, key: object = None) -> bool:
        """Learn from a ``BuiltBatch`` — the D4 measurement of a built transaction."""
        return self.observe_measurement(
            (built.estimated_size, built.estimated_mem, built.estimated_steps),
            (built.actual_size, built.actual_mem, built.actual_steps),
            key,
        )

    def seed_from_d4(self, rows: Iterable[dict]) -> int:
        """Replay measured D4 rows. Returns how many were used."""
        used = 0
        for row in rows:
            try:
                estimates = (int(row["est_size"]), int(row["est_mem"]), int(row["est_steps"]))
                actuals = (
                    int(row["actual_size"]),
                    int(row["actual_mem"]),
                    int(row["actual_steps"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            self.observe_measurement(estimates, actuals)
            used += 1
        self._last_key = None
        return used

    def record_failure(
        self,
        error: BaseException,
        sizes: Sequence[int],
        mems: Sequence[int],
        steps: Sequence[int],
    ) -> tuple[str, ...]:
        """Tighten the dimensions a refused build of these orders exceeded.

        Returns the dimensions, empty if ``error`` is not a capacity failure.
        """
        found = capacity_failure(error)
        if found is None:
            return ()
        dimensions, measured_size = found
        n = len(sizes)
        estimates = dict(zip(DIMENSIONS, self._estimates(n, sizes, mems, steps), strict=True))
        for dimension in dimensions:
            if dimension == SIZE and measured_size is not None:
                self.observe(SIZE, estimates[SIZE], measured_size)
                continue
            estimate = estimates[dimension]
            # The refused transaction was over the limit, so its ratio was at least this.
            bound = self.limits.of(dimension) / estimate if estimate > 0 else None
            self.corrections[dimension].tighten(bound)
        return dimensions

    # --- the calibrated gate -----------------------------------------------------------------

    @property
    def factors(self) -> dict[str, float]:
        return {d: c.factor for d, c in self.corrections.items()}

    def corrected(
        self, n: int, sizes: Sequence[int], mems: Sequence[int], steps: Sequence[int]
    ) -> tuple[int, int, int]:
        base = self._estimates(n, sizes, mems, steps)
        return tuple(
            math.ceil(self.corrections[d].factor * value)
            for d, value in zip(DIMENSIONS, base, strict=True)
        )  # type: ignore[return-value]

    def fits(self, n: int, sizes: Sequence[int], mems: Sequence[int], steps: Sequence[int]) -> bool:
        return all(
            value <= self.limits.of(d)
            for d, value in zip(DIMENSIONS, self.corrected(n, sizes, mems, steps), strict=True)
        )

    def max_n(self, sizes: Sequence[int], mems: Sequence[int], steps: Sequence[int]) -> int:
        """Largest ``n`` whose corrected estimates fit the effective limits."""
        n = 0
        while n < len(sizes) and self.fits(n + 1, sizes, mems, steps):
            n += 1
        return n

    def exceeded(self, built) -> list[str]:
        """Dimensions in which a built transaction measured above the effective limit."""
        actual = {SIZE: built.actual_size, MEM: built.actual_mem, STEPS: built.actual_steps}
        return [d for d in DIMENSIONS if actual[d] > self.limits.of(d)]

    # --- observability -----------------------------------------------------------------------

    def snapshot(self) -> dict:
        """Factors, limits and warnings raised since the previous snapshot."""
        unreported, self._unreported = self._unreported, []
        return {
            "factors": {d: round(f, 4) for d, f in self.factors.items()},
            "samples": {d: c.samples for d, c in self.corrections.items()},
            "limits": asdict(self.limits),
            "live_limits": dict(self.live_limits),
            "warnings": [w["message"] for w in unreported],
        }

    def _estimates(self, n, sizes, mems, steps) -> tuple[int, int, int]:
        return tx_size(n, sizes), tx_mem(n, mems), tx_steps(n, steps)

    def _warn(self, height: int | None, message: str) -> None:
        if self.warnings and self.warnings[-1]["message"] == message:
            return
        warning = {"height": height, "message": message}
        self.warnings = [*self.warnings, warning][-WARNINGS_KEPT:]
        self._unreported.append(warning)


def _positive_int(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
