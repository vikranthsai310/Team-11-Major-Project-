"""P2 · Constrained optimizer — forecast, then optimize under the two gates.

Explainable, deterministic, and the safety net for the whole project. It exists
even if P3 wins: a review panel can follow it line by line, it cannot fail to
converge, and it is the honest comparator that separates how much of any gain
comes from *forecasting* versus from *learning* (``docs/06-ML-SPEC.md`` §4).

Note what this policy does **not** do: it never clamps for safety. Gate A
clamping, the pool lock and the starvation deadline are enforced by the
environment, so the decisions below are preferences, not permissions. Duplicating
the enforcement here would hide a bug in whichever copy was wrong.
"""

from __future__ import annotations

from batcher.build.estimator import (
    block_usage_from_fill,
    max_n_satisfying_gate_a,
    max_n_satisfying_gate_b,
)
from batcher.config.params import D_MAX, N_MIN
from batcher.policy.base import Action, Observation, StatelessPolicy


class ConstrainedOptimizer(StatelessPolicy):
    def __init__(self, d_max: int = D_MAX, n_min: int = N_MIN, horizon: int = 3):
        self.d_max = d_max
        self.n_min = n_min
        self.horizon = horizon
        self.name = f"p2(D={d_max},N={n_min})"

    def decide(self, obs: Observation) -> Action:
        if obs.pool_locked or obs.queue_depth == 0:
            return Action(submit=False)

        n_feasible = self._gate_a_max(obs)
        if n_feasible == 0:
            return Action(submit=False)

        # Fairness override: past the deadline, cost stops mattering.
        if obs.oldest_wait >= self.d_max:
            return Action(submit=True, n=n_feasible)

        n = min(n_feasible, self._gate_b_max(obs))

        if n == 0:
            return Action(submit=False)  # predicted no room
        if n < self.n_min and self._quieter_block_predicted(obs):
            return Action(submit=False)  # wait for amortization
        return Action(submit=True, n=n)

    def _gate_a_max(self, obs: Observation) -> int:
        if obs.gate_a_max_n:
            return obs.gate_a_max_n
        return max_n_satisfying_gate_a(obs.queue_sizes, obs.queue_mem, obs.queue_steps)

    def _gate_b_max(self, obs: Observation) -> int:
        """Largest batch predicted to fit in the next block.

        With no forecast the prediction is an empty block, which makes Gate B
        non-binding and leaves Gate A as the only cap — the correct degenerate
        behaviour, and the one the ORACLE and E4 variants differ from only in the
        value of ``fill_hat``.
        """
        fill_hat = obs.fill_hat[0] if obs.fill_hat else 0.0
        return max_n_satisfying_gate_b(
            *block_usage_from_fill(fill_hat),
            obs.queue_sizes,
            obs.queue_mem,
            obs.queue_steps,
        )

    def _quieter_block_predicted(self, obs: Observation) -> bool:
        """Is any block within the horizon predicted emptier than the next one?

        Waiting here cannot starve an order: the ``D_MAX`` override above fires
        first, which is why no second threshold is needed and none is added.
        """
        horizon = obs.fill_hat[: self.horizon]
        if len(horizon) < 2:
            return False
        return min(horizon[1:]) < horizon[0]


class OracleOptimizer(ConstrainedOptimizer):
    """P2 driven by the **true** next-block fill instead of a forecast (ablation A1).

    The P2→ORACLE gap is the honest measure of what forecast error costs the
    *policy*, which is more informative than MAE alone. On this dataset it is also
    the measure of how much a perfect forecast is worth at all, given Gate B binds
    about once in 180 blocks.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = f"oracle(D={self.d_max},N={self.n_min})"
