# 12 · Roadmap

Build order, milestones, exit gates and scope-cut policy. The sequence follows the module dependency graph in `04-MODULE-SPECS.md`; nothing is scheduled before the thing it depends on.

---

## Principles

1. **Prove the premise before building on it.** Phase 1 answers "is congestion predictable?" before any model is written. Risk R4 is the highest-impact unknown in the project.
2. **Baselines before the contribution.** The simulator and static baselines exist before any learning, so there is always something to compare against.
3. **The safe result first.** P2 is a complete deliverable. P3 is an upgrade on top of it.
4. **Optional work last.** M7 is scheduled at the end and has a pre-authorised drop decision.

---

## Phase 0 · Foundation

**Deliverables**
- Repository structure per `02-TECH-SPEC.md` §3
- `config/protocol.py` with every protocol constant
- `config/settings.py` with the preprod network guard
- `.gitignore`, pre-commit secret scan, pytest scaffold
- CI running the unit suite

**Exit gate**
- T-C1, T-C2, T-C3 pass — constants correct, no literal appears elsewhere, mainnet unreachable

**Risk addressed** — R8, R12

---

## Phase 1 · Data and premise validation

**Deliverables**
- M1 collector, resumable and rate-limited
- D1: 90 days of size-based congestion, 7-day execution-unit sample
- Dataset manifest and checksum
- Exploratory analysis notebook
- **Predictability report** — the Phase 1 decision artifact

**Exit gate**
- No gaps in `block_height`; `abs_slot` strictly increasing; re-run byte-identical
- Figure F1 produced, showing the 80–90 % congestion band
- **Predictability answered**: autocorrelation of `fill_pct`, and lag-1 MAE against global-mean MAE

**Decision point.** If a naive lag-1 predictor barely beats the global mean, congestion is close to a random walk at this horizon. Take the R4 fallback: pivot to queue-aware batching, report the negative forecasting result as a finding, and reduce Phase 3 to the E4 baseline plus one model.

**Risk addressed** — R1, R4, R7

---

## Phase 2 · Simulator and baselines

**Deliverables**
- M6 event loop on the real slot clock
- Mempool and pool-lock model
- D2 order generator with diurnal intensity fitted to D1
- Baselines E1, E2, E3 behind the `Policy` interface
- Metrics module and the paired-episode harness

**Exit gate**
- T-S1 to T-S6 pass — determinism, NULL floor, greedy shape, large-M behaviour, head-of-line blocking observable, real slot clock
- T-P3 conservation holds: orders in equals settled plus expired plus queued
- E1 and E2 tuned on the validation split; tuned values recorded

**Note.** T-S3 — greedy giving lowest latency and highest per-user cost — is the single strongest correctness signal. Do not proceed past this gate until it holds.

**Risk addressed** — R6

---

## Phase 3 · Congestion forecaster

**Deliverables**
- E4 moving-average baseline
- P1a LightGBM with the feature set from `06-ML-SPEC.md` §3
- P1b LSTM variant
- Forecast evaluation: MAE, RMSE, directional accuracy
- Figure F4

**Exit gate**
- T-I4 and T-N3 pass — no temporal leakage at split or feature level
- T-L1 leakage check passes
- Success metric S1: P1 MAE below E4 on the test split

If S1 fails, report it and continue. A policy over a moving-average forecast is still adaptive, and the finding stands on its own.

**Risk addressed** — R4

---

## Phase 4 · Constrained optimizer (P2)

**Deliverables**
- Gate A and Gate B implementations
- P2 policy with `D_MAX` and `N_MIN` tuned on validation
- ORACLE ablation variant
- Full paired evaluation of E1–E3 against P2

**Exit gate**
- T-G1 to T-G5 pass, **especially T-G5** — an empty block must not raise the Gate A cap
- Success metric S2: zero Gate A violations across every episode
- P2 evaluated against all baselines at all three arrival rates

**This is the point at which the project has a defensible result.** Everything after it is an upgrade. If the schedule collapses, stop here and write up.

**Risk addressed** — R2, R5

---

## Phase 5 · Reinforcement learning (P3)

**Deliverables**
- Gymnasium environment with action masking
- Reward with calibrated term scales
- DQN agent, five seeds
- Diagnostics: action distribution over congestion deciles (figure F7)
- Ablations A3 and A4

**Exit gate**
- T-L3 passes: a random agent cannot execute an illegal action
- T-L4: reward terms comparable in magnitude on the reference episode
- T-L6: no policy collapse
- Five seeds trained, mean and standard deviation reported

P3 beating P2 is **not** an exit gate. The gate is a correctly trained and honestly reported agent. R2 accepts the outcome either way.

**Risk addressed** — R2

---

## Phase 6 · Evaluation and write-up

**Deliverables**
- Full evaluation: 7 policies x 3 arrival rates x 100 paired episodes
- Paired Wilcoxon tests, bootstrap confidence intervals, Holm–Bonferroni correction
- Ablations A1–A5
- Figures F1–F8
- Results tables with tuned baseline parameters disclosed
- Project report

**Exit gate**
- Every claim in the report traceable to a metric with a confidence interval
- Test split used exactly once
- Threats to validity section written from `09-EVALUATION-PROTOCOL.md` §9

**Risk addressed** — R6, R10

---

## Phase 7 · On-chain demonstration (optional)

**Deliverables**
- `order.ak` with pass-through fee and cancellation
- `pool.ak` with constant-product invariant
- Deployment to preprod
- M5 live submitter via PyCardano
- D4 log and estimator calibration
- One end-to-end swap, transaction hash recorded

**Exit gate**
- T-O1 to T-O6 pass, including the security tests T-O2 and T-O3
- Estimator within ±5 % size and ±10 % execution units against D4

**Pre-authorised drop.** If preprod deployment is not achieved within three weeks of starting Phase 7, drop it and reallocate to evaluation depth. This decision is made now so it does not have to be argued under deadline pressure (risk R3).

---

## Dependency graph

```
Phase 0 ──▶ Phase 1 ──▶ Phase 2 ──▶ Phase 4 ──▶ Phase 5 ──▶ Phase 6
                 │           ▲          ▲
                 └─▶ Phase 3 ┘          │
                                        │
                            Phase 7 ────┘  (optional, independent of results)
```

Phase 3 and Phase 2 can proceed in parallel once Phase 1 delivers D1. Phase 7 can start any time after Phase 0 but is scheduled last on purpose.

---

## Review checkpoints

Map the phases onto the academic review schedule.

| Review | Phases complete | What to show |
|---|---|---|
| **Review 1** | 0, 1 | The problem is real: F1, F2, the congestion band, the predictability finding |
| **Review 2** | 2, 3, 4 | The system works: simulator validated, forecaster beats baseline, P2 beats static batchers |
| **Review 3** | 5, 6, (7) | The full result: Pareto plot F5, ablations, statistics, optional live demo |

Review 1 is a data story, not a demo. Showing real Cardano blocks at 80–90 % capacity, and answering whether that is predictable, is a stronger first review than a partially working prototype.

---

## Scope-cut order

If the schedule slips, cut in this order. Cutting from the top loses the least.

| Order | Cut | Effect |
|---|---|---|
| 1 | Phase 7 on-chain demo | None on results |
| 2 | P1b LSTM variant | Report LightGBM only |
| 3 | Arrival-rate sweep, 3 rates to 1 | Weakens robustness claim; state it |
| 4 | P3 RL agent | Project stands on P2; the "learned policy" claim becomes "adaptive policy" |
| 5 | Ablations A4, A5 | Weakens analysis depth |

**Never cut:** Phase 1 predictability validation, Phase 2 simulator validation, Gate A enforcement, the chronological split, or the paired evaluation design. Each of those is load-bearing for the validity of every number in the report.

---

## Definition of done

The project is complete when:

1. Every success metric in `01-PRD.md` §6 has been measured and reported, whether it passed or failed
2. Every claim in the report traces to a metric with a confidence interval
3. The full test suite passes with no unexplained skips
4. A reader can reproduce every figure from the repository, a seed and a dataset checksum
5. Every assumption and limitation is stated in the report rather than left for a reviewer to find
