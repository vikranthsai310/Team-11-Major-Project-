"""P7-6/P7-7 offline: every transaction the demo needs, built against a fake chain.

Nothing here touches a network. The fake context supplies protocol parameters,
UTxOs and execution units, so PyCardano runs its real balancing, fee and
collateral logic; what is checked is that the resulting transactions satisfy the
rules ``order.ak`` and ``pool.ak`` will apply on preprod.
"""

from __future__ import annotations

import pytest
from pycardano import (
    Address,
    ChainContext,
    ExecutionUnits,
    GenesisParameters,
    Network,
    PaymentSigningKey,
    ProtocolParameters,
    TransactionInput,
    TransactionOutput,
    UTxO,
    Value,
)

from batcher.build import tx_builder
from batcher.build.estimator import max_n_satisfying_gate_a
from batcher.build.submitter import A_TO_B, GateAViolation
from batcher.config.protocol import (
    MAX_BLOCK_EX_MEM,
    MAX_BLOCK_EX_STEPS,
    MAX_BLOCK_SIZE,
    MAX_TX_EX_MEM,
    MAX_TX_EX_STEPS,
    MAX_TX_SIZE,
    MIN_FEE_A,
    MIN_FEE_B,
    PRICE_MEM,
    PRICE_STEPS,
)
from batcher.onchain import blueprint, datums
from batcher.onchain import deployment as dex

pytestmark = pytest.mark.skipif(not blueprint.BLUEPRINT.exists(), reason="plutus.json not built")

TIP = 50_000_000
POOL_ADA, POOL_TOKENS = 1_000_000_000, 1_000_000


class FakeChain(ChainContext):
    """Just enough chain for PyCardano's builder to do its real work offline."""

    def __init__(self):
        self.by_address: dict[str, list[UTxO]] = {}
        self.submitted = []

    @property
    def protocol_param(self):
        return ProtocolParameters(
            min_fee_constant=MIN_FEE_B,
            min_fee_coefficient=MIN_FEE_A,
            max_block_size=MAX_BLOCK_SIZE,
            max_tx_size=MAX_TX_SIZE,
            max_block_header_size=1_100,
            key_deposit=2_000_000,
            pool_deposit=500_000_000,
            pool_influence=0.3,
            monetary_expansion=0.003,
            treasury_expansion=0.2,
            decentralization_param=0,
            extra_entropy="",
            protocol_major_version=9,
            protocol_minor_version=0,
            min_utxo=1_000_000,
            min_pool_cost=170_000_000,
            price_mem=PRICE_MEM,
            price_step=PRICE_STEPS,
            max_tx_ex_mem=MAX_TX_EX_MEM,
            max_tx_ex_steps=MAX_TX_EX_STEPS,
            max_block_ex_mem=MAX_BLOCK_EX_MEM,
            max_block_ex_steps=MAX_BLOCK_EX_STEPS,
            max_val_size=5_000,
            collateral_percent=150,
            max_collateral_inputs=3,
            coins_per_utxo_word=34_482,
            coins_per_utxo_byte=4_310,
            cost_models={"PlutusV3": {str(i): 0 for i in range(297)}},
            maximum_reference_scripts_size={"bytes": 204_800},
            min_fee_reference_scripts={"base": 15, "range": 25_600, "multiplier": 1.2},
        )

    @property
    def genesis_param(self):
        return GenesisParameters(
            active_slots_coefficient=0.05,
            update_quorum=5,
            max_lovelace_supply=45_000_000_000_000_000,
            network_magic=1,
            epoch_length=432_000,
            system_start=1_654_041_600,
            slots_per_kes_period=129_600,
            slot_length=1,
            max_kes_evolutions=62,
            security_param=2_160,
        )

    @property
    def network(self):
        return Network.TESTNET

    @property
    def epoch(self):
        return 200

    @property
    def last_block_slot(self):
        return TIP

    def _utxos(self, address):
        return list(self.by_address.get(str(address), []))

    def submit_tx_cbor(self, cbor):
        self.submitted.append(cbor)

    def evaluate_tx_cbor(self, cbor):
        units = ExecutionUnits(700_000, 250_000_000)
        return {f"{tag}:{i}": units for tag in ("spend", "mint") for i in range(40)}

    def add(self, address, amount, datum=None, tx_byte=0, index=0):
        utxo = UTxO(
            TransactionInput.from_primitive([f"{tx_byte:02x}" * 32, index]),
            TransactionOutput(address, amount, datum=datum),
        )
        self.by_address.setdefault(str(address), []).append(utxo)
        return utxo


def unapplied(module, name, _params):
    """CI has no Aiken compiler; structure tests use the unapplied scripts."""
    return blueprint.validator(blueprint.load(), f"{module}.{name}.spend")


@pytest.fixture
def world():
    chain = FakeChain()
    batcher = PaymentSigningKey.generate()
    user = PaymentSigningKey.generate()
    deployment, scripts = dex.derive(
        batcher.to_verification_key().hash(), TIP + 3_600, apply=unapplied
    )
    batcher_address = tx_builder.key_address(batcher, chain)
    user_address = tx_builder.key_address(user, chain)
    # Enough to open a 1,000 ADA pool and still pay fees and collateral.
    chain.add(batcher_address, Value(2_000_000_000), tx_byte=0xB0)
    chain.add(user_address, Value(200_000_000), tx_byte=0x05)
    return chain, batcher, user, deployment, scripts


def pool_utxo(chain, deployment, tx_byte=0x90):
    _, pool_address = dex.addresses(deployment)
    amount = Value(POOL_ADA, tx_builder._tokens(deployment, tokens=POOL_TOKENS, nft=1))
    return chain.add(pool_address, amount, datum=dex.pool_datum(deployment), tx_byte=tx_byte)


def order_utxo(chain, deployment, user, i, amount_in=10_000_000, min_out=9_000, deposit=15_000_000):
    order_address, _ = dex.addresses(deployment)
    owner = user.to_verification_key().hash()
    datum = datums.OrderDatum(
        owner=owner.payload,
        return_address=datums.PlutusAddress.from_address(Address(owner, network=Network.TESTNET)),
        direction=datums.AtoB(),
        amount_in=amount_in,
        min_out=min_out,
        margin=1_000_000,
    )
    return chain.add(order_address, Value(deposit), datum=datum, tx_byte=0x10 + i, index=i)


def outputs_at(tx, address):
    return [o for o in tx.transaction_body.outputs if o.address == address]


# --- deployment --------------------------------------------------------------------------------


def test_the_deployment_record_round_trips_and_carries_no_script_code(world):
    _, _, _, deployment, _ = world
    text = deployment.to_json()
    assert dex.Deployment.from_json(text) == deployment
    assert "compiledCode" not in text and len(text) < 1_000


def test_a_record_whose_scripts_changed_is_refused(world):
    _, _, _, deployment, _ = world
    tampered = dex.Deployment.from_json(
        deployment.to_json().replace(deployment.pool_script_hash, "00" * 28)
    )
    with pytest.raises(dex.DeploymentMismatch):
        dex.scripts_for(tampered, apply=unapplied)


def test_deploy_mints_one_nft_and_opens_the_pool(world):
    chain, batcher, _, deployment, _ = world
    tx = tx_builder.build_deploy_tx(chain, batcher, deployment, POOL_ADA, POOL_TOKENS, 10_000_000)

    policy = bytes.fromhex(deployment.mint_policy_id)
    minted = {
        name.payload: qty
        for pid, assets in tx.transaction_body.mint.items()
        for name, qty in assets.items()
        if pid.payload == policy
    }
    assert minted == {b"TEAM11": 10_000_000, b"POOL": 1}

    _, pool_address = dex.addresses(deployment)
    (pool,) = outputs_at(tx, pool_address)
    assert pool.amount.coin == POOL_ADA
    assert tx_builder._quantity(pool.amount, deployment, deployment.nft_name) == 1
    assert datums.PoolDatum.from_cbor(pool.datum.to_cbor()) == dex.pool_datum(deployment)
    assert tx.transaction_body.ttl == deployment.mint_before_slot


def test_deploy_refuses_a_closed_mint_window(world):
    chain, batcher, _, _, _ = world
    stale, _ = dex.derive(batcher.to_verification_key().hash(), TIP - 1, apply=unapplied)
    with pytest.raises(ValueError, match="closed"):
        tx_builder.build_deploy_tx(chain, batcher, stale, POOL_ADA, POOL_TOKENS, 10_000_000)


# --- orders -----------------------------------------------------------------------------------


def test_an_order_lands_at_the_order_script_with_a_decodable_datum(world):
    chain, _, user, deployment, _ = world
    tx = tx_builder.build_order_tx(
        chain, user, deployment, A_TO_B, 10_000_000, 9_000, 1_000_000, 15_000_000
    )

    order_address, _ = dex.addresses(deployment)
    (locked,) = outputs_at(tx, order_address)
    assert locked.amount.coin == 15_000_000
    decoded = datums.OrderDatum.from_cbor(locked.datum.to_cbor())
    assert decoded.min_out == 9_000 and isinstance(decoded.direction, datums.AtoB)


def test_an_order_deposit_that_cannot_cover_the_swap_is_refused(world):
    chain, _, user, deployment, _ = world
    with pytest.raises(ValueError):
        tx_builder.build_order_tx(
            chain, user, deployment, A_TO_B, 10_000_000, 9_000, 1_000_000, 10_000_000
        )


def test_t_o1_cancel_is_signed_by_the_owner(world):
    chain, _, user, deployment, scripts = world
    order = order_utxo(chain, deployment, user, 0)
    tx = tx_builder.build_cancel_tx(chain, user, order, scripts["order"])

    assert order.input in tx.transaction_body.inputs
    assert tx.transaction_body.required_signers == [user.to_verification_key().hash()]


def test_junk_at_the_order_script_is_ignored(world):
    chain, _, user, deployment, _ = world
    order_address, _ = dex.addresses(deployment)
    order_utxo(chain, deployment, user, 0)
    chain.add(order_address, Value(3_000_000), datum=datums.PoolBatch(), tx_byte=0xEE)
    chain.add(order_address, Value(3_000_000), tx_byte=0xEF)

    found = tx_builder.read_orders(chain.utxos(order_address), deployment, Network.TESTNET)
    assert len(found) == 1


def test_the_pool_is_found_by_its_nft(world):
    chain, _, _, deployment, _ = world
    pool = pool_utxo(chain, deployment)
    _, pool_address = dex.addresses(deployment)
    chain.add(pool_address, Value(5_000_000), tx_byte=0x91)  # dust without the NFT
    assert tx_builder.read_pool(chain.utxos(pool_address), deployment) == pool

    with pytest.raises(tx_builder.PoolNotFound):
        tx_builder.read_pool([], deployment)


# --- the batch ---------------------------------------------------------------------------------


@pytest.fixture
def batch(world):
    chain, batcher, user, deployment, scripts = world
    pool = pool_utxo(chain, deployment)
    for i in range(3):
        order_utxo(chain, deployment, user, i)
    order_address, _ = dex.addresses(deployment)
    orders = tx_builder.read_orders(chain.utxos(order_address), deployment, Network.TESTNET)
    built = tx_builder.build_batch_tx(chain, batcher, deployment, scripts, pool, orders)
    return built, orders, pool, world


def test_a_batch_spends_every_order_and_the_pool(batch):
    built, orders, pool, _ = batch
    inputs = built.transaction.transaction_body.inputs
    assert pool.input in inputs
    assert all(utxo.input in inputs for utxo, _ in orders)
    assert built.plan.n == 3


def test_t_o5_on_chain_rule_holds_for_the_fee_the_transaction_actually_pays(batch):
    """What order.ak checks, applied to the built transaction rather than the plan."""
    built, orders, _, (_, _, user, deployment, _) = batch
    fee, n = built.fee, built.plan.n
    user_address = Address(user.to_verification_key().hash(), network=Network.TESTNET)
    payouts = outputs_at(built.transaction, user_address)

    for _, order in orders:
        tag = datums.OutputRef(bytes.fromhex(order.tx_hash), order.index)
        (payout,) = [
            p for p in payouts if p.datum is not None and p.datum.to_cbor() == tag.to_cbor()
        ]
        allowed = order.lovelace - order.amount_in - (fee // n + order.margin)
        assert payout.amount.coin >= allowed
        assert (
            tx_builder._quantity(payout.amount, deployment, deployment.token_name) >= order.min_out
        )
    assert fee >= built.plan.network_fee


def test_t_o4_the_new_pool_output_carries_the_nft_the_datum_and_the_plan(batch):
    built, _, _, (_, _, _, deployment, _) = batch
    _, pool_address = dex.addresses(deployment)
    (pool,) = outputs_at(built.transaction, pool_address)

    assert pool.amount.coin == built.plan.pool_lovelace
    assert (
        tx_builder._quantity(pool.amount, deployment, deployment.token_name)
        == built.plan.pool_tokens
    )
    assert tx_builder._quantity(pool.amount, deployment, deployment.nft_name) == 1
    assert datums.PoolDatum.from_cbor(pool.datum.to_cbor()) == dex.pool_datum(deployment)


def test_t_o3_the_batch_requires_the_batchers_signature_and_expires(batch):
    built, _, _, (_, batcher, _, _, _) = batch
    body = built.transaction.transaction_body
    assert body.required_signers == [batcher.to_verification_key().hash()]
    assert body.ttl == built.ttl_slot > TIP


def test_the_batch_records_estimate_and_actual_for_calibration(batch):
    built, _, _, _ = batch
    row = tx_builder.d4_row(built, submit_slot=TIP, outcome="included", confirm_slot=TIP + 40)
    assert row["n"] == 3
    assert row["actual_size"] == len(built.transaction.to_cbor())
    assert row["actual_mem"] > 0 and row["est_mem"] > 0
    assert set(row) >= {"tx_hash", "submit_slot", "confirm_slot", "fee_lovelace", "outcome"}


def test_a_queue_nobody_can_fill_builds_nothing(world):
    chain, batcher, user, deployment, scripts = world
    pool = pool_utxo(chain, deployment)
    order_utxo(chain, deployment, user, 0, min_out=10_000_000)
    order_address, _ = dex.addresses(deployment)
    orders = tx_builder.read_orders(chain.utxos(order_address), deployment, Network.TESTNET)
    with pytest.raises(tx_builder.NothingToBatch):
        tx_builder.build_batch_tx(chain, batcher, deployment, scripts, pool, orders)


def test_gate_a_is_rechecked_before_anything_is_built(world):
    chain, batcher, user, deployment, scripts = world
    pool = pool_utxo(chain, deployment)
    for i in range(max_n_satisfying_gate_a(limit=200) + 1):
        order_utxo(chain, deployment, user, i)
    order_address, _ = dex.addresses(deployment)
    orders = tx_builder.read_orders(chain.utxos(order_address), deployment, Network.TESTNET)
    with pytest.raises(GateAViolation):
        tx_builder.build_batch_tx(chain, batcher, deployment, scripts, pool, orders)


# --- confirmation -------------------------------------------------------------------------------


def test_confirmation_returns_the_inclusion_slot():
    seen = iter([None, None, TIP + 60])
    outcome = tx_builder.await_confirmation(
        lambda _: next(seen), lambda: TIP, "tx", ttl_slot=TIP + 600, sleep=lambda _: None
    )
    assert outcome == ("included", TIP + 60)


def test_a_batch_past_its_ttl_is_reported_expired():
    outcome = tx_builder.await_confirmation(
        lambda _: None, lambda: TIP + 601, "tx", ttl_slot=TIP + 600, sleep=lambda _: None
    )
    assert outcome == ("expired", None)
