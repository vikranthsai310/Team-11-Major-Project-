# 01 · Product Requirements Document

**Project:** AI-Driven Adaptive Transaction Batching for Cardano Decentralized Exchanges
**Status:** Approved specification · supersedes conflicting statements in `Doc/`
**Owners:** Vikranth Sai (23P61A67F1) · Ganesh (23P61A67F0) · Sowmya (23P61A67H8)
**Guide:** Ms. B. Mamatha · CSE (Data Science) · Vignana Bharathi Institute of Technology · AY 2026–27

---

## 1. Summary

An intelligent off-chain **batcher** for a Cardano decentralized exchange. A DEX pool is a single UTXO that admits one batch per block, so orders queue behind whatever batch is in flight. This system decides when to submit and how many orders to include — managing that shared lock under uncertain confirmation time, and reading the chain before deciding, which the fixed-rule batchers deployed today do not.

The product is a **server-side process**, not a website and not a browser extension. It has no user interface; it is infrastructure that sits behind a DEX.

## 2. Background and problem

### 2.1 Why batching exists

Cardano uses the eUTXO ledger model. A DEX liquidity pool is stored as **a single UTXO**, and a UTXO can be consumed only once per block. If a hundred users try to swap against the same pool simultaneously, only one transaction can succeed and the rest fail.

The ecosystem answer is **batching**. Users do not swap directly. Each user submits an *order* — a transaction locking their funds at the DEX script address with a datum stating the swap terms, slippage tolerance and return address. An off-chain batcher scans the chain, collects pending orders, and executes many of them in a single transaction against the pool.

Batching therefore exists to solve **concurrency**. Cost amortization is a secondary effect.

### 2.2 The problem with today's batchers

Deployed batchers trigger on constants:

- fixed size — submit when the queue reaches *M* orders
- fixed interval — submit every *T* seconds
- greedy — submit whatever is queued, immediately

None of them read the chain before deciding. This is the gap.

### 2.3 The Cardano-specific insight

Cardano transaction fees are **deterministic**:

```
fee = 44 * size_bytes + 155381 + 0.0577 * mem_units + 0.0000721 * cpu_steps   (lovelace)
```

There is no gas auction and no priority-fee bidding. Two identical transactions cost the same on an idle chain and on a congested one.

**Therefore waiting on Cardano does not cost money. It costs time.** A batch that does not confirm promptly keeps every user inside it waiting — and, because it holds the pool UTXO while it waits, keeps every order *behind* it waiting too.

This single fact redirects the entire product. The objective is **not** to minimize fees; it is to minimize **confirmation latency** and **per-user cost through amortization**, subject to hard capacity limits. Any framing that promises "lower gas fees during congestion" is technically wrong on Cardano — see `adr/ADR-001`.

Note what this argument does **not** require: that blocks be full. Deterministic fees make time the currency regardless of how busy the chain is, and §2.4 shows the waiting is caused mainly by the pool lock rather than by block capacity.

### 2.4 Evidence the problem is real

**This section was rewritten in Phase 1 from measured data. See `adr/ADR-008`.**

The project was originally motivated by a widely-repeated claim that Cardano blocks
reach 80–90 % of capacity during peak activity, leaving no room for a ~30-order
batch (~11 % of a block). Deliverable **D1** was collected to quantify it. It does
not hold on the current chain:

| Statistic | Measured on D1 |
|---|---|
| Mean block fill | 6.83 % |
| Median block fill | 2.95 % |
| Blocks above 80 % | 0.564 % |
| Blocks above 90 % | 0.395 % |

*(388,781 blocks over 92 days, 2026-06-13 to 2026-09-13, `sha256 48cd6f8b9a9e`.)*

Congestion is real but **rare and interleaved**. The 2,193 congested blocks fall
into 1,679 separate episodes; the longest unbroken run above 80 % is **10 blocks,
five minutes**, and no run reaches 50. They cluster into busy days — 64 % fall in
the busiest five — but even the busiest day spends only 11.2 % of its blocks above
80 %. A batcher therefore never faces a *run* of blocks it cannot enter, only
isolated ones it can wait out. Gate B binds on a 30-order batch above roughly 89 %
fill: about one block in 180.

**The problem that is real is concurrency, not congestion.** A pool is a single
UTXO and admits one batch per block; a submitted batch holds it until confirmation,
and every order behind it waits (`adr/ADR-004`). That constraint is a property of
the eUTXO ledger and is fully present on an empty chain. It is what deployed
batchers, triggering on constants, handle badly — and it is what this project
addresses.

The congestion measurement is retained as a **result** rather than as motivation:
a characterisation of mainnet block occupancy, and the observation that the
ecosystem's congestion claim does not describe the chain as it currently runs.

## 3. Goals and non-goals

### Goals

| ID | Goal |
|---|---|
| G1 | Reduce mean and 95th-percentile confirmation latency for user orders versus static batchers |
| G2 | Reduce average per-user cost by amortizing the flat fee component across larger batches |
| G3 | Never construct a transaction that violates Cardano capacity limits |
| G4 | Guarantee no order starves, regardless of congestion |
| G5 | Produce a reproducible, publishable evaluation against static baselines |
| G6 | Require no change to wallets, to CIP-30, or to the Cardano protocol |

### Non-goals

| ID | Non-goal | Reason |
|---|---|---|
| N1 | Reducing Cardano transaction fees during congestion | Fees are demand-independent; the premise does not exist |
| N2 | A wallet, browser extension, or consumer web application | A wallet sees only its own owner funds and has nothing to aggregate |
| N3 | Integrating with Minswap or any deployed DEX | Their validators require whitelisted, licensed batchers — see `adr/ADR-003` |
| N4 | Multi-pool routing, order-book matching, or cross-DEX arbitrage | Out of scope for the research question |
| N5 | Mainnet deployment | All live work targets preprod testnet |
| N6 | Security audit, MEV protection, liquidity incentives, batcher decentralisation | Production concerns, not required to prove the thesis |

## 4. Users and stakeholders

| Actor | Interacts how | Cares about |
|---|---|---|
| **Swap user** | Signs an order in any Cardano wallet; never sees the batcher | Order confirms fast, costs little, honours slippage |
| **DEX operator** | Runs the batcher process | Throughput, inclusion reliability, operating cost |
| **Researcher / evaluator** | Runs the simulator and reads the metrics | Reproducibility, honest baselines, statistical rigour |
| **Project guide and review panel** | Reads the report, watches the demo | Correctness of premise, novelty, evidence |

The swap user is the beneficiary but never a direct user of this system. Wallets and the batcher are fully decoupled and communicate only through on-chain order UTXOs.

## 5. Requirements

### 5.1 Functional

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | Collect per-block congestion data (height, slot, size, fill %, execution units, tx count) from public APIs | Must |
| FR-2 | Persist collected data as a versioned, reproducible dataset | Must |
| FR-3 | Forecast next-block fill percentage and capacity headroom from recent history | Must |
| FR-4 | Maintain a queue of pending orders with arrival slot, waiting time, size and execution cost | Must |
| FR-5 | Decide each block whether to WAIT or SUBMIT(n), for n bounded by capacity | Must |
| FR-6 | Reject any candidate batch that violates per-transaction limits **before** construction | Must |
| FR-7 | Force submission when the oldest queued order reaches deadline D_max | Must |
| FR-8 | Refuse to submit while a previous batch is unconfirmed and holds the pool UTXO | Must |
| FR-9 | Record every decision to a structured log (dataset D3) | Must |
| FR-10 | Replay historical blocks as background congestion in a discrete-event simulator | Must |
| FR-11 | Provide static baseline batchers E1, E2, E3 and forecaster baseline E4 | Must |
| FR-12 | Compute and export the full metric set with paired statistical comparison | Must |
| FR-13 | Build, sign and submit a real batch transaction via PyCardano | Should |
| FR-14 | Deploy an Aiken order validator and pool validator on preprod | Could |
| FR-15 | Provide a local dashboard visualising the decision loop | Could |

### 5.2 Non-functional

| ID | Requirement | Target |
|---|---|---|
| NFR-1 | Decision latency — the policy must decide well within one block interval | < 1 s per decision |
| NFR-2 | RL training must complete on a student laptop CPU | < 6 h per agent |
| NFR-3 | All experiments reproducible from a seed | Bit-identical metric output |
| NFR-4 | Protocol limits defined in exactly one module | Single source of truth |
| NFR-5 | Data collection must stay inside free API tiers | No paid plan required |
| NFR-6 | No secrets, keys or mnemonics committed to the repository | Enforced by `.gitignore` |
| NFR-7 | Testnet keys only; no mainnet key material ever loaded | Hard network guard in config |

### 5.3 Constraints (external, non-negotiable)

These are Cardano protocol parameters, not design choices. Full treatment in `07-CONSTRAINTS-COST-MODEL.md`.

| Limit | Per transaction | Per block |
|---|---|---|
| Serialized size | 16,384 B | 90,112 B |
| Execution memory | 14,000,000 | 62,000,000 |
| Execution steps | 10,000,000,000 | 40,000,000,000 |

The per-**transaction** limits bind batch size at roughly **20–40 orders**. Block limits determine *inclusion*, not maximum size. Conflating the two is the error corrected in `adr/ADR-002`.

## 6. Success metrics

Measured on held-out replayed congestion with identical order streams across all policies.

| ID | Metric | Success condition |
|---|---|---|
| S1 | Next-block fill MAE, P1 vs E4 | P1 lower on the test split |
| S2 | Gate A violations | Exactly zero |
| S3 | Mean confirmation latency vs. best static baseline | Lower, significant on paired runs |
| S4 | Order expiry rate | No worse than baseline |
| S5 | Latency–cost trade-off | Adaptive policy Pareto-dominates E1–E3 |
| S6 | Fairness (Jain index on waiting times) | No worse than baseline |

S5 failing is a reportable result. **S2 failing is a defect**, not a result.

## 7. Release plan

| Milestone | Contents | Exit gate |
|---|---|---|
| M0 Foundation | Repo, config, protocol constants | All limits in one module, tested |
| M1 Data | D1 collected, congestion analysed | F1/F2 produced and the occupancy distribution characterised, **whatever it shows** (revised per ADR-008; the original gate presupposed its own answer) |
| M2 Simulator | M6 + baselines E1–E3 | Baselines run on real slots, paired seeds |
| M3 Forecast | P1 trained and evaluated | Beats E4 on chronological test split |
| M4 Policy | P2 constrained optimizer | Zero Gate A violations |
| M5 Learning | P3 RL agent | Beats P2 on paired episodes |
| M6 Evidence | Metrics, Pareto plot, report | Confidence intervals reported |
| M7 Demo *(optional)* | Aiken DEX live on preprod | End-to-end swap settles |

M7 is droppable without weakening the core claim. The result lives in the simulator.

## 8. Open questions

| # | Question | Needed by | Default if unresolved |
|---|---|---|---|
| ~~Q1~~ **answered** | Can per-block execution units be collected at 90-day scale within free tiers? | M1 | **No — and the fallback holds.** Two 2-day samples (17,280 blocks) give a size↔execution correlation of 0.912 in the congested regime, 0.852 pooled; steps never exceed 49.9 % of the block budget. Size fill is the primary signal, the forecaster trains on all 92 days. `adr/ADR-005` §Result |
| Q2 | DQN or PPO for P3? | M5 | DQN with action masking — discrete action space |
| Q3 | Is the optional dashboard built? | M7 | No; terminal logs and plots suffice |
| Q4 | Exact order-arrival process for D2 | M2 | Poisson with diurnal intensity fitted to D1 tx counts |
