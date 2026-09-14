"""P3 · Gymnasium wrapper around the simulator (P5-1 … P5-4).

The same event loop M6 runs, exposed so Stable-Baselines3 can drive it. Two
properties matter more than the rest:

**Masking, not penalising.** Illegal actions are removed from the agent's reach
rather than punished after the fact, and the mask is enforced **inside** ``step``
as well as exposed through ``action_masks()``. An agent that ignores the mask —
or a random agent that never saw it — still cannot violate a ledger rule or
starve an order. That is what makes invariants I1 and I2 structural rather than
learned, and why S2 is achieved by construction.

**No inclusion-failure penalty.** A submitted transaction is not rejected for
being late; it waits in the mempool. Penalising a non-existent event would teach
the agent a false model of its environment (ADR-004).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces

from batcher.build.estimator import (
    flat_component_lovelace,
    max_n_satisfying_gate_a,
)
from batcher.config.params import ACTION_BUCKETS, D_MAX, QUEUE_CAP, TTL_SLOTS
from batcher.config.protocol import MAX_BLOCK_EX_MEM
from batcher.queue.manager import OrderQueue
from batcher.sim.env import SettledOrder, _block_usage, _settle
from batcher.sim.mempool import ConstantProductPool, InFlight, build_in_flight
from batcher.sim.orders import ArrivalProcess, OrderStream

STATE_DIM = 11
WAIT_ACTION = 0
N_MAX_REFERENCE = 40  # normalisation ceiling for gate_a_max_n, not a ledger limit
SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class RewardWeights:
    """Applied **after** each term is normalised to unit scale (P5-5).

    Raw, the cost term spans ~0.07–0.30 ADA while latency spans tens to hundreds
    of slots, so cost would be numerically invisible and the agent would optimise
    latency alone while appearing to trade off. The normalisers below are measured
    on a reference episode and recorded in the run manifest.
    """

    cost: float = 1.0
    latency: float = 1.0
    slip: float = 1.0
    lock: float = 1.0

    # Unit-scale normalisers, measured on a reference episode.
    cost_norm: float = 1.0
    latency_norm: float = 1.0
    slip_norm: float = 1.0
    lock_norm: float = 1.0

    def as_dict(self) -> dict:
        return {
            "w_cost": self.cost,
            "w_latency": self.latency,
            "w_slip": self.slip,
            "w_lock": self.lock,
            "cost_norm": self.cost_norm,
            "latency_norm": self.latency_norm,
            "slip_norm": self.slip_norm,
            "lock_norm": self.lock_norm,
        }


class BatchingEnv(gym.Env):
    """One episode is one replayed D1 window."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        blocks: pd.DataFrame,
        process: ArrivalProcess,
        *,
        forecaster=None,
        weights: RewardWeights | None = None,
        rate_multiplier: float = 1.0,
        d_max: int = D_MAX,
        ttl_slots: int = TTL_SLOTS,
        latency_power: int = 2,
        seed: int | None = None,
    ):
        """``latency_power`` is 2 as specified; ablation A4 sets it to 1 to ask
        whether the quadratic tail penalty is what does the work."""
        super().__init__()
        if latency_power not in (1, 2):
            raise ValueError("latency_power must be 1 (A4) or 2 (specified)")
        self.latency_power = latency_power
        self.blocks = blocks.reset_index(drop=True)
        self.process = process
        self.forecaster = forecaster
        self.weights = weights or RewardWeights()
        self.rate_multiplier = rate_multiplier
        self.d_max = d_max
        self.ttl_slots = ttl_slots
        self._seed = seed

        self.observation_space = spaces.Box(0.0, 1.0, shape=(STATE_DIM,), dtype=np.float32)
        self.action_space = spaces.Discrete(len(ACTION_BUCKETS) + 2)  # WAIT, buckets, n_max

        self.settled: list[SettledOrder] = []
        self.mask_hits = 0
        self.actions_taken: list[int] = []

    # --- gymnasium API -------------------------------------------------------

    def reset(self, *, seed: int | None = None, options=None):
        super().reset(seed=seed)
        effective = seed if seed is not None else self._seed
        self.rng = np.random.default_rng(effective)
        self.stream = OrderStream(
            self.process,
            np.random.default_rng(effective),
            rate_multiplier=self.rate_multiplier,
            episode_id="rl",
        )

        self.queue = OrderQueue()
        self.pool = ConstantProductPool()
        self.in_flight: InFlight | None = None
        self.index = 0
        self.previous_slot = int(self.blocks.iloc[0]["abs_slot"]) - 1
        self.arrival_prices: dict[str, float] = {}
        self.settled = []
        self.mask_hits = 0
        self.actions_taken = []
        self.submissions: list[int] = []
        self.fees: list[int] = []
        self.locked_slots = 0
        self.total_slots = 0
        self.orders_arrived = 0
        self.fills: list[float] = []

        self._seek_decision()
        return self._state(), {}

    def step(self, action: int):
        action = int(action)
        mask = self.action_masks()

        # Enforced here as well as exposed: an agent that ignores the mask still
        # cannot act illegally.
        if not mask[action]:
            self.mask_hits += 1
            action = int(np.argmax(mask))

        self.actions_taken.append(action)
        n = self._action_to_n(action)

        settled_before = len(self.settled)

        if n > 0:
            taken = self.queue.take(n)
            self.in_flight = build_in_flight(taken, self.current_slot, self.ttl_slots)
            self.submissions.append(len(taken))
            self.fees.append(self.in_flight.fee)

        # The decision for this block is made; move past it before looking for
        # the next decision point, or the episode never advances on WAIT.
        self.index += 1
        locked_slots = self._seek_decision()
        self.locked_slots += locked_slots

        reward = self._reward(settled_before, locked_slots, n)
        terminated = self.index >= len(self.blocks)
        return self._state(), reward, terminated, False, {"mask_hits": self.mask_hits}

    def action_masks(self) -> np.ndarray:
        """Legal actions. The three rules of ``docs/06-ML-SPEC.md`` §5, verbatim."""
        mask = np.zeros(self.action_space.n, dtype=bool)

        if self.index >= len(self.blocks):
            mask[WAIT_ACTION] = True
            return mask

        gate_a_max = self._gate_a_max()
        forced = self.queue and self.queue.oldest_wait(self.current_slot) >= self.d_max

        # WAIT is legal unless the deadline has passed with orders available.
        if not (forced and gate_a_max > 0):
            mask[WAIT_ACTION] = True

        for index, n in enumerate(self._buckets(), start=1):
            if 0 < n <= gate_a_max:
                mask[index] = True

        if not mask.any():  # nothing feasible: waiting is the only option
            mask[WAIT_ACTION] = True
        return mask

    # --- internals -----------------------------------------------------------

    def _buckets(self) -> list[int]:
        return [*ACTION_BUCKETS, self._gate_a_max()]

    def _action_to_n(self, action: int) -> int:
        if action == WAIT_ACTION:
            return 0
        return min(self._buckets()[action - 1], self._gate_a_max())

    def _gate_a_max(self) -> int:
        sizes, mems, steps = self.queue.dimensions()
        return max_n_satisfying_gate_a(sizes, mems, steps)

    @property
    def current_slot(self) -> int:
        row = self.blocks.iloc[min(self.index, len(self.blocks) - 1)]
        return int(row["abs_slot"])

    def _seek_decision(self) -> int:
        """Advance from the current block until a decision exists.

        Returns the slots spent with the pool locked along the way, which is the
        head-of-line cost the reward charges for. The episode ends when the
        window runs out.
        """
        locked_slots = 0

        while self.index < len(self.blocks):
            locked, decidable = self._process_block()
            locked_slots += locked
            if decidable:
                return locked_slots
            self.index += 1

        return locked_slots

    def _process_block(self) -> tuple[int, bool]:
        """Admit arrivals and resolve any in-flight batch at the current block.

        Returns ``(locked_slots, decision_available)``. No decision exists while
        a batch holds the pool — that is the mechanism, not a special case.
        """
        block = self.blocks.iloc[self.index]
        slot = int(block["abs_slot"])
        locked_slots = 0

        self.total_slots += max(0, slot - self.previous_slot)
        self.fills.append(float(block["fill_pct"]))

        arriving = self.stream.arrivals(self.previous_slot, slot, block["block_time"].hour)
        for order in arriving:
            self.arrival_prices[order.order_id] = self.pool.price
        self.queue.admit(arriving)
        self.orders_arrived += len(arriving)
        self.queue.evict_expired(slot)

        decidable = True
        if self.in_flight is not None:
            locked_slots = max(0, slot - self.previous_slot)
            if self._fits(block):
                _settle(
                    _EpisodeShim(self.settled),
                    self.pool,
                    self.in_flight,
                    slot,
                    self.arrival_prices,
                )
                self.in_flight = None
            elif self.in_flight.ttl_slot < slot:
                self.queue.give_back(self.in_flight.orders)
                self.in_flight = None
            else:
                decidable = False

        self.previous_slot = slot
        return locked_slots, decidable

    def to_episode_result(self):
        """Convert to the simulator's result type so the *same* metrics apply.

        The RL return is a weighted penalty in reward units and is not comparable
        to P2's numbers. Scoring the agent through this path is what makes a
        P3-against-P2 claim mean anything.
        """
        from batcher.sim.env import EpisodeResult

        still_queued = list(self.queue.orders)
        if self.in_flight is not None:
            still_queued.extend(self.in_flight.orders)

        return EpisodeResult(
            settled=list(self.settled),
            expired=list(self.queue.expired),
            still_queued=still_queued,
            submissions=list(self.submissions),
            fees=list(self.fees),
            locked_slots=self.locked_slots,
            total_slots=self.total_slots,
            orders_arrived=self.orders_arrived,
        )

    def _fits(self, block) -> bool:
        from batcher.build.estimator import gate_b

        size, mem, steps = _block_usage(_Row(block))
        return gate_b(
            self.in_flight.n,
            size,
            mem,
            steps,
            [o.size_bytes for o in self.in_flight.orders],
            [o.mem_exunits for o in self.in_flight.orders],
            [o.step_exunits for o in self.in_flight.orders],
        )

    def _state(self) -> np.ndarray:
        if self.index >= len(self.blocks):
            return np.zeros(STATE_DIM, dtype=np.float32)

        block = self.blocks.iloc[self.index]
        slot = int(block["abs_slot"])
        waits = self.queue.waits(slot)
        fill_hat = self._forecast(block)
        _, block_mem, _ = _block_usage(_Row(block))

        seconds = block["block_time"].hour * 3600 + block["block_time"].minute * 60
        angle = 2 * np.pi * seconds / SECONDS_PER_DAY

        state = np.array(
            [
                len(self.queue) / QUEUE_CAP,
                self.queue.oldest_wait(slot) / self.d_max,
                (np.mean(waits) if waits else 0.0) / self.d_max,
                fill_hat[0],
                fill_hat[1],
                fill_hat[2],
                (MAX_BLOCK_EX_MEM - block_mem) / MAX_BLOCK_EX_MEM,
                self._gate_a_max() / N_MAX_REFERENCE,
                1.0 if self.in_flight is not None else 0.0,
                0.0,
                (np.sin(angle) + 1) / 2,
            ],
            dtype=np.float32,
        )
        return np.clip(state, 0.0, 1.0)

    def _forecast(self, block) -> tuple[float, float, float]:
        if self.forecaster is None:
            return (0.0, 0.0, 0.0)
        values = self.forecaster.predict(_Row(block))
        return tuple(list(values)[:3]) if len(values) >= 3 else (values[0], values[0], values[0])

    def _reward(self, settled_before: int, locked_slots: int, n: int) -> float:
        weights = self.weights
        newly = self.settled[settled_before:]

        # Only the flat fee amortizes; the marginal component is constant per
        # order and would add a constant that dilutes the gradient.
        cost = flat_component_lovelace() / n if n > 0 else 0.0
        latency = sum(order.latency**self.latency_power for order in newly)
        slip = sum(order.slippage for order in newly)

        penalty = (
            weights.cost * cost / weights.cost_norm
            + weights.latency * latency / weights.latency_norm
            + weights.slip * slip / weights.slip_norm
            + weights.lock * locked_slots / weights.lock_norm
        )
        return float(-penalty)


@dataclass
class _EpisodeShim:
    """Minimal stand-in so the settlement path is shared with the simulator."""

    settled: list


class _Row:
    """Adapts a pandas Series to the attribute access the simulator helpers use."""

    def __init__(self, series):
        self._series = series

    def __getattr__(self, name):
        return self._series[name]


def calibrate_weights(env_factory, episodes: int = 3, seed: int = 0) -> RewardWeights:
    """Measure each reward term's natural scale, then normalise it to unit size.

    T-L4. Without this the latency term dominates by orders of magnitude and the
    agent optimises one objective while appearing to trade off four.
    """
    totals = {"cost": 0.0, "latency": 0.0, "slip": 0.0, "lock": 0.0}

    for index in range(episodes):
        env = env_factory(seed + index)
        env.reset(seed=seed + index)
        raw = RewardWeights()
        env.weights = raw

        terminated = False
        while not terminated:
            mask = env.action_masks()
            action = int(np.argmax(mask[1:]) + 1) if mask[1:].any() else WAIT_ACTION
            before = len(env.settled)
            n = env._action_to_n(action)
            _, _, terminated, _, _ = env.step(action)

            newly = env.settled[before:]
            totals["cost"] += flat_component_lovelace() / n if n > 0 else 0.0
            # Normalise the latency term the env will actually charge, so A4's
            # linear penalty is calibrated to unit scale like the quadratic one.
            totals["latency"] += sum(o.latency**env.latency_power for o in newly)
            totals["slip"] += sum(o.slippage for o in newly)
        totals["lock"] += 1.0

    return replace(
        RewardWeights(),
        cost_norm=max(totals["cost"] / episodes, 1e-9),
        latency_norm=max(totals["latency"] / episodes, 1e-9),
        slip_norm=max(totals["slip"] / episodes, 1e-9),
        lock_norm=max(totals["lock"], 1e-9),
    )
