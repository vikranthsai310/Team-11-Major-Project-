# 01 · Product Requirements Document

**Project:** AI-Driven Adaptive Transaction Batching for Cardano Decentralized Exchanges
**Status:** Approved specification · supersedes conflicting statements in `Doc/`
**Owners:** Vikranth Sai (23P61A67F1) · Ganesh (23P61A67F0) · Sowmya (23P61A67H8)
**Guide:** Ms. B. Mamatha · CSE (Data Science) · Vignana Bharathi Institute of Technology · AY 2026–27

---

## 1. Summary

An intelligent off-chain **batcher** for a Cardano decentralized exchange. It observes live blockchain congestion, forecasts near-term block capacity, and decides when to submit a batch of user swap orders and how many orders to include — replacing the fixed rules deployed batchers use today.

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

**Therefore congestion on Cardano does not cost money. It costs time.** When blocks approach capacity, a batch waits for a later block, and every user inside it waits with it.

This single fact redirects the entire product. The objective is **not** to minimize fees; it is to minimize **confirmation latency** and **per-user cost through amortization**, subject to hard capacity limits. Any framing that promises "lower gas fees during congestion" is technically wrong on Cardano — see `adr/ADR-001`.

### 2.4 Evidence the problem is real

Input Output has publicly described Cardano blocks reaching **80–90 % of capacity** during peak activity. A batch of ~30 orders occupies roughly 11 % of a block, so it fails to fit precisely in that 80–90 % regime. Quantifying this from collected data is deliverable **D1** and the first milestone.

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
| M1 Data | D1 collected, congestion analysed | Plot showing 80–90 % blocks |
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
| Q1 | Can per-block execution units be collected at 90-day scale within free tiers? | M1 | Size-only D1 plus a 7-day ExUnit sample (`adr/ADR-005`) |
| Q2 | DQN or PPO for P3? | M5 | DQN with action masking — discrete action space |
| Q3 | Is the optional dashboard built? | M7 | No; terminal logs and plots suffice |
| Q4 | Exact order-arrival process for D2 | M2 | Poisson with diurnal intensity fitted to D1 tx counts |
