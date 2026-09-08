# 03 · Architecture

Authoritative architecture document. Where this conflicts with `Doc/team-11-architecture.drawio` or the proposed-system deck, **this document wins**; each divergence is recorded in `adr/`.

---

## 1. Architectural style

An **event-driven control loop** wrapped around a **forecast-then-decide** pipeline, with an offline **simulation environment** that can substitute for the live chain.

Three properties drive the design:

1. **The environment is partially observable.** The batcher cannot know how full the next block will be, or how long its own batch will take to confirm. Hence a forecaster and a policy rather than a scheduler.
2. **There is one shared resource.** The pool UTXO can be consumed by one transaction at a time. The system is fundamentally a lock manager under uncertain service time.
3. **Constraints are hard and external.** Capacity limits come from the protocol, not from configuration. They are enforced structurally, not learned.

## 2. Layered view

```
┌── L4 · OFFLINE TRAINING AND EVALUATION ────────────────────────────┐
│  M6 Simulator ──▶ Baselines E1–E3 ──▶ Metrics, statistics, plots   │
│       │                                                            │
│       └── training episodes ──▶ (into L2 policy)                   │
└────────────────────────────────────────────────────────────────────┘
                     ▲ replays                       ▲ trains
┌── L3 · DATA ───────┴────────────────────────────────────────────┐
│  Koios / Blockfrost ──▶ M1 Collector ──▶ Feature store D1       │
└─────────────────────────────────────────────────────────────────┘
                     │ features
┌── L2 · OFF-CHAIN BATCHER  (the proposed system) ────────────────┐
│                                                                 │
│   M2 Forecaster ──┐                                             │
│                   ├──▶ M4 Policy ──▶ M5 Builder & Submitter     │
│   M3 Queue    ────┘        ▲                  │                 │
│                            └── outcome ───────┘                 │
└─────────────────────────────────────────────────────────────────┘
              ▲ scans orders            │ submits batch tx
┌── L1 · ON-CHAIN  (Cardano preprod) ───┴─────────────────────────┐
│  User wallet ──▶ Order UTXOs ──▶ Pool UTXO ──▶ Block producer   │
│  (CIP-30)        (order         (one spend      (90,112 B,      │
│                   validator)     per block)      ExUnit caps)   │
└─────────────────────────────────────────────────────────────────┘
```

L2 is the deliverable. L1 is scaffolding that gives L2 something real to serve. L3 supplies the signal. L4 is where the result is produced.

## 3. Component responsibilities

| ID | Component | Responsibility | Owns |
|---|---|---|---|
| M1 | Chain Data Collector | Poll block endpoints, normalise, persist | D1 |
| M2 | Congestion Forecaster | Predict fill % and capacity headroom for t+1..t+3 | P1, E4 models |
| M3 | Order Queue Manager | Track pending orders, ages, sizes, execution costs | queue state |
| M4 | Adaptive Batching Policy | Decide WAIT or SUBMIT(n) under Gate A and forecast Gate B | P2, P3 |
| M5 | Batch Builder & Submitter | Estimate cost, enforce Gate A, build, sign, submit, observe outcome | tx construction |
| M6 | Simulator & Evaluation | Replay blocks, model mempool and pool lock, score policies | D2, D3, metrics |
| M7 | On-chain DEX *(optional)* | Order validator and pool validator on preprod | D4 |

Full input/output contracts: `04-MODULE-SPECS.md`.

## 4. The control loop

One iteration per observed block. The order of operations matters and is fixed.

```
on_block(blk):
    1. M3.admit(orders arriving at or before blk.slot)
    2. if pool_locked:
           if in_flight_tx included in blk:
               M5.observe(included) ; pool_locked = False
           elif in_flight_tx.ttl < blk.slot:
               M5.observe(expired)  ; pool_locked = False ; M3.return(orders)
           else:
               record head-of-line wait ; return          # no decision possible
    3. f_hat = M2.predict(history up to blk)
    4. obs   = Observation(M3.state(), f_hat, blk.headroom, pool_locked=False)
    5. act   = M4.decide(obs)                             # WAIT masked if oldest_wait >= D_MAX
    6. if act.submit:
           tx = M5.build(M3.take(act.n))                  # Gate A enforced here
           if tx.valid: submit(tx) ; pool_locked = True
    7. D3.log(obs, act, result)
```

Two invariants the loop guarantees, independent of which policy is plugged in:

- **I1** — no transaction violating Gate A is ever submitted
- **I2** — no order waits longer than `D_MAX` without being offered for submission

Both are enforced by the loop and the environment, never by the policy. A learned agent must be structurally incapable of breaking a ledger rule or starving a user.

## 5. Data flow

```
Koios/Blockfrost ──raw JSON──▶ M1 ──parquet──▶ D1
                                                │
                          ┌─────────────────────┴──────────────┐
                          ▼                                    ▼
                   M2 training                        M6 replay stream
                   (chronological split)              (real slots, real fill)
                          │                                    │
                          ▼                                    ▼
                       f_hat ──────────▶ M4 ◀────── queue state from M3 ◀── D2 orders
                                          │
                                          ▼
                                        M5 ──▶ tx ──▶ mempool ──▶ block
                                          │                        │
                                          └◀──── outcome ◀─────────┘
                                          │
                                          ▼
                                         D3 decision log ──▶ metrics ──▶ plots
```

## 6. Deployment views

### 6.1 Research mode (default, produces all results)

A single Python process. No network. Reads D1 from disk, generates D2 internally, runs a policy against M6, writes D3 and metrics. Fully deterministic given a seed.

```
[ laptop ] ── python scripts/evaluate.py --policy p2 --episodes 100 --seed 42
```

### 6.2 Live mode (optional demo, M7)

A long-running process against preprod.

```
[ batcher host ]                    [ Blockfrost / Koios ]        [ Cardano preprod ]
  batcher daemon ──── HTTPS ─────────▶ chain query API ──────────▶ node network
       │                                                                 ▲
       └──────────── HTTPS submit ───────────────────────────────────────┘
```

No inbound ports. No database server — parquet and JSON on local disk. No user-facing endpoint.

## 7. Why there is no frontend

Recorded here because it has been asked repeatedly.

A batcher aggregates orders belonging to **many different users** into one transaction. A wallet or browser extension can see only **its own owner** funds, so it has nothing to aggregate — the capability is structurally unavailable to client-side software. Batching is inherently an aggregator role and must run server-side.

Wallets and this system never communicate. They are coupled only through the chain:

```
wallet ──signs order──▶ [ order UTXO on chain ] ◀──scans, independently── batcher
                                                        │
user address ◀── swapped tokens ◀── batch tx ◀──────────┘
```

The user experience is: click swap in any Cardano wallet, wait, receive tokens. The batcher is invisible.

The only optional UI is a local dashboard over the simulator (FR-15) for demonstration purposes. It is not part of the product.

## 8. Quality attributes and how the architecture serves them

| Attribute | Mechanism |
|---|---|
| **Correctness** | Gate A enforced at two levels; invariants I1/I2 owned by the loop, not the policy |
| **Reproducibility** | Seeded episodes, run manifests, dataset checksums, chronological splits |
| **Comparability** | One `Policy` interface; every policy sees identical observations and identical replayed blocks |
| **Modularity** | Forecaster, policy and builder are independently replaceable; any eUTXO DEX could reuse M2–M5 |
| **Testability** | Pure functions for estimation and gates; the simulator is deterministic and steppable |
| **Safety** | Network guard pins preprod; keys never enter the repo; slippage enforced on-chain |
| **Degradability** | Forecast failure falls back to E4; M7 can be dropped entirely without affecting results |

## 9. Key architectural decisions

Each links to its ADR.

| Decision | Rationale | ADR |
|---|---|---|
| Objective is latency and amortized cost, not fees | Cardano fees are demand-independent | [001](adr/ADR-001-latency-not-fees.md) |
| Batch size bounded by **transaction** limits; block limits govern inclusion only | 16,384 B / 14 M mem per tx vs 90,112 B / 62 M per block | [002](adr/ADR-002-tx-limits-not-block-limits.md) |
| Build a minimal own DEX instead of integrating with Minswap | Orders bind to their creating validator; Minswap batchers are whitelisted and licensed | [003](adr/ADR-003-own-dex-not-minswap.md) |
| Failure modelled as pool-UTXO head-of-line blocking | A submitted tx waits in the mempool; it is not rejected for lateness | [004](adr/ADR-004-pool-lock-failure-model.md) |
| D1 collects size at scale, execution units on a sample | Per-block ExUnits require ~10M API calls or a full db-sync | [005](adr/ADR-005-size-only-d1.md) |
| Order validator charges a pass-through fee | Otherwise amortization benefits the batcher, not the user | [006](adr/ADR-006-passthrough-fee.md) |
| Simulator clock is the recorded slot sequence | Block intervals are geometric with mean 20 s, not fixed | [007](adr/ADR-007-real-slot-clock.md) |

## 10. Known architectural limitations

Stated plainly so they can be defended rather than discovered.

1. **Single pool.** The architecture assumes one liquidity pool and one batcher. Multi-pool scheduling is a different, harder problem.
2. **Counterfactual replay.** Injecting a batch into a recorded block adds load that did not historically exist. The simulator does not displace historical transactions; it treats recorded usage as fixed background. Stated as an assumption in `08-SIMULATOR-SPEC.md`.
3. **Transaction chaining is not modelled.** Cardano permits chaining an unconfirmed output within the same block. Real batchers sometimes exploit this. Excluding it is conservative — it makes the pool lock stricter than reality — and is a candidate extension.
4. **Forecast error compounds into the policy.** P3 consumes `f_hat` as state, so forecaster error propagates. An alternative giving the agent raw history is noted as future work.
5. **Slippage is endogenous.** Price movement is derived from the simulated constant-product pool, not from real market data. It measures the mechanism, not real-world price risk.
6. **Protocol drift.** Governance can change capacity parameters. Mitigated by a single constants module, not by adaptivity.
