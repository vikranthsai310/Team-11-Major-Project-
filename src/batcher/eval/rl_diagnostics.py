"""RL training diagnostics (P5-11).

**A collapsed policy is detected by the action distribution, not by the return
curve.** An agent that always waits until the mask forces it, or always submits
the maximum, can show a smooth improving return while having learned nothing
about *when* to act. That failure is common enough that the roadmap names it, so
it is measured rather than eyeballed.
"""

from __future__ import annotations

from collections import Counter

import numpy as np

# Below this, the action distribution is effectively a single choice. Chosen so
# that an always-one-action policy fails and a policy using two actions in a
# 90/10 split still passes.
COLLAPSE_FLOOR = 0.2


def action_entropy(actions) -> float:
    """Shannon entropy of the action distribution, normalised to [0, 1].

    1.0 is a uniform spread across the actions used; 0.0 is a single action
    forever.
    """
    actions = list(actions)
    if not actions:
        return 0.0

    counts = np.array(list(Counter(actions).values()), dtype="float64")
    if len(counts) < 2:
        return 0.0

    probabilities = counts / counts.sum()
    entropy = -np.sum(probabilities * np.log(probabilities))
    return float(entropy / np.log(len(probabilities)))


def has_collapsed(actions, floor: float = COLLAPSE_FLOOR) -> bool:
    return action_entropy(actions) < floor


def action_profile(actions, n_actions: int) -> dict[int, float]:
    """Share of each action, so a flat or degenerate policy is visible."""
    actions = list(actions)
    if not actions:
        return {index: 0.0 for index in range(n_actions)}
    counts = Counter(actions)
    return {index: counts.get(index, 0) / len(actions) for index in range(n_actions)}


def profile_by_congestion(actions, fills, deciles: int = 10) -> dict:
    """Submit rate against congestion decile — the basis of figure F7.

    **This is what distinguishes a learned policy from a lucky one.** A flat
    profile means the agent ignores the forecast however good the headline
    numbers look, and should be cross-checked against ablation A3.
    """
    actions = np.asarray(list(actions))
    fills = np.asarray(list(fills), dtype="float64")
    if len(actions) == 0 or len(actions) != len(fills):
        return {}

    edges = np.quantile(fills, np.linspace(0, 1, deciles + 1))
    edges[-1] += 1e-9
    bucket = np.clip(np.searchsorted(edges, fills, side="right") - 1, 0, deciles - 1)

    profile = {}
    for decile in range(deciles):
        selected = actions[bucket == decile]
        if len(selected) == 0:
            continue
        profile[decile] = {
            "submit_rate": float((selected != 0).mean()),
            "n": int(len(selected)),
        }
    return profile
