"""M5 · Building real transactions with PyCardano (P7-6, P7-7, P7-11).

Four transactions make up the demonstration: **deploy** (mint the pool token and
NFT, open the pool), **order** (a user locks funds at the order script),
**cancel** (the user takes them back) and **batch** (the batcher executes orders
against the pool). Each builder is a pure function of a chain context, so all of
them are exercised offline against a fake context before one lovelace moves.

**The fee settles before the batch is accepted.** ``order.ak`` lets the batcher
keep at most ``tx.fee // n + margin`` from each user. Users are charged for the
fee the plan assumed, so the built transaction's fee must be **at least** that.
The builder therefore rebuilds on the real fee until the two agree, and never
returns a batch whose fee fell below the one users were charged for.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import cbor2
from pycardano import (
    Address,
    MultiAsset,
    PaymentSigningKey,
    Redeemer,
    Transaction,
    TransactionBuilder,
    TransactionOutput,
    UTxO,
    Value,
    min_lovelace_post_alonzo,
)
from pycardano.exception import DeserializeException

from batcher.build.estimator import tx_mem, tx_size, tx_steps
from batcher.build.submitter import A_TO_B, B_TO_A, BatchPlan, OrderUtxo, plan_batch
from batcher.config.params import TTL_SLOTS
from batcher.onchain.blueprint import CompiledValidator
from batcher.onchain.datums import (
    AtoB,
    BtoA,
    Cancel,
    Execute,
    OrderDatum,
    OutputRef,
    PlutusAddress,
    PoolBatch,
)
from batcher.onchain.deployment import Deployment, addresses, mint_policy, pool_datum

# Padding on the builder's fee estimate, so a rebuild after replanning does not
# come in a few lovelace under the fee users were charged for.
FEE_BUFFER_LOVELACE = 10_000
# A rebuilt fee within this distance of the planned one is accepted as settled.
FEE_TOLERANCE_LOVELACE = 2 * FEE_BUFFER_LOVELACE
MAX_FEE_ROUNDS = 4


class NothingToBatch(RuntimeError):
    """No queued order can be filled at its slippage floor."""


class FeeDidNotSettle(RuntimeError):
    """Rebuilding never produced a fee at or above the one users were charged for."""


class PoolNotFound(RuntimeError):
    """The pool script address does not hold exactly one UTxO carrying the pool NFT."""


# --- values ----------------------------------------------------------------------------


def _tokens(deployment: Deployment, tokens: int = 0, nft: int = 0) -> MultiAsset:
    names = {}
    if tokens:
        names[bytes.fromhex(deployment.token_name)] = tokens
    if nft:
        names[bytes.fromhex(deployment.nft_name)] = nft
    if not names:
        return MultiAsset()
    return MultiAsset.from_primitive({bytes.fromhex(deployment.mint_policy_id): names})


def _coin(amount) -> int:
    return amount.coin if isinstance(amount, Value) else int(amount)


def _quantity(amount, deployment: Deployment, name_hex: str) -> int:
    if not isinstance(amount, Value):
        return 0
    policy = bytes.fromhex(deployment.mint_policy_id)
    name = bytes.fromhex(name_hex)
    for policy_id, assets in amount.multi_asset.items():
        if policy_id.payload == policy:
            for asset_name, quantity in assets.items():
                if asset_name.payload == name:
                    return quantity
    return 0


def _with_min_ada(output: TransactionOutput, context) -> TransactionOutput:
    required = min_lovelace_post_alonzo(output, context)
    if output.amount.coin < required:
        output.amount.coin = required
    return output


def key_address(signing_key: PaymentSigningKey, context) -> Address:
    return Address(signing_key.to_verification_key().hash(), network=context.network)


# --- deploy ------------------------------------------------------------------------------


def build_deploy_tx(
    context,
    batcher_skey: PaymentSigningKey,
    deployment: Deployment,
    pool_lovelace: int,
    pool_tokens: int,
    total_supply: int,
) -> Transaction:
    """Mint the token supply and the pool NFT, and open the pool with liquidity."""
    if pool_tokens > total_supply:
        raise ValueError("the pool cannot hold more tokens than are minted")

    batcher_hash = batcher_skey.to_verification_key().hash()
    policy = mint_policy(batcher_hash, deployment.mint_before_slot)
    if policy.hash().payload.hex() != deployment.mint_policy_id:
        raise ValueError("this deployment was derived for a different key or mint window")
    if context.last_block_slot >= deployment.mint_before_slot:
        raise ValueError("the mint window has already closed; derive a new deployment")

    owner = key_address(batcher_skey, context)
    _, pool_address = addresses(deployment, context.network)

    builder = TransactionBuilder(context)
    builder.add_input_address(owner)
    builder.mint = _tokens(deployment, tokens=total_supply, nft=1)
    builder.native_scripts = [policy]
    builder.ttl = deployment.mint_before_slot
    builder.add_output(
        TransactionOutput(
            pool_address,
            Value(pool_lovelace, _tokens(deployment, tokens=pool_tokens, nft=1)),
            datum=pool_datum(deployment),
        )
    )
    if total_supply > pool_tokens:
        builder.add_output(
            _with_min_ada(
                TransactionOutput(
                    owner, Value(0, _tokens(deployment, tokens=total_supply - pool_tokens))
                ),
                context,
            )
        )
    return builder.build_and_sign([batcher_skey], change_address=owner)


# --- orders ------------------------------------------------------------------------------


def build_order_tx(
    context,
    user_skey: PaymentSigningKey,
    deployment: Deployment,
    direction: str,
    amount_in: int,
    min_out: int,
    margin: int,
    deposit_lovelace: int,
) -> Transaction:
    """Lock an order at the order script, as a user's wallet would."""
    owner_hash = user_skey.to_verification_key().hash()
    owner = Address(owner_hash, network=context.network)
    order_address, _ = addresses(deployment, context.network)

    if direction == A_TO_B:
        if deposit_lovelace <= amount_in:
            raise ValueError("an AtoB deposit must cover amount_in plus the payout's min-ADA")
        value, side = Value(deposit_lovelace), AtoB()
    elif direction == B_TO_A:
        value, side = Value(deposit_lovelace, _tokens(deployment, tokens=amount_in)), BtoA()
    else:
        raise ValueError(f"unknown direction {direction!r}")

    datum = OrderDatum(
        owner=owner_hash.payload,
        return_address=PlutusAddress.from_address(owner),
        direction=side,
        amount_in=amount_in,
        min_out=min_out,
        margin=margin,
    )
    builder = TransactionBuilder(context)
    builder.add_input_address(owner)
    builder.add_output(TransactionOutput(order_address, value, datum=datum))
    return builder.build_and_sign([user_skey], change_address=owner)


def build_cancel_tx(
    context, user_skey: PaymentSigningKey, order_utxo: UTxO, order_script: CompiledValidator
) -> Transaction:
    """T-O1 on-chain: the owner reclaims an unbatched order."""
    owner_hash = user_skey.to_verification_key().hash()
    owner = Address(owner_hash, network=context.network)

    builder = TransactionBuilder(context)
    builder.add_script_input(order_utxo, script=order_script.script, redeemer=Redeemer(Cancel()))
    builder.add_input_address(owner)
    builder.required_signers = [owner_hash]
    return builder.build_and_sign([user_skey], change_address=owner)


def read_orders(
    utxos: Sequence[UTxO], deployment: Deployment, network
) -> list[tuple[UTxO, OrderUtxo]]:
    """Orders at the order script, in the order the chain returned them.

    Anyone can send anything to a script address, so a UTxO whose datum does not
    decode, or a BtoA order not holding the tokens it offers, is ignored rather
    than allowed to break the batch.
    """
    found = []
    for utxo in utxos:
        datum = utxo.output.datum
        if datum is None:
            continue
        try:
            raw = datum.to_cbor() if hasattr(datum, "to_cbor") else cbor2.dumps(datum)
            order = OrderDatum.from_cbor(raw)
        except (DeserializeException, ValueError, TypeError, KeyError):
            continue

        direction = A_TO_B if isinstance(order.direction, AtoB) else B_TO_A
        held = _quantity(utxo.output.amount, deployment, deployment.token_name)
        if direction == B_TO_A and held < order.amount_in:
            continue
        found.append(
            (
                utxo,
                OrderUtxo(
                    tx_hash=str(utxo.input.transaction_id),
                    index=utxo.input.index,
                    lovelace=_coin(utxo.output.amount),
                    direction=direction,
                    amount_in=order.amount_in,
                    min_out=order.min_out,
                    margin=order.margin,
                    return_address=str(order.return_address.to_address(network)),
                ),
            )
        )
    return found


def read_pool(utxos: Sequence[UTxO], deployment: Deployment) -> UTxO:
    pools = [u for u in utxos if _quantity(u.output.amount, deployment, deployment.nft_name) == 1]
    if len(pools) != 1:
        raise PoolNotFound(f"expected exactly one pool UTxO, found {len(pools)}")
    return pools[0]


# --- batch -------------------------------------------------------------------------------


@dataclass(frozen=True)
class BuiltBatch:
    transaction: Transaction
    plan: BatchPlan
    ttl_slot: int
    estimated_size: int
    actual_size: int
    estimated_mem: int
    actual_mem: int
    estimated_steps: int
    actual_steps: int

    @property
    def fee(self) -> int:
        return self.transaction.transaction_body.fee


def build_batch_tx(
    context,
    batcher_skey: PaymentSigningKey,
    deployment: Deployment,
    scripts: dict[str, CompiledValidator],
    pool_utxo: UTxO,
    orders: Sequence[tuple[UTxO, OrderUtxo]],
    ttl_slots: int = TTL_SLOTS,
) -> BuiltBatch:
    """Plan, build and sign one batch. Gate A is re-checked inside ``plan_batch``."""
    x = _coin(pool_utxo.output.amount)
    y = _quantity(pool_utxo.output.amount, deployment, deployment.token_name)
    queued = [order for _, order in orders]
    by_ref = {(order.tx_hash, order.index): utxo for utxo, order in orders}
    ttl = context.last_block_slot + ttl_slots

    plan = plan_batch(queued, x, y, deployment.fee_bps)
    for _ in range(MAX_FEE_ROUNDS):
        if plan.n == 0:
            raise NothingToBatch("no queued order can be filled at its min_out")
        tx = _assemble(context, batcher_skey, deployment, scripts, pool_utxo, by_ref, plan, ttl)
        fee = tx.transaction_body.fee
        if plan.network_fee <= fee <= plan.network_fee + FEE_TOLERANCE_LOVELACE:
            return _measure(tx, plan, ttl)
        # Charge users for the fee this transaction actually carries, then rebuild.
        plan = plan_batch(queued, x, y, deployment.fee_bps, network_fee=fee)

    if tx.transaction_body.fee >= plan.network_fee:
        return _measure(tx, plan, ttl)
    raise FeeDidNotSettle(
        f"fee {tx.transaction_body.fee} stayed below the planned {plan.network_fee}"
    )


def _assemble(context, skey, deployment, scripts, pool_utxo, by_ref, plan, ttl) -> Transaction:
    batcher_hash = skey.to_verification_key().hash()
    batcher = Address(batcher_hash, network=context.network)
    _, pool_address = addresses(deployment, context.network)

    builder = TransactionBuilder(context, fee_buffer=FEE_BUFFER_LOVELACE)
    for payout in plan.payouts:
        utxo = by_ref[(payout.order.tx_hash, payout.order.index)]
        builder.add_script_input(utxo, script=scripts["order"].script, redeemer=Redeemer(Execute()))
    builder.add_script_input(
        pool_utxo, script=scripts["pool"].script, redeemer=Redeemer(PoolBatch())
    )
    builder.add_input_address(batcher)  # the network fee and the collateral

    for payout in plan.payouts:
        amount = (
            Value(payout.lovelace, _tokens(deployment, tokens=payout.tokens))
            if payout.tokens
            else Value(payout.lovelace)
        )
        builder.add_output(
            TransactionOutput(
                Address.from_primitive(payout.order.return_address),
                amount,
                # Tagging the payout with its order is what order.ak matches on.
                datum=OutputRef(bytes.fromhex(payout.order.tx_hash), payout.order.index),
            )
        )
    builder.add_output(
        TransactionOutput(
            pool_address,
            Value(plan.pool_lovelace, _tokens(deployment, tokens=plan.pool_tokens, nft=1)),
            datum=pool_datum(deployment),
        )
    )
    builder.required_signers = [batcher_hash]
    builder.ttl = ttl
    return builder.build_and_sign([skey], change_address=batcher)


def _redeemer_units(tx: Transaction) -> tuple[int, int]:
    redeemers = tx.transaction_witness_set.redeemer
    if not redeemers:
        return 0, 0
    values = redeemers.values() if hasattr(redeemers, "values") else redeemers
    mem = sum(r.ex_units.mem for r in values)
    values = redeemers.values() if hasattr(redeemers, "values") else redeemers
    steps = sum(r.ex_units.steps for r in values)
    return mem, steps


def _measure(tx: Transaction, plan: BatchPlan, ttl: int) -> BuiltBatch:
    orders = [p.order for p in plan.payouts]
    n = len(orders)
    mem, steps = _redeemer_units(tx)
    return BuiltBatch(
        transaction=tx,
        plan=plan,
        ttl_slot=ttl,
        estimated_size=tx_size(n, [o.size_bytes for o in orders]),
        actual_size=len(tx.to_cbor()),
        estimated_mem=tx_mem(n, [o.mem_exunits for o in orders]),
        actual_mem=mem,
        estimated_steps=tx_steps(n, [o.step_exunits for o in orders]),
        actual_steps=steps,
    )


# --- after submission ----------------------------------------------------------------------


def await_confirmation(
    lookup: Callable[[str], int | None],
    current_slot: Callable[[], int],
    tx_id: str,
    ttl_slot: int,
    poll_seconds: float = 20.0,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, int | None]:
    """Poll until the batch is included (``"included", slot``) or its TTL passes."""
    while True:
        slot = lookup(tx_id)
        if slot is not None:
            return "included", slot
        if current_slot() > ttl_slot:
            # Inclusion can race the TTL check; look once more before giving up.
            slot = lookup(tx_id)
            return ("included", slot) if slot is not None else ("expired", None)
        sleep(poll_seconds)


def blockfrost_lookup(context) -> Callable[[str], int | None]:  # pragma: no cover - network
    from blockfrost import ApiError

    def lookup(tx_id: str) -> int | None:
        try:
            return int(context.api.transaction(tx_id).slot)
        except ApiError as error:
            if getattr(error, "status_code", None) == 404:
                return None
            raise

    return lookup


def d4_row(
    built: BuiltBatch,
    submit_slot: int,
    outcome: str,
    confirm_slot: int | None,
) -> dict:
    """One row of dataset D4 (``05-DATA-SPEC.md``), plus steps for the ±10 % check."""
    return {
        "tx_hash": str(built.transaction.id),
        "submit_slot": submit_slot,
        "confirm_slot": confirm_slot,
        "n": built.plan.n,
        "est_size": built.estimated_size,
        "actual_size": built.actual_size,
        "est_mem": built.estimated_mem,
        "actual_mem": built.actual_mem,
        "est_steps": built.estimated_steps,
        "actual_steps": built.actual_steps,
        "fee_lovelace": built.fee,
        "outcome": outcome,
    }
