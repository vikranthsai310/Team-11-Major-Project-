# ADR-001 · Optimize latency and amortized cost, not gas fees

**Status:** Accepted · **Supersedes:** the original project framing

## Context

The project began with an Ethereum-shaped intuition: *when blocks are heavy, submit smaller bundles to reduce gas fees; when blocks are light, submit large bundles.* This assumes fees rise with network demand.

On Cardano they do not. The fee is a deterministic function of transaction size and script execution cost:

```
fee = 44 * size_bytes + 155,381 + 0.0577 * mem_units + 0.0000721 * cpu_steps
```

There is no gas auction, no priority-fee bidding and no mempool bidding war. Two identical transactions cost exactly the same on an idle chain and on a saturated one. This is a direct consequence of eUTXO determinism [1]: validation is local, so cost is knowable before submission and cannot depend on what else is in the block.

What congestion actually causes on Cardano is **delay**. When blocks approach capacity, a transaction waits in the mempool for a later block. The user never pays more; they wait longer.

## Decision

The objective function is **confirmation latency** and **per-user cost through amortization**, subject to hard capacity constraints. It is **not** fee minimization under congestion.

Concretely:
- The fee function takes no block-state argument. It is structurally incapable of depending on congestion (guarded by test T-F3)
- The reward has no congestion-priced fee term
- Reporting language never claims reduced fees during congestion

Roughgarden's EIP-1559 analysis [10] is cited as the **contrast**: it models precisely the demand-responsive pricing that Cardano lacks, which is what makes the objective different here.

## Consequences

**Positive**
- The premise is technically correct. A reviewer familiar with Cardano would immediately flag the original framing
- The optimization target is sharper: batch size trades per-user cost against latency and inclusion timing, a genuine and non-trivial trade-off
- It gives the project a clean literature position — [10] establishes the contrast, [1] explains the mechanism

**Negative**
- "Reduces gas fees" is a more intuitive pitch than "reduces confirmation latency". The framing needs explaining every time
- The cost-side gain is modest, because only the flat fee component amortizes (see `ADR-002` and the amortization curve in `07-CONSTRAINTS-COST-MODEL.md` §5). Latency does most of the work in the objective

**Language rule for all written material**

> Do **not** write: "reduces gas fees via congestion-aware bundling."
> Write: "minimizes per-user cost through amortization while minimizing confirmation latency, subject to block-size and execution-unit limits."

## References

[1] Chakravarty et al., The Extended UTXO Model, FC 2020
[10] Roughgarden, EIP-1559 analysis, arXiv:2012.00854
