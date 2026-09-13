"""T-S1 … T-S6, T-I1 … T-I3, T-P1 … T-P3, T-N5 — the simulator and its invariants.

A simulator that has not been validated proves nothing. T-S3 is the strongest
single check here: greedy giving the lowest latency and the highest per-user cost
follows directly from the cost model, so its absence means something upstream of
every result is wrong.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from batcher.build.estimator import gate_a, max_n_satisfying_gate_a
from batcher.config.params import D_MAX
from batcher.config.protocol import MAX_BLOCK_SIZE
from batcher.data.collector import collect_blocks
from batcher.eval import metrics
from batcher.policy.base import Action, Observation
from batcher.policy.static import FixedInterval, FixedSize, Greedy, Null
from batcher.sim.env import run_episode
from batcher.sim.orders import ArrivalProcess, OrderStream
from conftest import BASE_HEIGHT, FakeSource, make_records

FLAT_DIURNAL = tuple([1.0] * 24)


@pytest.fixture(scope="module")
def blocks():
    source = FakeSource(make_records(1500, seed=11))
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        return collect_blocks(
            source,
            start_height=BASE_HEIGHT,
            end_height=source.tip_height(),
            staging_dir=Path(tmp),
            page_size=500,
        )


def process(rate: float = 0.05) -> ArrivalProcess:
    return ArrivalProcess(base_per_slot=rate, diurnal=FLAT_DIURNAL, bursts_per_day=0.0)


def episode(blocks, policy, seed: int = 7, **kwargs):
    stream = OrderStream(process(), np.random.default_rng(seed), episode_id="t")
    return run_episode(
        blocks, policy, stream, np.random.default_rng(seed + 1), policy_name=policy.name, **kwargs
    )


# --- Determinism -------------------------------------------------------------


def test_the_same_seed_produces_identical_metrics(blocks):
    """T-S1 / T-I5 — byte-identical output across two identical runs."""
    first = metrics.compute(episode(blocks, Greedy()))
    second = metrics.compute(episode(blocks, Greedy()))
    assert first.as_dict() == second.as_dict()


def test_different_seeds_produce_different_episodes(blocks):
    """Determinism must not be achieved by ignoring the seed."""
    a = metrics.compute(episode(blocks, Greedy(), seed=1))
    b = metrics.compute(episode(blocks, Greedy(), seed=2))
    assert a.as_dict() != b.as_dict()


# --- Validation V1–V3 --------------------------------------------------------


def test_null_policy_settles_only_what_the_deadline_forces(blocks):
    """T-S2 / V1 — the sanity floor.

    NULL never submits voluntarily, so everything it does settle was forced by
    the D_MAX starvation rule. Its latency is therefore the worst legal latency.
    """
    null = metrics.compute(episode(blocks, Null()))
    greedy = metrics.compute(episode(blocks, Greedy()))

    assert null.submissions > 0, "the deadline rule should force submissions"
    assert null.l_mean > greedy.l_mean
    assert null.throughput < greedy.throughput


def test_a_huge_fixed_size_behaves_like_null_until_the_deadline(blocks):
    """T-S4 / V3 — E1 with M far above n_max cannot trigger on its own rule."""
    huge = metrics.compute(episode(blocks, FixedSize(m=10_000)))
    null = metrics.compute(episode(blocks, Null()))

    assert huge.l_mean == pytest.approx(null.l_mean, rel=0.05)
    assert huge.submissions == pytest.approx(null.submissions, rel=0.1)


@pytest.fixture(scope="module")
def congested_blocks(blocks):
    """The same window, but with every block nearly full.

    Head-of-line blocking cannot be demonstrated on the empty chain the other
    fixtures replay: a batch confirms in the very next block, so the lock never
    lasts. Sustained congestion is what holds the pool open.
    """
    frame = blocks.copy()
    frame["block_size"] = int(0.99 * MAX_BLOCK_SIZE)
    frame["fill_pct"] = frame["block_size"] / MAX_BLOCK_SIZE
    return frame


def test_head_of_line_blocking_is_observable(congested_blocks):
    """T-S5 / ADR-004 — while the pool is locked the queue grows and no decision exists.

    This is the mechanism the whole project manages: the cost of a mistimed
    submission is not rejection, it is everyone behind it waiting.
    """
    result = episode(congested_blocks, Greedy(), ttl_slots=100_000)
    log = result.decision_log()

    locked = log[log["pool_locked"]]
    assert len(locked) > 10, "a batch should stay in flight across many full blocks"
    assert (locked["action"] == "WAIT").all(), "no decision may be taken while locked"
    assert result.locked_slots > 0

    # Orders pile up behind the batch holding the pool. Depth is not strictly
    # monotonic — orders also reach their own TTL and are evicted while locked —
    # so the assertion is on sustained growth, not on every step.
    depths = locked["queue_depth"].to_numpy()
    assert depths[-1] > depths[0] + 10
    assert depths.max() > 2 * max(depths[0], 1)


def test_a_batch_that_never_fits_eventually_expires_rather_than_bouncing(congested_blocks):
    """ADR-004: it leaves the mempool by TTL, never by rejection."""
    result = episode(congested_blocks, Greedy(), ttl_slots=200)
    log = result.decision_log()

    assert (log["resolution"] == "expired").any()
    assert not (log["resolution"] == "rejected").any()
    assert metrics.conserved(result)


def test_the_clock_is_the_recorded_slot_sequence(blocks):
    """T-S6 / ADR-007 — duration matches recorded slots, not blocks x 20 s."""
    result = episode(blocks, Greedy())
    recorded = int(blocks["abs_slot"].max() - blocks["abs_slot"].min()) + 1
    fixed_tick = len(blocks) * 20

    assert result.total_slots == recorded
    assert result.total_slots != fixed_tick


# --- T-S3, the shape check ---------------------------------------------------


def test_greedy_gives_lowest_latency_and_highest_cost(blocks):
    """⚠ T-S3 — the single strongest correctness signal in the project.

    Greedy submits immediately, so batches are small: users wait least and each
    pays the most, because the flat fee is split fewer ways. If this does not
    hold, something upstream of every result is wrong — stop rather than proceed.
    """
    policies = [Greedy(), FixedSize(m=10), FixedSize(m=25), FixedInterval(t=120), Null()]
    scored = {p.name: metrics.compute(episode(blocks, p)) for p in policies}

    latencies = {name: m.l_mean for name, m in scored.items() if m.l_mean is not None}
    costs = {name: m.c_user for name, m in scored.items() if m.c_user is not None}

    assert min(latencies, key=latencies.get) == "e3(greedy)"
    assert max(costs, key=costs.get) == "e3(greedy)"


def test_larger_batches_cost_less_per_user(blocks):
    """The cost half of T-S3, isolated: amortization must show up in the metric."""
    small = metrics.compute(episode(blocks, FixedSize(m=5)))
    large = metrics.compute(episode(blocks, FixedSize(m=25)))

    assert large.batch_n > small.batch_n
    assert large.c_user < small.c_user


# --- Invariants --------------------------------------------------------------


@pytest.mark.parametrize(
    "policy", [Greedy(), Null(), FixedSize(m=15), FixedInterval(t=90)], ids=lambda p: p.name
)
def test_every_policy_runs_a_full_episode(blocks, policy):
    """T-N5."""
    result = episode(blocks, policy)
    assert result.total_slots > 0
    assert metrics.compute(result) is not None


@pytest.mark.parametrize(
    "policy", [Greedy(), Null(), FixedSize(m=15), FixedInterval(t=90)], ids=lambda p: p.name
)
def test_no_submission_ever_violates_gate_a(blocks, policy):
    """T-I1 / S2 — zero Gate A violations, by construction rather than by training."""
    result = episode(blocks, policy)
    assert result.gate_a_violations == 0
    assert all(gate_a(n) for n in result.submissions)


@pytest.mark.parametrize("policy", [Greedy(), Null(), FixedSize(m=15)], ids=lambda p: p.name)
def test_no_order_waits_past_the_deadline_without_being_offered(blocks, policy):
    """T-I2 — the starvation guarantee, enforced by the environment.

    The precise invariant: at **every decision opportunity** where the oldest
    order has reached D_MAX, the action is SUBMIT. WAIT is masked.
    """
    log = episode(blocks, policy).decision_log()
    decisions = log[(~log["pool_locked"]) & (log["queue_depth"] > 0)]
    past_deadline = decisions[decisions["oldest_wait"] >= D_MAX]

    assert not (past_deadline["action"] == "WAIT").any()


def test_the_effective_deadline_is_d_max_plus_one_decision_gap(congested_blocks):
    """D_MAX bounds the *decision*, not the wait — and the gap is not negligible.

    A decision exists only when a block arrives and the pool is free, so an order
    can pass D_MAX and keep waiting until the next such moment. G4's "no order
    starves" holds, but the bound is D_MAX + the inter-decision gap, not D_MAX.
    Stating it here so the report does not claim the tighter bound.
    """
    result = episode(congested_blocks, Null(), ttl_slots=100_000)
    log = result.decision_log()

    overshoot = log["oldest_wait"].max() - D_MAX
    assert overshoot > 0, "expected the lock to delay enforcement past the deadline"

    decisions = log[(~log["pool_locked"]) & (log["queue_depth"] > 0)]
    assert not (decisions[decisions["oldest_wait"] >= D_MAX]["action"] == "WAIT").any()


@pytest.mark.parametrize("policy", [Greedy(), FixedSize(m=15)], ids=lambda p: p.name)
def test_no_submission_while_the_pool_is_locked(blocks, policy):
    """T-I3."""
    log = episode(blocks, policy).decision_log()
    assert not ((log["pool_locked"]) & (log["action"] == "SUBMIT")).any()


def test_orders_are_conserved(blocks):
    """T-P3 — in == settled + expired + still queued.

    If order accounting leaks, throughput and expiry are both wrong and the leak
    is otherwise invisible.
    """
    for policy in (Greedy(), Null(), FixedSize(m=12), FixedInterval(t=150)):
        result = episode(blocks, policy)
        assert metrics.conserved(result), f"{policy.name} leaked orders"


def test_latency_is_never_negative(blocks):
    """T-P2."""
    result = episode(blocks, Greedy())
    assert all(order.latency >= 0 for order in result.settled)


def test_a_rogue_policy_cannot_break_an_invariant(blocks):
    """T-P1 — clamping happens in the environment, so a bad policy is harmless."""

    class Rogue:
        name = "rogue"

        def decide(self, obs: Observation) -> Action:
            return Action(submit=True, n=10_000)

        def observe_outcome(self, outcome) -> None:
            return None

    result = episode(blocks, Rogue())
    assert result.gate_a_violations == 0
    assert all(gate_a(n) for n in result.submissions)
    assert max(result.submissions) <= max_n_satisfying_gate_a(limit=1000)


def test_the_decision_log_has_one_row_per_block(blocks):
    """P2-11 — D3 records every observed block, including locked ones."""
    result = episode(blocks, Greedy())
    assert len(result.decision_log()) == len(blocks)


def test_the_decision_log_records_what_the_policy_saw(blocks):
    """D3's queue_depth is the observed depth, not the queue left after acting.

    Logging the post-action depth makes every SUBMIT row read as though it
    decided on an empty queue, which quietly defeats the I2 deadline assertion.
    """
    log = episode(blocks, Greedy()).decision_log()
    submissions = log[log["action"] == "SUBMIT"]

    assert len(submissions) > 0
    assert (submissions["queue_depth"] >= submissions["n"]).all()
    assert (submissions["queue_depth"] > 0).all()


def test_no_bounce_state_exists():
    """ADR-004 guard: a batch is never rejected for being late."""
    from batcher.sim.mempool import Resolution

    assert {r.value for r in Resolution} == {"included", "expired", "rolled_back"}
    assert not any("bounce" in r.value for r in Resolution)


def test_empty_episode_returns_null_metrics_not_nan():
    """T-M4 — a silent NaN poisons a results table."""
    empty = pd.DataFrame(columns=["abs_slot"])
    result = type("R", (), {})()
    from batcher.sim.env import EpisodeResult

    scored = metrics.compute(EpisodeResult(total_slots=0))
    assert scored.l_mean is None and scored.l_p95 is None
    assert scored.throughput == 0.0
    assert empty is not None and result is not None
