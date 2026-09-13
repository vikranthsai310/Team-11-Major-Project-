"""P2-5, P2-6 — the D2 order stream.

The arrival rate is the single most load-bearing modelling parameter in the
evaluation: if it is wrong, every latency and expiry number describes a system
under the wrong load. These tests pin it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from batcher.data.collector import collect_blocks
from batcher.sim.orders import (
    ARRIVAL_RATES,
    ArrivalProcess,
    OrderStream,
    fit_arrival_process,
)
from conftest import BASE_HEIGHT, FakeSource, make_records

FLAT = tuple([1.0] * 24)


@pytest.fixture(scope="module")
def blocks(tmp_path_factory):
    source = FakeSource(make_records(2000, seed=3))
    return collect_blocks(
        source,
        start_height=BASE_HEIGHT,
        end_height=source.tip_height(),
        staging_dir=tmp_path_factory.mktemp("staging"),
        page_size=500,
    )


def drain(stream: OrderStream, blocks: pd.DataFrame) -> list:
    orders = []
    previous = int(blocks.iloc[0]["abs_slot"]) - 1
    for block in blocks.itertuples():
        slot = int(block.abs_slot)
        orders += stream.arrivals(previous, slot, block.block_time.hour)
        previous = slot
    return orders


def test_the_fitted_rate_produces_the_requested_orders_per_block(blocks):
    """The regression guard for a real bug: bursts once inflated this 4.5x.

    A per-block burst probability read without reference to burst duration put
    the stream in burst ~78 % of the time, so the configured base rate was never
    observed and E1 appeared to fail catastrophically at small M.
    """
    target = 2.0
    process = fit_arrival_process(blocks, orders_per_block=target)
    stream = OrderStream(process, np.random.default_rng(0))

    per_block = len(drain(stream, blocks)) / len(blocks)
    assert per_block == pytest.approx(target, rel=0.25)


def test_bursts_are_rare_rather_than_the_normal_state(blocks):
    process = fit_arrival_process(blocks, bursts_per_day=1.0, burst_hours=1.0)
    assert process.to_manifest()["expected_burst_share"] == pytest.approx(1 / 24)
    assert process.burst_probability_per_block < 0.001


def test_bursts_raise_the_rate_when_they_happen(blocks):
    quiet = fit_arrival_process(blocks, bursts_per_day=0.0)
    bursty = fit_arrival_process(blocks, bursts_per_day=24.0, burst_multiplier=6.0)

    quiet_n = len(drain(OrderStream(quiet, np.random.default_rng(1)), blocks))
    bursty_n = len(drain(OrderStream(bursty, np.random.default_rng(1)), blocks))
    assert bursty_n > quiet_n


def test_arrival_rate_multipliers_scale_the_stream(blocks):
    process = fit_arrival_process(blocks, bursts_per_day=0.0)
    counts = {}
    for name, multiplier in ARRIVAL_RATES.items():
        stream = OrderStream(process, np.random.default_rng(5), rate_multiplier=multiplier)
        counts[name] = len(drain(stream, blocks))

    assert counts["light"] < counts["matched"] < counts["heavy"]
    assert counts["heavy"] / counts["matched"] == pytest.approx(2.0, rel=0.1)
    assert counts["light"] / counts["matched"] == pytest.approx(0.5, rel=0.1)


def test_the_diurnal_shape_is_fitted_to_real_transaction_counts(blocks):
    process = fit_arrival_process(blocks)
    assert len(process.diurnal) == 24
    assert np.mean(process.diurnal) == pytest.approx(1.0, rel=0.1)


def test_a_flat_process_has_no_diurnal_variation():
    process = ArrivalProcess(base_per_slot=0.1, diurnal=FLAT)
    assert process.intensity(3) == process.intensity(15)


def test_the_same_seed_regenerates_an_identical_stream(blocks):
    """Order ids come from the seeded sequence, never a UUID (docs/08 §6)."""
    process = fit_arrival_process(blocks, bursts_per_day=0.0)
    first = drain(OrderStream(process, np.random.default_rng(9), episode_id="e"), blocks)
    second = drain(OrderStream(process, np.random.default_rng(9), episode_id="e"), blocks)

    assert [o.order_id for o in first] == [o.order_id for o in second]
    assert [o.arrival_slot for o in first] == [o.arrival_slot for o in second]


def test_orders_carry_the_estimator_cost_dimensions(blocks):
    from batcher.build.estimator import ORDER_MEM, ORDER_SIZE_B, ORDER_STEPS

    process = fit_arrival_process(blocks)
    order = drain(OrderStream(process, np.random.default_rng(2)), blocks)[0]

    assert order.size_bytes == ORDER_SIZE_B
    assert order.mem_exunits == ORDER_MEM
    assert order.step_exunits == ORDER_STEPS
    assert order.ttl_slot > order.arrival_slot
