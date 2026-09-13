"""Static baselines E1–E3, plus the NULL reference.

These are the deployed state of the art: they trigger on constants and never read
the chain. They are **tuned on the validation split**, not guessed — an untuned
baseline is a straw man and invalidates the entire comparison
(``docs/06-ML-SPEC.md`` §2).

They are subject to exactly the same structural rules as the proposed policies:
they cannot submit while the pool is locked, and they cannot exceed Gate A. The
comparison is therefore confined to the decision logic.
"""

from __future__ import annotations

from batcher.policy.base import Action, Observation, StatelessPolicy


class FixedSize(StatelessPolicy):
    """E1 — submit once the queue reaches ``M`` orders."""

    def __init__(self, m: int = 20):
        self.m = m
        self.name = f"e1(M={m})"

    def decide(self, obs: Observation) -> Action:
        if obs.queue_depth >= self.m:
            return Action(submit=True, n=min(self.m, obs.gate_a_max_n))
        return Action(submit=False)


class FixedInterval(StatelessPolicy):
    """E2 — submit every ``T`` slots, regardless of queue depth or chain state."""

    def __init__(self, t: int = 60):
        self.t = t
        self.name = f"e2(T={t})"
        self._last_submit: int | None = None

    def reset(self) -> None:
        self._last_submit = None

    def decide(self, obs: Observation) -> Action:
        if obs.queue_depth == 0:
            return Action(submit=False)
        if self._last_submit is None or obs.slot - self._last_submit >= self.t:
            self._last_submit = obs.slot
            return Action(submit=True, n=obs.gate_a_max_n)
        return Action(submit=False)


class Greedy(StatelessPolicy):
    """E3 — submit whatever is queued, immediately.

    Expected to give the **lowest latency and the highest per-user cost** of any
    policy. That shape follows directly from the cost model, and T-S3 treats its
    absence as a simulator bug rather than a result.
    """

    name = "e3(greedy)"

    def decide(self, obs: Observation) -> Action:
        if obs.queue_depth == 0:
            return Action(submit=False)
        return Action(submit=True, n=obs.gate_a_max_n)


class Null(StatelessPolicy):
    """The sanity floor: never submits voluntarily.

    The environment's deadline rule still forces submission at ``D_MAX``, so a
    NULL episode is not literally empty — it is the worst legal behaviour, which
    is the more useful floor.
    """

    name = "null"

    def decide(self, obs: Observation) -> Action:
        return Action(submit=False)
