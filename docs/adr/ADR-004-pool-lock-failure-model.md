# ADR-004 · Model failure as pool-UTXO head-of-line blocking, not batch rejection

**Status:** Accepted · **Supersedes:** the "bounce penalty" in the earlier reward design

## Context

The earlier design modelled the failure mode as: submit a batch → the block is full → the batch is **rejected** → resubmit. The reinforcement-learning reward carried a large penalty for a batch that "failed to get included," and the simulator resubmitted bounced batches.

That is not how Cardano works. A submitted transaction enters the **mempool** and is included whenever a block has room for it. It is not rejected for arriving during a full block, and lateness is not a rejection condition. Penalising a non-existent event would teach the agent an incorrect model of its environment.

The real mechanism is different and more interesting. **A batch consumes the pool UTXO.** Until the batch confirms, the new pool output does not exist, so a second batch cannot be constructed on top of it. At most one batch is in flight per pool.

```
t0  submit batch A             -> pool locked
t1  block full, A not included -> queue grows, NO decision possible
t2  block full, A not included -> queue grows further
t3  A included                 -> pool unlocked, decision possible again
```

Submitting into predicted congestion does not waste a fee — it **locks the pool** and every order behind it waits. That is the real cost of a mistimed submission.

## Decision

Model the failure mode as **head-of-line blocking on the pool UTXO**.

- `pool_locked` is an explicit state variable, in the observation and enforced by the environment
- While locked, the only legal action is WAIT — enforced by the loop, not left to the policy
- The reward term is `w_lock * slots_pool_locked`, replacing the bounce penalty
- **No inclusion-failure penalty exists**, because that event does not exist

Genuine failures are limited to three, counted separately because they have different causes and different fixes:

| Failure | Cause |
|---|---|
| TTL expiry | Validity interval passes before inclusion |
| Mempool rejection | Mempool full at submission time |
| Rollback | A short fork reverts an included batch |

## Consequences

**Positive**
- The MDP is materially more defensible: the agent manages **a single shared lock under uncertain service time**, a well-posed sequential decision problem, rather than guessing whether a block is full
- It explains *why forecasting has value* — the agent is predicting how long the lock will be held, not merely whether a block has room
- Head-of-line blocking is directly observable in the decision log (D3) and produces a clear, explicable figure for the report

**Negative**
- The simulator is more complex: it needs a mempool, an in-flight transaction and a lock state, rather than a simple fit-or-bounce test
- Latency now has two components, `queue_wait` and `in_flight_wait`, only the first of which the policy controls directly. Attribution in the results requires care

**Conservative simplification**

Cardano permits chaining a transaction onto an unconfirmed output, and real batchers sometimes do this to keep working while a batch is in flight. The model forbids chaining, making the lock stricter than reality. This biases measured latency **upward** — the safe direction for a claim — and chaining is recorded as a candidate extension.

**Regression guards**

- **T-S5** — with an artificially long confirmation time, queue depth must grow monotonically while locked
- The outcome enumeration contains no `bounced` variant, so the old model cannot be reintroduced by accident
