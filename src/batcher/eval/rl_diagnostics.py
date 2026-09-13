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


def profile_by_congestion(actions, fills, batch_sizes=None, deciles: int = 10) -> dict:
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

    sizes = np.asarray(list(batch_sizes)) if batch_sizes is not None else None

    profile = {}
    for decile in range(deciles):
        selected = actions[bucket == decile]
        if len(selected) == 0:
            continue

        entry = {"submit_rate": float((selected != 0).mean()), "n": int(len(selected))}
        if sizes is not None and len(sizes) == len(actions):
            submitted = sizes[(bucket == decile) & (actions != 0)]
            entry["mean_batch_n"] = float(submitted.mean()) if len(submitted) else 0.0
        profile[decile] = entry
    return profile


def profile_trend(profile: dict) -> dict:
    """Does the submit rate actually vary with congestion, and in which direction?

    A **flat** profile means the agent ignores congestion however good the
    headline numbers look. A rising one means it submits *more* as blocks fill,
    which is the opposite of congestion avoidance and is more likely a queue-depth
    confound than a learned behaviour — ablation A3 is what separates the two.
    """
    if len(profile) < 2:
        return {"flat": True, "direction": "none", "ratio": 1.0}

    ordered = [profile[key]["submit_rate"] for key in sorted(profile, key=int)]
    low, high = ordered[0], ordered[-1]
    ratio = high / low if low > 0 else float("inf")

    return {
        "flat": bool(abs(high - low) < 0.05),
        "direction": "rising" if high > low else "falling",
        "ratio": float(ratio),
        "lowest_decile": float(low),
        "highest_decile": float(high),
    }
