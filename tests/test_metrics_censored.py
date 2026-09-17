"""Phase 8 — censored latency: an expired order must not make a policy look faster."""

from __future__ import annotations

import numpy as np
import pytest

from batcher.eval import metrics
from batcher.queue.manager import Order
from batcher.sim.env import EpisodeResult, SettledOrder


def settled(arrival: int, confirm: int) -> SettledOrder:
    return SettledOrder(
        order_id=f"s{arrival}",
        arrival_slot=arrival,
        confirm_slot=confirm,
        fee_share=100.0,
        slippage=0.0,
    )


def expired(arrival: int, ttl: int) -> Order:
    return Order(
        order_id=f"x{arrival}",
        arrival_slot=arrival,
        size_bytes=100,
        mem_exunits=1,
        step_exunits=1,
        amount_in=1,
        min_out=0,
        ttl_slot=ttl,
    )


def result() -> EpisodeResult:
    return EpisodeResult(
        settled=[settled(0, 10), settled(5, 25), settled(10, 40)],
        expired=[expired(20, 3_620)],
        submissions=[3],
        total_slots=4_000,
        orders_arrived=4,
    )


def test_settled_only_metrics_are_unchanged():
    m = metrics.compute(result())
    assert m.l_mean == pytest.approx(20.0)
    assert m.l_p95 == pytest.approx(np.percentile([10, 20, 30], 95))
    assert m.w_max == 30
    assert m.x_rate == pytest.approx(0.25)


def test_expired_orders_count_their_wait_until_expiry():
    m = metrics.compute(result())
    censored = [10, 20, 30, 3_600]
    assert metrics.censored_latencies(result()) == censored
    assert m.l_mean_all == pytest.approx(np.mean(censored))
    assert m.l_p95_all == pytest.approx(np.percentile(censored, 95))
    assert m.w_max_all == 3_600
    assert m.l_p95_all > m.l_p95


def test_without_expiries_both_views_agree():
    r = result()
    r.expired = []
    m = metrics.compute(r)
    assert (m.l_mean_all, m.l_p95_all, m.w_max_all) == (m.l_mean, m.l_p95, m.w_max)


def test_an_all_expired_episode_still_has_a_censored_latency():
    r = EpisodeResult(expired=[expired(0, 100)], total_slots=200, orders_arrived=1)
    m = metrics.compute(r)
    assert m.l_p95 is None
    assert m.l_p95_all == pytest.approx(100.0)


def test_the_new_columns_are_appended_after_the_existing_ones():
    keys = list(metrics.compute(result()).as_dict())
    assert keys[:13] == [
        "l_mean",
        "l_p95",
        "w_max",
        "c_user",
        "x_rate",
        "throughput",
        "f_jain",
        "s_slip",
        "lock_occupancy",
        "batch_n",
        "submissions",
        "settled",
        "gate_a_violations",
    ]
    assert keys[13:] == ["l_mean_all", "l_p95_all", "w_max_all"]
