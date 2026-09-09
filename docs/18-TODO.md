# 18 · Master TODO

Execution checklist for the whole project. Every task traces to a specification document, states its deliverable as a file path, and states the condition under which it may be ticked.

**Status at time of writing:** specification complete (docs 01–17, ADR 001–007); `src/` does not exist; no code written.

---

## How to use this document

| Rule | |
|---|---|
| Task IDs are stable | `P0-1`, `P1-4` … Never renumber. Add with a letter suffix (`P1-4a`) |
| A task is done when its **Done when** line is literally true | Not when the code exists — when the stated check passes |
| Do not start a phase before its predecessor's exit gate | The gates are in `12-ROADMAP.md`; they are repeated here |
| Tests named `T-xx` are defined in `10-TEST-PLAN.md` | Write the test in the same commit as the code it guards |
| `[opt]` marks a task that may be cut | Cut order is in `12-ROADMAP.md` §Scope-cut order |

**Owners** — three members (Vikranth Sai, Ganesh, Sowmya). A suggested split is recorded per phase; adjust it, but record it, because R9 assumes any member can pick up another's module.

---

## Progress tracker

| Phase | Tasks | Done | Exit gate met | Review |
|---|---|---|---|---|
| 0 · Foundation | 12 | 0 | ☐ | — |
| 1 · Data and premise | 16 | 0 | ☐ | Review 1 |
| 2 · Simulator and baselines | 18 | 0 | ☐ | Review 2 |
| 3 · Forecaster | 12 | 0 | ☐ | Review 2 |
| 4 · Optimizer P2 | 11 | 0 | ☐ | Review 2 |
| 5 · RL agent P3 | 13 | 0 | ☐ | Review 3 |
| 6 · Evaluation and write-up | 17 | 0 | ☐ | Review 3 |
| 7 · On-chain demo `[opt]` | 12 | 0 | ☐ | Review 3 |
| X · Cross-cutting | 14 | 0 | — | all |

---

# Phase 0 · Foundation

**Goal** — a repository that cannot silently produce a wrong number: constants in one place, mainnet unreachable, tests running on every commit.
**Depends on** — nothing. Start here.
**Suggested owner** — whoever sets up first; everyone must be able to run it.

### P0-1 · Create the package skeleton
Create the directory tree exactly as in `02-TECH-SPEC.md` §3: `src/batcher/{config,data,forecast,queue,policy,build,sim,eval}/`, plus `tests/`, `scripts/`, `experiments/`, `notebooks/`, `data/{raw,processed}/`, `figures/`, `tables/`.
Add `__init__.py` to every package directory.
**Done when** — `python -c "import batcher"` succeeds from a clean venv install.

### P0-2 · Packaging and dependencies
Write `pyproject.toml` targeting Python 3.11 with an `[project.optional-dependencies] dev` extra.
Runtime: `pandas`, `pyarrow`, `numpy`, `requests`, `lightgbm`, `torch`, `gymnasium`, `stable-baselines3`, `sb3-contrib`, `matplotlib`, `pycardano`, `python-dotenv`.
Dev: `pytest`, `pytest-cov`, `hypothesis`, `ruff`, `pre-commit`.
Pin exact versions and record them.
**Done when** — `pip install -e ".[dev]"` succeeds on a clean venv and `pytest --version` runs.
**Note** — any later dependency bump is a security-review trigger (CVE check on the new versions).

### P0-3 · Protocol constants module — the single source of truth
Write `src/batcher/config/protocol.py` containing exactly the constants listed in `07-CONSTRAINTS-COST-MODEL.md` §9, and nothing derived: `MAX_TX_SIZE`, `MAX_TX_EX_MEM`, `MAX_TX_EX_STEPS`, `MAX_BLOCK_SIZE`, `MAX_BLOCK_EX_MEM`, `MAX_BLOCK_EX_STEPS`, `MIN_FEE_A`, `MIN_FEE_B`, `PRICE_MEM`, `PRICE_STEPS`, `SLOT_SECONDS`, `ACTIVE_SLOT_COEFF`.
Add a docstring stating these are governance-changeable configuration, not literals.
**Done when** — **T-C1** passes: every value matches `07-CONSTRAINTS-COST-MODEL.md` §1 exactly, asserted in a test.

### P0-4 · The no-literals test
Write `tests/test_protocol_constants.py::test_no_constant_literals_outside_protocol` — walk `src/` and fail if `16384`, `90112`, `14000000`, `62000000`, `10000000000`, `40000000000`, `155381` appear in any file other than `config/protocol.py`. Treat `44` contextually (fee context only).
**Done when** — **T-C2** passes, and fails correctly when a literal is deliberately planted.
**Why it matters** — NFR-4. Without this the constants module drifts into decoration.

### P0-5 · Settings and the preprod network guard
Write `src/batcher/config/settings.py`: load `.env`, expose `CARDANO_NETWORK`, `BLOCKFROST_PROJECT_ID`, `BATCHER_KEY_DIR`.
Raise `SettingsError` at load time if `CARDANO_NETWORK != "preprod"`.
**Done when** — **T-C3** passes: loading settings with any other network raises, and no code path can override it.
**Why it matters** — NFR-7. Mainnet unreachable by construction, not by discipline.

### P0-6 · Derived project parameters
Add `src/batcher/config/params.py` for tunables that are *not* protocol constants: `D_MAX` (default 120 slots), `N_MIN` (default 8), `TTL_SLOTS`, `QUEUE_CAP`, forecast horizon `k = 20`, `ACTION_BUCKETS = {1,4,8,12,16,20,25,30,n_max}`.
Every one of these is tuned later on validation — mark each with a `# tuned: <phase>` comment.
**Done when** — no policy or simulator module contains a magic number that belongs here.

### P0-7 · Security hygiene
Write `.gitignore` blocking `*.skey`, `*.vkey`, `*.mnemonic`, `.env`, `data/raw/`, `data/processed/*.parquet`, model checkpoints, `.venv/`, `__pycache__/`.
**Done when** — `git status` is clean after a full collection and training run.

### P0-8 · Pre-commit secret scan
Configure `.pre-commit-config.yaml` with `ruff`, `ruff-format`, and a hook that greps staged files for key-shaped strings (`ed25519_sk`, `addr_test1`, long bech32/base58 runs, `BLOCKFROST_PROJECT_ID=`).
**Done when** — committing a file containing a planted fake key is blocked, and `--no-verify` is documented as forbidden (`13-RUNBOOK.md` §8).

### P0-9 · Test scaffold
Create `tests/` with `conftest.py`, a `slow` marker registered in `pyproject.toml`, and the two commit-gate commands from `10-TEST-PLAN.md` §10 documented in the README.
**Done when** — `pytest tests/ -m "not slow"` runs green in under 30 s with the tests written so far.

### P0-10 · CI
Add `.github/workflows/ci.yml`: Python 3.11, `pip install -e ".[dev]"`, `ruff check`, `pytest -m "not slow"`, coverage report.
**Done when** — CI is green on `main` and fails on a deliberately broken commit.

### P0-11 · Run manifest utility
Write `src/batcher/eval/manifest.py`: writes `experiments/<id>/manifest.json` capturing seed, git SHA, config hash, dataset checksum, protocol parameters, and later reward weights and tuned baseline values.
**Done when** — every entry point calls it. `02-TECH-SPEC.md` §9: "a result without a manifest is not a result".

### P0-12 · Repository status accuracy *(recurring)*
Keep the root `README.md` status line and `docs/README.md` §Status honest as phases complete.
**Done when** — the status table reflects reality at every phase gate. Re-tick each phase.

### ✅ Phase 0 exit gate
- [ ] T-C1, T-C2, T-C3 pass
- [ ] CI green
- [ ] Manifest writer exists and is called by at least one script
- [ ] `pytest -m "not slow"` under 30 s

---

# Phase 1 · Data and premise validation

**Goal** — collect D1, and answer the highest-impact unknown in the project: **is Cardano block congestion predictable at a ~20 s horizon?** (risk R4).
**Depends on** — Phase 0.
**Suggested owner** — the data-engineering member; the predictability analysis is reviewed by all three.

### P1-1 · Koios and Blockfrost clients
Write `src/batcher/data/sources.py`: a `BlockSource` protocol, `KoiosSource` (primary, no key) and `BlockfrostSource` (fallback), both returning the same normalised record. Handle HTTP 429 with exponential backoff 1 s → 60 s.
**Done when** — both clients fetch an identical known block and agree field-for-field; disagreement is logged and Koios preferred (`04-MODULE-SPECS.md` M1).

### P1-2 · M1 collector
Write `src/batcher/data/collector.py`: page `/blocks` descending, normalise to the D1 row shape, persist incrementally, resume from the last persisted height. Never write a partial page.
**Done when** — **T-N2** passes: interrupting and resuming produces the same file as an uninterrupted run.

### P1-3 · D1 schema and writer
Implement the exact schema in `05-DATA-SPEC.md` §D1 with correct dtypes and **nullable** `mem_exunits` / `step_exunits`. `fill_pct = block_size / MAX_BLOCK_SIZE` read from `config.protocol`. Compute `slot_gap`.
**Done when** — **T-N1** passes against fixture API responses, and rows outside the ExUnit sample carry `exunits_source == "absent"`, **never `0`** (ADR-005 regression guard).

### P1-4 · `scripts/collect.py`
Entry point with `--days`, `--out`, `--resume`, `--exunits-sample`. Writes parquet, `.sha256` and a manifest.
**Done when** — the three commands in `13-RUNBOOK.md` §3 run as documented.

### P1-5 · Collect 90 days of block data
Expect ~390,000 rows, ~12 MB parquet, a few hours under rate limiting.
**Done when** — no gaps in `block_height`; `abs_slot` strictly increasing; a re-run is byte-identical.
**Watch** — R7 (free-tier limits). Spread across days if needed; it is resumable by design.

### P1-6 · Collect the 7-day execution-unit sample
Per-transaction fetch over a 7-day window, summing redeemer `unit_mem` / `unit_steps` per block. Set `exunits_source = "per_tx"`.
**Done when** — the sampled window is complete and `mem_pct` / `step_pct` are populated only there.

### P1-7 · Dataset verifier
Write `scripts/verify_dataset.py`: height continuity, monotone slots, null policy on execution units, checksum match.
**Done when** — it passes on the collected D1 and fails on a deliberately corrupted copy.

### P1-8 · Dataset manifest and checksum
Commit `data/processed/d1_blocks_<start>_<end>.sha256` and `manifest.json` (window, row count, checksum, source, collector git SHA, protocol parameters in force). **Do not commit the parquet.**
**Done when** — an experiment referencing a mismatched checksum fails loudly.

### P1-9 · Preprocessing and cleaning
Write `src/batcher/data/features.py` per `05-DATA-SPEC.md` §Preprocessing: sort ascending, forward-fill at most one missing slot, leave 2+ slot gaps as holes excluded from feature windows, flag and exclude epoch boundaries, clip percentages to `[0,1]`.
**Done when** — no NaN in feature columns after preprocessing (**T-N3**, first half).

### P1-10 · Feature engineering
Same module: lags 1–20 of `fill_pct`, rolling mean and std over 5/10/20, `slot_gap` and its rolling mean, `tx_count` lags 1–5, hour-of-day sine/cosine, day of week. Queue features are injected at decision time, not stored in D1.
**Done when** — **T-N3** passes fully: every feature at slot `t` is computable from data at or before `t`. Write it as an explicit assertion, not a comment — this is the leakage guard.

### P1-11 · Chronological split utility
Implement the 70/15/15 chronological split as a function, never a shuffle. Expose the boundaries so the forecaster, the simulator and the RL trainer all use the *same* ones.
**Done when** — **T-I4** passes: `max(train.abs_slot) < min(val.abs_slot) < min(test.abs_slot)`.

### P1-12 · Congestion analysis script
Write `scripts/analyze_congestion.py`: produces F1 and F2 and prints the Phase 1 decision numbers.
**Done when** — it runs from the manifest and regenerates both figures identically.

### P1-13 · **Figure F1** — congestion over time
Per `17-UI-SPEC.md` F1: line over 90 days with a 48-hour inset; 80–90 % band shaded and labelled *inclusion-risk band* in place; one peak episode annotated with its date. Single series → no legend. Ship the table view.
**Done when** — script-generated (never hand-edited) with n, seed and split in the caption.
**Failure signature to report honestly** — if fill never approaches the band, the premise is weaker than assumed and the report must say so.

### P1-14 · **Figure F2** — distribution of block fill
Histogram, 2-point bins, bars above 80 % at full chroma. Direct-label the share of blocks above 80 % and above 90 %.
**Done when** — both share numbers are computed and recorded. **The >80 % number goes into the abstract** (see X-1).

### P1-15 · **Figure F3** — amortization curve *(early, analytic)*
Per `17-UI-SPEC.md` F3, derived analytically from `07-CONSTRAINTS-COST-MODEL.md` §5 — no experimental results needed. Label the knee near n ≈ 10; shade n > n_max as *infeasible (Gate A)*.
**Done when** — the curve reproduces the per-user cost table in §5 and the knee is visible.
**Why early** — it sharpens the objective before any policy is written, and pre-empts "why not always batch the maximum?".

### P1-16 · ⚠ **The predictability report — the Phase 1 decision artifact**
Compute and write up in `experiments/phase1-predictability/`:
- autocorrelation of `fill_pct` out to lag 20
- MAE of a lag-1 persistence predictor on the test split
- MAE of a global-mean predictor on the same split
- MAE of the E4 rolling-mean predictor (k = 20)
- correlation between size-based fill and execution-based fill **on the 7-day sample**

**Done when** — all five numbers are recorded with the code that produced them, and the team has made an explicit written decision.

**Decision rule** (`12-ROADMAP.md` Phase 1, risk R4):
- lag-1 clearly beats global-mean → congestion is predictable; proceed to Phase 3 as specified.
- lag-1 barely beats global-mean → **take the R4 fallback**: pivot to queue-aware batching, report the negative forecasting result as a genuine finding about Cardano block dynamics, and reduce Phase 3 to E4 plus one model.
- size↔execution correlation on the sample **below 0.7** → size fill is not a valid proxy (R1 trigger); restrict the forecaster to the sampled window and state it in the report.

### ✅ Phase 1 exit gate
- [ ] No gaps in `block_height`; `abs_slot` strictly increasing; re-run byte-identical
- [ ] F1 produced, showing the 80–90 % band
- [ ] Predictability answered in writing, decision recorded
- [ ] T-N1, T-N2, T-N3, T-I4 pass
- [ ] Risk register updated (R1, R4, R7)

**→ Review 1 material:** F1, F2, the congestion band numbers, the predictability finding. A data story, not a demo.

---

# Phase 2 · Simulator and baselines

**Goal** — a deterministic environment that replays real congestion, plus tuned static baselines to beat. Nothing downstream is trustworthy until T-S3 holds.
**Depends on** — Phase 1 (D1). Runs in parallel with Phase 3.
**Suggested owner** — the member who will also own the RL environment.

### P2-1 · Core dataclasses
Write `src/batcher/policy/base.py` with `Observation`, `Action`, `Outcome` and the `Policy` protocol exactly as in `02-TECH-SPEC.md` §4. All frozen dataclasses.
**Done when** — a static and a learned policy are interchangeable without the simulator knowing which is which.

### P2-2 · Order record and queue manager (M3)
Write `src/batcher/queue/manager.py`. Strict FIFO. Selection is always the prefix `Q[0:n]`, never a chosen subset — the deliberate fairness property that removes order-selection MEV from the design space. Returned orders reinsert at their original position with their original `arrival_slot`.
**Done when** — **T-Q1** (FIFO), **T-Q2** (age continuity, no reset), **T-Q3** (expiry eviction), **T-Q4** (depth and oldest-wait match an independent recomputation) all pass.

### P2-3 · Estimator — the pure half of M5
Write `src/batcher/build/estimator.py`: `tx_size(n, sizes)`, `tx_mem(n, mems)`, `tx_steps(n, steps)`, `fee_lovelace(size, mem, steps)`.
Seed per-order marginal costs from `07-CONSTRAINTS-COST-MODEL.md` §4 (~250–350 B, ~0.5 M mem, ~200 M steps) and mark them `# ESTIMATE — recalibrate in P7-9`.
**Done when** — **T-F1** (zero tx = `MIN_FEE_B`), **T-F2** (hand-computed value to the lovelace), **T-F3** (monotone in size/mem/steps, and the signature takes **no block state** — the ADR-001 guard), **T-F4** (`cost_per_user` decreasing in n) and **T-F5** (amortization flattens) all pass.

### P2-4 · Gate A and Gate B
Implement both exactly as in `02-TECH-SPEC.md` §5, plus `max_n_satisfying_gate_a(obs)` and `max_n_satisfying_gate_b(obs, fill_hat)`.
**Done when** — **T-G1** (Gate A identical for an empty and a 90 %-full block), **T-G2** (binds in [15, 50]), **T-G3** (memory binds before size), **T-G4** (Gate B tightens with fullness) and above all **T-G5** (`max_n(fill=0.0) == max_n_gate_a`) pass.
**T-G5 must never be deleted** — it is the permanent regression guard against the ADR-002 error in which an empty block was thought to permit a larger batch.

### P2-5 · D2 order generator
Write `src/batcher/sim/orders.py`: non-homogeneous Poisson `lambda(t) = lambda_base · diurnal(hour(t)) · burst(t)`, with the diurnal shape **fitted to the `tx_count` rhythm observed in D1** — not invented. Order ids derived from the seed, never a UUID.
**Done when** — the generated arrival rate reproduces the D1 diurnal shape, and regenerating from a manifest yields an identical stream.

### P2-6 · Arrival-rate configurations
Expose light (0.5×), matched (1.0×) and heavy (2.0×) as named configurations.
**Done when** — all three are reachable from `scripts/evaluate.py --rate {light,matched,heavy,all}`.

### P2-7 · Mempool and pool-lock model
Write `src/batcher/sim/mempool.py`. A submitted transaction **stays in the mempool** and is retried against each subsequent block; it is **never rejected for being late**. It leaves only by inclusion, TTL expiry or mempool eviction. `pool_locked` is set on submit and cleared on confirmation, TTL expiry or rollback.
**Done when** — the `Outcome` enum contains **no "bounce" state** (ADR-004 guard), and rollback is modelled as an independent low-probability event.

### P2-8 · M6 event loop
Write `src/batcher/sim/env.py::run_episode` exactly as in `08-SIMULATOR-SPEC.md` §3, including the `continue` at step 2 — **while the pool is locked, no decision exists**. Advance on recorded `abs_slot`, never a fixed 20 s tick.
**Done when** — **T-S6** passes: episode duration matches the recorded `abs_slot` span, not `4300 × 20 s` (ADR-007 guard).

### P2-9 · Determinism discipline
One seeded `numpy.random.Generator` per episode, passed explicitly. No global random state, no wall-clock in a decision path, no dict iteration order in a decision path, fixed-order float aggregation.
**Done when** — **T-S1** / **T-I5** pass: two runs with the same seed produce byte-identical metrics.

### P2-10 · Structural rules enforced outside the policy
In the environment, not the policy: (1) if `pool_locked`, only WAIT is legal; (2) if `oldest_wait >= D_MAX`, WAIT is masked; (3) any proposed `n` is clamped to the Gate A maximum.
**Done when** — **T-I1**, **T-I2**, **T-I3** pass and **T-P1** holds over random observations. A policy must be structurally incapable of expressing an infeasible or starving action.

### P2-11 · D3 decision log
Emit one row per observed block per episode per policy with every column in `05-DATA-SPEC.md` §D3. Write parquet.
**Done when** — a head-of-line-blocking episode is visible in the log exactly as in the worked example in that section.

### P2-12 · Baselines E1, E2, E3
Write `src/batcher/policy/static.py`: E1 fixed size `M`, E2 fixed interval `T`, E3 greedy — all subject to the same structural rules as the proposed policies.
**Done when** — **T-N5** passes: every policy runs a full episode without error.

### P2-13 · Metrics module
Write `src/batcher/eval/metrics.py`: L-mean, L-p95, C-user, X-rate, R-rate, TP, F-jain, W-max, S-slip, LOCK, BATCH-n per `09-EVALUATION-PROTOCOL.md` §2.
**Done when** — **T-M1** (Jain bounds), **T-M2** (p95 vs `numpy.percentile`), **T-M3** (throughput vs manual count) and **T-M4** (empty episode returns null metrics, not a silent NaN) pass.

### P2-14 · Paired-episode harness
Build the fixed 100-episode set per arrival rate: identical D1 window, identical order stream, identical seed presented to every policy.
**Done when** — swapping the policy changes nothing else about the episode, and no episode selection is possible after the fact.

### P2-15 · Conservation law
**Done when** — **T-P3** passes: orders in == settled + expired + still queued, over random episodes. If order accounting leaks, throughput and expiry are both wrong and the leak is otherwise invisible.

### P2-16 · Simulator validation V1–V3
- **T-S2 / V1** — a NULL policy that never submits gives zero throughput and all orders expire
- **T-S4 / V3** — E1 with `M > n_max` behaves like NULL until `D_MAX` forces submission
- **T-S5** — with an artificially long confirmation time, queue depth grows monotonically while locked (head-of-line blocking observable; ADR-004 guard)

**Done when** — all three pass.

### P2-17 · ⚠ **T-S3 — the greedy shape check**
E3 greedy must give the **lowest L-mean and the highest C-user** of all policies.
**Done when** — it holds.
**If it does not hold, stop.** That shape follows directly from the cost model; failing it means something upstream of every result is wrong. `12-ROADMAP.md` names this the single strongest correctness signal — do not proceed past this gate.

### P2-18 · Tune E1 and E2 on the validation split
Sweep `M` and `T`, select on validation only, record the tuned values in the manifest and in the results table.
**Done when** — tuned values are recorded. An untuned baseline is a straw man and invalidates the entire comparison.

### ✅ Phase 2 exit gate
- [ ] T-S1 … T-S6 pass, **especially T-S3**
- [ ] T-P3 conservation holds
- [ ] E1 and E2 tuned on validation, values recorded
- [ ] V4 fee replay complete or scheduled (X-4)

---

# Phase 3 · Congestion forecaster

**Goal** — beat the moving average, honestly.
**Depends on** — Phase 1 (D1 and the predictability decision). Parallel with Phase 2.
**Suggested owner** — the ML member.
**If P1-16 concluded "not predictable"** — reduce this phase to P3-1, P3-2 and P3-9 and report the negative result.

### P3-1 · E4 moving-average baseline
`src/batcher/forecast/baseline.py`: `fill_hat(t+1) = mean(fill(t-k+1..t))`, `k = 20`. Naive but strong on autocorrelated series.
**Done when** — **T-L2** passes: it beats a constant global-mean predictor.

### P3-2 · Forecast interface
Implement the `Forecast` dataclass from `04-MODULE-SPECS.md` M2: `fill_hat` for t+1..t+3, `mem_headroom`, `step_headroom`, `model` tag.
**Done when** — all three backends return the same type and predictions are clipped to `[0,1]` (**T-P5**, including adversarial feature vectors).

### P3-3 · P1a LightGBM
`src/batcher/forecast/lgbm.py`: ~500 trees, early stopping on validation MAE, feature set from `06-ML-SPEC.md` §3.
**Done when** — trains in under 5 min on CPU and inference is under 10 ms per call (NFR-1).

### P3-4 · P1b LSTM `[opt — cut #2]`
`src/batcher/forecast/lstm.py`: 2 layers, 64 hidden, sequence length 20, Adam. Under 45 min on CPU.
**Done when** — trained and evaluated. **Report the result whether or not it beats LightGBM.** A negative result honestly reported is stronger than a tuned-until-it-wins result.

### P3-5 · Training scripts
`scripts/train_forecaster.py --model {lgbm,lstm}` and `scripts/eval_forecaster.py --models lgbm lstm ma --split test`. Models written to `experiments/<id>/models/` with a manifest.
**Done when** — the runbook commands work verbatim.

### P3-6 · ⚠ Leakage tests
**Done when** — **T-L1** passes: deliberately shuffling the split *improves* the apparent test score. If it does not, the pipeline is leaking and every forecaster number is worthless. Combine with **T-N3** (feature level) and **T-I4** (split level).

### P3-7 · Forecaster metrics
MAE (primary), RMSE, and **directional accuracy (DIR)** — was the sign of the change predicted correctly? DIR matters more than MAE, because the policy makes a threshold comparison rather than using the exact value.
**Done when** — all three are reported for E4, P1a and P1b on the test split.

### P3-8 · Fallback path
If a model artifact fails to load, silently fall back to E4 with `model = "ma"`. The decision loop must never block on the forecaster.
**Done when** — **T-N4** passes with a deliberately corrupted artifact.

### P3-9 · **Figure F4** — forecast against actual
Per `17-UI-SPEC.md` F4: ~500 blocks of a test window; actual solid blue, forecast dashed in the same hue at step 250, both direct-labelled at the right edge; 80–90 % band shaded; two or three correct anticipations marked.
**Done when** — script-generated with provenance in the caption.
**Failure signature to report** — if the forecast is a smoothed lag of actual with no anticipation, it has learned persistence. Say so, and cite R4.

### P3-10 · Success metric S1
**Done when** — P1 test MAE is below E4 on the test split, tested paired for significance. **If S1 fails, report it and continue** — a policy over a moving-average forecast is still adaptive, and the finding stands on its own.

### P3-11 · Freeze P1
Once selected on validation, freeze the forecaster. P3 consumes its output as state; joint training is out of scope and listed as future work.
**Done when** — the checkpoint used by every downstream run is pinned in the manifest.

### P3-12 · Touch the test split exactly once
**Done when** — a written record exists of when the test split was used and for what. Every tuning decision happened on validation.

### ✅ Phase 3 exit gate
- [ ] T-I4, T-N3, T-L1 pass — no leakage at split or feature level
- [ ] S1 measured and reported, pass or fail
- [ ] F4 produced

---

# Phase 4 · Constrained optimizer (P2)

**Goal** — the project's defensible result. **If the schedule collapses, stop here and write up.**
**Depends on** — Phases 2 and 3.
**Suggested owner** — all three; this is the core contribution.

### P4-1 · P2 policy
Write `src/batcher/policy/optimizer.py` exactly as the pseudocode in `06-ML-SPEC.md` §4: pool-locked → WAIT; `n_feasible` from Gate A; deadline override; `n_fit` from Gate B against `fill_hat[0]`; `n = min(n_feasible, n_fit)`; wait below `N_MIN` only when a quieter block is predicted.
**Done when** — deterministic given identical observations, with every branch unit-tested.

### P4-2 · Tune `D_MAX`, `N_MIN` and horizon on validation
Sweep and select on validation only. `N_MIN = 8` starts from the amortization-curve knee, not from a guess — justify the final value from F3.
**Done when** — tuned values are recorded in the manifest and disclosed in the results table.

### P4-3 · ORACLE ablation variant
P2 given the **true** next-block fullness instead of `fill_hat`.
**Done when** — it runs on the same paired episodes. The P2→ORACLE gap is the honest measure of forecast quality — more informative than MAE alone, and worth running regardless of outcome.

### P4-4 · NULL reference policy
A policy that never submits — the sanity floor.
**Done when** — it appears in the results table as a reference row.

### P4-5 · `scripts/evaluate.py`
`--policy {e1,e2,e3,p2,p3,oracle,null,all} --episodes N --rate {light,matched,heavy,all} --seed S`. Writes D3, per-episode metric records and a manifest.
**Done when** — `--policy all` runs all seven over identical paired episodes.

### P4-6 · Full paired evaluation, E1–E3 against P2
All three arrival rates, 100 paired episodes each.
**Done when** — the run completes in roughly the budgeted 20 min and produces a metrics table.

### P4-7 · ⚠ Success metric S2 — zero Gate A violations
**Done when** — exactly zero Gate A violations across every episode of every run.
**S2 failing is a defect, not a result**, and it blocks the release. Do not widen the gate; fix the estimator.

### P4-8 · Ablation A2
P2 driven by the E4 moving average against P2 driven by P1.
**Done when** — reported. This answers "does the learned forecaster help the *policy*, or only the MAE?" — a reviewer will ask.

### P4-9 · Ablation A1
P2 with forecast against P2 with ORACLE.
**Done when** — the gap is quantified. That gap is what forecast error costs.

### P4-10 · Interim results table
Produce the `09-EVALUATION-PROTOCOL.md` §6 main table for NULL, E1, E2, E3, P2 and ORACLE, with medians and 95 % CIs and tuned baseline parameters disclosed.
**Done when** — every cell has a confidence interval.

### P4-11 · Update the risk register
Record R2 and R5 status and the P2 result.
**Done when** — `11-RISK-REGISTER.md` §Review log has a dated row. A register that is never updated is decoration.

### ✅ Phase 4 exit gate
- [ ] T-G1 … T-G5 pass, **especially T-G5**
- [ ] S2: zero Gate A violations
- [ ] P2 evaluated against all baselines at all three arrival rates
- [ ] **Checkpoint: the project now has a defensible result.** Everything after this is an upgrade.

**→ Review 2 material:** Chapter 5, simulator validation, forecaster beats baseline, P2 beats static batchers.

---

# Phase 5 · Reinforcement learning (P3)

**Goal** — a correctly trained and **honestly reported** agent. Beating P2 is *not* the exit gate.
**Depends on** — Phase 4.
**Suggested owner** — the ML member, with the environment owner reviewing the masking.

### P5-1 · Gymnasium environment
Wrap M6 as `BatchingEnv` per `08-SIMULATOR-SPEC.md` §8: `Box(0, 1, shape=(11,))` observation, `Discrete(len(ACTION_BUCKETS) + 1)` action.
**Done when** — a random agent completes an episode and the SB3 env checker passes.

### P5-2 · State vector
The 11-dimensional normalised vector from `06-ML-SPEC.md` §5, **including `gate_a_max_n`** so the agent can see its own feasible action range rather than infer it.
**Done when** — every component lies in roughly `[0,1]` and is unit-tested against hand-computed values.

### P5-3 · Action space and masking
Buckets `{1,4,8,12,16,20,25,30,n_max}` plus WAIT. Mask illegal actions rather than penalising them, and enforce the mask **inside `step`** as well as exposing `action_masks()`.
**Done when** — **T-L3** passes: over 10,000 steps with a random agent, no illegal action is executed. This is what makes invariants I1 and I2 structural rather than learned.

### P5-4 · Reward function
`r = -(w_cost·flat_fee_share(n) + w_latency·Σwait² / NORM + w_slip·slippage(n) + w_lock·slots_pool_locked)`.
Only the flat fee share — the marginal component is constant per order and would dilute the gradient. Quadratic waiting encodes the p95 objective. `slots_pool_locked` replaces the earlier "bounce penalty" (ADR-004).
**Done when** — there is **no inclusion-failure penalty anywhere in the reward**. A submitted transaction is not rejected for lateness; penalising a non-existent event teaches the agent the wrong model of its environment.

### P5-5 · ⚠ Reward weight calibration
Normalise each term to unit scale on a reference episode **before** applying weights. Left raw, the cost term (0.07–0.30 ADA) is numerically invisible beside latency (tens to hundreds of slots).
**Done when** — **T-L4** passes: each reward term has comparable magnitude on the reference episode, and the weights are recorded in the run manifest.

### P5-6 · Constant-product pool and slippage
Simulate `x·y = k` so slippage is endogenous — price drift between arrival and execution. It measures the mechanism, not real-world price risk (assumption A7).
**Done when** — S-slip is computable per episode and is monotone in waiting time under a fixed trade direction.

### P5-7 · DQN agent
2M timesteps, batch 64, lr 1e-4, gamma 0.99, replay 100k, epsilon annealed 1.0 → 0.05 over the first 20 %.
**Done when** — training completes in under 6 h on a laptop CPU (NFR-2).

### P5-8 · MaskablePPO alternative `[opt]`
`sb3-contrib` MaskablePPO, native action masking.
**Done when** — either it is trained and compared, or the decision to skip it is recorded (open question Q2 defaults to DQN).

### P5-9 · Training protocol
Episodes sampled from the **train** split only; checkpoints selected on validation; test split used once.
**Done when** — the split boundaries used are the same ones from P1-11, asserted in code.

### P5-10 · Five seeds
Train seeds 0–4 and report mean and standard deviation.
**Done when** — all five complete. **A single-seed RL result is not a result.**

### P5-11 · Diagnostics
Log episode return, action distribution over time, mean queue depth and mask-hit rate.
**Done when** — **T-L6** passes: action entropy over a test episode is above a floor, flagging always-WAIT and always-MAX collapse. A collapsed policy is detected by the action distribution, **not** by the return curve.

### P5-12 · Checkpoint reproducibility
**Done when** — **T-L5** passes: reloading a checkpoint reproduces evaluation metrics exactly.

### P5-13 · Ablations A3 and A4
- **A3** — P3 with `fill_hat` removed from the state. Does the agent use the forecast at all?
- **A4** — a linear rather than quadratic latency penalty. Does the tail penalty do the work?

**Done when** — both are reported. **If A3 shows no degradation, the claim weakens from "congestion-aware" to "queue-aware" and the report must say so.**

### ✅ Phase 5 exit gate
- [ ] T-L3 passes — a random agent cannot act illegally
- [ ] T-L4 passes — reward terms comparable in magnitude
- [ ] T-L6 passes — no policy collapse
- [ ] Five seeds trained, mean and std reported
- [ ] **P3 beating P2 is not required.** R2 accepts either outcome. Do **not** tune P3 until it wins on the test split — that is the one action that would invalidate the evaluation.

---

# Phase 6 · Evaluation and write-up

**Goal** — every claim traceable to a number with a confidence interval.
**Depends on** — Phases 4 and 5.
**Suggested owner** — all three; report assembly split by chapter.

### P6-1 · Full evaluation run
7 policies × 3 arrival rates × 100 paired episodes, plus 4 additional P3 seeds × 300 episodes.
**Done when** — complete, with a manifest, in roughly the budgeted 20 min.

### P6-2 · Paired statistics
Write `src/batcher/eval/stats.py` and `scripts/run_stats.py`: Wilcoxon signed-rank on per-episode paired differences; median paired difference with a 95 % bootstrap CI (10,000 resamples); Holm–Bonferroni across the primary metrics; `alpha = 0.05`.
**Done when** — non-parametric throughout (latency is heavy-tailed), and every p-value is reported alongside an effect size and CI. A significant but negligible improvement is reported as negligible.

### P6-3 · `scripts/make_tables.py`
**Done when** — the main table renders with medians and 95 % CIs, the best value per column in bold, significant improvements over the best static baseline marked, and tuned baseline parameters shown in the policy column.

### P6-4 · `scripts/make_figures.py`
One script generates F1–F8 including dark variants. Never hand-edit a figure.
**Done when** — deleting `figures/` and re-running regenerates every figure identically from a manifest.

### P6-5 · **Figure F5** — Pareto, L-p95 against C-user `headline`
Per `17-UI-SPEC.md` F5. **Every point directly labelled** — this discharges the light-mode contrast relief rule. "← better" on both axes; dominated region lightly shaded; 95 % bootstrap CI error bars on both axes; ORACLE as the neutral dashed ceiling.
**Done when** — produced, with the table view alongside.
**Failure signature** — proposed points sitting *along* the static frontier means no dominance: S5 fails, the result is a trade-off, and it must be reported as one.

### P6-6 · **Figure F6** — latency CDF
Up to four series, with a horizontal rule at 0.95 and each crossing marked. A CDF, not a histogram — the question is about quantiles.
**Done when** — produced. If curves separate at the median but converge in the tail, the mean improved and the tail did not: state the weaker claim.

### P6-7 · **Figure F7** — action distribution over congestion deciles
Stacked bars, SUBMIT (`#0ca30c`) and WAIT (muted `#898781`), with mean batch size as direct-labelled numerals above each bar — **not** a second y-axis.
**Done when** — produced.
**This is the figure that distinguishes a learned policy from a lucky one.** A flat profile means the agent ignores the forecast regardless of how good F5 looks; cross-check with A3.

### P6-8 · **Figure F8** — robustness across arrival rates
Three small-multiple panels (light / matched / heavy) on **one shared y-scale**. Per-panel scales would let a policy look consistent while its absolute latency tripled.
**Done when** — produced with 95 % CI error bars.

### P6-9 · Ablation A5
Inject ±10 % estimation error and report the effect on Gate A robustness.
**Done when** — reported. It bounds simulator assumption A4 (perfect estimation).

### P6-10 · Success metrics S1–S6 verdict table
For each: measured value, threshold, pass/fail.
**Done when** — every metric is reported **whether it passed or failed** (`12-ROADMAP.md` Definition of done #1).

### P6-11 · Report Chapters 1–5
Assemble per `16-REPORT-OUTLINE.md` — roughly 80 % is expansion of documents that already exist.
Write §1.4 (latency-not-fees) as a **highlighted subsection**: it is the intellectual pivot, and a reviewer who misses it will misread everything after it.
**Done when** — drafted and reviewed by the guide.

### P6-12 · UML and flow diagrams
Produce the eight diagrams in `16-REPORT-OUTLINE.md` §5.10: use case, class, sequence, activity, DFD level 0, DFD level 1, **state**, deployment.
**Done when** — all eight exist. Give the **state diagram** extra care — it is where the pool lock, the mechanism that makes the project non-trivial, becomes visible at a glance.

### P6-13 · Report Chapter 6 — Implementation
Show **code that embodies a decision** — the gates, the reward, the mask, the fee. Two well-annotated listings beat ten pages of paste.
**Done when** — drafted.

### P6-14 · Report Chapter 7 — Testing
Structure from `10-TEST-PLAN.md`. **§7.4 simulator validation (V1–V4) is the chapter's most important section** — it answers "why should we believe your simulator?" in the report rather than in the viva.
**Done when** — the results table (test ID, description, expected, actual, pass/fail) is complete with no unexplained skips.

### P6-15 · Report Chapter 8 — Results and Discussion
Every cell carries a confidence interval. §8.12 threats to validity, from `09-EVALUATION-PROTOCOL.md` §9, is **not optional**.
**Done when** — drafted, with every claim traceable to a metric.

### P6-16 · Report Chapter 9 — Conclusion and Future Work
§9.2 marks each of G1–G6 achieved, partially achieved or not achieved, **with evidence**. A partially achieved objective with evidence is stronger than an overclaimed one.
Future work: transaction chaining, joint forecaster-and-policy training, multi-pool scheduling, MEV-resistant order selection, re-evaluation under Leios, heterogeneous order costs.
**Done when** — drafted.

### P6-17 · Reproducibility audit
Write `scripts/reproduce.py --manifest experiments/<id>/manifest.json`: restore the seed, verify the dataset checksum, check out the recorded git SHA if it differs, re-run.
**Done when** — a reader can reproduce every figure from the repository, a seed and a dataset checksum, bit-identically (NFR-3). A mismatch is a defect to file, not to work around.

### ✅ Phase 6 exit gate
- [ ] Every claim in the report traceable to a metric with a confidence interval
- [ ] Test split used exactly once, with a written record
- [ ] Threats to validity written
- [ ] Full test suite passes with no unexplained skips

**→ Review 3 material:** F5, ablations, statistics, optional live demo.

---

# Phase 7 · On-chain demonstration `[opt — cut #1]`

**Goal** — one real swap on preprod, and estimator calibration against reality.
**Depends on** — Phase 0 only; scheduled last on purpose (risk R3).
**Suggested owner** — the Cardano-development member.

> ⚠ **Pre-authorised drop.** If preprod deployment is not achieved within **three weeks** of starting this phase, drop it and reallocate to evaluation depth. The decision is made now so it does not have to be argued under deadline pressure.

### P7-1 · Aiken toolchain
Install Aiken; scaffold `onchain/` with `aiken.toml`.
**Done when** — `aiken build && aiken check` runs on an empty project.

### P7-2 · `order.ak` validator
Enforce: datum shape; the consuming transaction pays `min_out` to `return_address`; only the authorised batcher key may execute; the user may always cancel and reclaim.
**Done when** — **T-O1** (user cancellation), **T-O2** (slippage enforcement) and **T-O3** (batcher authorisation) pass.
**Security note** — T-O2 and T-O3 are what make the batcher untrusted for correctness by design. A misbehaving or buggy batcher must be unable to short-change a user.

### P7-3 · Pass-through fee in `order.ak`
`user_pays = network_fee(n) / n + fixed_margin`, **not** a flat fee.
**Done when** — **T-O5** passes. Without this, amortization accrues to the batcher and goal G2 is not actually delivered to users (ADR-006).

### P7-4 · `pool.ak` validator
Constant product `x·y = k` after fees; reserves updated correctly; pool NFT preserved.
**Done when** — **T-O4** passes: `x·y` after fees is preserved or increased.

### P7-5 · Key management
Generate preprod keys into `BATCHER_KEY_DIR` (`~/.cardano-batcher/`), **outside the repository**. Never copy them in.
**Done when** — the pre-commit hook fires on a planted key and `git status` stays clean through a full live run.

### P7-6 · Deploy to preprod
`scripts/deploy_dex.py --network preprod`.
**Done when** — both validators are deployed and their script addresses are recorded.

### P7-7 · Submitter — the impure half of M5
`src/batcher/build/submitter.py` using PyCardano: build, sign, submit via Blockfrost, poll for inclusion until confirmed or TTL.
Re-check Gate A first — a violation here **raises**, it does not silently truncate. Every output must satisfy the minimum-ADA requirement. Set `ttl = current_slot + TTL_SLOTS`.
**Done when** — **T-N6** passes: simulation and live mode call the identical estimator function.

### P7-8 · Live daemon
`scripts/run_batcher.py --policy p2 --live --log-json`.
**Done when** — it runs against preprod, makes exactly one decision per block when unlocked, and shuts down cleanly only when `pool_locked` is false.

### P7-9 · ⚠ Estimator calibration against D4
Collect the D4 log (`05-DATA-SPEC.md` §D4) and compare estimated against actual size and execution units.
**Done when** — the estimator is within **±5 % on size** and **±10 % on execution units**.
**Then** — update the per-order cost estimates in `07-CONSTRAINTS-COST-MODEL.md` §4 from measurement and re-run P1-15 (F3) and P2-3. That document says explicitly: *"these figures are estimates until measured … and must be updated from measurement before the final report."*

### P7-10 · V4 fee replay
Recompute fees for 100 recorded transactions from the fee formula and compare against actual.
**Done when** — **T-F6** passes. This validates the fee model against ground truth independently of everything else in the system.

### P7-11 · End-to-end swap
**Done when** — **T-O6** passes: one swap settles on preprod, with the transaction hash recorded in D4 and in the report.

### P7-12 · Dashboard `[opt — lowest priority]`
Build only the **Run view** from `17-UI-SPEC.md` Part A — ~1 day budget, `localhost` only, reading the D3 stream.
Priorities within it: the **Pool panel** (LOCKED state, blocks in flight) and the **Decision panel showing Gate A and Gate B separately** — that is what makes ADR-002 and ADR-004 visible to a viva panel rather than merely asserted.
Honour the visual rules: WAIT carries no colour; every state ships an icon **and** a label; colour is never the sole carrier.
**Done when** — an operator can watch head-of-line blocking happen live. The Compare view is skippable — the results table plus F5 already carry it.

### ✅ Phase 7 exit gate
- [ ] T-O1 … T-O6 pass, including the security tests T-O2 and T-O3
- [ ] Estimator within ±5 % size and ±10 % execution units against D4
- [ ] `07-CONSTRAINTS-COST-MODEL.md` §4 updated from measurement

---

# Cross-cutting tasks

Not owned by a single phase. Several must happen before their phase, not after.

### X-1 · ⚠ Correct the three errors in `Doc/` before resubmission
`docs/README.md` §Authority names exactly three:
- [ ] **Deck slide 13** — the optimizer formula `capacity ← (1 − fill_hat) × 90,112` sizes batches against *block* limits. Replace it with the Gate A / Gate B distinction (ADR-002).
- [ ] **Deck slide 15** — the execution-unit footnote: correct the per-block step budget from 20 G to **40 G**, and note the sampled-collection decision (ADR-005).
- [ ] **`Doc/team-11-abstract.docx`** — the batch-sizing sentence currently describes sizing against block capacity. Rewrite it per ADR-002, and add the F2 ">80 % of blocks" number once P1-14 produces it.

**Done when** — all three artifacts match the specification, and `Doc/team-11-architecture.drawio` is either reconciled with `03-ARCHITECTURE.md` §2 or its divergence is recorded.

### X-2 · Update the decks for ADR-004 and ADR-007
The existing decks cover Reviews 1 and 2 and need updating only where they conflict: the "bounce penalty" failure model (→ pool-lock head-of-line blocking) and the fixed-tick simulator (→ recorded slot clock).
**Done when** — no deck slide contradicts an ADR.

### X-3 · Keep the risk register live *(recurring)*
Update `11-RISK-REGISTER.md` §Review log at **every** milestone gate — R1, R2, R3, R4, R5, R6 and R7 all have concrete triggers that fire during this project.
**Done when** — the log has a dated row per phase.

### X-4 · V4 fee replay without waiting for Phase 7
The fee replay can run against **recorded mainnet transactions** collected during Phase 1, not only against preprod submissions. Do it early — it validates the fee model independently of the simulator.
**Done when** — **T-F6** passes on 100 recorded transactions.

### X-5 · Coverage target
90 % on `config/`, `build/estimator.py`, `policy/`, `sim/`, `eval/metrics.py`. Notebooks and plotting excluded.
**Done when** — `pytest --cov=src/batcher --cov-report=term-missing` meets it and CI enforces it.

### X-6 · Regression suite for the corrected assumptions
Permanent guards so a future refactor cannot silently reintroduce an overturned assumption:

| ADR | Guard | Task |
|---|---|---|
| 001 latency not fees | T-F3 — `fee()` takes no block state | P2-3 |
| 002 tx limits not block limits | T-G5 — an empty block does not raise the Gate A cap | P2-4 |
| 004 pool-lock failure model | T-S5, plus no "bounce" in the outcome enum | P2-7, P2-16 |
| 005 sampled execution units | T-N1 — absent rows carry `"absent"`, never `0` | P1-3 |
| 006 pass-through fee | T-O5 | P7-3 |
| 007 real slot clock | T-S6 | P2-8 |

**Done when** — all six exist and are marked in the source as ADR guards that must not be deleted.
**The ADR-005 guard matters most quietly**: representing absent execution units as `0` rather than null would make blocks look empty and would corrupt every downstream congestion statistic.

### X-7 · Notebook discipline
Notebooks are exploratory only. **No result reaches the report through a notebook.**
**Done when** — every number and figure in the report is produced by a script under test.

### X-8 · Housekeeping policy
Committed: checksums, manifests, `experiments/<id>/`, figures, tables. Gitignored: `data/`, model checkpoints.
**Done when** — the policy in `13-RUNBOOK.md` §9 is enforced by `.gitignore` and observed in practice.

### X-9 · Resolve open question Q1 — execution units at scale
Answered in Phase 1 by P1-6 and the correlation in P1-16.
**Done when** — recorded in `01-PRD.md` §8 with the outcome.

### X-10 · Resolve open question Q2 — DQN or PPO
**Done when** — decided in Phase 5 and recorded. Default: DQN with action masking.

### X-11 · Resolve open question Q3 — is the dashboard built?
**Done when** — decided at Phase 7 and recorded. Default: no; terminal logs and plots suffice.

### X-12 · Resolve open question Q4 — the order arrival process
**Done when** — the fitted diurnal shape from P2-5 is documented in `05-DATA-SPEC.md` §D2 with its parameters.

### X-13 · Watch R11 — Leios
Position the work as a complementary application-layer optimization **from the outset**, in the PRD and the report introduction, not defensively at the review. Block capacity limits and single-UTXO pool concurrency do not disappear at higher throughput.
**Done when** — the framing appears in Chapter 1, written before Review 1.

### X-14 · Rehearse the answer to "why should we believe your simulator?"
In order: congestion is **replayed from real recorded blocks**, not generated; four validation checks with independently derived expected outcomes; every assumption stated in advance with its direction of bias; the injection assumption is conservative; D4 cross-checks the estimator against reality.
**Done when** — rehearsed and evidence-backed **before** Review 3, not improvised in it (risk R6).

---

## Never cut

From `12-ROADMAP.md`. Each is load-bearing for the validity of every number in the report.

1. Phase 1 predictability validation — P1-16
2. Phase 2 simulator validation — P2-16, P2-17
3. Gate A enforcement — P2-4, P2-10
4. The chronological split — P1-11, T-I4
5. The paired evaluation design — P2-14

## Cut order if the schedule slips

| Order | Cut | Tasks | Effect |
|---|---|---|---|
| 1 | Phase 7 on-chain demo | P7-1 … P7-12 | None on results |
| 2 | P1b LSTM | P3-4 | Report LightGBM only |
| 3 | Arrival-rate sweep, 3 → 1 | P2-6, P6-8 | Weakens the robustness claim; state it |
| 4 | P3 RL agent | P5-1 … P5-13 | The project stands on P2; "learned" becomes "adaptive" |
| 5 | Ablations A4, A5 | P5-13 (A4), P6-9 | Weakens analysis depth |

## Definition of done

The project is complete when:

1. Every success metric in `01-PRD.md` §6 has been measured and reported, **whether it passed or failed**
2. Every claim in the report traces to a metric with a confidence interval
3. The full test suite passes with no unexplained skips
4. A reader can reproduce every figure from the repository, a seed and a dataset checksum
5. Every assumption and limitation is stated in the report rather than left for a reviewer to find
