# 11 · Risk Register

Live document. Review at every milestone gate. Scores are Likelihood × Impact on a 1–5 scale; anything scoring 12 or above needs an active mitigation, not a watch.

---

## Summary

| ID | Risk | L | I | Score | Status |
|---|---|---|---|---|---|
| R1 | Execution-unit data infeasible to collect at scale | 5 | 3 | **15** | Mitigated (ADR-005) |
| R2 | RL agent fails to beat the optimizer | 4 | 3 | **12** | Accepted with fallback |
| R3 | Aiken and on-chain work consumes the schedule | 4 | 4 | **16** | Mitigated by scope design |
| R4 | Congestion is not predictable enough to exploit | 3 | 5 | **15** | Active — early test |
| R5 | Estimator inaccuracy causes Gate A violations live | 3 | 4 | 12 | Mitigated |
| R6 | Reviewer challenges the simulator's validity | 3 | 4 | 12 | Mitigated |
| R7 | Free-tier API limits block data collection | 3 | 3 | 9 | Watch |
| R8 | Protocol parameters change mid-project | 2 | 3 | 6 | Watch |
| R9 | Team member unavailable at a critical phase | 2 | 4 | 8 | Watch |
| R10 | Results are negative across the board | 2 | 4 | 8 | Accepted |
| R11 | Leios changes the premise before submission | 2 | 3 | 6 | Watch |
| R12 | Key material or secrets committed | 2 | 5 | 10 | Mitigated |

---

## R1 · Execution-unit data infeasible at scale

**Likelihood 5 · Impact 3 · Score 15 · Mitigated**

Per-block execution units are not exposed by Koios or Blockfrost block endpoints. Collecting them for 90 days requires roughly 10 million per-transaction API calls, or a full `cardano-db-sync` instance needing hundreds of gigabytes and days of syncing.

*Impact:* the D1 schema as originally specified cannot be filled. Discovering this in month three would invalidate the collection plan and the forecaster feature set.

*Mitigation:* resolved before implementation. D1 collects size-based fullness for the full window and execution units for a 7-day sample; the correlation between them is reported and justifies size fill as the primary signal. Recorded in `adr/ADR-005`.

*Residual:* execution-based Gate B is modelled from sampled data rather than the full window. Stated in the report.

*Trigger to revisit:* if the sampled correlation between size fill and execution fill is below 0.7, size fill is not a good proxy and the forecaster must be restricted to the sampled window.

---

## R2 · RL agent fails to beat the optimizer

**Likelihood 4 · Impact 3 · Score 12 · Accepted with fallback**

P3 may not outperform P2. This is common: a well-formed constrained optimizer over a good forecast is a strong baseline, and RL frequently fails to beat it on low-dimensional problems.

*Mitigation:* P2 is built first and is a complete result on its own. The project's claim is "adaptive beats static", not "RL beats everything". P2 satisfies that claim.

*If it happens:* report it. "Learning added no value beyond forecast-then-optimize on this problem" is a legitimate and interesting finding, particularly with ablation A2 showing where the value actually came from. Do not tune P3 until it wins on the test split — that is the one action that would invalidate the evaluation.

---

## R3 · On-chain work consumes the schedule

**Likelihood 4 · Impact 4 · Score 16 · Mitigated by design**

Aiken, off-chain transaction building, key management and preprod deployment carry a real learning curve. It is the classic failure mode for this shape of project: the smart-contract work expands and the research contribution is never finished.

*Mitigation:* the architecture makes M7 strictly optional. Every result is produced in the simulator. M7 is scheduled last and is explicitly droppable at its gate without affecting any success criterion.

*Trigger:* if M7 is not deployed to preprod within three weeks of starting it, drop it and reallocate to evaluation depth. This decision is pre-authorised so it does not have to be argued for under time pressure.

---

## R4 · Congestion is not predictable enough to exploit

**Likelihood 3 · Impact 5 · Score 15 · Active**

The project assumes near-term block fullness is predictable enough that acting on the forecast beats acting on a constant. If block fullness is close to a random walk at a 20-second horizon, the forecaster adds nothing and the entire premise weakens.

*Impact:* the most severe risk in the register. It does not break the engineering, but it removes the reason for the machine learning.

*Mitigation:* test it **first**, in Phase 1, before building anything downstream. The autocorrelation of `fill_pct` and the MAE of a simple lag-1 predictor against a global-mean predictor answer this in an afternoon.

*If predictability is weak:* the project pivots to queue-aware rather than congestion-aware batching — still adaptive, still beats static baselines on latency through the pool-lock mechanism, and the negative forecasting result is reported as a finding about Cardano block dynamics. The ORACLE ablation quantifies exactly what was lost.

*Owner action:* this is the first analysis run after D1 collection, and its result is a gate on Phase 3.

---

## R5 · Estimator inaccuracy causes Gate A violations

**Likelihood 3 · Impact 4 · Score 12 · Mitigated**

If the size or execution-unit estimator under-counts, a batch that passes Gate A in simulation is invalid on-chain.

*Mitigation:* calibration against real preprod transactions is an M5 acceptance criterion (±5 % size, ±10 % execution units); a safety margin is applied to the Gate A cap; ablation A5 injects ±10 % estimation error and reports the effect.

*Residual:* simulation assumes perfect estimation (assumption A4). The ablation bounds the error.

---

## R6 · Reviewer challenges the simulator's validity

**Likelihood 3 · Impact 4 · Score 12 · Mitigated**

All results come from a simulator the team wrote. A reviewer is entitled to ask why it should be believed.

*Mitigation:*
- Congestion is **replayed from real recorded blocks**, not generated — say this first
- Four validation checks with expected outcomes derived independently of the policies (`08-SIMULATOR-SPEC.md` §9), including a fee replay against ground truth
- Every assumption stated in advance with its direction of bias, and the injection assumption is conservative
- D4 preprod submissions cross-check the estimator against reality

*Preparation:* the answer to "why trust the simulator" is rehearsed and evidence-backed before the review, not improvised in it.

---

## R7 · Free-tier API limits block collection

**Likelihood 3 · Impact 3 · Score 9 · Watch**

Koios has no key requirement but does rate-limit; Blockfrost free tier caps daily requests.

*Mitigation:* the collector backs off exponentially and is resumable from the last persisted height, so collection can be spread across days. Size-only collection (R1's mitigation) reduces call volume by more than two orders of magnitude.

---

## R8 · Protocol parameters change mid-project

**Likelihood 2 · Impact 3 · Score 6 · Watch**

Cardano governance can alter capacity limits and fee coefficients.

*Mitigation:* a single constants module (NFR-4). A change is a one-line edit plus a re-run. Any change is noted in the report with the date and its effect on results.

---

## R9 · Team member unavailable at a critical phase

**Likelihood 2 · Impact 4 · Score 8 · Watch**

Three members, several distinct skill areas: data engineering, ML, Cardano development.

*Mitigation:* the specification in `docs/` is detailed enough for any member to pick up another's module. No knowledge lives only in someone's head. Module boundaries are clean, with explicit interfaces.

---

## R10 · Results are negative across the board

**Likelihood 2 · Impact 4 · Score 8 · Accepted**

The adaptive policy may fail to beat tuned static baselines.

*Mitigation:* the evaluation protocol is fixed **before** results exist (`09-EVALUATION-PROTOCOL.md`), and §10 of that document states in advance what would falsify the thesis. A rigorously executed negative result with the ORACLE ablation explaining why is a defensible project.

*What must not happen:* adjusting the protocol, the baselines or the test split after seeing results. That converts a negative result into an invalid positive one.

---

## R11 · Leios changes the premise before submission

**Likelihood 2 · Impact 3 · Score 6 · Watch**

Ouroboros Leios raises base-layer throughput and targets exactly the congestion this project addresses.

*Mitigation:* position the work as a complementary application-layer optimization from the outset. Block capacity limits and single-UTXO pool concurrency do not disappear at higher throughput — batching remains necessary and the decision problem remains. This framing is in the PRD and the report introduction, not added defensively at the review.

---

## R12 · Key material or secrets committed

**Likelihood 2 · Impact 5 · Score 10 · Mitigated**

Testnet keys have no monetary value, but committed secrets are a habit-forming failure and a Blockfrost project ID is a real credential.

*Mitigation:* `.gitignore` blocks `*.skey`, `*.vkey`, `*.mnemonic`, `.env`; keys live outside the repository; API tokens come from environment variables only; a pre-commit hook greps staged files for key-shaped strings; the network guard makes mainnet unreachable regardless.

---

## Review log

| Date | Milestone | Changes |
|---|---|---|
| — | Specification | Register created; R1, R3, R4 identified as the schedule-critical set |

Update this table at every milestone gate. A risk register that is never updated is decoration.
