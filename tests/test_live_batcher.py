"""P7-8 offline: the live batcher's control loop against a fake preprod.

The done-when for P7-8 is behavioural — exactly one decision per block while the
pool is free, none while it is locked, and a clean shutdown only once no batch is
in flight. Every one of those is checked here without a network, using the fake
chain from ``test_tx_builder`` so PyCardano still builds real transactions.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from pycardano import PaymentSigningKey, TransactionInput, UTxO, Value
from pycardano.exception import InvalidTransactionException

from batcher.build.calibration import CapacityCalibrator
from batcher.build.tx_builder import key_address
from batcher.config.protocol import MAX_TX_SIZE
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
    batcher = make(world, policy=spy, submit=True, d4_path=d4, confirmation_depth=0)
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
    batcher = make(world, submit=True, confirmation_depth=0)
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


# --- order hygiene: quarantine ------------------------------------------------------------------


def ref(utxo) -> tuple[str, int]:
    return (str(utxo.input.transaction_id), utxo.input.index)


def test_an_order_that_can_never_fill_stops_forcing_submission(world, monkeypatch):
    """Market crash: an unfillable order must not pin oldest_wait past D_MAX forever."""
    monkeypatch.setattr(daemon, "QUARANTINE_STRIKES", 3)
    fake, _, user, deployment, _ = world
    stuck = order_utxo(fake.context, deployment, user, 0, min_out=10_000_000)
    fake.arrivals[str(stuck.input.transaction_id)] = TIP - 500
    order_utxo(fake.context, deployment, user, 1)  # fresh and fillable
    batcher = make(world, policy=Null(), d_max=120)

    for _ in range(3):
        (record,) = batcher.step()
        assert record["action"] == "SUBMIT", "D_MAX forces a batch while the order is queued"
        fake.next_block()
    assert batcher.quarantined == {ref(stuck)}

    (record,) = batcher.step()
    assert record["action"] == "WAIT" and record["resolution"] == "wait"
    assert record["queue_depth"] == 1 and record["oldest_wait"] < 120
    assert record["quarantined"] == 1


def test_a_quarantined_order_is_released_after_the_timeout(world, monkeypatch):
    monkeypatch.setattr(daemon, "QUARANTINE_STRIKES", 1)
    monkeypatch.setattr(daemon, "QUARANTINE_BLOCKS", 2)
    fake = world[0]
    (stuck,) = add_orders(world, 1, min_out=10_000_000)
    batcher = make(world)

    (record,) = batcher.step()
    assert record["resolution"] == "unfillable" and batcher.quarantined == {ref(stuck)}
    fake.next_block()
    (record,) = batcher.step()
    assert record["queue_depth"] == 0, "quarantined orders are not offered to the policy"
    fake.next_block()
    (record,) = batcher.step()
    assert record["queue_depth"] == 1 and record["resolution"] == "unfillable"


def test_a_poison_order_is_isolated_by_bisection_and_the_rest_are_batched(world, monkeypatch):
    orders = add_orders(world, 4)
    poison = ref(orders[2])
    real = daemon.build_batch_tx
    builds = []

    def poisoned(context, skey, deployment, scripts, pool, queued, ttl):
        builds.append(len(queued))
        if any((o.tx_hash, o.index) == poison for _, o in queued):
            raise RuntimeError("EvaluationFailure")
        return real(context, skey, deployment, scripts, pool, queued, ttl)

    monkeypatch.setattr(daemon, "build_batch_tx", poisoned)
    fake = world[0]
    batcher = make(world, submit=True)

    (record,) = batcher.step()
    assert record["resolution"] == "build_failed" and "quarantined" in record["error"]
    assert batcher.quarantined == {poison}
    assert len(builds) <= 1 + 2 + 2, "isolation is bounded to O(log n) extra builds"
    assert fake.submitted == [], "nothing is submitted while isolating"

    fake.next_block()
    (record,) = batcher.step()
    assert record["resolution"] == "submitted" and record["executed"] == 3


def test_a_failure_no_single_order_causes_quarantines_nothing(world, monkeypatch):
    add_orders(world, 2)

    def only_pairs_fail(context, skey, deployment, scripts, pool, queued, ttl):
        if len(queued) > 1:
            raise RuntimeError("EvaluationFailure")
        raise daemon.NothingToBatch("alone, each is merely unfillable")

    monkeypatch.setattr(daemon, "build_batch_tx", only_pairs_fail)
    batcher = make(world)
    (record,) = batcher.step()
    assert record["resolution"] == "build_failed" and "quarantined" not in record["error"]
    assert batcher.quarantined == set()


def test_a_failure_every_build_shares_strikes_instead_of_quarantining(world, monkeypatch):
    """An empty batcher wallet fails every build; it must not empty the queue at once."""
    monkeypatch.setattr(daemon, "QUARANTINE_STRIKES", 2)
    fake = world[0]
    orders = add_orders(world, 3)

    def broke(*_args, **_kwargs):
        raise RuntimeError("UTxOSelectionException: not enough funds")

    monkeypatch.setattr(daemon, "build_batch_tx", broke)
    batcher = make(world)
    (record,) = batcher.step()
    assert "strike 1" in record["error"] and batcher.quarantined == set()
    fake.next_block()
    (record,) = batcher.step()
    assert batcher.quarantined == {ref(orders[0])}, "only repeated strikes quarantine"


# --- the input-liveness watchdog -----------------------------------------------------------------


def cancel(world, utxo) -> None:
    """The owner (or a rival batcher) spends an order out from under our batch."""
    fake, _, _, deployment, _ = world
    order_address, _ = dex.addresses(deployment)
    utxos = fake.context.by_address[str(order_address)]
    utxos[:] = [u for u in utxos if u.input != utxo.input]


def test_a_cancelled_order_unlocks_the_pool_at_the_next_block_not_at_ttl(world):
    fake = world[0]
    orders = add_orders(world, 2)
    spy = Spy()
    batcher = make(world, policy=spy, submit=True)
    batcher.step()
    ttl = batcher.in_flight.ttl_slot

    cancel(world, orders[0])
    fake.next_block()
    resolved, decision = batcher.step()

    assert fake.slot < ttl
    assert resolved["resolution"] == "invalidated"
    assert str(orders[0].input.transaction_id) in resolved["error"]
    assert batcher.d4_rows[0]["outcome"] == "invalidated"
    assert spy.outcomes[0].included is False
    assert decision["resolution"] == "submitted" and decision["executed"] == 1
    assert len(fake.submitted) == 2


def test_our_own_batch_indexed_before_its_transaction_is_not_invalidation(world):
    """Every order and the pool gone at once is our batch landing, not a rival."""
    fake = world[0]
    add_orders(world, 2)
    batcher = make(world, submit=True)
    batcher.step()

    tx = fake.submitted[0]
    fake.confirm(tx)
    del fake.included[str(tx.id)]  # the UTxO index is ahead of the transaction endpoint
    fake.next_block()
    (record,) = batcher.step()
    assert record["resolution"] == "locked" and batcher.pool_locked


def test_an_owner_who_keeps_cancelling_under_our_batches_is_served_last(world, monkeypatch):
    monkeypatch.setattr(daemon, "GRIEF_LIMIT", 1)
    fake, _, griefer, deployment, _ = world
    honest = PaymentSigningKey.generate()
    batcher = make(world, submit=True, confirmation_depth=0)

    for i in range(2):
        order = order_utxo(fake.context, deployment, griefer, i)
        batcher.step()
        assert batcher.pool_locked
        cancel(world, order)
        fake.next_block()
        resolved, _ = batcher.step()
        assert resolved["resolution"] == "invalidated"
        fake.next_block()

    late = order_utxo(fake.context, deployment, honest, 3)
    early = order_utxo(fake.context, deployment, griefer, 2)
    fake.arrivals[str(early.input.transaction_id)] = TIP - 1_000
    fake.arrivals[str(late.input.transaction_id)] = TIP
    queue = batcher._queue(fake.height)
    assert [o.tx_hash for _, o in queue] == [
        str(late.input.transaction_id),
        str(early.input.transaction_id),
    ], "the griefer's older order is sorted after the honest one"


# --- settlement depth, rollback and the expiry race ----------------------------------------------


def test_a_batch_settles_only_at_confirmation_depth(world):
    fake = world[0]
    add_orders(world, 2)
    spy = Spy()
    batcher = make(world, policy=spy, submit=True, confirmation_depth=3)
    batcher.step()

    fake.next_block()
    fake.confirm(fake.submitted[0])
    for _ in range(3):
        (record,) = batcher.step()
        assert record["resolution"] == "tentative" and batcher.pool_locked
        assert spy.outcomes == [] and batcher.d4_rows == []
        fake.next_block()

    resolved, decision = batcher.step()
    assert resolved["resolution"] == "included" and not batcher.pool_locked
    assert batcher.d4_rows[0]["outcome"] == "included" and spy.outcomes[0].included
    assert decision["resolution"] == "wait"


def roll_back_after_sighting(world, spy):
    """Submit a batch, see it on chain, then lose it to a rollback."""
    fake = world[0]
    add_orders(world, 2)
    batcher = make(world, policy=spy, submit=True, confirmation_depth=3)
    batcher.step()

    fake.next_block()
    tx = fake.submitted[0]
    fake.confirm(tx, apply_to_utxos=False)
    (record,) = batcher.step()
    assert record["resolution"] == "tentative"

    del fake.included[str(tx.id)]  # the block carrying it was rolled back
    fake.next_block()
    return batcher, tx


def test_a_rollback_keeps_the_pool_locked_until_ttl_then_returns_the_orders(world):
    """A rolled-back transaction is still valid and can return from a mempool until
    its TTL. Unlocking at once (the previous behaviour) let the next batch spend the
    same orders and clash with it, so the orders are only given back at TTL."""
    fake = world[0]
    spy = Spy()
    batcher, _ = roll_back_after_sighting(world, spy)

    (resolved,) = batcher.step()
    assert resolved["resolution"] == "rolled_back" and resolved["pool_locked"]
    assert batcher.pool_locked, "no decision may be made over orders the rolled-back tx spends"
    assert spy.outcomes == [] and batcher.d4_rows == [], "nothing is recorded before settlement"
    decisions = len(spy.observations)

    ttl = batcher.in_flight.ttl_slot
    while fake.slot + 20 <= ttl:
        fake.next_block()
        (record,) = batcher.step()
        assert record["resolution"] == "locked" and batcher.pool_locked
    assert len(spy.observations) == decisions and len(fake.submitted) == 1

    fake.next_block(slots=ttl - fake.slot + 1)
    expired, decision = batcher.step()
    assert expired["resolution"] == "expired" and spy.outcomes[0].included is False
    assert decision["queue_depth"] == 2 and decision["resolution"] == "submitted"


def test_a_rolled_back_batch_that_is_re_included_settles_normally(world):
    fake = world[0]
    spy = Spy()
    batcher, tx = roll_back_after_sighting(world, spy)
    batcher.step()

    fake.confirm(tx, apply_to_utxos=False)  # it came back from the mempool
    fake.next_block()
    (record,) = batcher.step()
    assert record["resolution"] == "tentative" and batcher.pool_locked
    for _ in range(3):
        fake.next_block()
        records = batcher.step()
    assert records[0]["resolution"] == "included" and spy.outcomes[0].included
    assert len(fake.submitted) == 1


class LateIndexing(FakePreprod):
    """The first inclusion lookup misses a transaction that a second one finds."""

    def __init__(self, chain):
        super().__init__(chain)
        self.late: dict[str, int] = {}

    def inclusion_slot(self, tx_hash: str) -> int | None:
        if tx_hash in self.late:
            self.included[tx_hash] = self.late.pop(tx_hash)
            return None
        return super().inclusion_slot(tx_hash)


def test_a_batch_included_just_before_ttl_but_seen_late_is_not_expired(world):
    _, batcher_key, user, deployment, scripts = world
    fake = LateIndexing(world[0].context)
    add_orders((fake, batcher_key, user, deployment, scripts), 1)
    batcher = LiveBatcher(fake, Greedy(), deployment, scripts, batcher_key, submit=True)
    batcher.step()
    ttl = batcher.in_flight.ttl_slot

    fake.next_block(slots=ttl - fake.slot + 1)
    fake.late[str(fake.submitted[0].id)] = ttl - 5
    (record,) = batcher.step()
    assert record["resolution"] == "tentative" and batcher.d4_rows == []


def test_the_arrival_cache_forgets_orders_that_have_settled(world):
    fake = world[0]
    add_orders(world, 2)
    batcher = make(world, submit=True, confirmation_depth=0)
    batcher.step()
    assert len(batcher._arrivals) == 2

    fake.next_block()
    fake.confirm(fake.submitted[0])
    batcher.step()
    assert batcher._arrivals == {}


# --- capacity calibration ------------------------------------------------------------------------


def test_the_daemon_clamps_the_policy_to_the_calibrated_max(world):
    add_orders(world, 3)
    calibrator = CapacityCalibrator()
    # Estimates: 1 100 bytes for two orders, 1 400 for three; a factor of 13 fits only two.
    calibrator.corrections["size"].factor = 13.0
    (record,) = make(world, policy=Oversized(), calibrator=calibrator).step()

    assert record["gate_a_max_n"] == 2 and record["n"] == 2 and record["executed"] == 2
    assert record["capacity"]["factors"]["size"] >= 13.0
    assert record["capacity"]["limits"]["size"] == MAX_TX_SIZE


def test_every_build_feeds_its_measurement_back(world):
    add_orders(world, 2)
    batcher = make(world)
    (record,) = batcher.step()
    assert record["resolution"] == "shadow"
    assert batcher.calibrator.corrections["size"].samples == 1
    world[0].next_block()
    batcher.step()
    assert batcher.calibrator.corrections["size"].samples == 1, "a shadow rebuild is not evidence"


def test_calibration_can_be_switched_off(world):
    add_orders(world, 1)
    batcher = make(world, calibration=False)
    (record,) = batcher.step()
    assert batcher.calibrator is None and record["capacity"] is None


class StricterChain(FakeChain):
    @property
    def protocol_param(self):
        return replace(super().protocol_param, max_tx_size=1_200)


def test_a_stricter_live_size_limit_lowers_gate_a_and_is_reported(world):
    _, batcher_key, user, deployment, scripts = world
    chain = StricterChain()
    chain.by_address = world[0].context.by_address
    fake = FakePreprod(chain)
    add_orders((fake, batcher_key, user, deployment, scripts), 3)
    batcher = LiveBatcher(fake, Oversized(), deployment, scripts, batcher_key, submit=True)

    (record,) = batcher.step()
    assert record["gate_a_max_n"] == 2, "1 100 estimated bytes fit under 1 200, 1 400 do not"
    assert record["capacity"]["limits"]["size"] == 1_200
    assert any("max_tx_size" in w for w in record["capacity"]["warnings"])
    assert fake.submitted == [], "real transactions are larger than 1 200 bytes"


def oversize_after(limit_orders: int, bytes_per_order: int):
    """A build that measures ``bytes_per_order`` per order: too large above ``limit_orders``."""
    real = daemon.build_batch_tx
    builds = []

    def build(context, skey, deployment, scripts, pool, queued, ttl):
        builds.append(len(queued))
        built = real(context, skey, deployment, scripts, pool, queued, ttl)
        return replace(built, actual_size=bytes_per_order * built.plan.n)

    return build, builds


def test_an_oversize_build_is_halved_until_it_fits_and_only_that_is_submitted(world, monkeypatch):
    fake = world[0]
    add_orders(world, 4)
    build, builds = oversize_after(2, 5_000)  # 20 000 bytes for four, 10 000 for two
    monkeypatch.setattr(daemon, "build_batch_tx", build)
    batcher = make(world, policy=Oversized(), submit=True)

    (record,) = batcher.step()
    assert record["resolution"] == "submitted" and record["executed"] == 2
    assert record["build_attempts"] == [4, 2] and builds == [4, 2]
    assert len(fake.submitted) == 1
    assert batcher.in_flight.built.actual_size <= MAX_TX_SIZE
    assert batcher.calibrator.factors["size"] > 10, "the oversize measurement was learned"
    assert batcher.quarantined == set(), "a batch too large is not a poison order"


def test_a_pycardano_size_refusal_is_retried_smaller_in_the_same_block(world, monkeypatch):
    fake = world[0]
    add_orders(world, 4)
    real = daemon.build_batch_tx
    builds = []

    def build(context, skey, deployment, scripts, pool, queued, ttl):
        builds.append(len(queued))
        if len(queued) > 1:
            raise InvalidTransactionException(
                "Transaction size (30000) exceeds the max limit (16384). Please try reducing"
            )
        return real(context, skey, deployment, scripts, pool, queued, ttl)

    monkeypatch.setattr(daemon, "build_batch_tx", build)
    batcher = make(world, policy=Oversized(), submit=True)
    (record,) = batcher.step()

    assert builds == [4, 2, 1] and record["build_attempts"] == [4, 2, 1]
    assert record["resolution"] == "submitted" and record["executed"] == 1
    assert len(fake.submitted) == 1
    assert batcher.calibrator.max_n([300] * 4, [500_000] * 4, [200_000_000] * 4) < 4


def test_a_single_order_too_large_for_any_batch_is_never_submitted(world, monkeypatch):
    fake = world[0]
    add_orders(world, 2)
    build, builds = oversize_after(0, 20_000)
    monkeypatch.setattr(daemon, "build_batch_tx", build)
    batcher = make(world, policy=Oversized(), submit=True)

    (record,) = batcher.step()
    assert record["resolution"] == "build_failed" and "CapacityExceeded" in record["error"]
    assert builds[:2] == [2, 1]
    assert fake.submitted == [] and not batcher.pool_locked
