"""P7-8 · The live batcher: the simulator's control loop, pointed at preprod.

One iteration per new block, in the order ``docs/03-ARCHITECTURE.md`` §4 fixes:

1. if a batch is in flight, resolve it — included, expired, or still waiting;
2. **while the pool is locked, no decision exists** (head-of-line blocking);
3. otherwise read the queue and the pool, observe, decide, and repair the decision
   with the *simulator's own* structural rules (``sim.env._enforce``: submission
   forced past ``D_MAX``, ``n`` clamped to Gate A);
4. build the batch, submit it, and hold the pool lock until it resolves.

**Shadow mode** (the default) does all of that except submit: it reads preprod,
decides, and builds and signs the exact transaction it would send, then logs it.
It is how a policy is watched on live traffic before it is trusted with the key.

**Shutdown** is only clean when the pool is free. A stop request while a batch is
in flight keeps the loop polling until that batch is included or expires, and no
new batch is started in the meantime (runbook §7.2).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from pycardano import PaymentSigningKey

from batcher.build.estimator import block_usage_from_fill, max_n_satisfying_gate_a
from batcher.build.submitter import GateAViolation
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
from batcher.onchain.blueprint import CompiledValidator
from batcher.onchain.deployment import Deployment, addresses
from batcher.policy.base import Action, Observation, Outcome, Policy
from batcher.sim.env import _enforce as enforce  # the simulator's rules, not a copy


@dataclass(frozen=True)
class InFlightBatch:
    tx_id: str
    submit_slot: int
    ttl_slot: int
    built: BuiltBatch
    pool_ref: tuple[str, int]


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
        emit: Callable[[dict], None] | None = None,
        d4_path: Path | None = None,
    ):
        self.chain = chain
        self.policy = policy
        self.deployment = deployment
        self.scripts = scripts
        self.batcher_skey = batcher_skey
        self.submit = submit
        self.d_max = d_max
        self.ttl_slots = ttl_slots
        self.emit = emit or (lambda record: None)
        self.d4_path = d4_path

        self.order_address, self.pool_address = addresses(deployment, chain.context.network)
        self.forecaster = MovingAverage(horizon=FORECAST_HORIZON)

        self.last_height: int | None = None
        self.in_flight: InFlightBatch | None = None
        self.consumed_pool_ref: tuple[str, int] | None = None
        self.stop_requested = False
        self.records: list[dict] = []
        self.d4_rows: list[dict] = []
        self._arrivals: dict[str, int] = {}

    @property
    def pool_locked(self) -> bool:
        return self.in_flight is not None

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
            if self.step():
                blocks += 1
                if max_blocks is not None and blocks >= max_blocks:
                    self.request_stop()
            if self.stop_requested and not self.pool_locked:
                return blocks
            sleep(poll_seconds)

    def step(self) -> list[dict]:
        """Process the newest block once. Returns its records; empty if it is not new."""
        tip = self.chain.tip()
        if tip.height == self.last_height:
            return []
        self.last_height = tip.height

        produced = []
        if self.in_flight is not None:
            batch = self.in_flight
            resolution = self._resolve(tip, batch)
            produced.append(
                self._record(tip, locked=True, tx_id=batch.tx_id, resolution=resolution)
            )
            if self.in_flight is not None:
                return self._publish(produced)  # head-of-line: no decision this block

        produced.append(self._decide(tip))
        return self._publish(produced)

    # --- resolving a batch in flight ------------------------------------------------------------

    def _resolve(self, tip: Tip, batch: InFlightBatch) -> str:
        confirm = self.chain.inclusion_slot(batch.tx_id)
        if confirm is not None:
            outcome = "included"
        elif tip.slot > batch.ttl_slot:
            outcome = "expired"
        else:
            return "locked"

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
        self.consumed_pool_ref = None

        queue = self._queue()
        obs = self._observe(tip, queue)
        action = enforce(self.policy.decide(obs), obs, self.d_max)
        if not action.submit or action.n == 0:
            return self._record(tip, obs=obs, action=action, resolution="wait")

        try:
            built = build_batch_tx(
                self.chain.context,
                self.batcher_skey,
                self.deployment,
                self.scripts,
                pool,
                queue[: action.n],
                self.ttl_slots,
            )
        except GateAViolation:
            raise  # a defect: stop the daemon rather than trade around it
        except NothingToBatch:
            return self._record(tip, obs=obs, action=action, resolution="unfillable")

        if not self.submit:
            return self._record(tip, obs=obs, action=action, built=built, resolution="shadow")

        try:
            tx_id = self.chain.submit(built.transaction)
        except Exception as error:  # mempool rejection, script failure: counted, not fatal
            self._write_d4(d4_row(built, tip.slot, "rejected", None))
            return self._record(
                tip,
                obs=obs,
                action=action,
                built=built,
                resolution="rejected",
                error=f"{type(error).__name__}: {error}",
            )

        self.in_flight = InFlightBatch(tx_id, tip.slot, built.ttl_slot, built, pool_ref)
        return self._record(
            tip, obs=obs, action=action, built=built, tx_id=tx_id, resolution="submitted"
        )

    def _queue(self):
        """Orders on chain, oldest first: FIFO by the slot their order was placed."""
        queue = read_orders(
            self.chain.utxos(self.order_address), self.deployment, self.chain.context.network
        )
        for _, order in queue:
            if order.tx_hash not in self._arrivals:
                self._arrivals[order.tx_hash] = self.chain.arrival_slot(order.tx_hash)
        return sorted(
            queue,
            key=lambda item: (self._arrivals[item[1].tx_hash], item[1].tx_hash, item[1].index),
        )

    def _observe(self, tip: Tip, queue) -> Observation:
        orders = [order for _, order in queue]
        sizes = tuple(o.size_bytes for o in orders)
        mems = tuple(o.mem_exunits for o in orders)
        steps = tuple(o.step_exunits for o in orders)

        # Live forecasting is E4 over recent real blocks: it needs no feature
        # history, and Phase 3 showed LightGBM adds little the policy can use.
        fills = self.chain.recent_fills(FORECAST_WINDOW_K)
        if fills:
            prediction = self.forecaster.predict_frame(pd.DataFrame({"fill_pct": fills}))[-1]
            fill_hat = tuple(float(v) for v in prediction)
        else:
            fill_hat = (0.0,) * FORECAST_HORIZON
        _, block_mem, block_steps = block_usage_from_fill(tip.fill)

        oldest = min(self._arrivals[o.tx_hash] for o in orders) if orders else tip.slot
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
            gate_a_max_n=max_n_satisfying_gate_a(sizes, mems, steps),
        )

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
        }

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
