# 10 · Test Plan

Testing strategy, test cases and their acceptance criteria. In a research codebase the danger is not a crash — it is a **quietly wrong number** that survives into the report. The tests below target that.

---

## 1. Strategy

| Level | Scope | Tooling |
|---|---|---|
| Unit | Pure functions: estimator, gates, fee, metrics | pytest |
| Property | Invariants that must hold for all inputs | hypothesis |
| Integration | Module pairs: collector→D1, forecaster→policy, policy→simulator | pytest |
| System | Full episode, all policies, determinism | pytest, slow marker |
| Validation | Simulator behaviour against known-correct expectations | pytest |
| Calibration | Estimator against real preprod transactions | manual, recorded in D4 |

**Coverage target:** 90 % on `config/`, `build/estimator.py`, `policy/`, `sim/`, `eval/metrics.py`. Notebooks and plotting are excluded.

**Guiding principle:** every number that reaches the report is produced by code covered by a test that would fail if the number were wrong.

---

## 2. Critical invariant tests

These five failing means the results are invalid. They run on every commit.

| ID | Invariant | Test |
|---|---|---|
| **T-I1** | No submitted transaction violates Gate A | Property test over random queues and policies: assert `gate_a(n)` holds for every submission in every episode |
| **T-I2** | No order waits beyond `D_MAX` without an offered submission | System test: assert `max(oldest_wait at WAIT decisions) < D_MAX` |
| **T-I3** | No submission while `pool_locked` | System test over all policies |
| **T-I4** | Chronological split never leaks | Assert `max(train.abs_slot) < min(val.abs_slot) < min(test.abs_slot)` |
| **T-I5** | Determinism | Same seed twice, assert byte-identical metrics |

---

## 3. Unit tests

### Protocol constants (`config/protocol.py`)

| ID | Test | Expected |
|---|---|---|
| T-C1 | Values match the documented protocol parameters | Exact match to `07-CONSTRAINTS-COST-MODEL.md` §1 |
| T-C2 | No constant literal appears elsewhere in `src/` | Source-tree grep for `16384`, `90112`, `14000000`, `62000000`, `10000000000`, `40000000000`, `155381`, `44` in a fee context returns only `protocol.py` — enforces NFR-4 |
| T-C3 | Network guard | Loading settings with `network != "preprod"` raises |

### Fee model (`build/estimator.py`)

| ID | Test | Expected |
|---|---|---|
| T-F1 | Zero-size, zero-execution transaction | `fee == MIN_FEE_B` |
| T-F2 | Known transaction | Matches hand-computed value to the lovelace |
| T-F3 | Monotonicity | Fee strictly increasing in size, memory and steps |
| T-F4 | Per-user cost decreasing in `n` | `cost_per_user(n+1) < cost_per_user(n)` for all `n` |
| T-F5 | Amortization flattens | `cost_per_user(10) - cost_per_user(30)` is less than `cost_per_user(1) - cost_per_user(10)` — encodes the finding in §5 of the cost model |
| T-F6 | Fee replay against real transactions | Recomputed fee matches actual for 100 recorded preprod transactions |

### Gates

| ID | Test | Expected |
|---|---|---|
| T-G1 | Gate A is independent of block state | Same result for an empty and a 90 %-full block |
| T-G2 | Gate A binds around 20–40 orders | `max_n_satisfying_gate_a` in `[15, 50]` with calibrated per-order costs |
| T-G3 | Execution memory binds before size | With default estimates, memory is the limiting dimension |
| T-G4 | Gate B tightens with fullness | `max_n_gate_b(fill=0.9) <= max_n_gate_b(fill=0.1)` |
| T-G5 | Empty block does not raise the Gate A cap | `max_n(fill=0.0) == max_n_gate_a` — the regression test for the `adr/ADR-002` error |

T-G5 is the direct guard against the original design error. It must never be deleted.

### Queue (`queue/manager.py`)

| ID | Test | Expected |
|---|---|---|
| T-Q1 | FIFO preserved | `take(n)` always returns the `n` oldest |
| T-Q2 | Age continuity on return | Returned orders keep their original `arrival_slot` |
| T-Q3 | Expiry eviction | Orders past `ttl_slot` removed and counted |
| T-Q4 | Depth and oldest-wait consistency | Match independent recomputation from the arrival log |

### Metrics (`eval/metrics.py`)

| ID | Test | Expected |
|---|---|---|
| T-M1 | Jain index bounds | Equal waits give 1.0; maximally unequal approaches `1/n` |
| T-M2 | p95 on a known distribution | Matches `numpy.percentile` |
| T-M3 | Throughput | Settled orders per 1000 slots matches manual count |
| T-M4 | Empty episode | No division by zero; returns null metrics, not NaN silently |

---

## 4. Property tests

| ID | Property | Generator |
|---|---|---|
| T-P1 | Any policy output, once clamped, satisfies Gate A | Random observations |
| T-P2 | Latency is never negative | Random episodes |
| T-P3 | Orders in equals orders settled plus expired plus still queued | Random episodes — conservation |
| T-P4 | Increasing congestion never decreases mean latency for a fixed policy | Monotone congestion sequences |
| T-P5 | `fill_hat` always in `[0, 1]` | Random feature vectors, including adversarial |

T-P3 is a conservation law. If order accounting leaks, throughput and expiry are both wrong and the leak is otherwise invisible.

---

## 5. Integration tests

| ID | Scope | Assertion |
|---|---|---|
| T-N1 | Collector → D1 | Fixture API responses produce the exact expected parquet |
| T-N2 | Collector resumability | Interrupting and resuming yields the same file as an uninterrupted run |
| T-N3 | D1 → features | No NaN in feature columns after preprocessing; no future information in any lag |
| T-N4 | Forecaster fallback | With a corrupt model artifact, prediction still returns with `model == "ma"` |
| T-N5 | Policy → simulator | Every policy runs a full episode without error |
| T-N6 | Estimator shared path | Simulation and live mode call the identical estimator function |

T-N3 is the leakage guard at feature level: assert that every feature at slot `t` is computable from data at or before `t`.

---

## 6. Simulator validation

From `08-SIMULATOR-SPEC.md` §9. These are correctness tests for the *environment*, without which no policy result means anything.

| ID | Check | Expected |
|---|---|---|
| T-S1 | Determinism | Byte-identical metrics across two identical runs |
| T-S2 | NULL policy | Zero throughput, all orders expire |
| T-S3 | Greedy shape | E3 gives lowest L-mean and highest C-user of all policies |
| T-S4 | Large-M behaviour | E1 with `M > n_max` behaves like NULL until `D_MAX` forces submission |
| T-S5 | Head-of-line blocking | With an artificially long confirmation time, queue depth grows monotonically while locked |
| T-S6 | Real slot clock | Episode duration matches the recorded `abs_slot` span, not `4300 * 20 s` |

T-S3 is the strongest single check on the simulator. Greedy producing lowest latency and highest per-user cost follows directly from the cost model; if it does not hold, something is wrong upstream of every result.

T-S6 is the regression test for `adr/ADR-007`.

---

## 7. ML-specific tests

| ID | Test | Expected |
|---|---|---|
| T-L1 | Leakage check | Shuffling the split *improves* apparent test score; if not, the pipeline leaks |
| T-L2 | Forecaster beats a constant predictor | MAE below predicting the global mean |
| T-L3 | Action masking respected | Over 10,000 environment steps, no illegal action is executed even with a random agent |
| T-L4 | Reward scale calibration | Each reward term has comparable magnitude on the reference episode |
| T-L5 | Checkpoint reproducibility | Reloading a checkpoint reproduces evaluation metrics exactly |
| T-L6 | Policy collapse detector | Action entropy over a test episode above a floor; flags always-WAIT or always-MAX |

T-L3 is what makes invariants I1 and I2 structural rather than learned — it verifies that even a random agent cannot break them.

---

## 8. On-chain tests (M7, optional)

| ID | Test | Expected |
|---|---|---|
| T-O1 | User cancellation | An unbatched order can be reclaimed by its owner |
| T-O2 | Slippage enforcement | A batch paying below `min_out` to any user fails validation |
| T-O3 | Batcher authorisation | A batch signed by a non-authorised key fails validation |
| T-O4 | Pool invariant | `x * y` after fees is preserved or increased |
| T-O5 | Pass-through fee | User charged `network_fee / n + margin`, verifying `adr/ADR-006` |
| T-O6 | End-to-end | One swap settles on preprod; transaction hash recorded in D4 |

T-O2 and T-O3 are security tests: they verify that a malicious or buggy batcher cannot harm users. The batcher is untrusted for correctness by design.

---

## 9. Regression suite for the corrected assumptions

Each correction recorded in `adr/` gets a permanent test, so a future refactor cannot silently reintroduce the original error.

| ADR | Guard test |
|---|---|
| 001 latency not fees | T-F3: fee has no congestion input; the function signature takes no block state |
| 002 tx limits not block limits | T-G5: empty block does not raise the Gate A cap |
| 004 pool-lock failure model | T-S5: head-of-line blocking observable; and no "bounce" outcome exists in the outcome enum |
| 005 sampled execution units | T-N1: rows outside the sample carry `exunits_source == "absent"`, not zero |
| 006 pass-through fee | T-O5 |
| 007 real slot clock | T-S6 |

The ADR-005 guard matters: representing absent execution units as `0` rather than null would make blocks look empty and would corrupt every downstream congestion statistic.

---

## 10. Execution

| Suite | Trigger | Runtime |
|---|---|---|
| Unit + property | Every commit | < 30 s |
| Integration | Every commit | < 2 min |
| Simulator validation | Every commit | < 3 min |
| System + ML | Before a milestone | < 20 min |
| On-chain | Manual, before the demo | — |

```bash
pytest tests/ -m "not slow"      # commit gate
pytest tests/                     # milestone gate
pytest tests/ --cov=src/batcher --cov-report=term-missing
```

## 11. Definition of done, per milestone

A milestone is complete when its exit gate in `12-ROADMAP.md` is met **and** all tests at or below its level pass **and** no test is skipped without a written reason in the test file.
