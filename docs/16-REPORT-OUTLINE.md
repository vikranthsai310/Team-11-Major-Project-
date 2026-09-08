# 16 · Report Outline

Maps this engineering documentation onto the academic project report, so the report is assembled from specifications that already exist rather than written from scratch.

Structure follows the standard major-project format. Page budgets assume a 60–75 page report; adjust to your department's requirement.

---

## Front matter

Certificate, declaration, acknowledgement, abstract, contents, list of figures, list of tables, list of abbreviations.

The **abstract** already exists in `Doc/team-11-abstract.docx`. It needs one revision: it currently describes batch sizing against block capacity. Update it to reflect `adr/ADR-002` — the objective is bounded by per-transaction limits, with block capacity governing inclusion. Abbreviations come from `14-GLOSSARY.md`.

---

## Chapter 1 · Introduction — 6–8 pages

| Section | Source |
|---|---|
| 1.1 Domain: Cardano and the eUTXO model | `14-GLOSSARY.md`, reference [1] |
| 1.2 Why batching exists — the concurrency constraint | `01-PRD.md` §2.1 |
| 1.3 Problem statement | `01-PRD.md` §2.2, §2.3 |
| 1.4 The latency-not-fees insight | `adr/ADR-001` — state it here, early and explicitly |
| 1.5 Objectives | `01-PRD.md` §3 (G1–G6) |
| 1.6 Scope and limitations | `01-PRD.md` §3 non-goals |
| 1.7 Report organisation | — |

**Write §1.4 as a highlighted subsection.** It is the intellectual pivot of the project, and a reviewer who misses it will misread everything after it.

---

## Chapter 2 · Literature Survey — 10–12 pages

Five core papers with the arc already worked out in `15-REFERENCES.md` §"How the literature supports the argument", plus the supporting set.

| Section | Content |
|---|---|
| 2.1 eUTXO foundations | [1] Chakravarty et al. — the platform and the bottleneck |
| 2.2 Batching for eUTXO concurrency | [5] MELD, [6] Brühwiler — the accepted solution, statically implemented |
| 2.3 Fee mechanism design | [10] Roughgarden — the contrast that justifies the objective |
| 2.4 Learned resource scheduling | [15] DeepRM, [16] Decima — the method template |
| 2.5 Supporting work | [3] Ouroboros, [4] Leios, [8][9] AMM theory, [11] reordering, [12–14][17] ML methods |
| 2.6 Comparison table | Existing deck slide 8, retained |
| 2.7 Research gap | The gap statement in `15-REFERENCES.md` |

The existing `Doc/Literature_Review_Filled (2).pptx` and `Literature_survey_filled (2).docx` already cover this and can be expanded directly.

---

## Chapter 3 · System Analysis — 8–10 pages

| Section | Source |
|---|---|
| 3.1 Existing system: static batching | `06-ML-SPEC.md` §2 — E1, E2, E3 with their pseudocode |
| 3.2 Limitations of the existing system | `01-PRD.md` §2.2; the chain is never read before deciding |
| 3.3 Proposed system | `03-ARCHITECTURE.md` §2, §3 |
| 3.4 Comparison, existing vs proposed | Existing deck slide 13 table |
| 3.5 Feasibility study | See below |
| 3.6 Requirements — functional and non-functional | `01-PRD.md` §5 verbatim |

**Feasibility study**, which most reports handle superficially and this project can handle with evidence:

- *Technical* — all components are free and CPU-only; capacity limits verified against the protocol parameter guide; the tractability of the action space follows from `07-CONSTRAINTS-COST-MODEL.md` §4
- *Economic* — zero cost. Koios needs no key, Blockfrost has a free tier, no GPU, no node, testnet tokens are valueless
- *Operational* — the batcher is a single background process with no inbound ports and no user-facing surface

---

## Chapter 4 · System Requirements — 3–4 pages

| Section | Source |
|---|---|
| 4.1 Hardware | `13-RUNBOOK.md` §1 |
| 4.2 Software and libraries | `02-TECH-SPEC.md` §2, with the justification column retained |
| 4.3 Protocol parameters | `07-CONSTRAINTS-COST-MODEL.md` §1 — this is a *requirement*, since the design is built against these exact values |

Keep the "why this and not the alternative" column from the tech spec. It turns a shopping list into an argued set of decisions.

---

## Chapter 5 · System Design — 14–18 pages, the longest chapter

| Section | Source |
|---|---|
| 5.1 Architecture overview | `03-ARCHITECTURE.md` §2, plus `Doc/team-11-architecture.drawio` |
| 5.2 Module design M1–M7 | `04-MODULE-SPECS.md` |
| 5.3 The two capacity gates | `07-CONSTRAINTS-COST-MODEL.md` §3 — **the technical core** |
| 5.4 Cost model and amortization | `07-CONSTRAINTS-COST-MODEL.md` §5, with figure F3 |
| 5.5 The pool lock and head-of-line blocking | `adr/ADR-004` |
| 5.6 Algorithm design: E1–E4 vs P1–P3 | `06-ML-SPEC.md` |
| 5.7 MDP formulation and reward | `06-ML-SPEC.md` §5 |
| 5.8 Dataset design D1–D4 | `05-DATA-SPEC.md` |
| 5.9 Simulator design | `08-SIMULATOR-SPEC.md` |
| 5.10 UML and flow diagrams | See below |

**Diagrams to produce.** The architecture diagram exists; these do not:

| Diagram | Shows |
|---|---|
| Use case | Actors: swap user, batcher operator, researcher. Emphasise that the user never interacts with the batcher |
| Class | `Policy`, `Observation`, `Action`, `Outcome`, `Order`, `EpisodeState` — the interfaces in `02-TECH-SPEC.md` §4 |
| Sequence | Order placed → chain scanned → forecast → decide → build → settle. The six steps of the existing deck slide 7 |
| Activity | The control loop of `03-ARCHITECTURE.md` §4, including the pool-locked early return |
| DFD level 0 | Chain, batcher, datasets as single processes |
| DFD level 1 | M1–M6 with D1–D4 as data stores |
| State | `pool_locked` transitions: idle → in-flight → confirmed / expired / rolled back |
| Deployment | Research mode and live mode, from `03-ARCHITECTURE.md` §6 |

The **state diagram** is worth extra care. It is where the pool lock — the mechanism that makes the whole project non-trivial — becomes visible at a glance.

---

## Chapter 6 · Implementation — 10–12 pages

*Written during Phases 1–5. Structure fixed now; content pending.*

| Section | Content |
|---|---|
| 6.1 Repository structure | `02-TECH-SPEC.md` §3 |
| 6.2 Protocol constants module | Include the source; explain the single-source-of-truth rule and test T-C2 |
| 6.3 M1 data collection | Resumability, rate limiting, and the ExUnit sampling decision (`adr/ADR-005`) |
| 6.4 Feature engineering | Lags, rolling windows, calendar encoding, and the anti-leakage rule |
| 6.5 P1 forecaster | LightGBM and LSTM, with training curves |
| 6.6 Gate implementation | Annotated code; T-G5 explained |
| 6.7 P2 optimizer | Annotated pseudocode from `06-ML-SPEC.md` §4 |
| 6.8 P3 RL agent | Environment, masking, reward calibration |
| 6.9 Simulator | The event loop, annotated |
| 6.10 On-chain validators *(if Phase 7 completes)* | Aiken source with the pass-through fee logic |

Show **code that embodies a decision** — the gates, the reward, the mask, the fee — not boilerplate. Two well-annotated listings beat ten pages of paste.

---

## Chapter 7 · Testing — 6–8 pages

*Structure from `10-TEST-PLAN.md`; results pending.*

| Section | Content |
|---|---|
| 7.1 Strategy and coverage | `10-TEST-PLAN.md` §1 |
| 7.2 Invariant tests | T-I1 to T-I5 — the tests that make the results trustworthy |
| 7.3 Unit and property tests | Selected cases with results |
| 7.4 Simulator validation | V1–V4 with outcomes. **This is the chapter's most important section** |
| 7.5 Regression guards for corrected assumptions | §9 of the test plan — T-G5, T-S5, T-S6 |
| 7.6 Results table | Test ID, description, expected, actual, pass/fail |

§7.4 is what answers "why should we believe your simulator?" — the question a reviewer *will* ask about a simulation-based result. Answer it in the report rather than in the viva.

---

## Chapter 8 · Results and Discussion — 12–15 pages

*Pending Phase 6. Every table and figure is pre-specified in `09-EVALUATION-PROTOCOL.md`.*

| Section | Content |
|---|---|
| 8.1 Congestion analysis | F1, F2 — the problem is real, with numbers |
| 8.2 Predictability of congestion | The Phase 1 finding; autocorrelation and lag-1 baseline |
| 8.3 Forecaster results | MAE, RMSE, directional accuracy; F4 |
| 8.4 Amortization curve | F3 — why huge batches do not pay |
| 8.5 Policy comparison | The main table; L-mean, L-p95, C-user, X-rate, TP, F-jain |
| 8.6 Pareto analysis | **F5, the headline figure** |
| 8.7 Latency distributions | F6 |
| 8.8 Does the agent adapt? | F7 — action distribution over congestion deciles |
| 8.9 Robustness across arrival rates | F8 |
| 8.10 Ablations | A1–A5, including the ORACLE gap |
| 8.11 Live demonstration *(if Phase 7 completes)* | D4, transaction hashes, estimator calibration |
| 8.12 Threats to validity | `09-EVALUATION-PROTOCOL.md` §9 |

Every cell carries a confidence interval. §8.12 is not optional — it is what separates a measured result from a demo.

---

## Chapter 9 · Conclusion and Future Work — 4–5 pages

| Section | Content |
|---|---|
| 9.1 Summary of contributions | The learned batching policy; the corrected constraint and cost model; the curated D1 dataset; the simulator |
| 9.2 Objectives revisited | G1–G6, each marked achieved, partially achieved, or not achieved, with evidence |
| 9.3 Limitations | `03-ARCHITECTURE.md` §10 and `08-SIMULATOR-SPEC.md` §10 |
| 9.4 Future work | See below |
| 9.5 Concluding remarks | — |

**Future work** — real candidates, already identified rather than invented at the end:

- Transaction chaining, relaxing the pool lock (simulator assumption A3)
- Joint training of forecaster and policy end to end
- Multi-pool scheduling, a genuinely harder problem
- Fairness-aware and MEV-resistant order selection
- Re-evaluation under Ouroboros Leios block dynamics
- Heterogeneous order costs, already supported by the D1/D2 schema

Report objectives honestly in §9.2. A partially achieved objective with evidence is stronger than an overclaimed one.

---

## Back matter

References in IEEE format from `15-REFERENCES.md`. Appendices: protocol parameter table, full metric definitions, run manifest example, additional figures.

---

## Chapter-to-document map

| Chapter | Primary sources |
|---|---|
| 1 | `01-PRD.md`, `adr/ADR-001` |
| 2 | `15-REFERENCES.md` |
| 3 | `01-PRD.md`, `03-ARCHITECTURE.md`, `06-ML-SPEC.md` §2 |
| 4 | `02-TECH-SPEC.md`, `07-CONSTRAINTS-COST-MODEL.md`, `13-RUNBOOK.md` |
| 5 | `03-ARCHITECTURE.md`, `04-MODULE-SPECS.md`, `05-DATA-SPEC.md`, `06-ML-SPEC.md`, `07-CONSTRAINTS-COST-MODEL.md`, `08-SIMULATOR-SPEC.md` |
| 6 | Source code, `02-TECH-SPEC.md` |
| 7 | `10-TEST-PLAN.md` |
| 8 | `09-EVALUATION-PROTOCOL.md` |
| 9 | `03-ARCHITECTURE.md` §10, `11-RISK-REGISTER.md` |

Roughly 80 % of the report is assembly and expansion of documents that already exist. The genuinely new writing is Chapters 6 to 8, and those cannot be written until the code runs.

## Review presentations

| Review | Phases | Draw from |
|---|---|---|
| Review 1 | 0–1 | Chapters 1–3; congestion analysis; the predictability finding |
| Review 2 | 2–4 | Chapter 5; simulator validation; P2 beating static baselines |
| Review 3 | 5–7 | Chapter 8; the Pareto figure; ablations; optional live demo |

The existing decks in `Doc/` cover Reviews 1 and 2 and need updating only where they conflict with `adr/002`, `004` and `007` — chiefly slide 13's optimizer formulation and slide 15's execution-unit footnote.
