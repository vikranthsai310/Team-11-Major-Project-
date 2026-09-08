# Documentation Index

**AI-Driven Adaptive Transaction Batching for Cardano Decentralized Exchanges**
Team 11 · Batch 11 · CSE (Data Science) · Vignana Bharathi Institute of Technology

---

## Reading paths

**New to the project** — `01-PRD` → `14-GLOSSARY` → `03-ARCHITECTURE` → `07-CONSTRAINTS-COST-MODEL`

**About to write code** — `02-TECH-SPEC` → `04-MODULE-SPECS` → `05-DATA-SPEC` → `08-SIMULATOR-SPEC` → `12-ROADMAP` → `13-RUNBOOK`

**Preparing for a review or viva** — `adr/` (every decision and its justification) → `09-EVALUATION-PROTOCOL` → `11-RISK-REGISTER`

**Writing the report** — `16-REPORT-OUTLINE`, which maps every chapter to the documents that already contain its content

---

## Documents

| # | Document | Contents |
|---|---|---|
| 01 | [PRD](01-PRD.md) | Problem, goals, non-goals, requirements, success metrics, release plan |
| 02 | [Tech Spec](02-TECH-SPEC.md) | Technology choices, repo layout, core interfaces, failure modes, security |
| 03 | [Architecture](03-ARCHITECTURE.md) | Four layers, control loop, data flow, deployment views, quality attributes |
| 04 | [Module Specs](04-MODULE-SPECS.md) | M1–M7 input/output contracts and acceptance criteria |
| 05 | [Data Spec](05-DATA-SPEC.md) | Datasets D1–D4: schema, collection, splits, preprocessing, ethics |
| 06 | [ML Spec](06-ML-SPEC.md) | Baselines E1–E4, forecaster P1, optimizer P2, RL agent P3, MDP and reward |
| 07 | [Constraints & Cost Model](07-CONSTRAINTS-COST-MODEL.md) | Protocol limits, the two gates, fee mathematics, the pool lock |
| 08 | [Simulator Spec](08-SIMULATOR-SPEC.md) | Event loop, inclusion model, stated assumptions, validation |
| 09 | [Evaluation Protocol](09-EVALUATION-PROTOCOL.md) | Metrics, experimental design, statistics, ablations, falsification |
| 10 | [Test Plan](10-TEST-PLAN.md) | Invariant, unit, property, integration and regression tests |
| 11 | [Risk Register](11-RISK-REGISTER.md) | Twelve risks, scored, with mitigations and triggers |
| 12 | [Roadmap](12-ROADMAP.md) | Phases 0–7, exit gates, review checkpoints, scope-cut order |
| 13 | [Runbook](13-RUNBOOK.md) | Setup, stage commands, troubleshooting, live operation |
| 14 | [Glossary](14-GLOSSARY.md) | Cardano, project and ML terminology |
| 15 | [References](15-REFERENCES.md) | Bibliography with the role each source plays |
| 16 | [Report Outline](16-REPORT-OUTLINE.md) | Chapter plan mapped onto these documents |

## Architecture Decision Records

Several of these **overturn assumptions in the earlier material in `Doc/`**. A reviewer will ask why, so each records the context, the decision, its consequences, and the test that prevents the original error returning.

| ADR | Decision | Overturns |
|---|---|---|
| [001](adr/ADR-001-latency-not-fees.md) | Optimize latency and amortized cost, not gas fees | The original Ethereum-shaped premise |
| [002](adr/ADR-002-tx-limits-not-block-limits.md) | Batch size is bounded by transaction limits, not block limits | The optimizer formula on deck slide 13 |
| [003](adr/ADR-003-own-dex-not-minswap.md) | Build a minimal own DEX rather than integrate with Minswap | — |
| [004](adr/ADR-004-pool-lock-failure-model.md) | Failure is pool-UTXO head-of-line blocking, not batch rejection | The RL "bounce penalty" |
| [005](adr/ADR-005-size-only-d1.md) | Size-based congestion at scale, execution units on a sample | The full-window ExUnit collection plan |
| [006](adr/ADR-006-passthrough-fee.md) | Pass-through batcher fee so amortization reaches users | The implicit flat-fee assumption |
| [007](adr/ADR-007-real-slot-clock.md) | Simulator advances on recorded slots, not a fixed 20 s tick | The fixed-tick simulator design |

---

## The project in five sentences

A Cardano DEX liquidity pool is a single UTXO that can be consumed only once per block, so swaps must be aggregated by an off-chain **batcher**. Deployed batchers trigger on constants and never read the chain. Because Cardano fees are deterministic, congestion costs **latency**, not money — so the right objective is to minimize confirmation delay and per-user cost under hard capacity limits. This project forecasts near-term block capacity and learns when to submit a batch and how large to make it, benchmarked in a simulator that replays real recorded congestion against tuned static baselines. The system is a server-side process: no wallet, no extension, no website.

---

## Authority

Where this documentation conflicts with the earlier artifacts in `Doc/` (abstract, literature-review deck, proposed-system deck), **this documentation is authoritative** and `adr/` explains each divergence. The `Doc/` artifacts need three specific corrections before resubmission — deck slide 13's optimizer formula, slide 15's execution-unit footnote, and the abstract's batch-sizing sentence.

## Status

| Area | State |
|---|---|
| Specification | Complete — documents 01–16 |
| Decision records | Complete — ADR 001–007 |
| Implementation | Not started; begin at `12-ROADMAP.md` Phase 0 |
| Report chapters 1–5 | Assemblable from these documents today |
| Report chapters 6–8 | Await implementation and results |
