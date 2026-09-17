"""Uniform clearing: one price per direction, opposing flow netted, pool invariant kept.

The scenario is a whale sharing a batch with retail orders. Under FIFO execution
the whale's price impact lands on whoever queues after it, and a batcher free to
reorder could choose who that is. Uniform clearing removes both effects.
"""

from __future__ import annotations

import itertools
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from batcher.build.submitter import (
    A_TO_B,
    B_TO_A,
    SEQUENTIAL,
    UNIFORM,
    OrderUtxo,
    clearing_prices,
    effective_prices,
    plan_batch,
    pool_invariant_holds,
    quote,
    uniform_fills,
)

X, Y, FEE = 1_000_000_000, 1_000_000, 30  # 1,000 ADA and 1,000,000 tokens at 30 bps
NETWORK_FEE = 400_000
MARGIN = 1_000_000


def sell(i, amount=10_000_000, min_out=0):
    """Sell ``amount`` lovelace for tokens; the deposit leaves room for min-ADA."""
    return OrderUtxo(f"{i:064x}", 0, amount + 5_000_000, A_TO_B, amount, min_out, MARGIN, "addr")


def buy(i, amount=10_000, min_out=0):
    """Sell ``amount`` tokens for lovelace."""
    return OrderUtxo(f"{i:064x}", 0, 5_000_000, B_TO_A, amount, min_out, MARGIN, "addr")


def by_order(plan):
    return {p.order: (p.lovelace, p.tokens, p.received) for p in plan.payouts}


def mixed_batch():
    return [sell(0, 200_000_000), sell(1, 2_000_000), buy(2, 30_000), sell(3, 5_000_000), buy(4)]


# --- fairness ---------------------------------------------------------------------------------


def test_any_permutation_of_the_batch_pays_every_order_the_same():
    orders = mixed_batch()
    first = plan_batch(orders, X, Y, FEE, network_fee=NETWORK_FEE)
    for perm in itertools.permutations(orders):
        plan = plan_batch(list(perm), X, Y, FEE, network_fee=NETWORK_FEE)
        assert by_order(plan) == by_order(first)
        assert (plan.pool_lovelace, plan.pool_tokens) == (first.pool_lovelace, first.pool_tokens)


def test_sequential_clearing_is_order_dependent_which_is_the_problem():
    orders = [sell(0, 200_000_000), sell(1, 2_000_000)]
    forward = plan_batch(orders, X, Y, FEE, network_fee=NETWORK_FEE, clearing=SEQUENTIAL)
    backward = plan_batch(orders[::-1], X, Y, FEE, network_fee=NETWORK_FEE, clearing=SEQUENTIAL)
    assert by_order(forward) != by_order(backward)


def test_every_order_in_a_direction_gets_the_same_price_within_rounding():
    orders = mixed_batch()
    sold_a = sum(o.amount_in for o in orders if o.direction == A_TO_B)
    sold_b = sum(o.amount_in for o in orders if o.direction == B_TO_A)
    prices = dict(zip((A_TO_B, B_TO_A), clearing_prices(sold_a, sold_b, X, Y, FEE), strict=True))
    fills, _, _ = uniform_fills(orders, X, Y, FEE)
    for order, received in zip(orders, fills, strict=True):
        num, den = prices[order.direction]
        exact = Fraction(order.amount_in * num, den)
        assert 0 <= exact - received < 1


def test_a_lone_order_gets_exactly_the_constant_product_quote():
    assert uniform_fills([sell(0)], X, Y, FEE)[0] == [quote(X, Y, 10_000_000, FEE)]
    assert uniform_fills([buy(0)], X, Y, FEE)[0] == [quote(Y, X, 10_000, FEE)]


def test_retail_after_a_whale_gets_a_strictly_better_price_than_under_fifo():
    orders = [sell(0, 300_000_000)] + [sell(i, 1_000_000) for i in range(1, 6)]
    fifo = effective_prices(orders, X, Y, FEE, clearing=SEQUENTIAL)
    uniform = effective_prices(orders, X, Y, FEE, clearing=UNIFORM)
    for i in range(1, 6):
        assert uniform[i] > fifo[i]
    # ...and every order, whale included, now pays the same price.
    assert max(uniform) - min(uniform) < Fraction(1, 1_000_000)


# --- netting ----------------------------------------------------------------------------------


def test_opposing_orders_net_and_both_sides_beat_trading_alone():
    sells, buys = [sell(0, 20_000_000), sell(1, 10_000_000)], [buy(2, 12_000), buy(3, 8_000)]
    together = effective_prices(sells + buys, X, Y, FEE)
    alone_sells = effective_prices(sells, X, Y, FEE)
    alone_buys = effective_prices(buys, X, Y, FEE)
    assert all(t > a for t, a in zip(together[:2], alone_sells, strict=True))
    assert all(t > a for t, a in zip(together[2:], alone_buys, strict=True))

    # 30 ADA against 20,000 tokens: lovelace is in excess, so the pool only sells tokens,
    # and only as many as the imbalance needs, never the gross 30 ADA's worth.
    fills, x_new, y_new = uniform_fills(sells + buys, X, Y, FEE)
    paid_to_sellers = sum(fills[:2])
    assert y_new == Y + 20_000 - paid_to_sellers < Y
    assert Y - y_new < quote(X, Y, 30_000_000, FEE)
    net_lovelace_in = x_new - X
    assert 0 < net_lovelace_in < 30_000_000
    assert Y - y_new <= quote(X, Y, net_lovelace_in, FEE)


def test_flows_that_cancel_inside_the_fee_band_leave_the_pool_untouched():
    orders = [sell(0, 10_000_000), buy(1, 10_000)]  # exactly the spot price
    fills, x_new, y_new = uniform_fills(orders, X, Y, FEE)
    assert fills == [10_000, 10_000_000]
    assert (x_new, y_new) == (X, Y)


# --- validity ---------------------------------------------------------------------------------


def test_the_planned_pool_passes_pool_ak_invariant():
    plan = plan_batch(mixed_batch(), X, Y, FEE, network_fee=NETWORK_FEE)
    assert plan.n == 5
    assert pool_invariant_holds(X, Y, plan.pool_lovelace, plan.pool_tokens, FEE)


def test_a_min_out_failure_drops_only_that_order_and_replans_the_fee():
    greedy = sell(9, 5_000_000, min_out=10_000)  # at most ~4,950 tokens are available
    ok = [sell(0, min_out=9_000), buy(1, min_out=9_000_000), sell(2, min_out=9_000)]
    plan = plan_batch([*ok, greedy], X, Y, FEE, network_fee=NETWORK_FEE)
    assert plan.skipped == (greedy,)
    assert [p.order for p in plan.payouts] == ok
    for p in plan.payouts:
        assert p.received >= p.order.min_out
        charge = NETWORK_FEE // 3 + MARGIN
        if p.order.direction == A_TO_B:
            assert p.lovelace == p.order.lovelace - p.order.amount_in - charge
        else:
            assert p.lovelace == p.order.lovelace + p.received - charge


def test_payouts_follow_order_ak_rules_exactly():
    plan = plan_batch(mixed_batch(), X, Y, FEE, network_fee=NETWORK_FEE)
    charge = NETWORK_FEE // plan.n + MARGIN
    for p in plan.payouts:
        o = p.order
        if o.direction == A_TO_B:
            assert p.tokens == p.received >= o.min_out
            assert p.lovelace >= o.lovelace - o.amount_in - charge
        else:
            assert p.tokens == 0
            assert p.lovelace >= o.lovelace + o.min_out - charge


def test_an_unknown_clearing_is_refused():
    with pytest.raises(ValueError):
        plan_batch([sell(0)], X, Y, FEE, clearing="pro-rata")


def assert_conserved(orders, fills, x_new, y_new):
    """Nothing is created: payouts plus the new pool equal the old pool plus inputs."""
    sold_a = sum(o.amount_in for o in orders if o.direction == A_TO_B)
    sold_b = sum(o.amount_in for o in orders if o.direction == B_TO_A)
    paid_a = sum(f for o, f in zip(orders, fills, strict=True) if o.direction == A_TO_B)
    paid_b = sum(f for o, f in zip(orders, fills, strict=True) if o.direction == B_TO_A)
    assert paid_b + x_new == X + sold_a
    assert paid_a + y_new == Y + sold_b
    assert x_new > 0 and y_new > 0


def test_rounding_never_pays_out_more_than_is_available():
    orders = [sell(i, 1_000_003 + 7 * i) for i in range(7)] + [buy(9, 3), buy(10, 1)]
    fills, x_new, y_new = uniform_fills(orders, X, Y, FEE)
    assert_conserved(orders, fills, x_new, y_new)
    assert pool_invariant_holds(X, Y, x_new, y_new, FEE)


order_strategy = st.builds(
    lambda i, direction, amount: (
        sell(i, amount) if direction == A_TO_B else buy(i, max(amount // 1_000, 1))
    ),
    st.integers(0, 10_000),
    st.sampled_from([A_TO_B, B_TO_A]),
    st.integers(1, 300_000_000),
)


@settings(max_examples=300, deadline=None)
@given(
    st.lists(order_strategy, min_size=1, max_size=20, unique_by=lambda o: o.tx_hash),
    st.randoms(use_true_random=False),
)
def test_property_uniform_clearing_is_fair_conserving_and_accepted_by_the_pool(orders, rng):
    fills, x_new, y_new = uniform_fills(orders, X, Y, FEE)
    assert_conserved(orders, fills, x_new, y_new)
    assert pool_invariant_holds(X, Y, x_new, y_new, FEE)

    shuffled = list(orders)
    rng.shuffle(shuffled)
    plan = plan_batch(orders, X, Y, FEE, network_fee=NETWORK_FEE)
    again = plan_batch(shuffled, X, Y, FEE, network_fee=NETWORK_FEE)
    assert by_order(plan) == by_order(again)
    assert set(plan.skipped) == set(again.skipped)
    assert pool_invariant_holds(X, Y, plan.pool_lovelace, plan.pool_tokens, FEE)
