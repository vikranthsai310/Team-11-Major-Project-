"""Runtime safety wrappers for any policy (Phase 8 robustness).

The simulator already makes a ledger violation or indefinite starvation
structurally impossible (``batcher.sim.env._enforce``). What it does not do is
keep a policy *sensible* outside the conditions it was built for:

* a learned agent sees queue depth normalised by ``QUEUE_CAP`` and the oldest wait
  normalised by ``D_MAX``, both clipped to 1. Past those ceilings its inputs
  saturate and it is extrapolating from states it never trained on;
* ``D_MAX`` is enforced only at the first decision point *after* it is missed, so
  a long block gap or a full block lets waits overshoot it.

:class:`ShieldedPolicy` addresses the first by delegating out-of-distribution
states to an explainable fallback (normally P2). :class:`DeadlineAwarePolicy`
addresses the second by submitting *before* the deadline, using block gaps and
confirmation delays it has itself observed — never future data.

Both are opt-in wrappers: nothing that produced a recorded result uses them.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from batcher.build.estimator import (
    block_usage_from_fill,
    max_n_satisfying_gate_a,
    max_n_satisfying_gate_b,
)
from batcher.config.params import D_MAX, QUEUE_CAP
from batcher.policy.base import Action, Observation, Outcome, Policy

# Oldest-wait share of D_MAX past which the RL state is treated as out of
# distribution. The agent trained at the matched rate, where waits this close to
# the deadline are rare; the environment forces submission at 1.0 anyway.
OOD_WAIT_SHARE = 0.8

# Before anything has been observed: Cardano block intervals are roughly
# geometric with a 20 s (= 20 slot) mean, whose 90th percentile is ~46 slots. A
# batch confirms at the earliest one block later, so the same prior serves both.
PRIOR_GAP_SLOTS = 46
PRIOR_CONFIRM_SLOTS = 46


def _gate_a_max(obs: Observation) -> int:
    if obs.gate_a_max_n:
        return obs.gate_a_max_n
    if not obs.queue_sizes:
        return 0
    return max_n_satisfying_gate_a(obs.queue_sizes, obs.queue_mem, obs.queue_steps)


def _clamp(action: Action, obs: Observation) -> Action:
    """Never express a Gate A violation, whatever the wrapped policy proposed."""
    if not action.submit:
        return action
    ceiling = _gate_a_max(obs)
    if ceiling == 0 or obs.queue_depth == 0:
        return Action(submit=False)
    return Action(submit=True, n=max(1, min(action.n, ceiling)))


class ShieldedPolicy:
    """Wrap ``inner`` so forced and out-of-distribution states are handled safely.

    1. **Forced submission** — queue non-empty and ``oldest_wait >= d_max``: submit
       the Gate A maximum, whatever ``inner`` wants. This mirrors the simulator's
       ``_enforce`` so a wrapped agent cannot drain a starving queue one order at
       a time.
    2. **Out of distribution** — ``queue_depth > max_queue_depth`` or
       ``oldest_wait >= max_oldest_wait``: the decision is delegated to
       ``fallback``. Defaults are the RL normalisation ceilings.

    Counters: ``decisions``, ``forced_overrides`` and ``ood_delegations``;
    ``interventions`` is their sum excluding plain decisions.
    """

    def __init__(
        self,
        inner: Policy,
        fallback: Policy,
        *,
        d_max: int = D_MAX,
        max_queue_depth: int = QUEUE_CAP,
        max_oldest_wait: float | None = None,
        name: str | None = None,
    ):
        self.inner = inner
        self.fallback = fallback
        self.d_max = d_max
        self.max_queue_depth = max_queue_depth
        self.max_oldest_wait = (
            OOD_WAIT_SHARE * d_max if max_oldest_wait is None else max_oldest_wait
        )
        self.name = name or f"shield({getattr(inner, 'name', 'policy')})"
        self.reset_counters()

    def reset_counters(self) -> None:
        self.decisions = 0
        self.forced_overrides = 0
        self.ood_delegations = 0

    @property
    def interventions(self) -> int:
        return self.forced_overrides + self.ood_delegations

    def counters(self) -> dict[str, int]:
        return {
            "decisions": self.decisions,
            "forced_overrides": self.forced_overrides,
            "ood_delegations": self.ood_delegations,
            "interventions": self.interventions,
        }

    def reset(self) -> None:
        self.reset_counters()
        for policy in (self.inner, self.fallback):
            if hasattr(policy, "reset"):
                policy.reset()

    def is_out_of_distribution(self, obs: Observation) -> bool:
        return obs.queue_depth > self.max_queue_depth or obs.oldest_wait >= self.max_oldest_wait

    def decide(self, obs: Observation) -> Action:
        self.decisions += 1
        if obs.pool_locked:
            return Action(submit=False)

        if obs.queue_depth > 0 and obs.oldest_wait >= self.d_max:
            ceiling = _gate_a_max(obs)
            if ceiling > 0:
                self.forced_overrides += 1
                return Action(submit=True, n=ceiling)

        if self.is_out_of_distribution(obs):
            self.ood_delegations += 1
            return _clamp(self.fallback.decide(obs), obs)
        return _clamp(self.inner.decide(obs), obs)

    def observe_outcome(self, outcome: Outcome) -> None:
        for policy in (self.inner, self.fallback):
            if hasattr(policy, "observe_outcome"):
                policy.observe_outcome(outcome)


class DeadlineAwarePolicy:
    """Submit before ``D_MAX`` is missed rather than after.

    From consecutive decision slots the wrapper learns two delays online:

    * **block gap** — slots between a WAIT and the next decision;
    * **confirmation delay** — slots between a SUBMIT and the next decision, which
      is when the batch resolved (the pool is locked until then).

    Waiting one more block and then submitting confirms the oldest order at about
    ``oldest_wait + gap + confirmation``. When a high quantile (``quantile``,
    default p90) of that sum reaches ``d_max`` the wrapper submits now. Under that
    deadline pressure it sizes the batch to what is predicted to fit the next block
    (``min(gate_a, gate_b)``) instead of waiting for a fuller one. Whenever
    ``inner`` already submits, or there is no pressure, ``inner`` decides. It never
    exceeds Gate A.

    Deterministic: the estimates are quantiles over bounded windows of observed
    slots, with fixed priors until ``min_samples`` observations exist.
    """

    def __init__(
        self,
        inner: Policy,
        *,
        d_max: int = D_MAX,
        quantile: float = 0.9,
        window: int = 500,
        min_samples: int = 20,
        prior_gap: float = PRIOR_GAP_SLOTS,
        prior_confirm: float = PRIOR_CONFIRM_SLOTS,
        include_confirmation: bool = True,
        name: str | None = None,
    ):
        if not 0.0 < quantile < 1.0:
            raise ValueError("quantile must be in (0, 1)")
        self.inner = inner
        self.d_max = d_max
        self.quantile = quantile
        self.window = window
        self.min_samples = min_samples
        self.prior_gap = prior_gap
        self.prior_confirm = prior_confirm
        self.include_confirmation = include_confirmation
        self.name = name or f"deadline({getattr(inner, 'name', 'policy')})"
        self.reset()

    def reset(self) -> None:
        self.gaps: deque[int] = deque(maxlen=self.window)
        self.confirmations: deque[int] = deque(maxlen=self.window)
        self._last_slot: int | None = None
        self._last_submitted = False
        self.deadline_submissions = 0
        self.gate_b_sized = 0
        if hasattr(self.inner, "reset"):
            self.inner.reset()

    def _estimate(self, samples: deque[int], prior: float) -> float:
        if len(samples) < self.min_samples:
            return float(prior)
        return float(np.quantile(np.fromiter(samples, dtype="float64"), self.quantile))

    def expected_delay(self) -> float:
        delay = self._estimate(self.gaps, self.prior_gap)
        if self.include_confirmation:
            delay += self._estimate(self.confirmations, self.prior_confirm)
        return delay

    def _learn(self, obs: Observation) -> None:
        if self._last_slot is not None and obs.slot > self._last_slot:
            elapsed = obs.slot - self._last_slot
            (self.confirmations if self._last_submitted else self.gaps).append(elapsed)
        self._last_slot = obs.slot

    def decide(self, obs: Observation) -> Action:
        self._learn(obs)
        action = self._decide(obs)
        self._last_submitted = action.submit
        return action

    def _decide(self, obs: Observation) -> Action:
        proposed = self.inner.decide(obs)
        if obs.pool_locked or obs.queue_depth == 0:
            return Action(submit=False)

        ceiling = _gate_a_max(obs)
        if ceiling == 0:
            return Action(submit=False)

        if proposed.submit or obs.oldest_wait + self.expected_delay() < self.d_max:
            return _clamp(proposed, obs)

        self.deadline_submissions += 1
        fits = self._gate_b_max(obs, ceiling)
        if 0 < fits < ceiling:
            self.gate_b_sized += 1
            return Action(submit=True, n=fits)
        # Gate B predicts no room at all: submitting the feasible maximum still
        # queues the batch in the mempool, which is better than missing D_MAX.
        return Action(submit=True, n=ceiling)

    @staticmethod
    def _gate_b_max(obs: Observation, ceiling: int) -> int:
        fill_hat = obs.fill_hat[0] if obs.fill_hat else 0.0
        if not obs.queue_sizes:
            return ceiling
        return max_n_satisfying_gate_b(
            *block_usage_from_fill(fill_hat),
            obs.queue_sizes[:ceiling],
            obs.queue_mem[:ceiling],
            obs.queue_steps[:ceiling],
        )

    def observe_outcome(self, outcome: Outcome) -> None:
        if hasattr(self.inner, "observe_outcome"):
            self.inner.observe_outcome(outcome)
