# 13 · Runbook

Operational guide: environment setup, how to run each stage, and what to do when something breaks. Written so a team member who has not touched the project can get from a clean machine to a reproduced result.

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11 | 3.12 untested |
| git | any recent | |
| Disk | ~2 GB | D1 parquet, models, experiment outputs |
| RAM | 8 GB | 16 GB comfortable for RL training |
| GPU | not required | Everything runs on CPU (NFR-2) |
| Aiken | latest | Phase 7 only |

No Cardano node is required. No paid API tier is required.

## 2. Setup

```bash
git clone <repo-url>
cd Team-11-Major-Project-

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pytest tests/ -m "not slow"        # must pass before doing anything else
```

### Environment variables

```bash
# .env  -- NEVER committed; .gitignore blocks it
CARDANO_NETWORK=preprod            # the guard refuses anything else
BLOCKFROST_PROJECT_ID=preprod...   # optional; Koios needs no key
BATCHER_KEY_DIR=~/.cardano-batcher # outside the repo; Phase 7 only
```

The network guard in `config/settings.py` raises on load if `CARDANO_NETWORK` is not `preprod`. Mainnet is unreachable by construction, not by discipline.

## 3. Stage commands

### Collect D1

```bash
python scripts/collect.py --days 90 --out data/processed/
python scripts/collect.py --days 90 --resume        # after an interruption
python scripts/collect.py --exunits-sample 7        # per-tx execution units, sampled window
```

Runs for a few hours under rate limiting. Resumable — safe to interrupt. Writes a parquet, a `.sha256` and a manifest.

**Verify before using:**
```bash
python scripts/verify_dataset.py data/processed/d1_blocks_*.parquet
```
Checks height continuity, monotone slots, null policy on execution units, and the checksum.

### Exploratory analysis and the premise check

```bash
python scripts/analyze_congestion.py --data data/processed/d1_*.parquet --out figures/
```

Produces F1 and F2, and prints the Phase 1 decision numbers: `fill_pct` autocorrelation, lag-1 MAE, global-mean MAE. **Read this output before building the forecaster** — it is the R4 gate.

### Train the forecaster

```bash
python scripts/train_forecaster.py --model lgbm --data data/processed/d1_*.parquet
python scripts/train_forecaster.py --model lstm --data data/processed/d1_*.parquet
python scripts/eval_forecaster.py  --models lgbm lstm ma --split test
```

Models are written to `experiments/<id>/models/` with a manifest.

### Run a policy

```bash
python scripts/evaluate.py --policy p2 --episodes 100 --rate matched --seed 42
python scripts/evaluate.py --policy all --episodes 100 --rate all --seed 42
```

`--policy all` runs E1, E2, E3, P2, P3, ORACLE and NULL over identical paired episodes.

### Train the RL agent

```bash
python scripts/train_rl.py --algo dqn --steps 2000000 --seed 0
for s in 0 1 2 3 4; do python scripts/train_rl.py --algo dqn --seed $s; done
```

Under 6 hours per seed on a laptop CPU. Checkpoints selected on the validation split.

### Produce the report artifacts

```bash
python scripts/make_figures.py  --experiment <id> --out figures/
python scripts/make_tables.py   --experiment <id> --out tables/
python scripts/run_stats.py     --experiment <id>     # paired Wilcoxon, bootstrap CIs
```

### Phase 7, on-chain

```bash
cd onchain && aiken build && aiken check
python scripts/deploy_dex.py --network preprod
python scripts/run_batcher.py --policy p2 --live       # long-running daemon
```

## 4. Reproducing a published result

Every result carries a manifest. To reproduce one:

```bash
python scripts/reproduce.py --manifest experiments/<id>/manifest.json
```

This restores the seed, verifies the dataset checksum, checks out the recorded git SHA if it differs, and re-runs. Output must be bit-identical (NFR-3). If it is not, that is a defect — file it rather than working around it.

## 5. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `SettingsError: network must be preprod` | `CARDANO_NETWORK` unset or wrong | Set it in `.env`. Do not edit the guard |
| Collector stalls, HTTP 429 | Rate limiting | Expected. It backs off. Resume with `--resume` |
| Collector output differs between runs | Non-deterministic paging | Defect. Check the resume cursor logic; do not proceed with the dataset |
| Forecaster suspiciously accurate | Temporal leakage | Run T-L1 and T-N3. Almost always a lag computed across the split boundary |
| Evaluation metrics differ across identical runs | Global random state | Defect. Find the unseeded generator; T-S1 should have caught it |
| RL return improves, action distribution flat | Policy collapse | Check T-L6. Recalibrate reward weights per `06-ML-SPEC.md` §5 |
| Gate A violation raised in M5 | Estimator under-counting | Defect (S2). Recalibrate against D4; do not widen the gate |
| Greedy is not the lowest-latency policy | Simulator bug | Stop. T-S3 is failing; every downstream result is suspect |
| Live batch never confirms | TTL too short, or preprod congestion | Check `slots_in_flight`; raise `TTL_SLOTS`; confirm the pool UTXO is unspent |
| `pool_locked` stuck true | Rollback or missed confirmation | Re-scan the chain for the in-flight hash; the unlock path must handle rollback |

## 6. Failure playbooks

### The dataset is corrupt or the checksum fails

Do not repair by hand. Delete, re-collect, re-verify. A dataset whose provenance is uncertain contaminates every result derived from it.

### An experiment cannot be reproduced

Treat as a defect, not an inconvenience. Check, in order: unseeded generator, dictionary iteration order in a decision path, wall-clock time in a code path, floating-point aggregation order, uncommitted local changes. Do not publish a number that cannot be reproduced.

### RL training does not converge

Do not tune against the test split. Diagnose in this order: reward term scales (T-L4), action-mask hit rate, episode length, then exploration schedule. If it still fails, report P2 as the result — R2 anticipates this and P2 is a complete deliverable.

### Preprod deployment stalls

Apply the Phase 7 pre-authorised drop: three weeks without deployment means drop it and reallocate. The decision was made in advance precisely so it does not need to be re-argued under pressure.

## 7. Operating the live batcher (Phase 7)

```bash
python scripts/run_batcher.py --policy p2 --live --log-json | tee logs/batcher.jsonl
```

**Health signals to watch**

| Signal | Healthy | Action if not |
|---|---|---|
| `pool_locked` duration | mostly under 5 blocks | Investigate confirmation path |
| Decisions per block | exactly 1 when unlocked | Loop is skipping blocks |
| Gate A violations | 0 | Stop the daemon; recalibrate |
| Expiry rate | low and stable | Raise TTL or reduce batch size |
| API error rate | near 0 | Check rate limits and backoff |

**Shutdown.** Stop only when `pool_locked` is false. Stopping with a batch in flight leaves orders queued and the pool committed until TTL expiry.

## 8. Security operations

- Keys live in `BATCHER_KEY_DIR`, outside the repository, and are never copied into it
- The pre-commit hook scans staged files for key-shaped strings; if it fires, do not use `--no-verify`, fix the staged content
- Rotate the Blockfrost project ID if it is ever printed into a log or a notebook output
- Preprod only. If mainnet access is ever needed, that is a project-level decision, not a configuration change

## 9. Housekeeping

| Item | Policy |
|---|---|
| `data/raw/`, `data/processed/` | Gitignored; reproducible by re-running M1 |
| Checksums, manifests | Committed |
| `experiments/<id>/` | Committed — configs, metrics, manifests |
| Model checkpoints | Gitignored; reproducible from a manifest |
| Figures and tables | Committed; regenerated by script, never edited by hand |
| Notebooks | Exploratory only. No result reaches the report through a notebook |

The last rule matters. Anything that appears in the report is produced by a script under test, not by a notebook cell whose state nobody can reconstruct.
