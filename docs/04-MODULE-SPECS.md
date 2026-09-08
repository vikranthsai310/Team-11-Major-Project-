# 04 · Module Specifications

Exact contracts for M1–M7. Each section states inputs, outputs, behaviour, failure handling and acceptance criteria. If a module satisfies its acceptance criteria it is done; nothing further is expected of it.

---

## M1 · Chain Data Collector

**Purpose** — turn public block endpoints into the congestion time series D1.

**Inputs**
| Name | Type | Source |
|---|---|---|
| `start_height`, `end_height` | int | run config |
| API credentials | env var | `BLOCKFROST_PROJECT_ID` (optional; Koios needs none) |

**Output** — D1 parquet rows (schema in `05-DATA-SPEC.md`):
`block_height, abs_slot, block_time, block_size, fill_pct, tx_count, mem_exunits, step_exunits, mem_pct, step_pct, exunits_source`

**Behaviour**
1. Page over `/blocks` from Koios in descending height, newest first
2. Normalise each block into the D1 row shape
3. `fill_pct = block_size / MAX_BLOCK_SIZE`, taken from `config.protocol`
4. Execution units are populated only for blocks in the sampled window (`adr/ADR-005`); elsewhere `mem_exunits` is null and `exunits_source = "absent"`
5. Persist incrementally; the collector is resumable from the last persisted height
6. Write a checksum and a row count alongside the parquet

**Failure handling**
| Condition | Response |
|---|---|
| HTTP 429 / rate limit | Exponential backoff from 1 s to 60 s, then resume |
| Partial page | Discard the page, retry; never write a partial block |
| Missing ExUnit rows at an epoch boundary | Leave null; downstream cleaning drops or forward-fills at most one slot |
| Source disagreement (Koios vs Blockfrost) | Prefer Koios; log the discrepancy; a persistent mismatch is a defect |

**Acceptance**
- 90 days collected with no gaps in `block_height`
- `abs_slot` strictly increasing
- Re-running the collector produces a byte-identical parquet
- Coverage report: rows with and without execution units

---

## M2 · Congestion Forecaster

**Purpose** — predict near-term capacity so M4 can anticipate rather than react.

**Inputs** — the last *k* D1 rows (default `k = 20`, about 7 minutes of chain), current queue depth, hour of day.

**Output**
```python
@dataclass(frozen=True)
class Forecast:
    fill_hat:     tuple[float, float, float]   # t+1, t+2, t+3, each in [0,1]
    mem_headroom: int                          # predicted free block execution memory
    step_headroom: int
    model:        str                          # "lgbm" | "lstm" | "ma" (fallback)
```

**Models**
| ID | Model | Role |
|---|---|---|
| E4 | Rolling mean of last *k* fill percentages | Baseline that P1 must beat |
| P1a | LightGBM regressor | Primary |
| P1b | PyTorch LSTM/GRU | Deep-learning variant, reported whether or not it wins |

**Features** — lag fills `1..k`, rolling mean and standard deviation over 5/10/20 blocks, inter-block slot gap, transaction count lags, queue depth, hour of day (cyclic sine/cosine encoding), day of week.

**Training** — chronological split 70 / 15 / 15, never shuffled. Shuffling would leak future congestion into training and is treated as a defect.

**Failure handling** — if a model artifact fails to load, silently fall back to E4 and set `model = "ma"`. The decision loop must never block on the forecaster.

**Acceptance**
- P1 MAE on the test split lower than E4 (success metric S1)
- Predictions clipped to `[0, 1]`
- Inference under 10 ms per call (NFR-1)
- A leakage test passes: shuffling the split degrades reported performance, proving the split is doing work

---

## M3 · Order Queue Manager

**Purpose** — maintain the set of pending orders and expose the state the policy reasons over.

**Inputs** — order arrivals. In simulation, from the D2 generator. In live mode, UTXOs scanned at the order script address.

**Order record**
```python
@dataclass(frozen=True)
class Order:
    order_id:      str
    arrival_slot:  int
    size_bytes:    int      # marginal serialized bytes this order adds to a batch
    mem_exunits:   int      # marginal execution memory
    step_exunits:  int
    amount_in:     int
    min_out:       int      # slippage floor, from the datum
    ttl_slot:      int
```

**Exposed state** — `queue_depth`, `oldest_wait = current_slot - min(arrival_slot)`, and per-order size/execution tuples in FIFO order.

**Behaviour**
- FIFO ordering. Selection is always a prefix `Q[0:n]`, never a chosen subset. This is a deliberate fairness property: the policy chooses *how many*, never *which*, removing order-selection MEV from the design space.
- Orders returned after an expired batch are reinserted at their original position, preserving their age.
- Orders past `ttl_slot` are evicted and counted as expiries.

**Acceptance**
- FIFO preserved across return-to-queue
- Age of a returned order is continuous — no reset
- Depth and oldest-wait match an independent recomputation from the raw arrival log

---

## M4 · Adaptive Batching Policy

**Purpose** — the decision. This is the module the project exists to build.

**Interface** — `decide(Observation) -> Action`, as defined in `02-TECH-SPEC.md`.

**Implementations**
| ID | Type | Summary |
|---|---|---|
| E1 | Static | `submit(Q[0:M])` when `len(Q) >= M` |
| E2 | Static | `submit(Q)` when `slot - last_submit >= T` |
| E3 | Static | `submit(Q)` whenever `len(Q) > 0` |
| P2 | Constrained optimizer | Forecast-then-optimize under Gate A and predicted Gate B |
| P3 | Reinforcement learning | Learned policy over the same observation space |

Algorithms and the MDP formulation: `06-ML-SPEC.md`.

**Hard rules applied to every implementation, enforced outside the policy**
1. If `pool_locked`, the only legal action is WAIT
2. If `oldest_wait >= D_MAX`, the WAIT action is masked — the policy must submit
3. Any proposed `n` is clamped to the largest value satisfying Gate A

Rule 3 means a policy *cannot* express an infeasible action. This is why success metric S2 (zero Gate A violations) is achievable by construction rather than by training.

**Acceptance**
- Zero Gate A violations across the full evaluation
- No order exceeds `D_MAX` without an offered submission
- P2 is deterministic given identical observations
- P3 loads from a checkpoint and reproduces its evaluation exactly

---

## M5 · Batch Builder and Submitter

**Purpose** — turn a decision into a valid Cardano transaction, and turn the result back into a learning signal.

**Two responsibilities, deliberately separated**

*Estimator* (pure, used everywhere including simulation):
```python
def tx_size(n, sizes)    -> int
def tx_mem(n, mems)      -> int
def tx_steps(n, steps)   -> int
def fee_lovelace(size, mem, steps) -> int
```

*Submitter* (impure, live mode only): build with PyCardano, sign with the batcher key, submit via Blockfrost, await confirmation or TTL.

**Behaviour**
1. Re-check Gate A. A violation here is a defect and raises, it does not silently truncate
2. Construct: consume `n` order UTXOs plus the pool UTXO; produce `n` user outputs plus the updated pool output
3. Every output must satisfy the minimum-ADA requirement
4. Set the validity interval; `ttl = current_slot + TTL_SLOTS`
5. Submit, then poll for inclusion until confirmed or expired
6. Emit `Outcome` to M4 and to D3

**Failure handling** — as tabulated in `02-TECH-SPEC.md` §7. Expiry and mempool rejection are counted separately; conflating them hides the mechanism the project is studying.

**Acceptance**
- Estimator error against real preprod transactions within ±5 % on size and ±10 % on execution units
- Simulation and live mode share the same estimator code path
- No transaction submitted while `pool_locked`

---

## M6 · Simulator and Evaluation

**Purpose** — the environment in which every result is produced.

Full specification in `08-SIMULATOR-SPEC.md`; metric definitions in `09-EVALUATION-PROTOCOL.md`. Summary of the contract:

**Inputs** — a D1 slice, a seed, an order-arrival configuration, a policy.
**Outputs** — D3 decision log, per-episode metric record, optional trajectory dump.

**Guarantees**
- Deterministic given `(D1 slice, seed, policy)`
- Advances on recorded `abs_slot` values, not a fixed tick (`adr/ADR-007`)
- Models the mempool and the pool lock (`adr/ADR-004`)
- Presents an identical episode to every policy for paired comparison

**Acceptance**
- Two runs with the same seed produce byte-identical metrics
- A no-op policy that never submits yields zero throughput and unbounded latency — the sanity floor
- E3 (greedy) yields the lowest latency at the highest per-user cost — the expected shape; if it does not, the simulator is wrong

---

## M7 · On-chain DEX *(optional)*

**Purpose** — give the live demonstration real orders to serve. Not required for any result.

**Components**
| Validator | Enforces |
|---|---|
| `order.ak` | Datum shape; the consuming transaction must pay `min_out` to `return_address`; only the authorised batcher key may execute; the user may always cancel and reclaim |
| `pool.ak` | Constant product `x * y = k` after fees; reserves updated correctly; pool NFT preserved |

**Fee design** — the order validator charges a **pass-through** batcher fee: the user pays `network_fee / n + margin` rather than a flat amount. Without this, amortization gains accrue to the batcher and goal G2 is not actually delivered to users. See `adr/ADR-006`.

**Acceptance**
- A user can cancel an unbatched order and recover funds
- A batch paying less than `min_out` to any user fails validation
- A batch signed by a non-authorised key fails validation
- One end-to-end swap settles on preprod, evidenced by a transaction hash

---

## Module dependency graph

```
config.protocol ──▶ everything

M1 ──▶ D1 ──▶ M2 ──┐
                    ├──▶ M4 ──▶ M5 ──▶ outcome ──┐
D2 ──▶ M3 ─────────┘                              │
                                                   ▼
M6 ──── drives M2..M5 offline, consumes outcome ──┘ ──▶ metrics, plots

M7 ──── independent; replaces the simulated chain in live mode only
```

Build order follows this graph and is scheduled in `12-ROADMAP.md`.
