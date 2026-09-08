# ADR-005 · Collect size-based congestion at scale, execution units on a sample

**Status:** Accepted

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

## Alternatives considered

| Alternative | Rejected because |
|---|---|
| Full per-transaction fetch, 90 days | ~10M API calls; weeks under rate limiting; no free tier permits it |
| `cardano-db-sync` on mainnet | Hundreds of GB and days of sync for one column |
| `cardano-db-sync` on preprod | Cheap to sync, but preprod congestion is unrepresentative — it would answer the wrong question |
| Narrow the whole project to 14 days | Too little data for a seasonal forecaster; the diurnal pattern needs weeks to be learnable |
