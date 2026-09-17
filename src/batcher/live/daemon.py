"""P7-8 · The live batcher: the simulator's control loop, pointed at preprod.

One iteration per new block, in the order ``docs/03-ARCHITECTURE.md`` §4 fixes:

1. if a batch is in flight, resolve it — settled, expired, invalidated, rolled
   back, or still waiting;
2. **while the pool is locked, no decision exists** (head-of-line blocking);
3. otherwise read the queue and the pool, observe, decide, and repair the decision
   with the *simulator's own* structural rules (``sim.env._enforce``: submission
   forced past ``D_MAX``, ``n`` clamped to Gate A);
4. build the batch, submit it, and hold the pool lock until it resolves.

**Shadow mode** (the default) does all of that except submit: it reads preprod,
decides, and builds and signs the exact transaction it would send, then logs it.
It is how a policy is watched on live traffic before it is trusted with the key.

**Shutdown** is only clean when the pool is free. A stop request while a batch is
in flight keeps the loop polling until that batch is resolved, and no new batch
is started in the meantime (runbook §7.2).

Every record carries a ``resolution``:

========================  ===================================================================
``wait``                  the policy (after the structural rules) chose not to submit
``shadow``                shadow mode built the batch it would have sent
``submitted``             the batch was sent; the pool is locked
``rejected``              the submission was refused; the pool stays free
``unfillable``            no candidate order can be filled at its ``min_out``
``build_failed``          building or evaluating failed; nothing was sent (a poison order
                          found by bisection is quarantined or struck, see below)
``stale_view``            the API still shows the pool our settled batch spent
``pool_missing``          no single pool UTxO was found
``stopping``              a stop was requested; no new batch is started
``locked``                a batch is in flight and not yet on chain
``tentative``             our batch is on chain but not ``confirmation_depth`` blocks deep
``included``              it reached that depth: settled, D4 written, policy informed
``expired``               its TTL passed without inclusion (checked twice, see ``_resolve``)
``invalidated``           an order input was spent by someone else, so it can never land
``rolled_back``           it left the chain before reaching depth; the pool stays locked until
                          it is re-included or its TTL passes (see ``_resolve``)
``api_unavailable``       the chain could not be read; no decision, nothing submitted
========================  ===================================================================

**Order hygiene.** An order the planner skips as unfillable gets a strike. An
order that makes a build fail on its own is found by bisection and quarantined at
once if the rest then build, or struck otherwise. A quarantined order sits out
``QUARANTINE_BLOCKS`` — out of the decision queue and out of ``oldest_wait`` — so
it can neither pin ``D_MAX`` nor block the queue behind it.
It is released automatically so a recovered market can still fill it.

**Cancel griefing.** An owner whose orders vanish from under our in-flight batches
more than ``GRIEF_LIMIT`` times within ``GRIEF_WINDOW_BLOCKS`` is deprioritised:
their orders are still served, but after everyone else's. The owner is identified
by the payout (return) address, the identity ``OrderUtxo`` carries; a vanished
order may also have been taken by a rival batcher, which is why the response is a
reordering and never an exclusion.

**Capacity calibration.** With a ``CapacityCalibrator`` (the default), Gate A is
evaluated against ``min(live, configured)`` protocol limits and estimates corrected
by what built transactions actually measured (``build.calibration``). The
observation's ``gate_a_max_n`` is the smaller of the static and calibrated maxima,
and the enforced ``n`` is clamped to it again. A build refused for size or budget,
or one that measures above a limit, is retried in the same block at half the
``n``, down to 1; a transaction over a limit is never submitted.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd
from pycardano import PaymentSigningKey, UTxO

from batcher.build.calibration import CapacityCalibrator, CapacityExceeded
from batcher.build.estimator import block_usage_from_fill, max_n_satisfying_gate_a
from batcher.build.submitter import GateAViolation, OrderUtxo
from batcher.build.tx_builder import (
    BuiltBatch,
    NothingToBatch,
    PoolNotFound,
    build_batch_tx,
    d4_row,
    read_orders,
    read_pool,
)
from batcher.config.params import D_MAX, FORECAST_HORIZON, FORECAST_WINDOW_K, TTL_SLOTS
from batcher.config.protocol import MAX_BLOCK_EX_MEM, MAX_BLOCK_EX_STEPS
from batcher.forecast.baseline import MovingAverage
from batcher.live.chain import LiveChain, Tip
from batcher.live.resilience import ChainUnavailable, is_api_error
from batcher.onchain.blueprint import CompiledValidator
from batcher.onchain.deployment import Deployment, addresses
from batcher.policy.base import Action, Observation, Outcome, Policy
from batcher.sim.env import _enforce as enforce  # the simulator's rules, not a copy

# Blocks our batch must be buried under before it is settled; 0 settles on sight.
CONFIRMATION_DEPTH = 3
# Consecutive strikes (unfillable plans, unconfirmed build failures) before quarantine.
QUARANTINE_STRIKES = 3
# Blocks a quarantined order sits out before it is offered to the planner again.
QUARANTINE_BLOCKS = 30
# Cancels under an in-flight batch an owner may make in the window before being
# deprioritised; the window is about a day and a half of preprod blocks.
GRIEF_LIMIT = 3
GRIEF_WINDOW_BLOCKS = 4_320

Ref = tuple[str, int]


def _ref(order: OrderUtxo) -> Ref:
    return (order.tx_hash, order.index)


def _refs(utxos: Sequence[UTxO]) -> set[Ref]:
    return {(str(u.input.transaction_id), u.input.index) for u in utxos}


@dataclass(frozen=True)
class InFlightBatch:
    tx_id: str
    submit_slot: int
    ttl_slot: int
    built: BuiltBatch
    pool_ref: tuple[str, int]
    # Set once the transaction is seen on chain: the slot it reported and the
    # tip height at which we first saw it, from which depth is counted.
    seen_slot: int | None = None
    seen_height: int | None = None

    @property
    def order_refs(self) -> list[Ref]:
        return [_ref(payout.order) for payout in self.built.plan.payouts]


class LiveBatcher:
    def __init__(
        self,
        chain: LiveChain,
        policy: Policy,
        deployment: Deployment,
        scripts: dict[str, CompiledValidator],
        batcher_skey: PaymentSigningKey,
        *,
        submit: bool = False,
        d_max: int = D_MAX,
        ttl_slots: int = TTL_SLOTS,
        confirmation_depth: int = CONFIRMATION_DEPTH,
        emit: Callable[[dict], None] | None = None,
        d4_path: Path | None = None,
        calibration: bool = True,
        calibrator: CapacityCalibrator | None = None,
    ):
        self.chain = chain
        self.policy = policy
        self.deployment = deployment
        self.scripts = scripts
        self.batcher_skey = batcher_skey
        self.submit = submit
        self.d_max = d_max
        self.ttl_slots = ttl_slots
        self.confirmation_depth = confirmation_depth
        self.emit = emit or (lambda record: None)
        self.d4_path = d4_path
        # ``calibration=False`` restores the static Gate A exactly.
        self.calibrator = (calibrator or CapacityCalibrator()) if calibration else None

        self.order_address, self.pool_address = addresses(deployment, chain.context.network)
        self.forecaster = MovingAverage(horizon=FORECAST_HORIZON)

        self.last_height: int | None = None
        self.in_flight: InFlightBatch | None = None
        self.consumed_pool_ref: tuple[str, int] | None = None
        self.stop_requested = False
        self.records: list[dict] = []
        self.d4_rows: list[dict] = []
        # Orders refused admission at the last queue read: (tx_hash, index, reason).
        self.rejected_orders: list[tuple[str, int, str]] = []
        self._arrivals: dict[str, int] = {}
        self._strikes: dict[Ref, int] = {}
        self._quarantine: dict[Ref, int] = {}  # order -> height at which it is released
        self._gone: set[Ref] = set()  # spent under a batch; ignored until the API agrees
        self._griefs: dict[str, list[int]] = {}  # owner -> heights of cancels

    @property
    def pool_locked(self) -> bool:
        return self.in_flight is not None

    @property
    def quarantined(self) -> set[Ref]:
        return set(self._quarantine)

    def request_stop(self) -> None:
        self.stop_requested = True

    # --- the loop ------------------------------------------------------------------------

    def run(
        self,
        max_blocks: int | None = None,
        poll_seconds: float = 10.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> int:
        """Poll until stopped. Returns the number of blocks processed."""
        blocks = 0
        while True:
            before = self.last_height
            self.step()
            if self.last_height != before:
                blocks += 1
                if max_blocks is not None and blocks >= max_blocks:
                    self.request_stop()
            if self.stop_requested and not self.pool_locked:
                return blocks
            sleep(poll_seconds)

    def step(self) -> list[dict]:
        """Process the newest block once. Returns its records; empty if it is not new.

        If the chain cannot be read part-way, an ``api_unavailable`` record is
        returned, nothing is decided or submitted on the partial view, any batch
        in flight is kept, and the same block is processed again at the next poll.
        Every chain read in a phase happens before that phase changes any state,
        so repeating the block is safe.
        """
        previous = self.last_height
        produced = []
        try:
            tip = self.chain.tip()
            if tip.height == self.last_height:
                return []
            self.last_height = tip.height

            if self.in_flight is not None:
                batch = self.in_flight
                resolution, error = self._resolve(tip, batch)
                produced.append(
                    self._record(
                        tip, locked=True, tx_id=batch.tx_id, resolution=resolution, error=error
                    )
                )
                if self.in_flight is not None:
                    return self._publish(produced)  # head-of-line: no decision this block

            produced.append(self._decide(tip))
        except Exception as error:
            if not is_api_error(error):
                raise
            self.last_height = previous
            produced.append(self._unavailable(error))
        return self._publish(produced)

    # --- resolving a batch in flight ------------------------------------------------------------

    def _resolve(self, tip: Tip, batch: InFlightBatch) -> tuple[str, str | None]:
        confirm = self.chain.inclusion_slot(batch.tx_id)

        if batch.seen_slot is not None:
            if confirm is None:
                # Left the chain before reaching depth. Its orders are unspent again, but
                # the transaction is still valid and can return from a mempool until its
                # TTL; a new batch over the same orders would clash with it. So the pool
                # stays locked and resolution restarts as if it had never been seen:
                # re-inclusion, TTL expiry (with its re-check) or invalidation frees it.
                self.in_flight = replace(batch, seen_slot=None, seen_height=None)
                return "rolled_back", None
            if confirm != batch.seen_slot:  # re-included in another block: count again
                self.in_flight = replace(batch, seen_slot=confirm, seen_height=tip.height)
                return "tentative", None
            if tip.height - batch.seen_height < self.confirmation_depth:
                return "tentative", None
            return self._settle(batch, "included", confirm), None

        if confirm is None and tip.slot > batch.ttl_slot:
            # Inclusion can race the TTL check; look once more before giving up.
            confirm = self.chain.inclusion_slot(batch.tx_id)
        if confirm is not None:
            if self.confirmation_depth <= 0:
                return self._settle(batch, "included", confirm), None
            self.in_flight = replace(batch, seen_slot=confirm, seen_height=tip.height)
            return "tentative", None
        if tip.slot > batch.ttl_slot:
            return self._settle(batch, "expired", None), None

        vanished = self._vanished_inputs(batch)
        if not vanished:
            return "locked", None
        self._invalidate(tip, batch, vanished)
        return "invalidated", "inputs spent elsewhere: " + ", ".join(
            f"{tx_hash}#{index}" for tx_hash, index in vanished
        )

    def _settle(self, batch: InFlightBatch, outcome: str, confirm: int | None) -> str:
        """The batch's final outcome: D4 row, the policy's feedback, the pool freed."""
        self._write_d4(d4_row(batch.built, batch.submit_slot, outcome, confirm))
        self.policy.observe_outcome(
            Outcome(
                included=outcome == "included",
                slots_to_confirm=confirm - batch.submit_slot if confirm is not None else None,
                fee_lovelace=batch.built.fee,
                n=batch.built.plan.n,
            )
        )
        if outcome == "included":
            # The API can lag our own confirmed batch; remember the pool it spent.
            self.consumed_pool_ref = batch.pool_ref
        self.in_flight = None
        return outcome

    def _vanished_inputs(self, batch: InFlightBatch) -> list[Ref]:
        """Order inputs of ``batch`` spent by a transaction other than ours.

        Our transaction spends every order input and the pool together. An input
        missing while another of ours is still present — or while the pool UTxO is
        still present, read *after* the orders so a batch indexed in between is
        not mistaken for a rival — cannot have been spent by us.
        """
        ours = batch.order_refs
        present = _refs(self.chain.utxos(self.order_address))
        missing = [ref for ref in ours if ref not in present]
        if not missing:
            return []
        if len(missing) < len(ours):
            return missing
        return missing if batch.pool_ref in _refs(self.chain.utxos(self.pool_address)) else []

    def _invalidate(self, tip: Tip, batch: InFlightBatch, vanished: list[Ref]) -> None:
        owners = {_ref(p.order): p.order.return_address for p in batch.built.plan.payouts}
        for ref in vanished:
            self._griefs.setdefault(owners[ref], []).append(tip.height)
        self._gone.update(vanished)
        self._settle(batch, "invalidated", None)

    # --- deciding -----------------------------------------------------------------------------

    def _decide(self, tip: Tip) -> dict:
        if self.stop_requested:
            return self._record(tip, resolution="stopping")

        try:
            pool = read_pool(self.chain.utxos(self.pool_address), self.deployment)
        except PoolNotFound as error:
            return self._record(tip, resolution="pool_missing", error=str(error))

        pool_ref = (str(pool.input.transaction_id), pool.input.index)
        if pool_ref == self.consumed_pool_ref:
            # Building on a pool UTxO our last batch already spent would be rejected.
            return self._record(tip, resolution="stale_view")

        if self.calibrator is not None:
            self.calibrator.refresh(self.chain.context, tip.height)
        queue = self._queue(tip.height)
        obs = self._observe(tip, queue)
        self.consumed_pool_ref = None
        action = enforce(self.policy.decide(obs), obs, self.d_max)
        if action.submit and action.n > obs.gate_a_max_n:  # the calibrated max binds
            action = Action(submit=obs.gate_a_max_n > 0, n=obs.gate_a_max_n)
        if not action.submit or action.n == 0:
            return self._record(tip, obs=obs, action=action, resolution="wait")

        n, attempts = action.n, []
        while True:
            candidates = queue[:n]
            attempts.append(n)
            try:
                built = self._build(pool, candidates)
                self._check_capacity(built)
                break
            except GateAViolation:
                raise  # a defect: stop the daemon rather than trade around it
            except NothingToBatch:
                self._strike(tip.height, [_ref(order) for _, order in candidates], [])
                return self._record(
                    tip, obs=obs, action=action, resolution="unfillable", attempts=attempts
                )
            except Exception as error:  # a failed build or evaluation submitted nothing
                if self._capacity_failure(error, candidates) and n > 1:
                    n //= 2  # too large for the chain: shrink and retry in this block
                    continue
                message = f"{type(error).__name__}: {error}"
                if not is_api_error(error):
                    message += self._handle_poison(tip.height, pool, candidates)
                return self._record(
                    tip,
                    obs=obs,
                    action=action,
                    resolution="build_failed",
                    error=message,
                    attempts=attempts,
                )
        self._strike(
            tip.height,
            [_ref(order) for order in built.plan.skipped],
            [_ref(payout.order) for payout in built.plan.payouts],
        )

        if not self.submit:
            return self._record(
                tip, obs=obs, action=action, built=built, resolution="shadow", attempts=attempts
            )

        try:
            tx_id = self.chain.submit(built.transaction)
        except ChainUnavailable as error:  # never sent: not a rejection
            return self._record(
                tip, obs=obs, action=action, resolution="api_unavailable", error=str(error)
            )
        except Exception as error:  # mempool rejection, script failure: counted, not fatal
            self._write_d4(d4_row(built, tip.slot, "rejected", None))
            return self._record(
                tip,
                obs=obs,
                action=action,
                built=built,
                resolution="rejected",
                error=f"{type(error).__name__}: {error}",
                attempts=attempts,
            )

        self.in_flight = InFlightBatch(tx_id, tip.slot, built.ttl_slot, built, pool_ref)
        return self._record(
            tip,
            obs=obs,
            action=action,
            built=built,
            tx_id=tx_id,
            resolution="submitted",
            attempts=attempts,
        )

    def _build(self, pool: UTxO, orders) -> BuiltBatch:
        return build_batch_tx(
            self.chain.context,
            self.batcher_skey,
            self.deployment,
            self.scripts,
            pool,
            orders,
            self.ttl_slots,
        )

    # --- capacity ---------------------------------------------------------------------------------

    def _check_capacity(self, built: BuiltBatch) -> None:
        """Feed a build's measurement back, and refuse it if it is over a limit."""
        if self.calibrator is None:
            return
        refs = tuple(sorted(_ref(payout.order) for payout in built.plan.payouts))
        self.calibrator.observe_built(built, key=refs)
        over = self.calibrator.exceeded(built)
        if over:
            limits = self.calibrator.limits
            measured = {"size": built.actual_size, "mem": built.actual_mem}
            measured["steps"] = built.actual_steps
            raise CapacityExceeded(
                over,
                f"a batch of {built.plan.n} measured "
                + ", ".join(f"{d} {measured[d]} > limit {limits.of(d)}" for d in over),
            )

    def _capacity_failure(self, error: BaseException, candidates) -> bool:
        """Whether ``error`` means the batch was too large; the calibrator learns from it."""
        if self.calibrator is None or is_api_error(error):
            return False
        if isinstance(error, CapacityExceeded):
            return True  # already measured and learned from in ``_check_capacity``
        orders = [order for _, order in candidates]
        return bool(
            self.calibrator.record_failure(
                error,
                [o.size_bytes for o in orders],
                [o.mem_exunits for o in orders],
                [o.step_exunits for o in orders],
            )
        )

    def _queue(self, height: int | None = None):
        """Eligible orders on chain: FIFO by the slot each was placed, griefers last.

        Orders refused admission, quarantined, or already spent under one of our
        batches are left out; bookkeeping for orders no longer on chain is pruned.
        """
        height = self.last_height if height is None else height
        self.rejected_orders = []
        orders = read_orders(
            self.chain.utxos(self.order_address),
            self.deployment,
            self.chain.context.network,
            self.rejected_orders,
        )
        self._prune(orders)
        for ref, release in list(self._quarantine.items()):
            if height is not None and height >= release:
                del self._quarantine[ref]

        queue = [
            item
            for item in orders
            if _ref(item[1]) not in self._quarantine and _ref(item[1]) not in self._gone
        ]
        for _, order in queue:
            if order.tx_hash not in self._arrivals:
                self._arrivals[order.tx_hash] = self.chain.arrival_slot(order.tx_hash)
        return sorted(
            queue,
            key=lambda item: (
                self._deprioritised(item[1].return_address, height),
                self._arrivals[item[1].tx_hash],
                item[1].tx_hash,
                item[1].index,
            ),
        )

    def _prune(self, orders) -> None:
        """Forget orders that are no longer at the order script (settled or cancelled)."""
        present = {_ref(order) for _, order in orders}
        hashes = {tx_hash for tx_hash, _ in present}
        self._arrivals = {h: s for h, s in self._arrivals.items() if h in hashes}
        self._strikes = {r: n for r, n in self._strikes.items() if r in present}
        self._quarantine = {r: h for r, h in self._quarantine.items() if r in present}
        self._gone &= present

    def _observe(self, tip: Tip, queue) -> Observation:
        orders = [order for _, order in queue]
        sizes = tuple(o.size_bytes for o in orders)
        mems = tuple(o.mem_exunits for o in orders)
        steps = tuple(o.step_exunits for o in orders)

        # Live forecasting is E4 over recent real blocks: it needs no feature
        # history. Ablation A2 found LightGBM helps P2 on cost, so running it
        # live, with a maintained feature window, is future work.
        fills = self.chain.recent_fills(FORECAST_WINDOW_K)
        if fills:
            prediction = self.forecaster.predict_frame(pd.DataFrame({"fill_pct": fills}))[-1]
            fill_hat = tuple(float(v) for v in prediction)
        else:
            fill_hat = (0.0,) * FORECAST_HORIZON
        _, block_mem, block_steps = block_usage_from_fill(tip.fill)

        oldest = min(self._arrivals[o.tx_hash] for o in orders) if orders else tip.slot
        gate_a_max_n = max_n_satisfying_gate_a(sizes, mems, steps)
        if self.calibrator is not None:
            # Never above the static gate either: ``plan_batch`` re-checks it and raises.
            gate_a_max_n = min(gate_a_max_n, self.calibrator.max_n(sizes, mems, steps))
        return Observation(
            slot=tip.slot,
            queue_depth=len(orders),
            oldest_wait=max(0, tip.slot - oldest),
            queue_sizes=sizes,
            queue_mem=mems,
            queue_steps=steps,
            fill_hat=fill_hat,
            mem_headroom=MAX_BLOCK_EX_MEM - block_mem,
            step_headroom=MAX_BLOCK_EX_STEPS - block_steps,
            pool_locked=False,
            slots_in_flight=0,
            gate_a_max_n=gate_a_max_n,
        )

    # --- order hygiene ---------------------------------------------------------------------------

    def _strike(self, height: int, skipped: list[Ref], executed: list[Ref]) -> None:
        """Count consecutive unfillable plans; an order planned into a batch is cleared."""
        for ref in executed:
            self._strikes.pop(ref, None)
        for ref in skipped:
            self._strikes[ref] = self._strikes.get(ref, 0) + 1
            if self._strikes[ref] >= QUARANTINE_STRIKES:
                self._quarantine_order(ref, height)

    def _quarantine_order(self, ref: Ref, height: int) -> None:
        self._strikes.pop(ref, None)
        self._quarantine[ref] = height + QUARANTINE_BLOCKS

    def _handle_poison(self, height: int, pool: UTxO, candidates) -> str:
        """After a failed build, quarantine or strike the order that causes it.

        Returns a note for the record. A suspect is quarantined at once only when
        the other candidates are shown to build without it; otherwise — a lone
        candidate, or a failure the rest share, such as an empty batcher wallet —
        it only gets a strike, so a fault that is not the order's own cannot empty
        the queue into quarantine in a single block.
        """
        suspect = self._isolate(pool, candidates)
        if suspect is None:
            return ""
        rest = [item for item in candidates if _ref(item[1]) != suspect]
        label = f"{suspect[0]}#{suspect[1]}"
        if rest and self._builds(pool, rest):
            self._quarantine_order(suspect, height)
            return f"; quarantined {label}"
        self._strike(height, [suspect], [])
        if suspect in self._quarantine:
            return f"; quarantined {label}"
        return f"; strike {self._strikes[suspect]} for {label}"

    def _isolate(self, pool: UTxO, candidates) -> Ref | None:
        """Bisect a failed build down to an order that fails on its own.

        Halves are only built, never submitted, so this is safe in live mode. If
        the left half builds, the failure is sought in the right half; otherwise
        in the left. With the confirming build in ``_handle_poison`` that is at
        most ``ceil(log2 n) + 2`` extra builds. An order is returned only if a
        build of it *alone* failed; a failure that needs a combination of orders,
        or an unreadable chain, yields ``None``.
        """
        group = list(candidates)
        failed_alone = len(group) == 1  # the build that just failed was this order alone
        while len(group) > 1:
            half = len(group) // 2
            left, right = group[:half], group[half:]
            builds = self._builds(pool, left)
            if builds is None:
                return None
            group, failed_alone = (right, False) if builds else (left, True)
        if not failed_alone and self._builds(pool, group) is not False:
            return None
        return _ref(group[0][1])

    def _builds(self, pool: UTxO, orders) -> bool | None:
        """Whether ``orders`` build; ``None`` if the chain could not be read."""
        try:
            self._build(pool, orders)
        except NothingToBatch:
            return True  # planning refused them cleanly; not a poison order
        except Exception as error:
            return None if is_api_error(error) else False
        return True

    def _deprioritised(self, owner: str, height: int | None) -> bool:
        heights = self._griefs.get(owner)
        if not heights:
            return False
        if height is not None:
            heights[:] = [h for h in heights if h > height - GRIEF_WINDOW_BLOCKS]
        return len(heights) > GRIEF_LIMIT

    # --- records --------------------------------------------------------------------------------

    def _record(
        self,
        tip: Tip,
        *,
        locked: bool = False,
        obs: Observation | None = None,
        action: Action | None = None,
        built: BuiltBatch | None = None,
        tx_id: str | None = None,
        resolution: str,
        error: str | None = None,
        attempts: list[int] | None = None,
    ) -> dict:
        submitting = action is not None and action.submit
        return {
            "block_height": tip.height,
            "abs_slot": tip.slot,
            "policy": self.policy.name,
            "mode": "live" if self.submit else "shadow",
            "queue_depth": obs.queue_depth if obs else None,
            "oldest_wait": obs.oldest_wait if obs else None,
            "fill_actual": tip.fill,
            "fill_hat": obs.fill_hat[0] if obs and obs.fill_hat else None,
            "pool_locked": locked,
            "action": "SUBMIT" if submitting else "WAIT",
            "n": action.n if submitting else 0,
            "gate_a_max_n": obs.gate_a_max_n if obs else None,
            "executed": built.plan.n if built else 0,
            "fee_lovelace": built.fee if built else None,
            "tx_id": tx_id,
            "resolution": resolution,
            "error": error,
            "quarantined": len(self._quarantine),
            # Each n tried, in order, when a build had to shrink to fit; None otherwise.
            "build_attempts": attempts if attempts and len(attempts) > 1 else None,
            # Effective limits, learned factors and new warnings; None without calibration.
            "capacity": self.calibrator.snapshot() if self.calibrator is not None else None,
        }

    def _unavailable(self, error: BaseException) -> dict:
        """The record of a poll on which the chain could not be read; its block is unknown."""
        batch = self.in_flight
        return self._record(
            Tip(None, None, None),  # type: ignore[arg-type]
            locked=batch is not None,
            tx_id=batch.tx_id if batch else None,
            resolution="api_unavailable",
            error=f"{type(error).__name__}: {error}",
        )

    def _publish(self, records: list[dict]) -> list[dict]:
        for record in records:
            self.records.append(record)
            self.emit(record)
        return records

    def _write_d4(self, row: dict) -> None:
        self.d4_rows.append(row)
        if self.d4_path is not None:
            self.d4_path.parent.mkdir(parents=True, exist_ok=True)
            with self.d4_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
