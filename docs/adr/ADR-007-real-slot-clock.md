# ADR-007 · The simulator advances on recorded slots, not a fixed 20-second tick

**Status:** Accepted · **Supersedes:** the fixed-interval stepping described in the earlier design

## Context

The earlier simulator design stepped forward "one block-slot (~20 s) at a time," treating Cardano block production as a regular 20-second tick.

Cardano block production is stochastic. Slots are **1 second** and the active slot coefficient is **f = 0.05**, so each slot produces a block with probability 0.05. Inter-block gaps are geometrically distributed with a *mean* of 20 seconds. In practice gaps of 3 seconds and gaps of 90 seconds both occur regularly.

A fixed tick therefore misrepresents the environment in a way that runs directly against the project's headline metric. Latency is measured in real time; if every gap is assumed to be exactly 20 seconds, the long gaps that dominate tail latency disappear. **The simulator would systematically understate p95 latency — the very number the project claims to improve.**

There is also a second-order effect: long gaps and fuller blocks are correlated, since more transactions accumulate while no block is produced. A fixed tick erases that correlation, which is exactly the kind of signal the forecaster exists to exploit.

## Decision

The simulator clock is the **recorded `abs_slot` sequence from D1**. The loop iterates over real blocks in recorded order, and all durations are computed from real slot differences.

`slot_gap` is stored as a D1 column and is available as a forecaster feature.

## Consequences

**Positive**
- Latency metrics, particularly p95 and worst-case wait, are honest
- No extra work: the slot numbers are already collected, and using them is simpler than generating a synthetic clock
- The forecaster gains a genuinely predictive feature. Long recent gaps signal accumulated pending load
- Head-of-line blocking is measured in real elapsed time rather than in ticks, so the pool-lock cost of `ADR-004` is quantified correctly

**Negative**
- Episodes contain a variable number of steps rather than a fixed count. RL episode lengths vary, so returns must be normalised by episode length or the agent learns to prefer short episodes
- Metrics are reported in slots (seconds), not in "blocks", which is slightly less intuitive but far more accurate

**Regression guard**

Test **T-S6** asserts that episode duration matches the recorded `abs_slot` span and **not** `4300 * 20 s`. This is the direct guard against reintroducing a fixed tick.

## Note

This correction only becomes visible when tail latency is measured. Under mean latency alone, a fixed 20-second tick gives roughly the right answer — which is precisely why it survives unnoticed in designs that only report averages. The project reports p95 as its headline metric, so it does not have that luxury.
