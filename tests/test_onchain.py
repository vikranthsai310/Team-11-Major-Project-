"""M7 off-chain guards: datums match the compiled validators, batch planning
respects every rule ``order.ak`` and ``pool.ak`` enforce, and live mode shares
the simulator's estimator (T-N6)."""

from __future__ import annotations

import json
from dataclasses import fields

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pycardano import Address, Network, VerificationKeyHash

from batcher.build import estimator, submitter
from batcher.build.submitter import (
    A_TO_B,
    B_TO_A,
    PAYOUT_MIN_LOVELACE,
    GateAViolation,
    OrderUtxo,
    plan_batch,
    pool_invariant_holds,
    quote,
)
from batcher.onchain import datums

BLUEPRINT_TYPES = {
    datums.OrderDatum: "dex/types/OrderDatum",
    datums.PoolDatum: "dex/types/PoolDatum",
    datums.AtoB: ("dex/types/Direction", "AtoB"),
    datums.BtoA: ("dex/types/Direction", "BtoA"),
    datums.Execute: ("dex/types/OrderAction", "Execute"),
    datums.Cancel: ("dex/types/OrderAction", "Cancel"),
    datums.PlutusAddress: "cardano/address/Address",
    datums.VerificationKeyCredential: ("cardano/address/Credential", "VerificationKey"),
    datums.ScriptCredential: ("cardano/address/Credential", "Script"),
    datums.SomeStake: ("Option<cardano/address/StakeCredential>", "Some"),
    datums.NoStake: ("Option<cardano/address/StakeCredential>", "None"),
    datums.InlineStake: ("cardano/address/StakeCredential", "Inline"),
}


@pytest.fixture(scope="module")
def blueprint(repo_root):
    path = repo_root / "onchain" / "plutus.json"
    if not path.exists():
        pytest.skip("onchain/plutus.json not built; run `aiken build` in onchain/")
    return json.loads(path.read_text())


# --- datums against the blueprint ---------------------------------------------------


@pytest.mark.parametrize("cls", list(BLUEPRINT_TYPES), ids=lambda c: c.__name__)
def test_datum_matches_the_compiled_validator(blueprint, cls):
    target = BLUEPRINT_TYPES[cls]
    name, constructor = target if isinstance(target, tuple) else (target, None)
    definition = blueprint["definitions"][name]
    alternatives = definition.get("anyOf", [definition])
    alternative = (
        next(a for a in alternatives if a["title"] == constructor)
        if constructor
        else alternatives[0]
    )

    assert cls.CONSTR_ID == alternative["index"]
    assert len(fields(cls)) == len(alternative.get("fields", []))
    named = [f["title"] for f in alternative.get("fields", []) if "title" in f]
    if named:
        assert [f.name for f in fields(cls)] == named


def test_validators_take_the_parameters_the_off_chain_code_supplies(blueprint):
    params = {
        v["title"]: [p["title"] for p in v.get("parameters", [])] for v in blueprint["validators"]
    }
    assert params["order.order.spend"] == ["batcher", "token_policy", "token_name"]
    assert params["pool.pool.spend"] == ["batcher"]


def test_an_order_datum_round_trips_through_cbor():
    owner = VerificationKeyHash(bytes(range(28)))
    datum = datums.OrderDatum(
        owner=owner.payload,
        return_address=datums.PlutusAddress.from_address(Address(owner, network=Network.TESTNET)),
        direction=datums.BtoA(),
        amount_in=10_000,
        min_out=9_000_000,
        margin=1_000_000,
    )
    decoded = datums.OrderDatum.from_cbor(datum.to_cbor())
    assert decoded == datum
    assert decoded.return_address.to_address() == Address(owner, network=Network.TESTNET)


def test_a_staked_address_survives_the_plutus_encoding():
    payment = VerificationKeyHash(b"\x01" * 28)
    stake = VerificationKeyHash(b"\x02" * 28)
    address = Address(payment, stake, network=Network.TESTNET)
    assert datums.PlutusAddress.from_address(address).to_address() == address


# --- T-N6: one estimator for simulation and live mode -----------------------------------


def test_live_mode_uses_the_simulators_estimator():
    """T-N6. Identity, not equality: a copy could drift and still pass a value check."""
    assert submitter.gate_a is estimator.gate_a
    assert submitter.fee_lovelace is estimator.fee_lovelace


# --- the swap maths against pool.ak ----------------------------------------------------------


def test_quote_matches_the_value_the_aiken_test_pins():
    # pool.ak t_o4_a_fair_swap_after_fees_is_accepted: 10 ADA into 1,000 ADA / 1M tokens.
    assert quote(1_000_000_000, 1_000_000, 10_000_000, 30) == 9_871


def test_python_invariant_agrees_with_the_aiken_cases():
    assert pool_invariant_holds(1_000_000_000, 1_000_000, 1_010_000_000, 990_129, 30)
    assert not pool_invariant_holds(1_000_000_000, 1_000_000, 1_010_000_000, 990_100, 30)
    assert not pool_invariant_holds(1_000_000_000, 1_000_000, 999_000_000, 999_000, 30)


order_strategy = st.builds(
    lambda i, direction, amount: OrderUtxo(
        tx_hash=f"{i:064x}",
        index=0,
        lovelace=amount + 20_000_000 if direction == A_TO_B else 20_000_000,
        direction=direction,
        amount_in=amount if direction == A_TO_B else amount // 1_000,
        min_out=0,
        margin=500_000,
        return_address="addr_test",
    ),
    st.integers(0, 10_000),
    st.sampled_from([A_TO_B, B_TO_A]),
    st.integers(1_000_000, 50_000_000),
)


@settings(max_examples=200, deadline=None)
@given(st.lists(order_strategy, min_size=1, max_size=20, unique_by=lambda o: o.tx_hash))
def test_t_o4_every_planned_batch_passes_the_pool_invariant(orders):
    """Whatever mix of orders is netted together, the pool never loses value."""
    x, y = 1_000_000_000, 1_000_000
    plan = plan_batch(orders, x, y, fee_bps=30)
    assert pool_invariant_holds(x, y, plan.pool_lovelace, plan.pool_tokens, 30)


# --- order.ak's rules, applied at planning time --------------------------------------------------


def sell(i: int = 0, amount: int = 10_000_000, min_out: int = 9_000, lovelace=15_000_000):
    return OrderUtxo(f"{i:064x}", 0, lovelace, A_TO_B, amount, min_out, 1_000_000, "addr_test")


def test_t_o5_each_user_is_charged_fee_share_plus_margin():
    plan = plan_batch([sell(0), sell(1)], 1_000_000_000, 1_000_000, 30, network_fee=400_000)
    for payout in plan.payouts:
        assert payout.lovelace == 15_000_000 - 10_000_000 - 200_000 - 1_000_000


def test_t_o2_an_order_the_pool_cannot_fill_is_left_out_and_the_fee_replanned():
    greedy = sell(1, min_out=10_000_000)  # asks for more tokens than the pool can pay
    plan = plan_batch([sell(0), greedy], 1_000_000_000, 1_000_000, 30, network_fee=400_000)

    assert [p.order for p in plan.payouts] == [sell(0)]
    assert plan.skipped == (greedy,)
    # Alone in the batch, order 0 now carries the whole fee.
    assert plan.payouts[0].lovelace == 15_000_000 - 10_000_000 - 400_000 - 1_000_000


def test_every_payout_meets_its_slippage_floor_and_min_ada():
    orders = [sell(i, min_out=9_000) for i in range(10)]
    plan = plan_batch(orders, 1_000_000_000, 1_000_000, 30)
    assert plan.n > 0
    assert all(p.received >= p.order.min_out for p in plan.payouts)
    assert all(p.lovelace >= PAYOUT_MIN_LOVELACE for p in plan.payouts)


def test_a_buy_ada_order_is_paid_its_deposit_plus_proceeds_less_charge():
    buy = OrderUtxo("f" * 64, 0, 5_000_000, B_TO_A, 10_000, 9_000_000, 1_000_000, "addr_test")
    plan = plan_batch([buy], 1_000_000_000, 1_000_000, 30, network_fee=400_000)
    (payout,) = plan.payouts
    assert payout.received == quote(1_000_000, 1_000_000_000, 10_000, 30)
    assert payout.lovelace == 5_000_000 + payout.received - 400_000 - 1_000_000


def test_gate_a_violation_raises_rather_than_truncating():
    too_many = [sell(i) for i in range(estimator.max_n_satisfying_gate_a(limit=200) + 1)]
    with pytest.raises(GateAViolation):
        plan_batch(too_many, 1_000_000_000, 1_000_000, 30)


def test_an_empty_queue_plans_nothing():
    plan = plan_batch([], 1_000_000_000, 1_000_000, 30)
    assert plan.n == 0 and plan.pool_lovelace == 1_000_000_000
