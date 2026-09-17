"""M6 · The discrete-event simulator.

The clock is the **recorded slot sequence**, never a fixed 20-second tick. Block
intervals on Cardano are geometric with a 20 s mean and range from seconds to
over a minute; a fixed tick systematically understates tail latency, which is
precisely the metric this project claims to improve (ADR-007).

Three structural rules are enforced **here, not in the policy**:

1. while the pool is locked, the only legal action is WAIT;
2. once ``oldest_wait >= D_MAX``, WAIT is masked and submission is forced;
3. any proposed ``n`` is clamped to the Gate A maximum.

A learned agent must be structurally incapable of violating a ledger rule or
starving a user. Success metric S2 is therefore achieved by construction rather
than by training.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from batcher.build.estimator import (
    gate_b,
    max_n_satisfying_gate_a,
)
from batcher.config.params import D_MAX, TTL_SLOTS
from batcher.config.protocol import MAX_BLOCK_EX_MEM, MAX_BLOCK_EX_STEPS, MAX_BLOCK_SIZE
from batcher.policy.base import Action, Observation, Policy
from batcher.queue.manager import Order, OrderQueue
from batcher.sim.mempool import ConstantProductPool, InFlight, Resolution, build_in_flight
from batcher.sim.orders import OrderStream

ROLLBACK_PROBABILITY = 0.0005  # assumption A6: rare and independent


@dataclass
class SettledOrder:
    order_id: str
    arrival_slot: int
    confirm_slot: int
    fee_share: float
    slippage: float

    @property
    def latency(self) -> int:
        return self.confirm_slot - self.arrival_slot


@dataclass
class EpisodeResult:
    settled: list[SettledOrder] = field(default_factory=list)
    expired: list[Order] = field(default_factory=list)
    still_queued: list[Order] = field(default_factory=list)
    submissions: list[int] = field(default_factory=list)
    fees: list[int] = field(default_factory=list)
    locked_slots: int = 0
    total_slots: int = 0
    gate_a_violations: int = 0
    rollbacks: int = 0
    orders_arrived: int = 0
    decisions: list[dict] = field(default_factory=list)

    def decision_log(self) -> pd.DataFrame:
        return pd.DataFrame(self.decisions)


def _block_usage(block) -> tuple[int, int, int]:
    """Recorded block usage. Execution units are null outside the sampled window;
    treating a null as 0 would make the block look empty (ADR-005), so the size
    dimension carries the load and the execution dimensions are scaled from it."""
    size = int(block.block_size)
    if pd.notna(getattr(block, "mem_exunits", None)):
        return size, int(block.mem_exunits), int(block.step_exunits)

    fill = size / MAX_BLOCK_SIZE
    return size, int(fill * MAX_BLOCK_EX_MEM), int(fill * MAX_BLOCK_EX_STEPS)


def run_episode(
    blocks: pd.DataFrame,
    policy: Policy,
    stream: OrderStream,
    rng: np.random.Generator,
    *,
    forecaster=None,
    d_max: int = D_MAX,
    ttl_slots: int = TTL_SLOTS,
    episode_id: str = "ep",
    policy_name: str | None = None,
    chain_depth: int = 1,
) -> EpisodeResult:
    """Replay ``blocks`` against ``policy``. Deterministic given ``rng``.

    ``chain_depth`` is how many batches may be pending at once. At the default of 1
    the pool is locked until its batch resolves, exactly as every recorded result
    was produced. Above 1 the batcher **chains**: a new batch spends the pool output
    of the batch still in the mempool, so at one decision point it can stack further
    batches while orders remain. Chained batches resolve strictly in order — a child
    can land in the same block as its parent, never before it — they must fit the
    block together, and a parent that is rolled back or expires takes every batch
    built on it down too.
    """
    if chain_depth < 1:
        raise ValueError("chain_depth must be at least 1")
    queue = OrderQueue()
    pool = ConstantProductPool()
    result = EpisodeResult()

    chain: list[InFlight] = []
    previous_slot = int(blocks.iloc[0]["abs_slot"]) - 1
    arrival_prices: dict[str, float] = {}

    for block in blocks.itertuples():
        slot = int(block.abs_slot)
        result.total_slots += max(0, slot - previous_slot)

        # 1. arrivals and expiry
        hour = block.block_time.hour
        arriving = stream.arrivals(previous_slot, slot, hour)
        for order in arriving:
            arrival_prices[order.order_id] = pool.price
        queue.admit(arriving)
        result.orders_arrived += len(arriving)
        queue.evict_expired(slot)

        block_size, block_mem, block_steps = _block_usage(block)

        # 2. resolve pending batches against the REAL recorded block, parent first
        if chain:
            result.locked_slots += max(0, slot - previous_slot)
            used_size, used_mem, used_steps = block_size, block_mem, block_steps
            while chain:
                batch = chain[0]
                batch.blocks_waited += 1
                if gate_b(
                    batch.n,
                    used_size,
                    used_mem,
                    used_steps,
                    [o.size_bytes for o in batch.orders],
                    [o.mem_exunits for o in batch.orders],
                    [o.step_exunits for o in batch.orders],
                ):
                    if rng.random() < ROLLBACK_PROBABILITY:
                        # Undoing a parent invalidates every batch chained on it.
                        for undone in reversed(chain):
                            queue.give_back(undone.orders)
                        chain.clear()
                        result.rollbacks += 1
                        _log(
                            result,
                            block,
                            policy_name,
                            episode_id,
                            queue,
                            None,
                            slot,
                            locked=True,
                            resolution=Resolution.ROLLED_BACK.value,
                        )
                        break
                    _settle(result, pool, batch, slot, arrival_prices)
                    chain.pop(0)
                    # A child landing in this same block shares its remaining space.
                    used_size += batch.size
                    used_mem += batch.mem
                    used_steps += batch.steps
                elif batch.ttl_slot < slot:
                    for undone in reversed(chain):
                        queue.give_back(undone.orders)
                    chain.clear()
                    _log(
                        result,
                        block,
                        policy_name,
                        episode_id,
                        queue,
                        None,
                        slot,
                        locked=True,
                        resolution=Resolution.EXPIRED.value,
                    )
                    break
                else:
                    break
            if len(chain) >= chain_depth:
                # Head-of-line blocking: no decision exists while the pool is held.
                _log(result, block, policy_name, episode_id, queue, None, slot, locked=True)
                previous_slot = slot
                continue

        # 3. forecast
        fill_hat = forecaster.predict(block) if forecaster is not None else (0.0, 0.0, 0.0)

        # 4-5. observe, decide, then repair the decision structurally. With chaining the
        #      batcher asks again while it can still stack a batch and orders remain; at
        #      chain_depth 1 the policy is asked exactly once per block.
        while True:
            sizes, mems, steps = queue.dimensions()
            gate_a_max = max_n_satisfying_gate_a(sizes, mems, steps)
            obs = Observation(
                slot=slot,
                queue_depth=len(queue),
                oldest_wait=queue.oldest_wait(slot),
                queue_sizes=sizes,
                queue_mem=mems,
                queue_steps=steps,
                fill_hat=tuple(fill_hat),
                mem_headroom=MAX_BLOCK_EX_MEM - block_mem,
                step_headroom=MAX_BLOCK_EX_STEPS - block_steps,
                pool_locked=False,
                slots_in_flight=0,
                gate_a_max_n=gate_a_max,
            )

            action = policy.decide(obs)
            action = _enforce(action, obs, d_max)
            submitted = action.submit and action.n > 0

            if submitted:
                taken = queue.take(action.n)
                batch = build_in_flight(taken, slot, ttl_slots)
                chain.append(batch)
                result.submissions.append(len(taken))
                result.fees.append(batch.fee)

            _log(result, block, policy_name, episode_id, queue, action, slot, locked=False, obs=obs)
            if not submitted or len(chain) >= chain_depth or len(queue) == 0:
                break
        previous_slot = slot

    result.still_queued = list(queue.orders)
    result.expired = list(queue.expired)
    for batch in chain:
        result.still_queued.extend(batch.orders)
    return result


def _enforce(action: Action, obs: Observation, d_max: int) -> Action:
    """Rules 2 and 3. A policy cannot express an infeasible or starving action."""
    forced = obs.queue_depth > 0 and obs.oldest_wait >= d_max

    if not action.submit and not forced:
        return action
    if obs.queue_depth == 0 or obs.gate_a_max_n == 0:
        return Action(submit=False)

    n = action.n if action.submit else obs.gate_a_max_n
    return Action(submit=True, n=max(1, min(n, obs.gate_a_max_n)))


def _settle(result, pool, in_flight, slot, arrival_prices) -> None:
    fee_share = in_flight.fee / in_flight.n
    for order in in_flight.orders:
        before = arrival_prices.get(order.order_id, pool.price)
        pool.execute(order.amount_in)
        drift = abs(pool.price - before) / before if before else 0.0
        result.settled.append(
            SettledOrder(
                order_id=order.order_id,
                arrival_slot=order.arrival_slot,
                confirm_slot=slot,
                fee_share=fee_share,
                slippage=drift,
            )
        )


def _log(
    result,
    block,
    policy_name,
    episode_id,
    queue,
    action,
    slot,
    *,
    locked,
    obs=None,
    resolution=None,
) -> None:
    # D3 records what the policy *saw*, not the queue left behind after its
    # action. Logging the post-action depth makes every SUBMIT row look like it
    # decided on an empty queue, which silently defeats the I2 deadline check.
    result.decisions.append(
        {
            "episode_id": episode_id,
            "policy": policy_name,
            "abs_slot": slot,
            "queue_depth": obs.queue_depth if obs is not None else len(queue),
            "oldest_wait": obs.oldest_wait if obs is not None else queue.oldest_wait(slot),
            "fill_actual": float(block.fill_pct),
            "fill_hat": float(obs.fill_hat[0]) if obs is not None and obs.fill_hat else None,
            "pool_locked": locked,
            "action": "WAIT" if action is None or not action.submit else "SUBMIT",
            "n": 0 if action is None or not action.submit else action.n,
            "gate_a_max_n": obs.gate_a_max_n if obs is not None else None,
            "resolution": resolution,
        }
    )
