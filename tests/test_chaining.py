"""Transaction chaining in the simulator: more than one batch pending at once.

At ``chain_depth=1`` the simulator is exactly the recorded one (the pool is locked
until its batch resolves). Above 1 a batch may spend the pool output of a batch still
in the mempool, which lifts the one-batch-per-block throughput ceiling that holds
orders past the deadline under heavy load.
"""

from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from batcher.build.estimator import gate_a, tx_size
from batcher.config.protocol import MAX_BLOCK_SIZE
from batcher.data.collector import collect_blocks
from batcher.eval import metrics
from batcher.policy.static import FixedSize, Greedy
from batcher.sim import env
from batcher.sim.env import run_episode
from batcher.sim.orders import ArrivalProcess, OrderStream
from conftest import BASE_HEIGHT, FakeSource, make_records

FLAT_DIURNAL = tuple([1.0] * 24)


@pytest.fixture(scope="module")
def blocks():
    source = FakeSource(make_records(1200, seed=23))
    with tempfile.TemporaryDirectory() as tmp:
        frame = collect_blocks(
            source,
            start_height=BASE_HEIGHT,
            end_height=source.tip_height(),
            staging_dir=Path(tmp),
            page_size=400,
        )
    # Empty blocks: capacity never binds, so only the chaining rule is under test.
    frame["block_size"] = 0
    frame["mem_exunits"] = 0
    frame["step_exunits"] = 0
    return frame


def run(blocks, policy, rate: float, seed: int = 5, **kwargs):
    process = ArrivalProcess(base_per_slot=rate, diurnal=FLAT_DIURNAL, bursts_per_day=0.0)
    stream = OrderStream(process, np.random.default_rng(seed), episode_id="chain")
    return run_episode(
        blocks, policy, stream, np.random.default_rng(seed + 1), policy_name=policy.name, **kwargs
    )


def submits_per_block(result) -> Counter:
    return Counter(d["abs_slot"] for d in result.decisions if d["action"] == "SUBMIT" and d["n"])


def test_a_chain_depth_below_one_is_refused(blocks):
    with pytest.raises(ValueError, match="chain_depth"):
        run(blocks, Greedy(), rate=0.1, chain_depth=0)


def test_depth_one_is_the_recorded_simulator(blocks):
    default = metrics.compute(run(blocks, Greedy(), rate=1.5))
    explicit = metrics.compute(run(blocks, Greedy(), rate=1.5, chain_depth=1))
    assert default.as_dict() == explicit.as_dict()
    assert max(submits_per_block(run(blocks, Greedy(), rate=1.5)).values()) == 1


def test_chaining_stacks_batches_when_the_backlog_exceeds_one_batch(blocks):
    """Arrivals faster than one Gate A batch per block: depth 1 falls behind, depth 3 keeps up."""
    single = run(blocks, Greedy(), rate=2.0)
    chained = run(blocks, Greedy(), rate=2.0, chain_depth=3)

    assert max(submits_per_block(chained).values()) > 1
    assert metrics.conserved(single) and metrics.conserved(chained)

    one, three = metrics.compute(single), metrics.compute(chained)
    assert three.l_p95 < one.l_p95
    assert len(chained.settled) >= len(single.settled)


def test_every_chained_batch_still_respects_gate_a(blocks):
    result = run(blocks, Greedy(), rate=2.0, chain_depth=3)
    assert result.submissions
    assert all(gate_a(n) for n in result.submissions)


def test_chained_batches_share_the_space_of_the_block_they_land_in(blocks):
    """Room for exactly one batch of four per block: a stacked child waits a block."""
    tight = blocks.copy()
    tight["block_size"] = MAX_BLOCK_SIZE - int(1.5 * tx_size(4))

    roomy = run(blocks, FixedSize(4), rate=1.0, chain_depth=2)
    cramped = run(tight, FixedSize(4), rate=1.0, chain_depth=2)

    per_block = lambda result: Counter(s.confirm_slot for s in result.settled)  # noqa: E731
    assert max(per_block(roomy).values()) == 8  # parent and child land together
    assert max(per_block(cramped).values()) == 4  # the child has to wait for the next block
    assert metrics.conserved(cramped)


def test_a_rolled_back_parent_takes_its_children_down(blocks, monkeypatch):
    monkeypatch.setattr(env, "ROLLBACK_PROBABILITY", 1.0)
    result = run(blocks, FixedSize(4), rate=1.0, chain_depth=2)

    assert result.rollbacks > 0
    assert result.settled == []  # nothing chained on an undone parent may settle
    assert metrics.conserved(result)


@pytest.mark.parametrize("depth", [1, 2, 4])
def test_orders_are_conserved_at_every_depth(blocks, depth):
    result = run(blocks, Greedy(), rate=2.5, chain_depth=depth)
    assert metrics.conserved(result)
    assert all(s.latency >= 0 for s in result.settled)
