# ADR-002 · Batch size is bounded by transaction limits, not block limits

**Status:** Accepted · **Supersedes:** the optimizer formulation in `Doc/team-11-proposed-system-and-design.pptx`, slide 13

## Context

The earlier design sized batches against the **block** limit:

```
P2 optimizer:   C_hat <- (1 - fill_hat) * S_max        # S_max = 90,112 bytes
                grow n while size/ExUnits fit C_hat
```

A batch is **one transaction**, and Cardano caps transactions well below blocks:

| Limit | Per transaction | Per block | Ratio |
|---|---|---|---|
| Size | **16,384 B** | 90,112 B | 18 % |
| Execution memory | **14,000,000** | 62,000,000 | 23 % |
| Execution steps | **10,000,000,000** | 40,000,000,000 | 25 % |

The formulation above has two defects. On an empty chain it proposes a batch of up to 90,112 bytes — an **invalid transaction**. And it implies that an emptier block permits a larger batch, which is false: the per-transaction ceiling is fixed regardless of congestion.

A second error was found alongside this: earlier material stated a per-block step budget of 20 G. It is **40 G**.

## Decision

Two independent constraint sets, evaluated separately and never conflated.

**Gate A — feasibility.** Always binding, congestion-independent:
```
TX_OVERHEAD + sum(order_size[:n])  <= 16,384
POOL_MEM    + sum(order_mem[:n])   <= 14,000,000
POOL_STEPS  + sum(order_steps[:n]) <= 10,000,000,000
```

**Gate B — inclusion.** Congestion-dependent, predicted at decide time and evaluated against the real block at inclusion time:
```
blk.size + tx_size(n) <= 90,112     (and the two execution dimensions)
```

Gate A bounds **how large a batch may be**. Gate B determines **whether it fits now**.

## Consequences

**Positive**
- Batch size is bounded at roughly **20–40 orders**, binding on per-transaction execution memory. This matches observed Minswap batch sizes of 25–40 — a useful independent check
- The action space becomes small and discrete, which makes DQN genuinely tractable rather than aspirational
- The problem statement survives with a number behind it: a 30-order batch is about 11 % of a block, so it fails Gate B only above roughly 89 % fullness — precisely the 80–90 % peak regime the project targets

**Negative**
- Removes an imagined lever. The policy cannot "batch bigger when the chain is quiet" beyond `n_max`; on an idle chain the only remaining decision is *when*, not *how much*
- The per-order size and execution estimates must be calibrated against real transactions, or Gate A is enforced against fiction (M5 acceptance criterion; risk R5)

**Regression guard**

Test **T-G5** asserts `max_n(fill=0.0) == max_n_gate_a` — an empty block must not raise the cap. This test exists solely to prevent the original error being reintroduced and must never be deleted.

## Notes

The error is a natural import from Ethereum, where the gas limit is per block and a transaction's practical ceiling is the block gas limit. Cardano meters transactions and blocks separately, and the transaction limit binds first.
