# AI-Driven Adaptive Transaction Batching for Cardano Decentralized Exchanges

Major project · Team 11 · Batch 11
Department of Computer Science and Engineering (Data Science)
Vignana Bharathi Institute of Technology · AY 2026–27

| | |
|---|---|
| **Team** | Vikranth Sai (23P61A67F1) · Ganesh (23P61A67F0) · Sowmya (23P61A67H8) |
| **Guide** | Ms. B. Mamatha |

---

## What this is

An intelligent off-chain **batcher** for a Cardano DEX. It watches blockchain congestion, forecasts near-term block capacity, and learns when to submit a batch of user swap orders and how many orders to include — replacing the fixed rules deployed batchers use today.

It is a **server-side process**. There is no website, no browser extension and no wallet code. A wallet can only see its own owner's funds, so it has nothing to aggregate; batching is inherently an aggregator's job.

## Why it is needed

On Cardano's eUTXO ledger, a DEX liquidity pool is a **single UTXO that can be consumed only once per block**. A hundred users cannot swap against it independently — one succeeds and the rest fail. The ecosystem solves this with batchers that aggregate many orders into one transaction.

Those batchers trigger on constants: every *M* orders, or every *T* seconds. They never read the chain before deciding.

## The insight the project turns on

Cardano fees are **deterministic**:

```
fee = 44 * size + 155,381 + 0.0577 * mem + 0.0000721 * steps    (lovelace)
```

No gas auction, no bidding. A transaction costs the same on an idle chain and a saturated one.

**So congestion on Cardano does not cost money. It costs time.** When blocks run at 80–90 % capacity, batches wait — and every user inside waits with them. The objective is therefore confirmation **latency** and amortized per-user cost, not fees. Anything promising "lower gas fees during congestion" is describing Ethereum, not Cardano.

## Approach

| | |
|---|---|
| **Forecast** | Predict next-block capacity from recent chain history (LightGBM, LSTM) |
| **Decide** | Choose WAIT or SUBMIT(n) — as a constrained optimizer and as an RL agent |
| **Constrain** | Enforce Cardano's per-transaction limits as hard gates, never as a learned preference |
| **Evaluate** | Replay real recorded blocks in a simulator against tuned static baselines |
| **Demonstrate** | *(optional)* A minimal Aiken DEX on the preprod testnet |

Two facts shape the design more than anything else:

- **Batch size is capped by per-transaction limits** (16,384 B, 14 M execution memory), not block limits — roughly **20–40 orders**. An empty block does not permit a bigger batch.
- **A submitted batch locks the pool UTXO** until it confirms, so a mistimed submission blocks the head of the queue. That, not transaction rejection, is what congestion actually costs.

## Repository

```
Doc/     submission artifacts — abstract, literature review, design decks
docs/    engineering specification (start at docs/README.md)
src/     implementation (not started)
```

## Status

Specification complete; implementation not started. Begin at [`docs/18-TODO.md`](docs/18-TODO.md), Phase 0 — the task-level checklist derived from [`docs/12-ROADMAP.md`](docs/12-ROADMAP.md).

The first real question the project must answer is **whether Cardano block congestion is predictable at a 20-second horizon** — Phase 1 answers it before anything is built on top of it.

## Documentation

Full index: [`docs/README.md`](docs/README.md)

| Start here | |
|---|---|
| [PRD](docs/01-PRD.md) | Problem, goals, requirements, success metrics |
| [Architecture](docs/03-ARCHITECTURE.md) | Layers, control loop, deployment |
| [Constraints & Cost Model](docs/07-CONSTRAINTS-COST-MODEL.md) | The protocol limits everything derives from |
| [ADRs](docs/README.md#architecture-decision-records) | Seven decisions, several overturning earlier assumptions |
| [Roadmap](docs/12-ROADMAP.md) | Phases, exit gates, scope-cut order |
| [Master TODO](docs/18-TODO.md) | Every task, with its done-when condition |
