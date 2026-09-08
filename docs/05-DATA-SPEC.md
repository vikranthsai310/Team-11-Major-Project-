# 05 · Data Specification

Four datasets. **D1** is collected from the public chain; **D2**, **D3** and **D4** are produced by this project.

---

## D1 · Cardano block congestion history

The signal the entire system learns from, and a publishable artifact in its own right.

**Nature** — secondary data, public on-chain, no personal information of any kind. This is why the curated dataset can itself be released as a deliverable.

**Source** — Koios REST `/blocks` (primary, no key required), Blockfrost `/blocks` (fallback).

**Grain** — one row per block.

### Schema

| Column | Type | Unit | Description |
|---|---|---|---|
| `block_height` | int64 | — | Primary key, strictly increasing |
| `abs_slot` | int64 | slots | Absolute slot number; the simulator clock |
| `block_time` | timestamp | UTC | Wall-clock time of the block |
| `block_size` | int32 | bytes | Serialized block body size |
| `fill_pct` | float32 | [0,1] | `block_size / 90112` |
| `tx_count` | int16 | — | Transactions in the block |
| `mem_exunits` | int64 \| null | units | Plutus memory consumed; null outside the sampled window |
| `step_exunits` | int64 \| null | units | Plutus steps consumed; null outside the sampled window |
| `mem_pct` | float32 \| null | [0,1] | `mem_exunits / 62000000` |
| `step_pct` | float32 \| null | [0,1] | `step_exunits / 40000000000` |
| `slot_gap` | int32 | slots | `abs_slot - previous abs_slot`; the real block cadence |
| `exunits_source` | category | — | `"dbsync"` \| `"per_tx"` \| `"absent"` |

### Volume

About 4,300 blocks/day. Ninety days gives roughly **390,000 rows**, approximately 12 MB as parquet (about 40 MB as CSV).

### The execution-unit problem

Neither Koios nor Blockfrost exposes execution units on the block endpoint. Obtaining them per block means fetching every transaction and summing its redeemers — roughly 390,000 blocks x ~25 transactions ≈ **10 million API calls**, which no free tier permits. The alternative, `cardano-db-sync`, holds the data in `redeemer.unit_mem` and `unit_steps` but requires syncing the full chain: hundreds of gigabytes and several days.

**Resolution (`adr/ADR-005`):** collect `block_size` and `fill_pct` for the full 90 days, and execution units for a **7-day sample** via per-transaction fetch. Report the correlation between size-based and execution-based fullness on the sample, and use it to justify treating size fill as the primary congestion signal.

This is a scope decision made deliberately and early, not a limitation discovered late. It must be stated in the report.

### Preprocessing

| Step | Treatment |
|---|---|
| Ordering | Sort by `block_height` ascending; assert strictly increasing |
| Missing execution units | Leave null; models that need them use the sampled window only |
| Missing blocks | Forward-fill at most one slot; a gap of two or more is left as a hole and excluded from feature windows |
| Epoch boundaries | Flag and exclude from training windows — block production behaves differently there |
| Clipping | `fill_pct`, `mem_pct`, `step_pct` clipped to `[0, 1]` |
| Derived features | Lags 1..20, rolling mean and standard deviation over 5/10/20, `slot_gap` statistics, hour of day as cyclic sine/cosine, day of week |

### Splits

**Chronological, never shuffled.**

| Split | Share | Purpose |
|---|---|---|
| Train | oldest 70 % | Fit the forecaster; train the RL agent |
| Validation | next 15 % | Hyperparameters, early stopping |
| Test | newest 15 % | Reported numbers only; touched once |

Shuffling would leak future congestion into training and inflate every reported result. A test asserts the split boundaries are monotone in time (`10-TEST-PLAN.md`, T-D3).

---

## D2 · Order stream

Simulated user swap orders. Primary data, generated.

**Why generated** — no DEX publishes per-order arrival data, and mainnet experimentation is impossible. The arrival process is therefore modelled and its parameters stated openly.

### Schema

| Column | Type | Description |
|---|---|---|
| `order_id` | str | Unique |
| `arrival_slot` | int64 | Absolute slot of arrival |
| `pair` | str | Token pair; single pair in the base configuration |
| `amount_in` | int64 | Input amount in lovelace or token units |
| `min_out` | int64 | Slippage floor from the datum |
| `size_bytes` | int32 | Marginal bytes added to a batch |
| `mem_exunits` | int64 | Marginal execution memory |
| `step_exunits` | int64 | Marginal execution steps |
| `ttl_slot` | int64 | Expiry slot |

### Arrival process

Non-homogeneous Poisson with a diurnal intensity fitted to the `tx_count` rhythm observed in D1. Cardano has a real daily activity cycle, and a homogeneous process would erase the very pattern the forecaster exploits.

```
lambda(t) = lambda_base * diurnal(hour(t)) * burst(t)
```

`burst(t)` injects occasional high-arrival episodes representing events such as NFT mints. Base rate, diurnal shape and burst parameters are recorded in the run manifest so any episode can be regenerated exactly.

**Sensitivity is required, not optional.** Results are reported across at least three arrival rates (light, matched, heavy). A policy tuned to one rate that collapses at another is a weak result, and the evaluation is designed to expose that.

---

## D3 · Batcher decision log

One row per observed block, per episode, per policy. This is the analysis substrate and the RL debugging surface.

### Schema

| Column | Type | Description |
|---|---|---|
| `episode_id` | str | Ties to the run manifest |
| `policy` | str | `e1` \| `e2` \| `e3` \| `p2` \| `p3` |
| `abs_slot` | int64 | Decision slot |
| `queue_depth` | int16 | Orders waiting |
| `oldest_wait` | int32 | Slots the oldest order has waited |
| `fill_actual` | float32 | Real fill of the replayed block |
| `fill_hat` | float32 | Forecast for this block |
| `pool_locked` | bool | Whether a batch was in flight |
| `slots_in_flight` | int16 | How long it had been in flight |
| `action` | category | `WAIT` \| `SUBMIT` |
| `n` | int16 | Batch size chosen |
| `gate_a_max_n` | int16 | Largest feasible `n` at this step |
| `included` | bool \| null | Outcome, once known |
| `slots_to_confirm` | int16 \| null | Inclusion delay |
| `fee_lovelace` | int64 \| null | Realised fee |
| `reward` | float32 \| null | RL reward, when applicable |

Example rows illustrating the mechanism the project targets:

| abs_slot | depth | fill_hat | action | n | locked | incl | conf |
|---|---|---|---|---|---|---|---|
| 152338397 | 14 | 0.41 | SUBMIT | 14 | false | yes | 3 |
| 152338418 | 5 | 0.63 | WAIT | 0 | true | — | — |
| 152338442 | 11 | 0.84 | WAIT | 0 | true | — | — |
| 152338464 | 19 | 0.79 | WAIT | 0 | true | — | — |
| 152338496 | 21 | 0.52 | SUBMIT | 21 | false | yes | 6 |

Slots 152338418–152338464 show head-of-line blocking: the queue grows while an earlier batch is in flight and no decision is available. That is the phenomenon the policy learns to avoid.

---

## D4 · Preprod testnet log

Real submissions from the optional on-chain demonstration. Its role is **validation of the simulator**, not results.

| Column | Type | Description |
|---|---|---|
| `tx_hash` | str | On-chain transaction hash |
| `submit_slot` | int64 | Slot at submission |
| `confirm_slot` | int64 \| null | Slot at inclusion |
| `n` | int16 | Orders in the batch |
| `est_size`, `actual_size` | int32 | Estimator calibration |
| `est_mem`, `actual_mem` | int64 | Estimator calibration |
| `fee_lovelace` | int64 | Realised fee |
| `outcome` | category | `included` \| `expired` \| `rejected` |

Feeds the M5 acceptance criterion: estimator within ±5 % on size and ±10 % on execution units.

---

## Storage, versioning and integrity

```
data/
├── raw/            API responses as fetched. Gitignored. Reproducible by re-running M1.
└── processed/
    ├── d1_blocks_<start>_<end>.parquet
    ├── d1_blocks_<start>_<end>.sha256      <- committed
    └── manifest.json                        <- committed
```

Datasets are not committed; **checksums and manifests are**. A manifest records the collection window, row count, checksum, source, collector git SHA and the protocol parameters in force. An experiment referencing a dataset whose checksum does not match its manifest fails loudly rather than producing a quietly wrong number.

## Ethics and licensing

D1 is public blockchain data containing no personal information. Addresses are pseudonymous and are not collected — only aggregate per-block statistics are retained. D2 and D3 are synthetic. D4 originates from a test network with valueless tokens.

No consent, anonymisation or data-protection process is required. The curated D1 may be released alongside the report.
