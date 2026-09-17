"""The live batcher under hostile conditions, offline.

Two adversaries are simulated here without a network: a **malicious user** who
sends order datums built to make the batcher pay or crash, and an **unreliable
chain provider** that times out, rate-limits and goes down while a batch is in
flight. Quarantine, cancel griefing and rollbacks are exercised in
``test_live_batcher`` next to the loop they change.
"""

from __future__ import annotations

import pytest
from pycardano import Address, Network, PaymentSigningKey, Value

from batcher.build import tx_builder
from batcher.build.tx_builder import key_address
from batcher.live.chain import Tip
from batcher.live.daemon import LiveBatcher
from batcher.live.resilience import (
    ChainUnavailable,
    CircuitBreaker,
    ResilientChain,
    is_api_error,
)
from batcher.onchain import blueprint, datums
from batcher.onchain import deployment as dex
from batcher.policy.static import Greedy
from test_live_batcher import FakePreprod
from test_tx_builder import TIP, FakeChain, order_utxo, pool_utxo, unapplied

needs_blueprint = pytest.mark.skipif(
    not blueprint.BLUEPRINT.exists(), reason="plutus.json not built"
)


@pytest.fixture
def world():
    chain = FakeChain()
    batcher = PaymentSigningKey.generate()
    user = PaymentSigningKey.generate()
    deployment, scripts = dex.derive(
        batcher.to_verification_key().hash(), TIP + 3_600, apply=unapplied
    )
    chain.add(key_address(batcher, chain), Value(2_000_000_000), tx_byte=0xB0)
    pool_utxo(chain, deployment)
    return FakePreprod(chain), batcher, user, deployment, scripts


# --- the malicious user: order admission ---------------------------------------------------------


def hostile_order(world, tx_byte, **fields):
    fake, _, user, deployment, _ = world
    owner = user.to_verification_key().hash()
    datum = dict(
        owner=owner.payload,
        return_address=datums.PlutusAddress.from_address(Address(owner, network=Network.TESTNET)),
        direction=datums.AtoB(),
        amount_in=10_000_000,
        min_out=9_000,
        margin=1_000_000,
    )
    datum.update(fields)
    order_address, _ = dex.addresses(deployment)
    return fake.context.add(
        order_address, Value(15_000_000), datum=datums.OrderDatum(**datum), tx_byte=tx_byte
    )


@needs_blueprint
@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"margin": -5_000_000}, "margin"),
        ({"amount_in": 0}, "amount_in"),
        ({"amount_in": -10_000_000}, "amount_in"),
        ({"min_out": -1}, "min_out"),
        (
            {
                "return_address": datums.PlutusAddress(
                    datums.VerificationKeyCredential(b"\x01" * 5), datums.NoStake()
                )
            },
            "return address",
        ),
        ({"owner": b"\x02" * 3}, "owner"),
    ],
)
def test_a_hostile_order_is_skipped_and_reported_while_valid_orders_still_read(
    world, fields, reason
):
    fake, _, user, deployment, _ = world
    valid = order_utxo(fake.context, deployment, user, 0)
    hostile = hostile_order(world, 0xE0, **fields)
    order_address, _ = dex.addresses(deployment)

    rejected = []
    found = tx_builder.read_orders(
        fake.context.utxos(order_address), deployment, Network.TESTNET, rejected
    )

    assert [utxo.input for utxo, _ in found] == [valid.input]
    ((tx_hash, index, why),) = rejected
    assert (tx_hash, index) == (str(hostile.input.transaction_id), hostile.input.index)
    assert reason in why


@needs_blueprint
def test_the_daemon_batches_around_a_hostile_order(world):
    fake, batcher_key, user, deployment, scripts = world
    order_utxo(fake.context, deployment, user, 0)
    hostile_order(world, 0xE1, margin=-5_000_000)
    batcher = LiveBatcher(fake, Greedy(), deployment, scripts, batcher_key)

    (record,) = batcher.step()
    assert record["resolution"] == "shadow" and record["executed"] == 1
    assert [reason for *_, reason in batcher.rejected_orders] == ["margin -5000000 is negative"]


# --- the unreliable provider: ResilientChain -----------------------------------------------------


class Provider:
    """A LiveChain whose ``tip`` answers from a script of results and errors."""

    def __init__(self, *script, name="primary"):
        self.context = object()
        self.script = list(script)
        self.calls = 0
        self.name = name
        self.submitted = []

    def tip(self):
        self.calls += 1
        outcome = self.script.pop(0) if self.script else Tip(1, 1, 0.0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def submit(self, tx):
        self.submitted.append(tx)
        raise TimeoutError("gateway timeout")


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def resilient(*providers, sleeps=None, clock=None, **kwargs):
    return ResilientChain(
        providers[0],
        providers[1:],
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
        clock=clock or Clock(),
        rng=lambda: 0.0,
        **kwargs,
    )


def test_transient_failures_succeed_after_backoff():
    provider = Provider(ConnectionError("reset"), TimeoutError("slow"), Tip(7, 70, 0.1))
    sleeps = []
    chain = resilient(provider, sleeps=sleeps, retries=3, base_delay=0.5)

    assert chain.tip() == Tip(7, 70, 0.1)
    assert provider.calls == 3
    assert sleeps == [0.5, 1.0], "exponential backoff between attempts"


def test_backoff_is_capped_and_jittered():
    chain = ResilientChain(
        Provider(), base_delay=1.0, max_delay=4.0, jitter=0.5, rng=lambda: 1.0, sleep=None
    )
    assert [chain.delay(a) for a in range(4)] == [1.5, 3.0, 6.0, 6.0]


def test_the_breaker_opens_after_k_failures_fails_fast_and_recovers_after_cooldown():
    clock = Clock()
    provider = Provider(*[ConnectionError("down")] * 3)
    chain = resilient(provider, clock=clock, retries=5, failure_threshold=3, cooldown_seconds=30.0)

    with pytest.raises(ChainUnavailable):
        chain.tip()
    assert provider.calls == 3, "the breaker stops retries once it opens"
    assert chain.breakers[0].state == "open"

    with pytest.raises(ChainUnavailable, match="circuit breaker is open"):
        chain.tip()
    assert provider.calls == 3, "an open breaker fails fast without calling the provider"

    clock.now = 31.0
    assert chain.breakers[0].state == "half_open"
    assert chain.tip() == Tip(1, 1, 0.0)
    assert chain.breakers[0].state == "closed"


def test_a_failed_trial_after_cooldown_reopens_the_breaker():
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=10.0, clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    clock.now = 11.0
    assert breaker.allow()
    breaker.record_failure()
    assert breaker.state == "open"


def test_failover_to_a_secondary_provider():
    primary = Provider(*[ConnectionError("down")] * 10)
    secondary = Provider(Tip(9, 90, 0.2), name="secondary")
    chain = resilient(primary, secondary, retries=1)

    assert chain.tip() == Tip(9, 90, 0.2)
    assert primary.calls == 2 and secondary.calls == 1


def test_a_client_error_is_not_retried_and_does_not_trip_the_breaker():
    class BadRequest(Exception):
        status_code = 400

    provider = Provider(BadRequest("malformed"))
    chain = resilient(provider, retries=3, failure_threshold=1)
    with pytest.raises(BadRequest):
        chain.tip()
    assert provider.calls == 1 and chain.breakers[0].state == "closed"


def test_a_submission_is_never_retried_or_failed_over():
    primary, secondary = Provider(), Provider(name="secondary")
    chain = resilient(primary, secondary, retries=3)
    with pytest.raises(TimeoutError):
        chain.submit("tx")
    assert primary.submitted == ["tx"] and secondary.submitted == []


def test_api_errors_are_told_apart_from_defects():
    class ApiError(Exception):
        pass

    assert is_api_error(ChainUnavailable("x")) and is_api_error(ConnectionError())
    assert is_api_error(ApiError())
    assert not is_api_error(ValueError("a defect"))


# --- the daemon through an outage ----------------------------------------------------------------


class Outage(FakePreprod):
    """FakePreprod whose reads fail while ``down`` names the failing method (or ``"all"``)."""

    down: str | None = None

    def _check(self, method):
        if self.down in (method, "all"):
            raise ConnectionError(f"{method}: blockfrost unreachable")

    def tip(self):
        self._check("tip")
        return super().tip()

    def utxos(self, address):
        self._check("utxos")
        return super().utxos(address)

    def recent_fills(self, count):
        self._check("recent_fills")
        return super().recent_fills(count)

    def inclusion_slot(self, tx_hash):
        self._check("inclusion_slot")
        return super().inclusion_slot(tx_hash)


@needs_blueprint
def test_the_daemon_survives_an_outage_with_a_batch_in_flight(world):
    _, batcher_key, user, deployment, scripts = world
    fake = Outage(world[0].context)
    for i in range(2):
        order_utxo(fake.context, deployment, user, i)
    chain = ResilientChain(fake, retries=1, failure_threshold=100, sleep=lambda _: None)
    batcher = LiveBatcher(
        chain, Greedy(), deployment, scripts, batcher_key, submit=True, confirmation_depth=0
    )
    (submitted,) = batcher.step()
    assert submitted["resolution"] == "submitted"
    in_flight = batcher.in_flight

    fake.next_block()
    fake.confirm(fake.submitted[0])
    fake.down = "inclusion_slot"
    (record,) = batcher.step()
    assert record["resolution"] == "api_unavailable" and record["pool_locked"]
    assert record["tx_id"] == in_flight.tx_id and batcher.in_flight is in_flight
    assert batcher.d4_rows == [] and len(fake.submitted) == 1

    fake.down = None
    resolved, decision = batcher.step()
    assert resolved["resolution"] == "included" and not batcher.pool_locked
    assert decision["resolution"] == "wait"


@needs_blueprint
def test_an_outage_mid_decision_decides_nothing_and_retries_the_block(world):
    _, batcher_key, user, deployment, scripts = world
    fake = Outage(world[0].context)
    order_utxo(fake.context, deployment, user, 0)
    batcher = LiveBatcher(fake, Greedy(), deployment, scripts, batcher_key, submit=True)

    fake.down = "recent_fills"  # the pool and queue were read; the forecast input was not
    (record,) = batcher.step()
    assert record["resolution"] == "api_unavailable" and record["action"] == "WAIT"
    assert fake.submitted == []

    fake.down = None
    (record,) = batcher.step()
    assert record["resolution"] == "submitted", "the same block is decided once the API is back"


@needs_blueprint
def test_run_keeps_polling_through_an_outage_instead_of_crashing(world):
    _, batcher_key, _, deployment, scripts = world
    fake = Outage(world[0].context)
    fake.down = "all"
    batcher = LiveBatcher(fake, Greedy(), deployment, scripts, batcher_key)
    polls = []

    def sleep(_seconds):
        polls.append(1)
        if len(polls) == 3:
            fake.down = None

    assert batcher.run(max_blocks=1, sleep=sleep) == 1
    assert [r["resolution"] for r in batcher.records] == ["api_unavailable"] * 3 + ["wait"]
