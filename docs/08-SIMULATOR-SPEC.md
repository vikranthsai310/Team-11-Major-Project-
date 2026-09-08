# 08 · Simulator Specification

The simulator is where every reported result is produced. It is therefore the most important component to get right, and the one most likely to be attacked in review. This document states exactly what it models, what it does not, and why.

---

## 1. Purpose

Mainnet experimentation is impossible: submitting experimental batches to a live chain is expensive, irreversible and unethical. Preprod has unrealistic congestion. The simulator replays **real recorded mainnet congestion** against a **generated order stream**, giving a safe, reproducible testbed in which policies can be trained and compared under identical conditions.

## 2. What is real and what is modelled

| Element | Source | Fidelity |
|---|---|---|
| Block fullness | Recorded D1 | **Real** |
| Block arrival times | Recorded `abs_slot` | **Real** |
| Execution-unit usage | Recorded, sampled window | **Real where available** |
| Protocol limits | `config.protocol` | **Real** |
| Fee formula | `config.protocol` | **Real** |
| Order arrivals | Non-homogeneous Poisson (D2) | Modelled |
| Batch size and execution cost | Estimator, calibrated against preprod | Modelled, measurable |
| Mempool | Finite queue with TTL | Simplified |
| Pool price | Constant product `x * y = k` | Modelled |
| Rollbacks | Rare stochastic event | Simplified |

The distinction matters in the report: congestion is not simulated, it is *replayed*. Only the order side is synthetic.

## 3. Event loop

The clock is the recorded slot sequence, not a fixed tick.

```python
def run_episode(d1_slice, policy, order_stream, seed):
    state = EpisodeState(seed)
    for blk in d1_slice.itertuples():          # blk.abs_slot advances irregularly
        # 1. arrivals
        state.queue.admit(order_stream.arrivals_upto(blk.abs_slot))
        state.queue.evict_expired(blk.abs_slot)

        # 2. resolve in-flight batch against the REAL block
        if state.pool_locked:
            if gate_b(state.in_flight, blk):
                state.confirm(blk.abs_slot)     # record latency, fee, slippage
            elif state.in_flight.ttl < blk.abs_slot:
                state.expire()                  # unlock, return orders, count expiry
            else:
                state.record_head_of_line_wait()
                state.log(blk, action=None)
                continue                        # NO decision is possible while locked

        # 3. forecast
        f_hat = forecaster.predict(history_upto(blk))

        # 4. decide
        obs = state.observe(blk, f_hat)
        act = policy.decide(obs)                # WAIT masked if oldest_wait >= D_MAX

        # 5. act
        if act.submit:
            n = clamp_to_gate_a(act.n, obs)     # policy cannot express infeasible n
            tx = estimator.build(state.queue.take(n), blk.abs_slot)
            state.submit(tx)                    # pool_locked = True

        state.log(blk, obs, act)
    return state.metrics(), state.decision_log
```

`continue` at step 2 is the mechanism the project studies: while a batch is in flight, **no decision exists**. Orders accumulate. That is head-of-line blocking, and it is the cost of a mistimed submission.

## 4. Inclusion model

A submitted transaction enters the mempool. Each subsequent block, it is included if Gate B holds against that block's recorded usage:

```
blk.size  + tx.size  <= 90,112
blk.mem   + tx.mem   <= 62,000,000
blk.steps + tx.steps <= 40,000,000,000
```

If it does not fit, it stays in the mempool and is retried against the next block. It is **not** rejected. It leaves the mempool only by inclusion, by TTL expiry, or by mempool eviction.

This is the correction recorded in `adr/ADR-004`. The earlier design modelled a batch "bouncing" off a full block and being resubmitted, which does not describe Cardano.

## 5. Stated assumptions

Every assumption a reviewer could raise, stated before they raise it.

### A1 · Counterfactual injection

The batch is added to a block that historically did not contain it. The simulator treats recorded usage as **fixed background load** and does not displace any historical transaction.

*Effect:* slightly pessimistic. In reality a block producer selecting from a mempool might have included this batch instead of some marginal transaction. The bias is conservative — it understates the policy's performance rather than overstating it — which is the safe direction for a claim.

### A2 · Single batcher, single pool

One batcher serves one pool with no competitor. No contention for the pool UTXO from other actors.

*Effect:* realistic for the project's own DEX, where the validator authorises exactly one batcher. Not realistic for a permissionless multi-batcher DEX, which is a different problem.

### A3 · No transaction chaining

Cardano permits building a transaction that spends an unconfirmed output. Real batchers sometimes chain batches this way. The simulator forbids it.

*Effect:* conservative. The pool lock is stricter than reality, so measured latency is an upper bound. Chaining is a documented candidate extension.

### A4 · Perfect execution-unit estimation

The estimator returns the exact cost the ledger would charge.

*Effect:* removes a source of Gate A violation that exists in production. Mitigated by the M5 acceptance criterion calibrating the estimator against real preprod transactions (±5 % size, ±10 % execution units), and by a sensitivity run with injected estimation error.

### A5 · Orders are homogeneous in cost

Every order contributes the same marginal size and execution units.

*Effect:* simplifies Gate A to a linear count. A heterogeneous variant is supported by the schema (per-order size and execution columns) and is a straightforward extension.

### A6 · Rollbacks are rare and independent

Modelled as an independent event with small fixed probability per block.

*Effect:* negligible on preprod and on mainnet under normal operation.

### A7 · Slippage is endogenous

Price movement comes from the simulated constant-product pool, not from real market data. It measures the mechanism, not real-world price risk.

## 6. Determinism

Given `(D1 slice, seed, policy, config)` the simulator must produce bit-identical output.

Rules:
- One seeded `numpy.random.Generator` per episode, passed explicitly. No global random state
- No wall-clock time and no dictionary iteration order in any decision path
- Order identifiers are derived from the seed, not from a UUID
- Floating-point metric aggregation happens in a fixed order

A test runs the same episode twice and asserts byte-identical metrics (`10-TEST-PLAN.md`, T-S1).

## 7. Episodes

| Property | Value |
|---|---|
| Length | One day of blocks, about 4,300 steps |
| Training pool | Windows sampled from the D1 train split |
| Validation | Fixed windows from the validation split |
| Test | Fixed windows from the test split, used once |
| Count | 100 episodes per policy per arrival rate |

**Paired evaluation.** Episode *i* presents an identical D1 window and an identical order stream to every policy. Comparisons are therefore paired, and differences are attributable to the decision logic rather than to sampling noise. This is what makes the statistics in `09-EVALUATION-PROTOCOL.md` valid.

## 8. Gymnasium interface

For P3, the same loop is wrapped as a standard environment so Stable-Baselines3 can drive it.

```python
class BatchingEnv(gymnasium.Env):
    observation_space = Box(low=0.0, high=1.0, shape=(11,))
    action_space      = Discrete(len(ACTION_BUCKETS) + 1)   # +1 for WAIT

    def reset(self, seed): ...
    def step(self, action): return obs, reward, terminated, truncated, info
    def action_masks(self): ...    # consumed by MaskablePPO; enforced regardless
```

The mask is enforced inside `step` as well as exposed, so an agent that ignores it still cannot violate an invariant.

## 9. Validation of the simulator itself

A simulator that has not been validated proves nothing. Four checks, all required:

| # | Check | Expected |
|---|---|---|
| V1 | Null policy that never submits | Zero throughput, unbounded latency |
| V2 | E3 greedy | Lowest latency, highest per-user cost |
| V3 | E1 with very large `M` | Behaves like the null policy until `D_MAX` forces submission |
| V4 | Fee replay | Recomputing fees for real recorded transactions from the fee formula matches the actual fees |

V2 is the important one. If greedy does **not** produce the lowest latency and highest cost, the simulator has a bug, because that shape follows directly from the cost model.

V4 validates the fee model against ground truth independently of anything else in the system.

## 10. Known limitations

1. **Order arrivals are modelled, not observed.** No DEX publishes per-order data. Mitigated by sensitivity across three arrival rates and by fitting the diurnal shape to real D1 transaction counts.
2. **Mempool capacity is approximate.** Real mempool behaviour depends on node configuration and propagation. Modelled as a finite queue.
3. **No block-producer selection policy.** Producers choose transactions by their own rules; the simulator assumes first-fit by arrival.
4. **Single pair, single pool.** Multi-pool scheduling is a different problem.
5. **Historical congestion may not represent the future.** Inherent to replay; stated in the report alongside Leios as a factor that will change block dynamics.
