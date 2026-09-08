# 06 · Machine Learning Specification

Algorithms, the MDP formulation, the reward, and the training protocol. Constants referenced here come from `07-CONSTRAINTS-COST-MODEL.md`.

---

## 1. Two learning problems

| | Problem | Type | Module |
|---|---|---|---|
| **P1** | Predict near-term block capacity | Supervised time-series regression | M2 |
| **P3** | Choose when and how much to batch | Sequential decision under uncertainty | M4 |

They are trained separately. P1 is trained first on D1 and then frozen; P3 consumes its output as an observation. Training them jointly is out of scope and noted as future work.

---

## 2. Baselines

Baselines are part of the contribution, not an afterthought. A result is only meaningful against an honest baseline.

### Forecasting

**E4 — moving average.** `fill_hat(t+1) = mean(fill(t-k+1 .. t))`, `k = 20`.

Naive, but strong on autocorrelated series. If LightGBM cannot beat it, that is the finding and it gets reported.

### Batching policies

```
E1  fixed size       if len(Q) >= M:                 submit(Q[0:M])
E2  fixed interval   if slot - last_submit >= T:     submit(Q[0:n_max])
E3  greedy           if len(Q) > 0:                  submit(Q[0:n_max])
```

`M` and `T` are **tuned on the validation split**, not guessed. Comparing against a deliberately badly configured baseline would invalidate the result. Report the tuned values.

All three are subject to the same structural rules as the proposed policies: they cannot submit while the pool is locked, and they cannot exceed Gate A. This keeps the comparison fair and confined to the decision logic.

---

## 3. P1 · Congestion forecaster

**Target** — `fill_pct` of the next block; extended to a 3-step horizon `t+1..t+3`.

**Features**

| Group | Features |
|---|---|
| Lags | `fill_pct` at lags 1..20 |
| Rolling | mean and standard deviation over windows 5, 10, 20 |
| Cadence | `slot_gap` and its rolling mean — long gaps correlate with fuller blocks |
| Load | `tx_count` lags 1..5 |
| Queue | current `queue_depth`, `oldest_wait` |
| Calendar | hour of day as sine/cosine, day of week |

Execution-unit features are available only on the sampled window (`05-DATA-SPEC.md`); the primary model uses size-based features so it can train on the full 90 days.

**Models**

| ID | Model | Configuration |
|---|---|---|
| P1a | LightGBM | ~500 trees, early stopping on validation MAE |
| P1b | LSTM | 2 layers, 64 hidden units, sequence length 20, Adam |

**Metrics** — MAE (primary), RMSE, and **directional accuracy**: did the model correctly predict whether fullness rises or falls? Directional accuracy matters more than MAE for the policy, since the decision is a threshold comparison rather than a use of the exact value.

**Protocol**
- Chronological split 70/15/15; never shuffled
- Early stopping and hyperparameters on validation only
- Test split touched once, for the reported number
- A leakage test must pass: deliberately shuffling the split should *improve* apparent scores; if it does not, the pipeline is leaking

**Acceptance** — P1 MAE below E4 on the test split (success metric S1). If P1b does not beat P1a, report it. A negative result honestly reported is stronger than a tuned-until-it-wins result.

---

## 4. P2 · Constrained optimizer

Explainable, deterministic, and the safety net for the whole project. Build this before P3 and keep it.

```
def decide(obs):
    if obs.pool_locked:
        return WAIT

    n_feasible = max_n_satisfying_gate_a(obs)          # hard cap, ~20-40
    if n_feasible == 0:
        return WAIT

    if obs.oldest_wait >= D_MAX:                       # fairness override
        return SUBMIT(n_feasible)

    n_fit = max_n_satisfying_gate_b(obs, obs.fill_hat[0])
    n = min(n_feasible, n_fit)

    if n == 0:
        return WAIT                                    # predicted no room
    if n < N_MIN and quieter_block_predicted(obs):
        return WAIT                                    # wait for amortization
    return SUBMIT(n)
```

**Parameters**

| Name | Meaning | Default | Tuned on |
|---|---|---|---|
| `D_MAX` | Hard deadline in slots before forced submission | 120 (~2 min) | validation |
| `N_MIN` | Batch size below which waiting may be worthwhile | 8 | validation, informed by the amortization curve |
| horizon | Forecast steps consulted | 3 | validation |

`N_MIN = 8` is not arbitrary: the amortization curve in `07-CONSTRAINTS-COST-MODEL.md` §5 flattens near `n ≈ 10`, so waiting to grow a batch beyond that trades meaningful latency for negligible cost saving.

**Why it must exist even if P3 wins.** It is explainable to a review panel, it is deterministic, it cannot fail to converge, and it is the fallback if RL training does not produce a usable agent. It is also the honest comparator that shows how much of the gain comes from *forecasting* versus from *learning*.

---

## 5. P3 · Reinforcement learning agent

### MDP

**State** — an 11-dimensional vector, all components normalised to roughly `[0, 1]`:

```
s = ( queue_depth / QUEUE_CAP,
      oldest_wait / D_MAX,
      mean_wait   / D_MAX,
      fill_hat[t+1], fill_hat[t+2], fill_hat[t+3],
      mem_headroom  / MAX_BLOCK_EX_MEM,
      gate_a_max_n  / N_MAX,
      pool_locked,
      slots_in_flight / D_MAX,
      hour_sin, hour_cos )
```

`gate_a_max_n` is included deliberately so the agent can see its own feasible action range rather than having to infer it.

**Action** — discrete: `WAIT`, or `SUBMIT(n)` for `n` in `1..n_max`, discretised into buckets `{1, 4, 8, 12, 16, 20, 25, 30, n_max}` to keep the space small. Nine to ten actions total.

**Action masking** — the environment masks illegal actions rather than penalising them:
- if `pool_locked`, only `WAIT` is legal
- if `oldest_wait >= D_MAX`, `WAIT` is illegal
- every `SUBMIT(n)` with `n > gate_a_max_n` is illegal

Masking rather than penalising is what makes invariants I1 and I2 structural. The agent is incapable of violating a ledger rule or starving an order; it does not have to learn not to.

**Transition** — the simulator (`08-SIMULATOR-SPEC.md`): advance to the next recorded block, admit arrivals, resolve any in-flight batch against the real block, then present the next observation.

### Reward

```
r = - ( w_cost    * flat_fee_share(n)
      + w_latency * sum(wait_i ** 2) / NORM
      + w_slip    * slippage(n)
      + w_lock    * slots_pool_locked )
```

| Term | Why |
|---|---|
| `flat_fee_share` | Only the flat fee amortizes; the marginal component is constant per order and cannot be optimised, so including it would add a constant and dilute the gradient |
| `wait ** 2` | Quadratic in waiting time, so the tail is penalised harder than the mean. Encodes the p95 latency objective directly and discourages starvation beyond the hard mask |
| `slippage(n)` | Endogenous price drift from the simulated constant-product pool between arrival and execution |
| `slots_pool_locked` | The real cost of a mistimed submission — head-of-line blocking. **This replaces the "bounce penalty" of the earlier design**, which modelled a rejection that does not occur (`adr/ADR-004`) |

**There is no inclusion-failure penalty.** A submitted transaction is not rejected for being late; it waits. Penalising a non-existent event would teach the agent the wrong model of its environment.

**Weight calibration is mandatory, not cosmetic.** From the amortization curve, the cost term spans roughly 0.07–0.30 ADA per user while latency spans tens to hundreds of slots. Left raw, cost is numerically invisible. Each term is therefore normalised to unit scale on a reference episode before weights are applied, and the weights are reported in the run manifest.

### Algorithms

| Choice | Use |
|---|---|
| **DQN** | Primary. Discrete action space, sample-efficient, simple to reproduce |
| **MaskablePPO** (`sb3-contrib`) | Alternative; native action masking |

**Configuration** — 2M timesteps, batch 64, learning rate 1e-4, gamma 0.99, replay buffer 100k, epsilon annealed 1.0 to 0.05 over the first 20 %. Under 6 hours on a laptop CPU (NFR-2).

**Training protocol**
- Episodes sample windows from the **training** split of D1 only
- Validation split for checkpoint selection
- Test split for reported numbers, once
- Five seeds, with mean and standard deviation reported. A single-seed RL result is not a result

**Diagnostics** — episode return, action distribution over time, mean queue depth, mask-hit rate. A collapsed policy (always WAIT until the mask forces submission, or always SUBMIT at maximum) is a common failure and is detected by the action distribution, not by the return curve.

---

## 6. Honest failure modes

Recorded in advance so they are reported rather than hidden.

| Failure | Symptom | Response |
|---|---|---|
| RL fails to beat P2 | Lower mean return on test episodes | Report it. P2 is a complete result; "learning did not add value beyond forecasting" is a legitimate finding |
| P1 fails to beat E4 | Higher test MAE | Report it, and note that a policy built on a moving average is still adaptive |
| Policy collapses to greedy | Action distribution concentrated at max `n` | Latency weight too high relative to cost; recalibrate and report both |
| Overfitting to arrival rate | Good at matched rate, poor at light or heavy | Exactly why sensitivity across three rates is required (`05-DATA-SPEC.md`) |
| Forecast error dominates | P2 with true fullness (oracle) far outperforms P2 with `fill_hat` | Run the oracle ablation and report the gap — it bounds how much better forecasting could make the system |

The **oracle ablation** is worth running regardless of outcome: P2 given the true next-block fullness establishes the ceiling that any forecaster could reach, and the distance from it is the honest measure of P1 quality.

---

## 7. Reproducibility

Every training and evaluation run writes a manifest containing the seed, git SHA, config hash, dataset checksum, protocol parameters, reward weights and tuned baseline parameters. Re-running from a manifest must reproduce the metrics bit-identically (NFR-3).
