# 18 · Master TODO

Execution checklist for the whole project. Every task traces to a specification document, states its deliverable as a file path, and states the condition under which it may be ticked.

**Status:** specification complete (docs 01–18, ADR 001–008). **Phases 0–4 complete — the project has a defensible result.** D1 collected and verified: 388,781 blocks over 92 days, `sha256 48cd6f8b9a9e`, plus 17,280 blocks of execution-unit sampling across two regimes. Simulator validated, baselines tuned, forecaster trained and frozen, P2 evaluated against tuned baselines with zero Gate A violations. Phase 5 trained five DQN seeds at 200k steps: none collapsed, zero Gate A violations, and P3 dominates two P2 configurations while being dominated by none. **240 tests green.**

**Phase 1 outcomes:** the congestion premise did not survive measurement and the project was reframed around concurrency (`adr/ADR-008`); R4 fired and its fallback was taken; R1 fired, was diagnosed and closed; R13 was opened and absorbed.

**Open items carried forward** *(none block Phase 4)*

1. **The cost model is internally inconsistent.** `07-CONSTRAINTS-COST-MODEL.md` §4's Gate A arithmetic implies a pool-validator cost putting the flat fee at ~0.35 ADA, while §5's table implies ~0.24 ADA. `build/estimator.py` follows §4, the Gate A source.
2. **The fee formula is missing a Conway-era term.** V4 (X-4) shows it under-estimates script-bearing transactions by ~29 %, and a batch transaction is script-bearing. Absolute costs are low; comparisons are unaffected. P7-9 recalibrates from measurement and should settle both 1 and 2 together.
3. **`D_MAX` bounds the decision, not the wait.** G4 and I2 are worded as though it bounds how long an order waits; measured overshoot is up to 114 slots. The code is right and tested; the prose needs correcting when Chapter 4 is written.
4. **The `Doc/` artifacts still carry the old framing** — X-1 and X-2, now the largest documentation debt because of ADR-008.

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
| 0 · Foundation | 12 | 12 | ☑ | — |
| 1 · Data and premise | 16 | 16 | ☑ | Review 1 |
| 2 · Simulator and baselines | 18 | 18 | ☑ | Review 2 |
| 3 · Forecaster | 12 | 11 + 1 cut | ☑ | Review 2 |
| 4 · Optimizer P2 | 11 | 11 | ☑ | Review 2 |
| 5 · RL agent P3 | 13 | 10 | ☐ | Review 3 |
| 6 · Evaluation and write-up | 17 | 0 | ☐ | Review 3 |
| 7 · On-chain demo `[opt]` | 12 | 0 | ☐ | Review 3 |
| X · Cross-cutting | 14 | 6 | — | all |

**Cross-cutting detail** — done: X-4 (fee replay), X-5 (coverage, CI-enforced),
X-7, X-8, X-9, X-12. On track and recurring: X-3, X-6 (5 of 6 guards exist; the
sixth is T-O5 in Phase 7). Not started: X-1, X-2 (both `Doc/` rewrites, now larger
because of ADR-008), X-10 (Phase 5), X-11 (Phase 7), X-13, X-14.

### Artifacts produced so far

| Path | What |
|---|---|
| `data/processed/d1_blocks_20260613_20260913.parquet` | D1 — 388,781 blocks, 92 days *(gitignored; checksum committed)* |
| `data/processed/*.sha256`, `manifest.json` | Dataset provenance |
| `experiments/phase1-predictability/` | The R4 gate numbers and written decision |
| `experiments/phase2-tuning/` | E1/E2 sweeps; selected M=16, T=20 |
| `experiments/phase2-baselines/` | Per-episode metrics, 3 arrival rates |
| `experiments/phase2-fee-replay/` | V4 against 200 real transactions |
| `experiments/phase3-forecaster/` | Scores, leakage check, frozen LightGBM |
| `figures/F1…F4`, `tables/` | Report figures, script-generated |

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
- [x] T-C1, T-C2, T-C3 pass
- [x] CI green — `.github/workflows/ci.yml`; verified locally (`ruff check`, `pytest -m "not slow"`)
- [x] Manifest writer exists and is called by at least one script — `scripts/verify_setup.py`
- [x] `pytest -m "not slow"` under 30 s — 27 tests, ~7 s, 95 % coverage on the modules written so far

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

### P1-6 · Collect the execution-unit sample — **2 days, amended from 7**
Per-transaction fetch over the newest 2 days, summing redeemer `unit_mem` / `unit_steps` per block. Set `exunits_source = "per_tx"`.
Window narrowed from 7 days to 2 by team decision; rationale, measured API limits and the cost recorded in `adr/ADR-005` §Amendment. The report must state the window as two days.
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

> **Written decision, 2026-09-13 — full window, 388,781 blocks / 92 days, `sha256 48cd6f8b9a9e`.**
> Recorded in full in `adr/ADR-008`.
>
> | Number | Value |
> |---|---|
> | Autocorrelation, lag 1 / 5 / 20 | 0.3724 / 0.3216 / 0.2723 |
> | MAE, lag-1 persistence | 0.06069 |
> | MAE, global mean | 0.06065 |
> | MAE, rolling mean k=20 | **0.05157** (15.0 % better than the global mean) |
> | Size ↔ execution correlation | **0.912 congested / 0.588 quiet / 0.852 pooled** — R1 closed, `adr/ADR-005` §Result |
>
> **Decision.** Take the R4 fallback, with the qualification that the series is not
> structureless: a rolling mean beats the global mean by 15 % and autocorrelation
> persists to lag 20 at 0.27. Lag-1 persistence loses because it copies spikes
> forward and is penalised twice under MAE on a right-skewed series. Phase 3
> reduces to E4 plus LightGBM; the LSTM is cut on scope grounds, not on
> unpredictability grounds. S1 (P1 beating E4) stays open.
>
> **The larger finding.** Congestion is rare and **never sustained** — median fill
> 2.95 %, 0.564 % of blocks above 80 %, 2,193 congested blocks in 1,679 separate
> episodes, longest unbroken run 10 blocks (5 minutes), no run reaching 50. It
> concentrates into busy days (64 % in the busiest five of 93) but even the busiest
> day runs only 11.2 % of its blocks above 80 %. The project is reframed from
> congestion to concurrency: `adr/ADR-008`, risk R13. Objective, goals and
> non-goals are unchanged.
>
> **The proxy.** Size fill is a valid stand-in for execution fill and the
> forecaster trains on the full 92 days. The first sample failed the 0.7 threshold
> at 0.588 — taken from the quietest two days, where half the blocks run no
> scripts and nothing approaches a limit. A second sample aimed at the busiest day
> gives 0.912. Both are reported; see `adr/ADR-005` §Result, including its stated
> threat to validity.
>
> **Carried into Phase 2:** the paired-episode set (P2-14) must deliberately
> include congested days, or uniform sampling will describe an empty chain only.
> Gate B may also be evaluated on size alone: execution steps never exceeded 49.9 %
> of the block budget in 17,280 sampled blocks, and memory bound without size in
> exactly one.

**Decision rule** (`12-ROADMAP.md` Phase 1, risk R4):
- lag-1 clearly beats global-mean → congestion is predictable; proceed to Phase 3 as specified.
- lag-1 barely beats global-mean → **take the R4 fallback**: pivot to queue-aware batching, report the negative forecasting result as a genuine finding about Cardano block dynamics, and reduce Phase 3 to E4 plus one model.
- size↔execution correlation on the sample **below 0.7** → size fill is not a valid proxy (R1 trigger); restrict the forecaster to the sampled window and state it in the report.

### ✅ Phase 1 exit gate
- [x] No gaps in `block_height`; `abs_slot` strictly increasing; re-run byte-identical — 388,781 rows verified, `sha256 48cd6f8b9a9e`; window pinnable via `--start-height/--end-height`
- [x] F1 produced — showing the band is **reached by 0.564 % of blocks and never sustained**, which is the honest answer to the question F1 asks
- [x] Predictability answered in writing, decision recorded — `adr/ADR-008`, roadmap Phase 1, P1-16 above
- [x] T-N1, T-N2, T-N3, T-I4 pass — 108 tests green
- [x] Risk register updated — R1 closed, R4 fired and absorbed, R13 opened, R7 not realised

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
- [x] T-S1 … T-S6 pass, **especially T-S3** — greedy gives the lowest latency and highest per-user cost in unit tests *and* on real replayed D1 at all three arrival rates
- [x] T-P3 conservation holds — asserted per episode in `scripts/evaluate.py`, so a leak fails the run rather than the suite alone
- [x] E1 and E2 tuned on validation, values recorded — **E1 M=16, E2 T=20**, selected on L-p95; sweeps in `experiments/phase2-tuning/sweeps.json`
- [x] V4 fee replay complete (X-4) — formula never exceeds the actual fee on 200 recorded transactions; a ~29 % systematic under-estimate on script-bearing transactions is recorded there

**Three defects found in Phase 2, all regression-tested:**
1. **Order conservation leaked.** The queue had an admission cap, so orders arriving at a full queue vanished from the in == settled + expired + queued identity. The cap was also wrong modelling — an order is a UTXO already on chain, and a batcher has no mechanism to refuse one. The queue is now unbounded and `QUEUE_CAP` is documented as an RL normalisation constant only.
2. **The arrival process ran 4.5× hot.** A per-block burst probability of 0.02 with hour-long bursts put the stream in burst ~78 % of the time, so 13.6 orders/block arrived where 3.0 were configured. E1 appeared to fail catastrophically at small `M` (68 % expiry) — a modelling artefact, not a policy result. Bursts are now expressed as onsets per day.
3. **D3 logged post-action queue depth**, so every SUBMIT row read as though it had decided on an empty queue, silently defeating the I2 deadline assertion. It now records what the policy saw.

**Specification gap to carry into the report.** I2 and goal G4 read as though `D_MAX` bounds how long an order waits. It does not: it bounds the *decision*. A decision exists only when a block arrives and the pool is free, so an order can pass `D_MAX` and wait until the next such moment — measured overshoot up to **114 slots**. The invariant that actually holds, and is now tested, is that **no decision opportunity past the deadline results in WAIT**. Report the bound as `D_MAX` + one decision gap.

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

### P3-4 · P1b LSTM `[opt — CUT]`
**Cut**, per the Phase 1 decision recorded in `12-ROADMAP.md`. The grounds are
scope, not unpredictability: the forecaster's *policy* leverage is limited because
Gate B binds about once in 180 blocks, so a second deep variant cannot earn its
place. Phase 3 reports E4 plus LightGBM. Original task retained below for the record.

### ~~P3-4 · P1b LSTM~~ `[cut #2]`
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
- [x] T-I4, T-N3, T-L1 pass — no leakage at split or feature level
- [x] S1 measured and reported — **PASS, +11.2 %**
- [x] F4 produced — and it reports the failure signature, see below

**Results (test split, 58,316 rows, touched once):**

| Model | MAE | RMSE | DIR |
|---|---|---|---|
| **P1a LightGBM** | **0.04578** | 0.08364 | **0.742** |
| E4 moving average | 0.05157 | **0.08355** | 0.710 |
| Global mean | 0.06065 | 0.08867 | 0.662 |
| Lag-1 persistence | 0.06069 | 0.10044 | 0.000 |

S1 passes on MAE (+11.2 %) and on directional accuracy (+3.1 points). It does
**not** win on RMSE — E4 is a hair better there, which follows from training on an
L1 objective and is reported rather than hidden.

⚠ **The S1 pass does not mean what it appears to mean.** F4's anticipation
diagnostic: the forecast correlates **0.399** with the value it predicts and
**0.616** with the value before it. It is a smoothed lag — the failure signature
`17-UI-SPEC.md` F4 names. Visually, the forecast never once enters the 80–90 %
band across the test window while the actual reaches 100 % repeatedly.

**What the model actually learned** is the slowly varying *level* of congestion,
and it exploits mean reversion around that level — which is where the MAE and DIR
gains come from. It cannot anticipate spikes, and spikes are the only thing Gate B
cares about. So the practical value of the forecaster to the *policy* is close to
zero, which is precisely what ADR-008 predicted when it demoted the forecaster to
a secondary input. Ablation A2 (P2 on E4 vs P2 on P1) will quantify it; expect
little difference, and report that.

**T-L1 note.** The first implementation of the leakage check compared MAEs
computed on *different rows* — the chronological test window against a random
15 % — and declared the pipeline "LEAKING". Periods differ in intrinsic
difficulty, so that comparison measured which window was easier. Rebuilt to score
both models on identical rows: leaking then helps by +2.6 %, and the verdict is
clean.

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

### Phase 4 results (validation split, matched rate, 10 paired episodes)

**S2 · zero Gate A violations — PASS.** Zero across every policy, every arrival
rate, every episode. Achieved by construction, not by training.

**The L-p95 tuning rule selects a degenerate P2.** The sweep picks
`p2(D=60,N=1)`, which is **byte-identical to greedy** on every metric at all
three arrival rates. That is not a bug: with `N_MIN=1` the amortization-wait
branch can never fire, and Gate B binds about once in 180 blocks, so nothing is
left to decide. **On a chain where capacity does not bind, the latency-optimal
batcher *is* greedy.** The rule was applied as documented and its output reported
rather than the rule being changed after the fact — but the single selected point
is not the informative artifact here. The frontier is.

**The frontier (P2 on LightGBM, sweeping `N_MIN`):**

| Policy | L-p95 | C-user | batch n | lock |
|---|---|---|---|---|
| p2(N=1) ≡ greedy | 120.0 | 160,439 | 3.4 | 0.69 |
| **p2(N=4)** | **127.0** | **127,469** | 4.9 | 0.46 |
| p2(N=8) | 142.0 | 113,604 | 6.1 | 0.37 |
| p2(N=12) | 156.0 | 108,876 | 6.7 | 0.34 |
| p2(N=20) | 165.0 | 106,920 | 7.0 | 0.32 |
| e2(T=20) *tuned* | 133.0 | 131,593 | 4.7 | 0.50 |
| e1(M=16) *tuned* | 181.5 | 82,986 | 13.2 | 0.17 |

**S5 · Pareto — PASS, with the detail stated.** `p2(N=4)` dominates the tuned
`e2(T=20)` on **both** axes (127.0 < 133.0 L-p95, and 127,469 < 131,593 C-user).
No static baseline dominates any P2 point, and all five P2 points sit on the
joint frontier. It does **not** dominate E3 or E1: those sit at opposite extremes
of the trade-off, and no single point can dominate both ends of a frontier — so
the strict reading of "dominates E1–E3" is unachievable by construction, and the
claim reported is the one just stated.

**A1 · what forecast error costs the policy.** P2 on LightGBM against P2 on the
true next-block fill, at equal `N_MIN`:

| N_MIN | L-p95 (P1) | L-p95 (oracle) | gap |
|---|---|---|---|
| 4 | 127.0 | 126.0 | 0.8 % |
| 8 | 142.0 | 134.0 | 5.6 % |
| 12 | 156.0 | 143.0 | 8.3 % |
| 20 | 165.0 | 151.0 | 8.5 % |

A perfect forecast is worth **5–9 % of tail latency** at equal cost, and the gap
widens as the policy leans on the forecast more. That is the honest measure of
forecast quality, and it is far more interpretable than the MAE.

⚠ **A2 · confounded as specified, and reported that way.** P2 on E4 is
**identical to greedy at every `N_MIN`**. E4 is a moving average, so its forecast
is *flat across the horizon*; `quieter_block_predicted` compares later horizon
steps against the next one and can therefore never fire. A2 as written compares
a **horizon-varying forecast against a flat one**, not a strong forecast against
a weak one. The measured differences (L-p95 +7 to +45 slots, C-user −33k to −54k
lovelace) are real but answer the wrong question. To answer the intended one,
A2 needs a naive baseline that varies across the horizon — recorded as an open
item rather than quietly reinterpreted.

### ✅ Phase 4 exit gate
- [x] T-G1 … T-G5 pass, **especially T-G5**
- [x] S2: zero Gate A violations — across every policy, rate and episode
- [x] P2 evaluated against all baselines at all three arrival rates
- [x] **Checkpoint: the project now has a defensible result.** Everything after this is an upgrade.

**Open item from this phase:** A2 needs a horizon-varying naive baseline to be
meaningful (see above). It does not block Phase 5.

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

### Phase 5 status — environment and training pipeline built and validated

**Done (P5-1 … P5-6, P5-11 partial):** Gymnasium env, 11-D state, masked action
space, reward with calibrated weights, constant-product slippage, and the
diagnostics. `scripts/train_rl.py` runs end to end and the SB3 env checker
passes. **240 tests.**

| Guard | Status |
|---|---|
| **T-L3** — a random agent cannot execute an illegal action | ✅ masked inside `step`, not only exposed |
| **T-L4** — reward terms commensurable | ✅ measured normalisers; latency is ~19× cost raw, hence mandatory |
| **T-L6** — collapse detector | ✅ entropy floor; always-WAIT scores 0.0, a trained agent 0.68 |
| **T-I1/T-I2 at the RL boundary** | ✅ every proposed `n` is Gate A feasible; always-WAIT still settles orders |
| ADR-004 guard | ✅ a test asserts no rejection/bounce/fail term exists in the reward |

**Smoke run (8,000 steps, seed 0, validation split):** agent return
−1,871 ± 534 against a greedy-by-mask reference of −3,976; action entropy 0.678;
**not collapsed**. Encouraging, but 8k steps is not a result.

**A real bug the environment tests caught.** The first implementation never
advanced the block index when the agent chose WAIT, so an episode looped on one
block forever — 5,000 steps on a 300-block window with one order settled. Stepping
is now `act → advance → seek the next decision point`, and
`test_the_episode_terminates_and_advances` pins it.

### ⚠ Training budget reduced from 2M to 200k steps — team decision, must be reported

`06-ML-SPEC.md` §5 specifies 2M timesteps per seed. **Five seeds are trained at
200,000 steps instead — a tenth of the specified budget.**

*Why.* Five seeds is the part that is not negotiable: "a single-seed RL result is
not a result". At ~6 h per seed the full budget is ~30 h of laptop CPU, against
~3 h at the reduced budget. Given that P3 beating P2 is **not** an exit gate, and
that the project's defensible result already exists at Phase 4, spending the
seed count to buy step count would have been the wrong trade.

*What it costs.* The agent is very likely under-trained. Any result must be read
as a **lower bound** on what DQN could achieve here, and the report must say so
in those words. If P3 underperforms P2, "under-trained at a tenth of the
specified budget" is a live explanation that cannot be ruled out — and it must be
offered rather than left for a reviewer to raise.

*What it does not change.* The exit gate is unaffected: the mask still holds, the
reward is still calibrated, collapse is still detected, and five seeds are still
reported with mean and standard deviation.

*Trigger to revisit.* If P3 comes within noise of P2, or if the action-entropy
trace is still rising at 200k, run the full budget on one seed before concluding
anything. Improvement still in progress at the cutoff is evidence of
under-training, not of a ceiling.

### Phase 5 results — five seeds at 200k steps, validation split

Scored through the **same metric path as every other policy**. The RL return is a
weighted penalty in reward units and is not comparable to P2's numbers; running
the checkpoints through `metrics.compute` is what makes a P3-against-P2 claim
mean anything.

| | P3 (mean ± sd, 5 seeds) |
|---|---|
| L-p95 | **149.0 ± 13.1** |
| C-user | **87,669 ± 6,211** |
| batch n | 12.28 ± 1.81 |
| lock occupancy | 0.26 |
| expiry rate | 0.00 |
| **Gate A violations** | **0** — S2 holds for the learned agent too |
| Collapsed seeds | **0 of 5** (T-L6) |

**Against the whole P2 frontier, same episodes and metrics:**

| Policy | L-p95 | C-user |
|---|---|---|
| e3(greedy) ≡ p2(N=1) | 114.0 | 150,168 |
| p2(N=4) | 121.5 | 116,759 |
| p2(N=8) | 131.0 | 102,729 |
| p2(N=12) | 150.3 | 98,062 |
| p2(N=20) | 156.3 | 96,457 |
| **P3 (mean)** | **149.0** | **87,669** |

**P3 dominates `p2(N=12)` and `p2(N=20)` on both axes, and is dominated by
nothing.** It reaches a per-user cost no P2 configuration attains — 9 % below
P2's best — at a tail latency between P2's N=12 and N=20. The learned policy
therefore *extends* the achievable frontier rather than merely sitting on it,
and it does so at a tenth of the specified training budget.

⚠ **Suggestive, not established.** Four episodes, five seeds, medians without
confidence intervals, and the validation split. The paired Wilcoxon tests and
bootstrap CIs are Phase 6 work, and the test split is still untouched. Seed
variance is real: sd is 8.8 % of the L-p95 mean, and seed 0 behaves like a
different policy entirely (L-p95 123.5, entropy 0.937, batch n 8.9 against ~13
for the rest).

### ⚠ The agent is queue-aware, not congestion-aware

Figure **F7** is not flat — submit rate climbs from 7 % in the emptiest decile to
53 % in the fullest, a ratio of 7.8. On its own that looks like congestion
reasoning. It is not.

Zeroing `fill_hat` in the observation at inference time changes almost nothing:

| Seed | L-p95 with forecast | forecast zeroed | Δ |
|---|---|---|---|
| 0 | 123.5 | 121.5 | −1.6 % |
| 1 | 157.5 | 155.0 | −1.6 % |
| 2 | 152.0 | 149.5 | −1.6 % |
| 3 | 152.0 | 149.0 | −2.0 % |
| 4 | 160.0 | 167.5 | +4.7 % |

Mean |Δ| is **2.3 %**, and **four of five seeds are slightly better without the
forecast**. The rising F7 profile is therefore a **queue-depth confound** — fuller
blocks coincide with busier periods, longer slot gaps and deeper queues — not
congestion avoidance.

This is exactly the outcome P5-13 was written to detect: *"If A3 shows no
degradation, the claim weakens from 'congestion-aware' to 'queue-aware' and the
report must say so."* **It must say so.** It is also the third independent route
to ADR-008's conclusion, after the F4 lag diagnostic and the A1 oracle gap.

*Caveat on method.* This is an **inference-time** ablation — the forecast inputs
are zeroed on a trained agent. A3 as specified **retrains** without the feature,
and a retrained agent might lean harder on the remaining state. The cheap version
is suggestive and points the same way as F4 and A1; the specified version is still
owed.

**Remaining (P5-9, P5-12, P5-13):** checkpoint reproducibility (T-L5), the
retrained A3, and A4 (linear vs quadratic latency penalty).

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

### Phase 6 results — test split, evaluated once (P6-1, P6-2, P6-10) ✅

`scripts/final_evaluation.py` → `experiments/phase6-final-evaluation/`, 8 policies ×
3 rates × 100 paired episodes, P3 seeds 0–4 seed-averaged per episode. Finished
2026-09-14 18:45 IST. Statistics: `scripts/run_stats.py` → `tables/main_results.md`,
`stats.json`. Figures F5, F6, F8: `scripts/make_figures.py`.

Matched rate, medians over episodes:

| Policy | L-p95 | C-user | F-jain |
|---|---|---|---|
| e3(greedy) ≡ p2(N=1) | **119.0** | 157,445 | 0.75 |
| p2(D=120,N=4) | 125.0 | 127,738 | 0.77 |
| oracle(N=4) | 124.0 | 124,567 | 0.76 |
| e2(T=20) | 130.5 | 129,729 | 0.78 |
| p3(dqn) | 158.6 | 89,704 | **0.83** |
| e1(M=16) | 183.3 | **82,906** | **0.83** |

| Metric | Verdict |
|---|---|
| S1 | PASS (Phase 3) |
| S2 | **PASS** — zero Gate A violations across the whole run |
| S3 | **FAIL at all rates** — best static on L-p95 is greedy, and p2(N=1) *is* greedy |
| S4 | PASS for P2; P3 FAIL at heavy (X-rate 0.07, one seed) |
| S5 | **matched only** — p2(N=4) dominates e2(T=20) by median; the paired latency difference is not significant (−5.1 [−14.5, +0.5]), the cost saving is |
| S6 | PASS for P3 at all rates; P2 FAIL at light and matched (0.77 vs E1 0.84/0.83) |

**Reading.** A trade-off result, not a dominance result — the outcome ADR-008
predicted: with capacity binding ~1 block in 180, greedy is latency-optimal and
cannot be beaten by waiting. P2(N=4) is the most robust policy across load (tracks
greedy's latency at every rate, 12–25 % cheaper), while tuned E1 collapses at the
heavy rate (L-p95 1,203, Jain 0.38) and E2 degrades to 253.5.

⚠ **P3 seed 3 fails at the heavy rate**: median L-p95 3,604, 34 % expiry, expiry in
65 of 100 episodes. The other four seeds give L-p95 186.5 [152.5, 253.9], zero
expiry, C-user 77,916 — cheaper than E1 at a sixth of its latency. Reported with
all five seeds; not excluded after the fact.

⚠ **ORACLE ≈ P2**: a perfect forecast is worth 1 slot at matched and nothing at
heavy — the fourth route to ADR-008.

⚠ **Provenance.** The manifest records `0a5c7d5`, clean — the revision at
*completion*, not at launch; the run started before its tooling was committed.
Stated in the report's threats to validity; not re-run (the test split is spent).

### Phase 5 owed items closed — T-L5, retrained A3, A4 ✅

Tooling committed first (`d171038`), then run: `train_rl.py --no-forecast` /
`--linear-latency`, five seeds each at 200k steps, trained in parallel with one
CPU thread per run (19:05–19:40); scored with `evaluate_rl.py --checkpoints …` on
the same four validation episodes as Phase 5. Test split not touched.

*Provenance.* The ten training manifests record `d171038` with `dirty: true`. The
only uncommitted paths at that moment were the sibling runs' own new
`experiments/` output folders — `git diff HEAD -- src scripts tests` was empty — so
the code that ran is exactly `d171038`. The "commit, then run" fix holds; the dirty
flag is an artefact of parallel runs writing into the tree.

**T-L5 — PASS.** `scripts/check_checkpoints.py` reloads all five
`phase5-dqn-seed*` checkpoints and reproduces every recorded metric in
`phase5-evaluation/rl_evaluation.json` exactly. Unit test in
`tests/test_rl_ablations.py`. → `experiments/phase6-checkpoint-reproducibility/`

| | P3 (Phase 5) | A3 no forecast | A4 linear latency |
|---|---|---|---|
| L-p95 | 149.0 ± 13.1 | 155.1 ± 11.7 | 148.8 ± 16.0 |
| C-user | 87,669 ± 6,211 | 87,423 ± 5,457 | 89,550 ± 8,204 |
| violations / expiry / collapsed | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |

**A3.** Retrained without the forecast: +4.1 % tail latency, cost unchanged. All
five seeds slower (0.5–12.5 slots) but the mean effect is below seed sd, on four
episodes — suggestive. Reverses the sign of the inference-time test (which zeroed
the input on agents trained with it). The claim stays **queue-aware**; the forecast
is a minor secondary input. → `experiments/phase6-ablation-a3/`

**A4.** Linear penalty: tail latency unchanged, cost +2.1 %, inside seed variation.
The D_MAX mask bounds the tail structurally, so the quadratic term is not what
does the work. → `experiments/phase6-ablation-a4/`

### A2 re-specified with a horizon-varying naive baseline (P4-8 open item) ✅

Committed first (`b6aaf24`), then run: `scripts/ablation_a2.py`, validation split,
12 paired episodes, matched rate. New baseline `MeanReverting` (E4b):
`fill_hat(t+h) = m_t + phi^h (fill_t − m_t)`, `m_t` = E4 rolling mean, `phi`
fitted on train = **0.084**. → `experiments/phase6-ablation-a2/`

| Forecaster | quieter-branch fires | MAE t+1 | DIR |
|---|---|---|---|
| E4 flat | **0.0 %** — the confound, confirmed | 0.0586 | 0.712 |
| E4b mean-reverting | 36.2 % | 0.0582 | 0.712 |
| LightGBM | 67.4 % | 0.0530 | 0.740 |
| ORACLE | 64.7 % | 0 | 1.000 |

LightGBM − E4b at equal N_MIN (paired, Holm): L-p95 +2.0 / +7.2 / +13.0 / +15.0,
C-user −17,186 / −21,348 / −22,582 / −23,332 at N = 4 / 8 / 12 / 20; all
significant; N = 1 identical (greedy).

**Reading.** Equal N_MIN is not like-for-like — LightGBM fires the branch twice as
often, so P2 waits more and batches 26–47 % larger. On the frontier, LightGBM N=4
(127.0, 120,945) dominates E4b at N = 8, 12, 20; nothing of LightGBM's is
dominated; E4b cannot get below ~123k lovelace. LightGBM matches ORACLE on cost
to 0.7 % at every N, trailing it on latency. **A2's answer: the learned forecaster
helps the policy on cost, not latency.** Frontier comparison is descriptive
(medians, 12 episodes); the equal-N paired tests are the formal result.

### Report draft — P6-11 … P6-16

`docs/report/Team11_Project_Report_Draft.docx`, 49 pages, generated by
`docs/report/build_report.js` (`npm install docx`, then `node docs/report/build_report.js`).
Never hand-edit numbers in the .docx; change the builder and regenerate, so every
number stays traceable to a script.

| Item | Status |
|---|---|
| P6-12 — eight diagrams | ✅ `docs/report/diagrams.md`, rendered to `docs/report/diagrams/` |
| P6-11 — Chapters 1–5 | ✅ drafted, including §1.4 as a highlighted subsection |
| P6-13 — Chapter 6 | ✅ drafted, with the gate, fee, optimizer and mask listings |
| P6-14 — Chapter 7 | ✅ drafted; T-L5 marked pending |
| P6-15 — Chapter 8 | ✅ test-split tables at all three rates with CIs, paired-difference table, F5, F6, F8, S1–S6 verdicts, threats to validity; only A3 (retrained) and A4 remain marked pending |
| P6-16 — Chapter 9 | ✅ G1–G6 marked with test-split evidence; limitations and future work updated |

Yellow highlights in the document mark every item the team must fill in or confirm:
member names and roll numbers, HoD name, guide designation, machine
specification, and the pending results.

### Ablation A5 — estimation error against Gate A (P6-9) ✅

`scripts/ablation_a5.py`, validation split, heavy rate (where batches approach the
cap), 21,359 batches.

| True cost vs estimate | Real Gate A cap | Invalid batches |
|---|---|---|
| −10 %, −5 %, 0 % | 24 | 0 |
| **+5 %** | 22 | **8.1 %** |
| **+10 %** | 21 | **8.2 %** |

**S2's zero is exact only under assumption A4 (perfect estimation).** Over-estimation
is harmless, but a 5 % *under*-estimate already invalidates about one batch in
twelve, because heavy-rate batches sit at the cap. A **safety margin of 3 orders**
below the estimated cap would have kept every batch valid, and should be applied in
live operation until P7-9 calibrates the estimator against real preprod
transactions. Recall V4 already found the fee side under-estimating
script-bearing transactions by ~29 %, so this direction of error is not
hypothetical.

### ⚠ Reproducibility gap found by `reproduce.py` (P6-17)

Run against `experiments/phase3-forecaster/manifest.json`, the checker passed the
dataset checksum and the config hash but **failed the git revision and the
clean-tree check**: the manifest records `2b82e64`, a commit from before the
forecaster code existed, and a dirty working tree.

The cause is procedural and applies to every manifest written so far: each
experiment was run from uncommitted code and committed afterwards, so the SHA a
manifest records is the *parent* of the code that produced it. The dataset and
parameters are pinned; the exact code is not.

**Fix going forward:** commit, then run, so every manifest records the SHA of the
code that produced it and `dirty: false`. The Phase 6 test evaluation already
running was launched from an uncommitted tree too, so it carries the same gap and
must be stated as such rather than silently re-run — re-running would spend the
test split a second time, which is the worse violation of the two.

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

### Phase 7 status — offline half built (started 2026-09-14)

Team decisions: Aiken v1.1.23 installed from the official GitHub release
(checksum verified, `%USERPROFILE%\.aiken\bin`); **build offline first**, then go
live only after the Blockfrost preprod project ID is in `.env` and the batcher
address is funded — both done by a team member, not by tooling — and with
explicit approval before any preprod transaction.

| Item | Status |
|---|---|
| P7-1 Aiken toolchain | ✅ `onchain/` project, stdlib v3.1.0, `aiken check` + `aiken build` clean |
| P7-2 `order.ak` | ✅ **T-O1, T-O2, T-O3** pass in Aiken, plus a double-satisfaction guard: each payout is tagged with its order's `OutputReference` |
| P7-3 pass-through fee | ✅ **T-O5** pass — `fee / n + margin`, `n` = order inputs in the batch; one lovelace over is rejected |
| P7-4 `pool.ak` | ✅ **T-O4** pass — fee on net inflow, NFT carried, datum immutable, batcher-only |
| P7-5 keys | ◐ `scripts/generate_keys.py` refuses paths inside the repo and overwrites; secret scan extended to the `.skey` JSON envelope and proven on a real generated key. Keys not yet generated |
| P7-6 deploy | ◐ built, **not submitted** — `scripts/deploy_dex.py` (dry run by default) derives the deployment from the batcher key and a mint window, mints `TEAM11` + one `POOL` NFT under a key-**and**-time-locked policy (no second NFT can ever be minted), opens the pool. Record holds hashes only and is re-verified on load. Dry run verified with real `aiken blueprint apply` |
| P7-7 submitter | ◐ offline complete — `plan_batch` (FIFO, drops unfillable orders and replans the fee share, Gate A raises), **T-N6** by identity; `build_batch_tx` assembles order + pool script inputs, tagged payouts, the new pool output, batcher signature and TTL, and **rebuilds until the real fee is at least the fee users were charged for** (else `order.ak` would reject); `await_confirmation`, `d4_row`. 18 offline tests against a fake chain context running PyCardano's real balancing. Live submission pending |
| P7-11 orders | ◐ `scripts/place_order.py` (dry run by default), `build_cancel_tx` for T-O1 on chain |
| P7-8 … P7-11 | ☐ need live preprod access |

**A defect worth recording.** The first `order.ak` bound the datum to a local
named `order` — the validator's own name — and failed to compile with no
diagnostic: Aiken prints errors only to a TTY. Found by bisection. Datums are now
guarded by `tests/test_onchain.py`, which checks every Python constructor index
and field order against `plutus.json`, and `tests/test_blueprint.py` checks that
PyCardano derives the same script hashes the compiler recorded.

### ✅ Phase 7 exit gate
- [ ] T-O1 … T-O6 pass, including the security tests T-O2 and T-O3
- [ ] Estimator within ±5 % size and ±10 % execution units against D4
- [ ] `07-CONSTRAINTS-COST-MODEL.md` §4 updated from measurement

---

# Cross-cutting tasks

Not owned by a single phase. Several must happen before their phase, not after.

### X-1 · ⚠ Correct the three errors in `Doc/` before resubmission
`docs/README.md` §Authority names exactly three:
- [ ] **The congestion framing throughout** — abstract, decks and `Doc/` all motivate the work by 80–90 % block occupancy. Measured median fill is **2.95 %**, with 0.56 % of blocks above 80 % and no run longer than 10 blocks. Reframe to concurrency per ADR-008; this is now the largest of the corrections, not the smallest.
- [ ] **Deck slide 13** — the optimizer formula `capacity ← (1 − fill_hat) × 90,112` sizes batches against *block* limits. Replace it with the Gate A / Gate B distinction (ADR-002).
- [ ] **Deck slide 15** — the execution-unit footnote: correct the per-block step budget from 20 G to **40 G**, and note the sampled-collection decision (ADR-005).
- [ ] **`Doc/team-11-abstract.docx`** — the batch-sizing sentence currently describes sizing against block capacity. Rewrite it per ADR-002, and add the F2 ">80 % of blocks" number once P1-14 produces it.

**Done when** — all three artifacts match the specification, and `Doc/team-11-architecture.drawio` is either reconciled with `03-ARCHITECTURE.md` §2 or its divergence is recorded.

### X-2 · Update the decks for ADR-004 and ADR-007
The existing decks cover Reviews 1 and 2 and need updating only where they conflict: the "bounce penalty" failure model (→ pool-lock head-of-line blocking) and the fixed-tick simulator (→ recorded slot clock).
**Done when** — no deck slide contradicts an ADR.

### X-3 · Keep the risk register live *(recurring)* — on track
Update `11-RISK-REGISTER.md` §Review log at **every** milestone gate — R1, R2, R3, R4, R5, R6 and R7 all have concrete triggers that fire during this project.
**Done when** — the log has a dated row per phase. Rows exist for Phase 1 and for Phases 2–3; R1 closed, R4 fired, R13 opened. Add a row at each remaining gate.

### X-4 · V4 fee replay without waiting for Phase 7 ✅
The fee replay can run against **recorded mainnet transactions** collected during Phase 1, not only against preprod submissions. Do it early — it validates the fee model independently of the simulator.
**Done when** — **T-F6** passes on 100 recorded transactions. ✅ `scripts/fee_replay.py`, 200 transactions, `experiments/phase2-fee-replay/`.

**Result: the invariant holds, and a real gap was found.**

| | Simple (n=161) | Script-bearing (n=39) |
|---|---|---|
| Formula ever exceeds actual | **never** (200/200) | **never** |
| Exact minimum-fee matches | 13 | 0 |
| Median under-estimate | **+0.39 %** | **+29.16 %** |
| 95th percentile | +34.37 % | +51.16 % |

The formula computes the protocol *minimum*, and a transaction may pay more, so
``estimate <= actual`` is the correct invariant and it held on every transaction.
For simple transactions the median residual is 0.39 % — the model is essentially
exact.

⚠ **Script-bearing transactions are under-estimated by ~29 % systematically.**
That is not noise; it is almost certainly the Conway-era reference-script
surcharge (`minFeeRefScriptCostPerByte`), which the formula in
`07-CONSTRAINTS-COST-MODEL.md` §5 predates. **A DEX batch transaction is
script-bearing**, so the project's absolute per-user cost figures are understated.

*What this does and does not affect.* Policy **comparisons** are unaffected —
every policy is priced by the same estimator, so the ranking and the Pareto shape
stand. Absolute C-user values, and the ADA figures on F3, are low. The missing
term is charged per transaction, so it is a **flat** component: adding it would
*strengthen* the amortization argument rather than weaken it. Fold it in at P7-9,
which already recalibrates the cost model from measurement.

### X-5 · Coverage target ✅
90 % on `config/`, `build/estimator.py`, `policy/`, `sim/`, `eval/metrics.py`. Notebooks and plotting excluded.
**Done when** — `pytest --cov=src/batcher --cov-report=term-missing` meets it and CI enforces it. ✅ **96 % overall**, every listed module at or above target; CI fails below 90 % via `--cov-fail-under`.

### X-6 · Regression suite for the corrected assumptions
Permanent guards so a future refactor cannot silently reintroduce an overturned assumption:

| ADR | Guard | Status | Where |
|---|---|---|---|
| 001 latency not fees | `fee()` takes no block state — enforced on the whole module, not one function | ✅ | `tests/test_estimator.py::test_the_fee_function_cannot_see_congestion` |
| 002 tx limits not block limits | T-G5 — an empty block does not raise the Gate A cap | ✅ | `tests/test_gates.py`, plus a test showing the deck-slide-13 formula *would* emit an invalid transaction |
| 004 pool-lock failure model | T-S5 head-of-line blocking, and no "bounce" member in `Resolution` | ✅ | `tests/test_simulator.py` |
| 005 sampled execution units | T-N1 — absent rows carry `"absent"`, never `0` | ✅ | `tests/test_collector.py` |
| 006 pass-through fee | T-O5 | ☐ Phase 7 | — |
| 007 real slot clock | T-S6 — duration matches recorded slots, not blocks × 20 s | ✅ | `tests/test_simulator.py` |
| **008 concurrency not congestion** | T-S5 must hold with congestion held low, or the reframing is unsupported | ✅ | `tests/test_simulator.py` uses a congested fixture *and* the quiet one |

**Done when** — all six exist and are marked in the source as ADR guards that must not be deleted. **Five of seven live now**; T-O5 arrives with Phase 7, and ADR-008 added a row that did not exist when this table was written.

**Two guards earned their keep already.** The ADR-001 module-wide scan fired when Gate B was added — correctly, since Gate B *is* congestion-dependent — and the fix was to scope the guard to the cost model rather than weaken it. The ADR-005 null-not-zero guard is the one that would have been most expensive to miss.
**The ADR-005 guard matters most quietly**: representing absent execution units as `0` rather than null would make blocks look empty and would corrupt every downstream congestion statistic.

### X-7 · Notebook discipline ✅ *(holding)*
Notebooks are exploratory only. **No result reaches the report through a notebook.**
**Done when** — every number and figure in the report is produced by a script under test. ✅ No notebook exists; every figure and number so far comes from `scripts/analyze_congestion.py`, `train_forecaster.py`, `tune_baselines.py`, `evaluate.py` or `fee_replay.py`.

### X-8 · Housekeeping policy ✅ *(holding)*
Committed: checksums, manifests, `experiments/<id>/`, figures, tables. Gitignored: `data/`, model checkpoints.
**Done when** — the policy in `13-RUNBOOK.md` §9 is enforced by `.gitignore` and observed in practice. ✅ `git status` stays clean through a full collection, training and evaluation run.

### X-9 · Resolve open question Q1 — execution units at scale ✅
Answered in Phase 1 by P1-6 and the correlation in P1-16. **Outcome:** per-block
execution units cannot be collected at 90-day scale, as ADR-005 predicted, but the
sampled proxy holds — 0.912 in the congested regime, 0.852 pooled. Size fill is the
primary signal and the forecaster trains on the full window.
**Done when** — recorded in `01-PRD.md` §8 with the outcome. ✅

### X-10 · Resolve open question Q2 — DQN or PPO
**Done when** — decided in Phase 5 and recorded. Default: DQN with action masking.

### X-11 · Resolve open question Q3 — is the dashboard built?
**Done when** — decided at Phase 7 and recorded. Default: no; terminal logs and plots suffice.

### X-12 · Resolve open question Q4 — the order arrival process ✅
**Done when** — the fitted diurnal shape from P2-5 is documented in `05-DATA-SPEC.md` §D2 with its parameters. ✅ Recorded there, including the burst parameterisation and the 4.5x over-arrival defect that made it necessary.

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
