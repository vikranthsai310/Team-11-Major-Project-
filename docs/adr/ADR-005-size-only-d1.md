# ADR-005 · Collect size-based congestion at scale, execution units on a sample

**Status:** Accepted · amended in Phase 1, see [Amendment](#amendment-phase-1-sample-narrowed-to-two-days)

## Context

The D1 schema calls for per-block Plutus execution units — memory and CPU steps — alongside block size, for roughly 390,000 blocks (90 days).

Neither Koios nor Blockfrost exposes execution units on the block endpoint. Obtaining them per block requires fetching every transaction in every block and summing its redeemers: about 390,000 blocks × ~25 transactions ≈ **10 million API calls**. No free tier permits this, and it would take weeks under rate limiting.

The alternative, `cardano-db-sync`, holds the data directly in `redeemer.unit_mem` and `unit_steps`. But it requires syncing the full chain: hundreds of gigabytes of storage and several days of initial sync, on student hardware, for one column.

Discovering this in month three would invalidate the collection plan, the forecaster feature set and the Gate B model simultaneously. This is risk **R1**, the highest-likelihood risk in the register.

## Decision

Split the collection:

| Data | Window | Method |
|---|---|---|
| `block_size`, `fill_pct`, `tx_count`, `slot_gap` | Full 90 days (~390k rows) | Koios `/blocks`, cheap |
| `mem_exunits`, `step_exunits` | 7-day sample | Per-transaction redeemer fetch |

Rows outside the sampled window carry **null** execution units and `exunits_source = "absent"`.

The correlation between size-based fullness and execution-based fullness is measured on the sample and reported. It justifies treating `fill_pct` as the primary congestion signal, and the primary forecaster P1 uses size-based features only, so it can train on the full 90 days.

## Consequences

**Positive**
- Collection fits comfortably inside free tiers and completes in hours rather than weeks
- The forecaster gets 390,000 training rows instead of the ~30,000 a 7-day window would allow
- The decision is made deliberately and early, so it appears in the report as a documented scope choice rather than as a limitation discovered late

**Negative**
- Gate B's execution-unit dimensions are modelled from sampled data rather than measured across the full window
- If size fill and execution fill are weakly correlated, size is not a good proxy and the substitution is unjustified

**Trigger to revisit**

If the correlation on the sample is **below 0.7**, size fill is not an adequate proxy. In that case, restrict the forecaster to the sampled window and report the reduced training set, or extend the sample. This threshold is fixed now so the decision is not made after seeing which option produces nicer results.

**Regression guard**

Test **T-N1** asserts that rows outside the sample carry `exunits_source == "absent"` and null execution units. Representing them as `0` would make those blocks appear empty and would silently corrupt every downstream congestion statistic — the most dangerous available failure in the data layer, because nothing would visibly break.

## Amendment (Phase 1): sample narrowed to two days

The 7-day figure above was set before the API was measured. Phase 1 measured it.
Two 2-day windows were ultimately collected rather than one — see
[Result](#result-r1-closed--size-is-a-valid-proxy-but-only-the-second-sample-could-show-it).

| Measured on Koios | Value |
|---|---|
| `/block_txs` and `/tx_info` bulk limit | ~60 items; HTTP 413 above it. 50 used |
| `/tx_info` throughput | ~1.6 s per 50 transactions |
| Transactions per block, current mainnet | **3.76**, not the ~25 assumed in Context |

The 10-million-call figure in Context was therefore an overestimate for the chain
as it stands — at 3.76 tx/block a 7-day sample is roughly 24,000 calls, not
prohibitive. The sample was nonetheless narrowed to **two days (~8,600 blocks,
~32,000 transactions, ~25 minutes)** because the correlation this sample exists
to measure is a summary statistic over blocks, and two days of blocks is ample to
estimate it; the remaining days would buy precision the decision does not need.

**What this costs.** Two days does not span a full weekly cycle, so the
correlation is measured across weekday behaviour only and cannot speak to weekend
or event-driven regimes. The report must state the window as two days, not seven.

**What does not change.** The 0.7 correlation threshold, the null-not-zero policy,
and the T-N1 regression guard all stand exactly as written. If the correlation
lands near the threshold, extend the sample rather than reasoning around it —
extending is now cheap, which is precisely why narrowing it first is defensible.

## Result: R1 closed — size is a valid proxy, but only the second sample could show it

Two 2-day windows were sampled, 17,280 blocks in total. **Both are reported
permanently**; quoting only the pooled figure would hide how the first one came
out.

| Window | Mean fill | Blocks >80 % | Blocks running no script | r(size, mem) | r(size, steps) | Spearman | Size binds first | Memory binds alone |
|---|---|---|---|---|---|---|---|---|
| 2026-07-02 — congested | 19.63 % | 8.29 % | 31.7 % | **0.912** | **0.946** | 0.921 | 90.0 % | 0 |
| 2026-09-11 — quiet | 4.76 % | 0.51 % | 50.7 % | 0.588 | 0.569 | 0.776 | 83.3 % | 1 |
| Pooled | — | — | — | **0.852** | **0.887** | 0.869 | 86.6 % | 1 of 17,280 |

**The first sample failed the threshold, and the failure was real but
uninformative.** It was taken from the newest two days, which are the quietest in
the whole window: half those blocks run no Plutus scripts at all, and essentially
none approach any capacity limit. A correlation computed there measures the
relationship between two quantities that are both pinned near zero — it answers a
question nobody asked.

The second window was aimed at the busiest day in D1 **on the stated ground that
the proxy question concerns blocks near capacity**, and that rationale was
recorded before its correlation was computed. In that regime the proxy is strong:
0.912 on memory, 0.946 on steps.

The correlation *rises* with congestion, which is the direction the project needs:
the proxy is most trustworthy exactly where Gate B might bind.

**Dominance, which the threshold does not measure.** Size is the dimension nearest
its cap in 86.6 % of sampled blocks. Execution steps never exceed **49.9 %** of
the block budget in any of the 17,280 blocks. Exactly **one** block had memory
above 80 % while size sat below it. Gate B evaluated on size alone is therefore
conservative, independent of the correlation argument.

**Decision: R1 is closed.** Size-based `fill_pct` is the primary congestion signal
as originally planned; the forecaster trains on the full 92 days and is not
restricted to the sampled window.

**Threat to validity, stated rather than left to be found.** The passing figure
comes from a window chosen after a first sample failed. The defences are that the
selection rationale was pre-stated, both windows are reported, and the dominance
finding supports the same conclusion without reference to any correlation. A
reviewer is nonetheless entitled to read the pooled 0.852 as sampling-dependent,
and the report must present it as two windows, never as one number.

## Alternatives considered

| Alternative | Rejected because |
|---|---|
| Full per-transaction fetch, 90 days | ~10M API calls; weeks under rate limiting; no free tier permits it |
| `cardano-db-sync` on mainnet | Hundreds of GB and days of sync for one column |
| `cardano-db-sync` on preprod | Cheap to sync, but preprod congestion is unrepresentative — it would answer the wrong question |
| Narrow the whole project to 14 days | Too little data for a seasonal forecaster; the diurnal pattern needs weeks to be learnable |
