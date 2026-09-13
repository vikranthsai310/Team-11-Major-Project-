"""Metric definitions (``docs/09-EVALUATION-PROTOCOL.md`` §2).

**L-p95 is the headline.** Mean latency can be improved by favouring easy
periods; the tail is where a badly timed batcher actually hurts users.

An episode in which nothing settled returns ``None`` for latency metrics rather
than a silent NaN — a NaN propagates into a mean and quietly poisons a results
table, which is exactly the failure mode this project's testing exists to catch.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from batcher.sim.env import EpisodeResult

SLOTS_PER_THROUGHPUT_UNIT = 1000


@dataclass(frozen=True)
class Metrics:
    l_mean: float | None
    l_p95: float | None
    w_max: int | None
    c_user: float | None
    x_rate: float
    throughput: float
    f_jain: float | None
    s_slip: float | None
    lock_occupancy: float
    batch_n: float | None
    submissions: int
    settled: int
    gate_a_violations: int

    def as_dict(self) -> dict:
        return asdict(self)


def jain_index(values) -> float | None:
    """``(sum w)^2 / (n * sum w^2)``. 1.0 means everyone waited equally.

    Included because a policy can improve mean latency by systematically
    sacrificing a minority of orders, and that must be visible.
    """
    array = np.asarray(list(values), dtype="float64")
    if array.size == 0:
        return None
    denominator = array.size * np.sum(array**2)
    if denominator == 0:
        return 1.0
    return float(np.sum(array) ** 2 / denominator)


def compute(result: EpisodeResult) -> Metrics:
    latencies = sorted(order.latency for order in result.settled)
    arrived = result.orders_arrived

    return Metrics(
        l_mean=float(np.mean(latencies)) if latencies else None,
        l_p95=float(np.percentile(latencies, 95)) if latencies else None,
        w_max=int(max(latencies)) if latencies else None,
        c_user=_mean([order.fee_share for order in result.settled]),
        x_rate=len(result.expired) / arrived if arrived else 0.0,
        throughput=(
            len(result.settled) * SLOTS_PER_THROUGHPUT_UNIT / result.total_slots
            if result.total_slots
            else 0.0
        ),
        f_jain=jain_index(latencies) if latencies else None,
        s_slip=_mean([order.slippage for order in result.settled]),
        lock_occupancy=result.locked_slots / result.total_slots if result.total_slots else 0.0,
        batch_n=_mean(result.submissions),
        submissions=len(result.submissions),
        settled=len(result.settled),
        gate_a_violations=result.gate_a_violations,
    )


def _mean(values) -> float | None:
    # Fixed-order aggregation: sorted input, summed left to right, so the
    # floating-point result is bit-identical across runs (docs/08 §6).
    values = list(values)
    if not values:
        return None
    return float(np.mean(values))


def conserved(result: EpisodeResult) -> bool:
    """T-P3 — orders in equals settled plus expired plus still queued.

    If order accounting leaks, throughput and expiry are both wrong and the leak
    is otherwise invisible.
    """
    accounted = len(result.settled) + len(result.expired) + len(result.still_queued)
    return accounted == result.orders_arrived
