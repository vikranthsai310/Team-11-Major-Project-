"""P7-8 offline: the live batcher's control loop against a fake preprod.

The done-when for P7-8 is behavioural — exactly one decision per block while the
pool is free, none while it is locked, and a clean shutdown only once no batch is
in flight. Every one of those is checked here without a network, using the fake
chain from ``test_tx_builder`` so PyCardano still builds real transactions.
"""

from __future__ import annotations

import json

import pytest
from pycardano import PaymentSigningKey, TransactionInput, UTxO, Value

from batcher.build.tx_builder import key_address
from batcher.live import daemon
from batcher.live.chain import Tip
from batcher.live.daemon import LiveBatcher
from batcher.onchain import blueprint
from batcher.onchain import deployment as dex
from batcher.policy.base import Action
from batcher.policy.static import Greedy, Null
from batcher.sim import env
from test_tx_builder import TIP, FakeChain, order_utxo, pool_utxo, unapplied

pytestmark = pytest.mark.skipif(not blueprint.BLUEPRINT.exists(), reason="plutus.json not built")


class FakePreprod:
    """The LiveChain port over a FakeChain UTxO set, with a hand-cranked tip."""

    def __init__(self, chain: FakeChain):
        self.context = chain
        self.height = 1_000
        self.slot = TIP
        self.fill = 0.03
        self.arrivals: dict[str, int] = {}
        self.included: dict[str, int] = {}
        self.submitted = []
        self.reject: Exception | None = None

    def tip(self) -> Tip:
        return Tip(self.height, self.slot, self.fill)

    def next_block(self, slots: int = 20) -> None:
        self.height += 1
        self.slot += slots

    def recent_fills(self, count: int) -> list[float]:
        return [self.fill] * count

    def utxos(self, address):
        return self.context.utxos(address)

    def arrival_slot(self, tx_hash: str) -> int:
        return self.arrivals.get(tx_hash, self.slot)

    def submit(self, tx) -> str:
        if self.reject is not None:
            raise self.reject
        self.submitted.append(tx)
        return str(tx.id)

    def inclusion_slot(self, tx_hash: str) -> int | None:
        return self.included.get(tx_hash)

    def confirm(self, tx, apply_to_utxos: bool = True) -> None:
        """Include ``tx``: optionally apply it to the UTxO set, as the chain would."""
        self.included[str(tx.id)] = self.slot
        if not apply_to_utxos:
            return
        spent = set(tx.transaction_body.inputs)
        for utxos in self.context.by_address.values():
            utxos[:] = [u for u in utxos if u.input not in spent]
        for index, output in enumerate(tx.transaction_body.outputs):
            self.context.by_address.setdefault(str(output.address), []).append(
                UTxO(TransactionInput(tx.id, index), output)
            )


class Spy(Greedy):
    def __init__(self):
        self.outcomes = []
        self.observations = []

    def decide(self, obs):
        self.observations.append(obs)
        return super().decide(obs)

    def observe_outcome(self, outcome):
        self.outcomes.append(outcome)


class Oversized(Greedy):
    name = "oversized"

    def decide(self, obs):
        return Action(submit=True, n=10_000)


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


def make(world, policy=None, **kwargs) -> LiveBatcher:
    fake, batcher, _, deployment, scripts = world
    return LiveBatcher(fake, policy or Greedy(), deployment, scripts, batcher, **kwargs)


def add_orders(world, count: int, **kwargs):
    fake, _, user, deployment, _ = world
    return [order_utxo(fake.context, deployment, user, i, **kwargs) for i in range(count)]


# --- the loop's shape ----------------------------------------------------------------------------


def test_live_mode_enforces_the_simulators_rules_not_a_copy():
    assert daemon.enforce is env._enforce


def test_exactly_one_decision_per_block(world):
    fake = world[0]
    add_orders(world, 2)
    batcher = make(world)

    assert len(batcher.step()) == 1
    assert batcher.step() == [], "the same block must not be decided twice"
    fake.next_block()
    assert len(batcher.step()) == 1


def test_an_empty_queue_waits(world):
    (record,) = make(world).step()
    assert record["action"] == "WAIT" and record["resolution"] == "wait"
    assert record["queue_depth"] == 0


def test_shadow_mode_builds_the_batch_but_never_submits(world):
    fake = world[0]
    add_orders(world, 3)
    batcher = make(world, submit=False)

    (record,) = batcher.step()
    assert record["action"] == "SUBMIT" and record["resolution"] == "shadow"
    assert record["executed"] == 3 and record["fee_lovelace"] > 0
    assert fake.submitted == [] and not batcher.pool_locked


# --- the pool lock ------------------------------------------------------------------------------


def test_no_decision_exists_while_a_batch_holds_the_pool(world):
    fake = world[0]
    add_orders(world, 2)
    spy = Spy()
    batcher = make(world, policy=spy, submit=True)

    (submitted,) = batcher.step()
    assert submitted["resolution"] == "submitted" and batcher.pool_locked
    decisions_before = len(spy.observations)

    for _ in range(3):
        fake.next_block()
        (record,) = batcher.step()
        assert record["pool_locked"] and record["resolution"] == "locked"
        assert record["action"] == "WAIT"
    assert len(spy.observations) == decisions_before, "the policy was consulted while locked"
    assert len(fake.submitted) == 1


def test_inclusion_unlocks_logs_d4_informs_the_policy_and_decides_again(world, tmp_path):
    fake = world[0]
    add_orders(world, 2)
    spy = Spy()
    d4 = tmp_path / "d4.jsonl"
    batcher = make(world, policy=spy, submit=True, d4_path=d4)
    batcher.step()

    fake.next_block()
    fake.confirm(fake.submitted[0])
    resolved, decision = batcher.step()

    assert resolved["resolution"] == "included" and not batcher.pool_locked
    assert decision["resolution"] == "wait" and decision["queue_depth"] == 0
    (outcome,) = spy.outcomes
    assert outcome.included and outcome.n == 2
    (row,) = [json.loads(line) for line in d4.read_text().splitlines()]
    assert row["outcome"] == "included" and row["confirm_slot"] == fake.slot


def test_a_lagging_api_view_of_our_own_batch_is_not_built_on(world):
    fake = world[0]
    add_orders(world, 2)
    batcher = make(world, submit=True)
    batcher.step()

    fake.next_block()
    fake.confirm(fake.submitted[0], apply_to_utxos=False)  # included, not yet indexed
    _, decision = batcher.step()
    assert decision["resolution"] == "stale_view"
    assert len(fake.submitted) == 1


def test_an_expired_batch_unlocks_and_its_orders_are_retried(world):
    fake = world[0]
    add_orders(world, 2)
    spy = Spy()
    batcher = make(world, policy=spy, submit=True)
    batcher.step()
    ttl = batcher.in_flight.ttl_slot

    fake.next_block(slots=ttl - fake.slot + 1)
    resolved, decision = batcher.step()
    assert resolved["resolution"] == "expired"
    assert spy.outcomes[0].included is False
    assert decision["resolution"] == "submitted", "the unspent orders are batched again"
    assert batcher.d4_rows[0]["outcome"] == "expired"


def test_a_rejected_submission_is_counted_and_leaves_the_pool_free(world):
    fake = world[0]
    add_orders(world, 1)
    fake.reject = RuntimeError("mempool full")
    batcher = make(world, submit=True)

    (record,) = batcher.step()
    assert record["resolution"] == "rejected" and "mempool full" in record["error"]
    assert not batcher.pool_locked
    assert batcher.d4_rows[0]["outcome"] == "rejected"


# --- the structural rules -------------------------------------------------------------------------


def test_d_max_forces_a_submission_the_policy_did_not_choose(world):
    fake = world[0]
    for utxo in add_orders(world, 1):
        fake.arrivals[str(utxo.input.transaction_id)] = TIP - 500
    (record,) = make(world, policy=Null(), d_max=120).step()

    assert record["oldest_wait"] >= 120
    assert record["action"] == "SUBMIT" and record["resolution"] == "shadow"


def test_an_oversized_request_is_clamped_to_gate_a(world):
    add_orders(world, 3)
    (record,) = make(world, policy=Oversized()).step()
    assert record["n"] == record["gate_a_max_n"] == 3


def test_orders_are_taken_oldest_first(world):
    fake = world[0]
    orders = add_orders(world, 3)
    for age, utxo in zip((10, 300, 50), orders, strict=True):
        fake.arrivals[str(utxo.input.transaction_id)] = TIP - age
    batcher = make(world)
    batcher.step()
    queue = batcher._queue()
    waits = [TIP - batcher._arrivals[order.tx_hash] for _, order in queue]
    assert waits == sorted(waits, reverse=True)


def test_an_unfillable_queue_is_logged_not_fatal(world):
    add_orders(world, 1, min_out=10_000_000)
    (record,) = make(world).step()
    assert record["resolution"] == "unfillable"


def test_a_missing_pool_is_logged_not_fatal(world):
    fake, _, _, deployment, _ = world
    _, pool_address = dex.addresses(deployment)
    fake.context.by_address[str(pool_address)] = []
    (record,) = make(world).step()
    assert record["resolution"] == "pool_missing"


# --- shutdown ---------------------------------------------------------------------------------


def test_stopping_with_the_pool_free_returns_at_once(world):
    batcher = make(world)
    batcher.request_stop()
    assert batcher.run(sleep=lambda _: pytest.fail("should not wait")) == 1


def test_shutdown_waits_for_the_batch_in_flight_and_starts_no_new_one(world):
    fake = world[0]
    add_orders(world, 2)
    batcher = make(world, submit=True)
    ticks = []

    def sleep(_seconds):
        ticks.append(1)
        if len(ticks) == 1:  # new demand arrives while the batcher is stopping
            order_utxo(fake.context, world[3], world[2], 7)
        fake.next_block()
        if len(ticks) == 3:
            fake.confirm(fake.submitted[0])

    batcher.run(max_blocks=1, sleep=sleep)

    assert not batcher.pool_locked
    assert len(fake.submitted) == 1, "no batch may start once a stop was requested"
    assert len(ticks) >= 3
    assert batcher.records[-1]["resolution"] == "stopping"


def test_a_failed_build_is_logged_and_the_daemon_keeps_running(world, monkeypatch):
    """Regression: on preprod a failed script evaluation crashed the daemon."""
    fake = world[0]
    add_orders(world, 1)

    def failing(*_args, **_kwargs):
        raise RuntimeError("EvaluationFailure")

    monkeypatch.setattr(daemon, "build_batch_tx", failing)
    batcher = make(world, submit=True)

    (record,) = batcher.step()
    assert record["resolution"] == "build_failed" and "EvaluationFailure" in record["error"]
    assert not batcher.pool_locked and fake.submitted == []
    fake.next_block()
    assert len(batcher.step()) == 1, "the next block is still decided"
