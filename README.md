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

An intelligent off-chain **batcher** for a Cardano DEX. A liquidity pool is a single UTXO that admits one batch per block, so every order queues behind whatever batch is currently in flight. This system decides when to submit and how many orders to include — managing that shared lock under uncertain confirmation time, and reading the chain before deciding, which the fixed-rule batchers deployed today do not.

It is a **server-side process**. There is no user-facing website, no browser extension and no wallet code. A wallet can only see its own owner's funds, so it has nothing to aggregate; batching is inherently an aggregator's job. A localhost-only presentation dashboard shows the batcher's decisions, the results and the live preprod deployment (see [Running it](#running-it)).

## Why it is needed

On Cardano's eUTXO ledger, a DEX liquidity pool is a **single UTXO that can be consumed only once per block**. A hundred users cannot swap against it independently — one succeeds and the rest fail. The ecosystem solves this with batchers that aggregate many orders into one transaction.

Those batchers trigger on constants: every *M* orders, or every *T* seconds. They never read the chain before deciding.

## The insight the project turns on

Cardano fees are **deterministic**:

```
fee = 44 * size + 155,381 + 0.0577 * mem + 0.0000721 * steps    (lovelace)
```

No gas auction, no bidding. A transaction costs the same on an idle chain and a saturated one.

**So waiting on Cardano does not cost money. It costs time.** A batch that does not confirm promptly keeps every user inside it waiting — and, because it holds the pool UTXO meanwhile, keeps every order behind it waiting too. The objective is therefore confirmation **latency** and amortized per-user cost, not fees. Anything promising "lower gas fees during congestion" is describing Ethereum, not Cardano.

**Measured, not assumed.** This project was originally motivated by a claim that Cardano blocks run at 80–90 % capacity. Phase 1 collected 92 days of mainnet — 388,781 blocks — to check it. Median block fill is **3.0 %**; **0.56 %** of blocks exceed 80 %; and the longest unbroken run above 80 % in the entire window is **10 blocks, five minutes**. The framing was therefore corrected: the binding problem is *concurrency* — one writer per pool per block — which is a property of the eUTXO ledger and is fully present on an empty chain. The congestion measurement is reported as a result in its own right. See [`adr/ADR-008`](docs/adr/ADR-008-concurrency-not-congestion.md).

## Approach

| | |
|---|---|
| **Decide** | Choose WAIT or SUBMIT(n) under the pool lock — as a constrained optimizer and as an RL agent |
| **Forecast** | Predict next-block capacity from recent chain history (LightGBM, LSTM) — a secondary, defensive input that avoids the rare full block |
| **Constrain** | Enforce Cardano's per-transaction limits as hard gates, never as a learned preference |
| **Evaluate** | Replay real recorded blocks in a simulator against tuned static baselines |
| **Demonstrate** | *(optional)* A minimal Aiken DEX on the preprod testnet |

Three facts shape the design more than anything else:

- **A submitted batch locks the pool UTXO** until it confirms, so a mistimed submission blocks the head of the queue. This is the central mechanism, and it does not depend on the chain being busy.
- **Batch size is capped by per-transaction limits** (16,384 B, 14 M execution memory), not block limits — roughly **20–40 orders**. An empty block does not permit a bigger batch.
- **Block capacity rarely binds.** A 30-order batch fails to fit only above ~89 % fill, which is about one block in 180 — and never for more than five minutes at a stretch. How rarely it binds is itself a reported result.

## Repository

```
Doc/          submission artifacts — abstract, literature review, design decks
docs/         engineering specification (start at docs/README.md)
src/batcher/  implementation
scripts/      entry points
tests/        test suite
experiments/  run manifests and results
```

## Status

Phases 0–7 complete: foundation, data collection and premise validation, simulator and tuned baselines, congestion forecaster, constrained optimizer, the RL agent (five DQN seeds), the test-split evaluation with ablations, and the on-chain DEX on preprod with the live batcher and the dashboard. 488 tests pass; one is skipped where the Aiken compiler is not installed. Task-level checklist: [`docs/18-TODO.md`](docs/18-TODO.md), derived from [`docs/12-ROADMAP.md`](docs/12-ROADMAP.md).

D1 is collected and verified — 388,781 blocks over 92 days — and the simulator replays it against tuned static baselines with zero Gate A violations.

Headline results, 100 paired test days ([`main_results.md`](experiments/phase6-final-evaluation/main_results.md)): P2 cuts cost per user by 19 % against greedy for about 5 % more tail latency; the DQN agent cuts it by 43 % at a larger latency cost; no policy beats greedy on speed on today's lightly loaded chain; zero capacity violations in every run. A batch settled end to end on preprod (T-O6).

Still open: the transaction-size estimator is calibrated from a single measured batch and does not yet meet its ±5 % / ±10 % target, so `07-CONSTRAINTS-COST-MODEL.md` §4 is not yet updated from measurement.

## Running it

After the setup under [Development](#development):

```bash
python scripts/dashboard.py                    # http://127.0.0.1:8050 — Overview, Simulator, Results, Live
python scripts/run_batcher.py --policy p2      # shadow mode on preprod: decides and builds, submits nothing
pytest tests/                                  # full suite
```

The Simulator view replays the test days and needs `data/processed/d1_blocks_*.parquet` (gitignored). It uses the trained forecaster in `experiments/phase3-forecaster/models/` (also gitignored) and falls back to the moving average without it; rebuild it with `python scripts/train_forecaster.py --data data/processed/d1_blocks_20260613_20260913.parquet`, which reproduces the committed scores exactly. The Live view needs `BLOCKFROST_PROJECT_ID` in `.env`. `run_batcher.py` also needs `batcher.skey` in `BATCHER_KEY_DIR`, which must be the key the DEX was deployed with.

## Development

Python 3.11 or 3.12. The machine-learning dependencies do not yet publish wheels for 3.13+.

```bash
python -m venv .venv && .venv/Scripts/activate   # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
python scripts/verify_setup.py
```

`verify_setup.py` loads the settings (which enforces the preprod guard), prints the protocol parameters in force, and writes a run manifest.

Test gates, from [`docs/10-TEST-PLAN.md`](docs/10-TEST-PLAN.md) §10:

```bash
pytest tests/ -m "not slow"                                  # commit gate, < 30 s
pytest tests/                                                # milestone gate
pytest tests/ --cov=src/batcher --cov-report=term-missing    # coverage
```

Configuration lives in `.env` (copy `.env.example`); it is gitignored, as are signing keys, which belong in `~/.cardano-batcher/`. A pre-commit hook scans staged files for key-shaped strings — committing with `--no-verify` is forbidden.

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
