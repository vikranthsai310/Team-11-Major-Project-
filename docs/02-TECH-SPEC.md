# 02 · Technical Specification

Companion to `01-PRD.md`. The PRD says *what and why*; this document says *how*, and records the engineering decisions that follow from it.

---

## 1. System in one picture

```
   Cardano chain (preprod)                Off-chain batcher process
   ────────────────────────               ─────────────────────────
   order UTXOs  ──── scan ─────────────▶  M3 queue
   block stream ──── poll ─────────────▶  M1 collector ──▶ M2 forecaster
                                                                │
                                              M4 policy ◀───────┘
                                                  │ WAIT | SUBMIT(n)
   pool UTXO    ◀─── batch tx ──────────  M5 builder
                                                  │
                            inclusion outcome ────┘ (reward + metrics)
```

Offline, the same M2–M5 stack is driven by **M6**, a discrete-event simulator that replays recorded blocks instead of a live chain. This is the only environment in which the RL agent trains and in which results are measured.

## 2. Technology choices

| Layer | Choice | Why this and not the alternative |
|---|---|---|
| Language | Python 3.11 | One language across data, ML and transaction building; PyCardano exists |
| Chain data | Koios REST (primary), Blockfrost (fallback) | Free, no node required. `cardano-db-sync` needs hundreds of GB and days of sync — rejected for D1 scale, see `adr/ADR-005` |
| Dataframes | pandas + pyarrow | Parquet keeps D1 compact and typed; CSV export for the report |
| Forecaster | LightGBM (primary), PyTorch LSTM (extension) | Tabular lag features suit gradient boosting; LSTM only to show the deep-learning variant does not automatically win |
| RL | Stable-Baselines3 + Gymnasium | Standard, maintained, supports action masking via `sb3-contrib` MaskablePPO |
| Simulator | Hand-written event loop | SimPy adds a process abstraction we do not need; the loop is ~200 lines and must be exactly auditable |
| Tx building | PyCardano | Pure Python, no node dependency, works against Blockfrost submit API |
| On-chain | Aiken | Modern Cardano contract language; Minswap V2 itself is written in it |
| Plots | Matplotlib | No styling dependencies, deterministic output for the report |
| Testing | pytest + hypothesis | Property tests matter here — see `10-TEST-PLAN.md` |

Everything above is free and runs on a laptop CPU. No GPU, no paid tier, no node.

## 3. Repository layout

```
Team-11-Major-Project-/
├── Doc/                          existing submission artifacts (abstract, decks)
├── docs/                         this specification
├── src/
│   └── batcher/
│       ├── config/
│       │   ├── protocol.py       protocol parameters — SINGLE SOURCE OF TRUTH
│       │   └── settings.py       runtime config, network guard
│       ├── data/
│       │   ├── collector.py      M1
│       │   ├── sources.py        Koios / Blockfrost clients
│       │   └── features.py       lag, rolling, calendar features
│       ├── forecast/
│       │   ├── baseline.py       E4 moving average
│       │   ├── lgbm.py           P1 gradient boosting
│       │   └── lstm.py           P1 deep variant
│       ├── queue/
│       │   └── manager.py        M3
│       ├── policy/
│       │   ├── base.py           Policy interface
│       │   ├── static.py         E1, E2, E3
│       │   ├── optimizer.py      P2
│       │   └── rl.py             P3
│       ├── build/
│       │   ├── estimator.py      size / ExUnit estimation, Gate A
│       │   └── submitter.py      M5 PyCardano transaction building
│       ├── sim/
│       │   ├── env.py            M6 event loop + Gymnasium wrapper
│       │   ├── mempool.py        mempool and pool-lock model
│       │   └── orders.py         D2 order generator
│       └── eval/
│           ├── metrics.py        metric definitions
│           ├── stats.py          paired tests, bootstrap CIs
│           └── plots.py          figures for the report
├── onchain/                      Aiken validators (optional, M7)
│   ├── validators/order.ak
│   └── validators/pool.ak
├── data/
│   ├── raw/                      API responses, gitignored
│   └── processed/                D1 parquet, gitignored; checksums committed
├── experiments/                  run configs + results, committed
├── notebooks/                    exploratory analysis only
├── tests/
└── scripts/                      entrypoints: collect, train, evaluate, run
```

**Rule:** nothing outside `config/protocol.py` may hard-code a protocol constant. This is enforced by a test that greps the source tree for the literal values.

## 4. Core interfaces

Every policy — static, optimizer or learned — implements one interface. This is what makes the comparison honest: the simulator cannot tell them apart.

```python
class Policy(Protocol):
    def decide(self, obs: Observation) -> Action: ...
    def observe_outcome(self, outcome: Outcome) -> None: ...   # no-op for E1-E3
```

```python
@dataclass(frozen=True)
class Observation:
    slot:            int        # absolute slot of the block just seen
    queue_depth:     int
    oldest_wait:     int        # slots the oldest order has waited
    queue_sizes:     tuple[int, ...]      # per-order serialized bytes
    queue_mem:       tuple[int, ...]      # per-order execution memory
    queue_steps:     tuple[int, ...]      # per-order execution steps
    fill_hat:        tuple[float, ...]    # forecast for t+1..t+3
    mem_headroom:    int        # forecast block execution-memory headroom
    step_headroom:   int
    pool_locked:     bool       # a batch is in flight and holds the pool UTXO
    slots_in_flight: int        # 0 if not locked

@dataclass(frozen=True)
class Action:
    submit: bool
    n:      int = 0             # order count; ignored when submit is False

@dataclass(frozen=True)
class Outcome:
    included:        bool
    slots_to_confirm: int | None
    fee_lovelace:    int
    n:               int
    expired:         list[OrderId]
```

## 5. The two capacity gates

The single most important piece of logic in the system. Detailed derivation in `07-CONSTRAINTS-COST-MODEL.md`.

```python
def gate_a(n, sizes, mems, steps) -> bool:
    """Feasibility. Always binding. Independent of congestion."""
    return (POOL_TX_OVERHEAD_B    + sum(sizes[:n]) <= MAX_TX_SIZE          # 16_384
        and POOL_VALIDATOR_MEM    + sum(mems[:n])  <= MAX_TX_EX_MEM        # 14_000_000
        and POOL_VALIDATOR_STEPS  + sum(steps[:n]) <= MAX_TX_EX_STEPS)     # 10_000_000_000

def gate_b(n, sizes, mems, steps, blk) -> bool:
    """Inclusion. Congestion dependent. Evaluated against forecast or actual block."""
    return (blk.size  + tx_size(n)  <= MAX_BLOCK_SIZE                      # 90_112
        and blk.mem   + tx_mem(n)   <= MAX_BLOCK_EX_MEM                    # 62_000_000
        and blk.steps + tx_steps(n) <= MAX_BLOCK_EX_STEPS)                 # 40_000_000_000
```

Gate A is checked by **M5 before construction** and by **M4 before proposing**. A Gate A violation reaching M5 is a defect (`S2`), not a runtime condition.

Gate B is *predicted* by M4 using the forecast and *evaluated* by M6 against the real replayed block.

## 6. Concurrency and state

The batcher is single-threaded and event-driven. One decision per observed block. There is no shared mutable state across threads and no locking beyond the logical pool lock described below.

**The pool lock is the central state variable.** A submitted batch consumes the pool UTXO. Until that transaction confirms, the pool output does not exist, so no second batch can be built. Therefore:

```
pool_locked = True   on submit
pool_locked = False  on confirmation, on TTL expiry, or on rollback
```

While locked the policy may only WAIT. This is enforced in the environment, not left to the policy — a learned agent must not be able to violate a ledger invariant.

Consequence: during congestion an in-flight batch **blocks the head of the queue**, orders accumulate behind it, and latency compounds. This, not batch rejection, is the real cost of a badly timed submission. See `adr/ADR-004`.

## 7. Failure modes and handling

| Failure | Cause | Handling |
|---|---|---|
| Gate A violation | Estimator under-counted size or execution units | Reject before build; log; treated as a defect and alerts in tests |
| TTL expiry | Batch never included within its validity interval | Unlock pool, return orders to queue, count as expiry in metrics |
| Mempool rejection | Mempool full at submission time | Retry next block with backoff; count separately from expiry |
| Chain rollback | Short fork reverts an included batch | Unlock pool, restore orders, log; rare on preprod, modelled but not optimized for |
| API rate limit | Free-tier throttling during collection | Exponential backoff, resume from last persisted height |
| Forecast unavailable | Model load failure or cold start | Fall back to E4 moving average; never block the decision loop |
| Starvation | Policy indefinitely defers an old order | WAIT is action-masked once `oldest_wait >= D_MAX`; enforced by the environment |

## 8. Security and safety

Scope is narrow — no user data, no PII, no payments in the academic sense — but key handling is real.

- **Network guard.** `settings.py` refuses to load if the configured network is not `preprod`. Mainnet is unreachable by construction.
- **Key material.** Signing keys live in `~/.cardano-batcher/` outside the repository. `.gitignore` blocks `*.skey`, `*.vkey`, `*.mnemonic`, `.env`. A pre-commit hook greps staged files for key-shaped strings.
- **API tokens.** Blockfrost project IDs come from environment variables only, never from committed config.
- **Slippage protection is on-chain, not off-chain.** The order validator enforces that each user receives at least what their datum demands. A misbehaving or buggy batcher cannot short-change a user; the transaction simply fails validation. The batcher is therefore untrusted by design for correctness, and trusted only for liveness and ordering.
- **Ordering fairness is acknowledged, not solved.** A batcher chooses which orders enter a batch and in what order, which is a reordering capability. The policy uses FIFO selection within the chosen `n` and a hard deadline; genuine MEV resistance is out of scope (`N6`).

## 9. Observability

| Signal | Where | Purpose |
|---|---|---|
| Decision log (D3) | one row per observed block, parquet | Post-hoc analysis, RL debugging, report tables |
| Metric snapshot | end of each episode, JSON | Evaluation and paired statistics |
| Structured logs | stdout, JSON lines | Live runs; grep-able by slot |
| Run manifest | `experiments/<id>/manifest.json` | Seed, git SHA, config hash, dataset checksum — reproducibility (NFR-3) |

Every experiment writes a manifest. A result without a manifest is not a result.

## 10. Performance

The workload is tiny by ML standards; the constraint is developer time, not compute.

| Operation | Budget | Notes |
|---|---|---|
| D1 collection, 90 days | < 4 h wall clock | Rate-limited, resumable, run once |
| Feature build | < 60 s | ~390k rows |
| LightGBM train | < 5 min | CPU |
| LSTM train | < 45 min | CPU, small model |
| One simulated episode (1 day) | < 2 s | ~4,300 steps |
| RL training, 2M steps | < 6 h | NFR-2 |
| Full evaluation, 5 policies x 100 episodes | < 20 min | Parallel over episodes |

## 11. What this system deliberately does not do

Restating the PRD non-goals in engineering terms, because each has been mistaken for a requirement at some point in this project:

- It does not run in a browser or ship any frontend code. Batching aggregates *many users* orders; a wallet holds *one user* funds and has nothing to aggregate.
- It does not connect to Minswap. Order UTXOs are locked to the DEX validator that created them, and Minswap V2 additionally requires a whitelisted, licensed batcher key. There is no integration point.
- It does not reduce fees during congestion, because Cardano fees do not respond to congestion.
- It does not touch mainnet.
