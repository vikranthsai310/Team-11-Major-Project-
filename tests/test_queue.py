"""T-Q1 … T-Q4 — the order queue."""

from __future__ import annotations

from batcher.queue.manager import Order, OrderQueue


def order(index: int, arrival: int = 0, ttl: int = 10_000) -> Order:
    return Order(
        order_id=f"o{index:03d}",
        arrival_slot=arrival,
        size_bytes=300,
        mem_exunits=500_000,
        step_exunits=200_000_000,
        amount_in=1_000_000,
        min_out=0,
        ttl_slot=ttl,
    )


def queue_of(n: int, **kwargs) -> OrderQueue:
    queue = OrderQueue(**kwargs)
    queue.admit(order(i, arrival=i) for i in range(n))
    return queue


def test_take_returns_the_oldest_orders_in_order():
    """T-Q1 — FIFO. Selection is a prefix, never a chosen subset."""
    queue = queue_of(10)
    taken = queue.take(3)
    assert [o.order_id for o in taken] == ["o000", "o001", "o002"]
    assert [o.order_id for o in queue.orders][:2] == ["o003", "o004"]


def test_returned_orders_keep_their_position_and_their_age():
    """T-Q2 — age continuity. A returned order has not just arrived."""
    queue = queue_of(6)
    taken = queue.take(3)
    queue.give_back(taken)

    assert [o.order_id for o in queue.orders] == [f"o{i:03d}" for i in range(6)]
    assert queue.oldest_wait(100) == 100  # o000 arrived at slot 0, not on return


def test_expired_orders_are_evicted_and_counted():
    """T-Q3 — expiry eviction."""
    queue = OrderQueue()
    queue.admit([order(0, arrival=0, ttl=50), order(1, arrival=0, ttl=500)])

    evicted = queue.evict_expired(100)

    assert [o.order_id for o in evicted] == ["o000"]
    assert len(queue) == 1
    assert len(queue.expired) == 1


def test_depth_and_oldest_wait_match_an_independent_recomputation():
    """T-Q4 — against the raw arrival log."""
    arrivals = [3, 17, 42, 8]
    queue = OrderQueue()
    queue.admit(order(i, arrival=slot) for i, slot in enumerate(arrivals))

    assert len(queue) == len(arrivals)
    assert queue.oldest_wait(100) == 100 - min(arrivals)
    assert sorted(queue.waits(100)) == sorted(100 - a for a in arrivals)


def test_an_empty_queue_has_no_wait():
    assert OrderQueue().oldest_wait(500) == 0


def test_taking_more_than_is_queued_takes_what_there_is():
    queue = queue_of(3)
    assert len(queue.take(99)) == 3
    assert len(queue) == 0


def test_the_queue_is_unbounded():
    """A batcher discovers on-chain orders; it cannot refuse them.

    A capacity limit here would drop orders out of the conservation law that
    proves none are lost — which is how it was found.
    """
    queue = queue_of(5_000)
    assert len(queue) == 5_000
    assert queue.admitted == 5_000


def test_dimensions_follow_fifo_order():
    queue = queue_of(4)
    sizes, mems, steps = queue.dimensions()
    assert len(sizes) == len(mems) == len(steps) == 4
    assert sizes[0] == 300


def test_orders_survive_a_take_and_return_cycle_without_loss():
    """The conservation property the simulator depends on, at queue level."""
    queue = queue_of(8)
    ids = {o.order_id for o in queue.orders}

    taken = queue.take(5)
    queue.give_back(taken)

    assert {o.order_id for o in queue.orders} == ids
