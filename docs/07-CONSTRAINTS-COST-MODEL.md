# 07 · Constraints and Cost Model

The quantitative foundation of the project. Every capacity and cost claim elsewhere in the documentation derives from this file, and every constant here has exactly one implementation: `src/batcher/config/protocol.py`.

---

## 1. Protocol parameters

Cardano mainnet values. Verified against the Cardano parameter guide; these can be changed by governance action, so treat them as configuration and not as literals in code.

| Parameter | Value | Meaning |
|---|---|---|
| `maxTxSize` | **16,384 B** | Maximum serialized size of one transaction |
| `maxTxExecutionUnits.memory` | **14,000,000** | Plutus memory units per transaction |
| `maxTxExecutionUnits.steps` | **10,000,000,000** | Plutus CPU steps per transaction |
| `maxBlockBodySize` | **90,112 B** | Maximum block body size |
| `maxBlockExecutionUnits.memory` | **62,000,000** | Plutus memory units per block |
| `maxBlockExecutionUnits.steps` | **40,000,000,000** | Plutus CPU steps per block |
| `minFeeA` | 44 lovelace/byte | Size coefficient |
| `minFeeB` | 155,381 lovelace | Flat component |
| `priceMemory` | 0.0577 lovelace/unit | Execution memory price |
| `priceSteps` | 0.0000721 lovelace/step | Execution step price |
| slot duration | 1 s | Slots are one second |
| active slot coefficient `f` | 0.05 | Probability a slot produces a block |

Two corrections to earlier project documents are embedded above:

- Earlier material stated a per-block step budget of 20 G. It is **40 G**.
- Earlier material sized batches against the **block** limits. Batch size is bounded by the **transaction** limits. See §3 and `adr/ADR-002`.

## 2. Block cadence

Slots are 1 second with `f = 0.05`, so inter-block gaps are geometric with mean 20 s. Observed gaps range from a few seconds to well over a minute.

**Consequence for the simulator:** a fixed 20-second tick is wrong and systematically understates tail latency, which is exactly the metric the project claims to improve. The simulator advances on recorded `abs_slot` values instead (`adr/ADR-007`).

## 3. The two gates

A batch is one transaction submitted into one block. Two independent constraint sets apply, and conflating them is the single most consequential error available in this design.

### Gate A — feasibility

Always binding. Independent of congestion. A violation makes the transaction invalid on an empty chain.

```
tx_size(n)  = TX_OVERHEAD_B   + sum(order_size[i]  for i < n)  <= 16,384
tx_mem(n)   = POOL_MEM        + sum(order_mem[i]   for i < n)  <= 14,000,000
tx_steps(n) = POOL_STEPS      + sum(order_steps[i] for i < n)  <= 10,000,000,000
```

`POOL_MEM` and `POOL_STEPS` are the cost of running the pool validator once per batch — paid regardless of `n`.

### Gate B — inclusion

Congestion dependent. The transaction is valid, but the block being produced may not have room.

```
blk.size  + tx_size(n)  <= 90,112
blk.mem   + tx_mem(n)   <= 62,000,000
blk.steps + tx_steps(n) <= 40,000,000,000
```

At decision time Gate B is evaluated against the **forecast**. In the simulator it is evaluated against the **actual replayed block**. The gap between those two is precisely what the forecaster is being paid to close.

### Why the distinction matters

| | Gate A | Gate B |
|---|---|---|
| Bounds | Maximum batch size | Whether the batch fits *now* |
| Depends on congestion | No | Yes |
| Violation means | Invalid transaction (defect) | Wait for a later block (normal) |
| Enforced by | M4 clamp + M5 assertion | Forecast at decide time, reality at inclusion time |

An empty block does **not** permit a larger batch. This is counter-intuitive if arriving from Ethereum, and it is why the optimizer formulation in the earlier deck — `capacity <- (1 - fill_hat) * 90,112` — would have proposed invalid transactions on an idle chain.

## 4. Maximum batch size

Marginal cost per order in a batch transaction:

| Component | Approximate cost |
|---|---|
| Input reference (tx id + index, CBOR) | ~40 B |
| Redeemer + execution-unit declaration | ~60 B |
| User output (address, value, min-ADA) | ~150 B |
| **Total size per order** | **~250–350 B** |
| Order validator execution, memory | ~0.5 M units |
| Order validator execution, steps | ~200 M |

Applying Gate A:

```
By size:   16,384 / 300                     ≈  54 orders
By memory: (14,000,000 - 2,000,000) / 500,000 ≈  24 orders
By steps:  (10,000,000,000 - 800,000,000) / 200,000,000 ≈ 46 orders
```

**Execution memory binds first. `n_max` is roughly 20–40 orders.**

This is consistent with observed Minswap batch sizes of about 25–40 orders, which is a useful independent check to cite.

Two design consequences:

1. The action space is small and discrete — `WAIT` plus `SUBMIT(n)` for `n` in `1..n_max`. This makes DQN genuinely tractable rather than aspirational.
2. A 30-order batch is roughly 9–10 KB, about **11 % of a block**. It therefore fails Gate B only when the block is above roughly 89 % full — precisely the 80–90 % peak regime the project targets. The problem statement survives the correction, now with a number behind it.

These figures are estimates until measured. Calibrating them against real preprod transactions is an M5 acceptance criterion, and the numbers here must be updated from measurement before the final report.

## 5. Fee model

```
fee(size, mem, steps) = 44 * size + 155,381 + 0.0577 * mem + 0.0000721 * steps    (lovelace)
```

Decomposed by how each term scales with batch size `n`:

```
fee(n) = [ 155,381 + 44*TX_OVERHEAD + 0.0577*POOL_MEM + 0.0000721*POOL_STEPS ]   <- FLAT
       + n * [ 44*order_bytes + 0.0577*order_mem + 0.0000721*order_steps ]        <- LINEAR

cost_per_user(n) = FLAT / n + MARGINAL
```

### The amortization curve

Only the flat term amortizes. Every order runs the order validator, so execution cost grows linearly with `n` and never amortizes.

| n | Total fee (est.) | Per user |
|---|---|---|
| 1 | ~0.30 ADA | 0.300 ADA |
| 5 | ~0.51 ADA | 0.102 ADA |
| 10 | ~0.80 ADA | 0.080 ADA |
| 20 | ~1.46 ADA | 0.073 ADA |
| 30 | ~2.12 ADA | 0.071 ADA |

The curve is a hyperbola that flattens quickly. Most of the benefit is realised by `n ≈ 10`; going from 10 to 30 orders buys about 11 % further saving.

**This is a significant finding and it strengthens the thesis.** Because the cost gradient nearly vanishes past `n ≈ 10–15`, there is little economic reason to hoard orders, so **latency dominates the objective**. It also means the RL reward must weight cost and latency on comparable scales, or the cost term becomes numerically irrelevant — see `06-ML-SPEC.md` §5.

It also pre-empts the obvious examiner question, *why not simply always batch the maximum?* — because beyond roughly 15 orders you pay latency for a saving that has already flattened out.

## 6. Who receives the amortization

A subtlety that determines whether goal G2 is genuinely delivered.

On Minswap each order pays a **flat** batcher fee of about 2 ADA. The batcher pays the network fee for the batch. When batches grow, the network fee per order falls but the user still pays 2 ADA — **the saving accrues to the batcher, not the user**.

For the claim *"reduces per-user cost"* to be true, the order validator must charge a **pass-through** fee:

```
user_pays = network_fee(n) / n + fixed_margin
```

This is a deliberate design decision in `onchain/validators/order.ak`, recorded in `adr/ADR-006`. Without it, the merit claimed in the proposed-system deck does not hold for users.

## 7. Latency model

Confirmation latency for an order, measured in slots:

```
latency(order) = confirm_slot - arrival_slot
               = queue_wait + in_flight_wait
```

- `queue_wait` — arrival until the batch containing it is submitted. Controlled by the policy.
- `in_flight_wait` — submission until inclusion. Controlled by congestion and by the block cadence, not by the policy.

The policy influences the first term directly and the second term only through timing: submitting into predicted congestion lengthens `in_flight_wait` and, because the pool is locked meanwhile, lengthens `queue_wait` for every order behind it.

## 8. The pool lock

The mechanism that makes a mistimed submission expensive.

A batch consumes the pool UTXO and produces a new one. Until the batch confirms, the new pool output does not exist, so a second batch cannot be constructed. Therefore at most one batch is in flight per pool.

```
t0  submit batch A            -> pool_locked = True
t1  block full, A not included -> every queued order waits, no new batch possible
t2  block full, A not included -> queue continues to grow
t3  A included                 -> pool_locked = False, decision possible again
```

**Head-of-line blocking is the real cost of submitting into congestion**, not transaction rejection. A submitted transaction is not rejected for being late; it waits in the mempool. This replaces the "bounce penalty" used in the earlier design with a mechanism that actually exists. See `adr/ADR-004`.

Genuine failures come from three places only:

| Failure | Cause | Metric |
|---|---|---|
| TTL expiry | Validity interval passes before inclusion | expiry rate |
| Mempool rejection | Mempool full at submission | rejection rate |
| Rollback | Short fork reverts an included batch | rollback rate |

## 9. Constants module contract

```python
# src/batcher/config/protocol.py  -- the ONLY place these values appear
MAX_TX_SIZE            = 16_384
MAX_TX_EX_MEM          = 14_000_000
MAX_TX_EX_STEPS        = 10_000_000_000
MAX_BLOCK_SIZE         = 90_112
MAX_BLOCK_EX_MEM       = 62_000_000
MAX_BLOCK_EX_STEPS     = 40_000_000_000
MIN_FEE_A              = 44
MIN_FEE_B              = 155_381
PRICE_MEM              = 0.0577
PRICE_STEPS            = 0.0000721
SLOT_SECONDS           = 1
ACTIVE_SLOT_COEFF      = 0.05
```

A test walks the source tree and fails if any of these literals appears outside this module (NFR-4).
