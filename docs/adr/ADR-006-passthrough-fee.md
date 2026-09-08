# ADR-006 · The order validator charges a pass-through batcher fee

**Status:** Accepted

## Context

Goal **G2** and the merits claimed in the proposed-system deck state that the system *"lowers average per-user cost by amortising the fixed fee component across larger batches."*

Whether that is true for **users** depends entirely on how the batcher fee is structured, and the deployed convention breaks it.

On Minswap, each order pays a **flat** batcher fee of about 2 ADA, baked into the order transaction. The batcher pays the network fee for the batch. So when a batch grows from 5 orders to 30:

- the network fee per order falls from about 0.102 ADA to about 0.071 ADA
- the user still pays a flat 2 ADA
- **the saving accrues entirely to the batcher**

Under a flat fee, the amortization the project optimizes for is real but is captured by the operator. The user-facing claim would be false, and a reviewer checking it against Minswap's actual fee structure would find it so.

## Decision

The order validator charges a **pass-through** fee:

```
user_pays = network_fee(n) / n + fixed_margin
```

The user pays their share of the actual network fee, plus a small fixed margin for the batcher's service. Amortization therefore reaches the user directly, and goal G2 is genuinely delivered.

This is enforced **on-chain** in `onchain/validators/order.ak`: a batch transaction that charges a user more than their computed share fails validation.

## Consequences

**Positive**
- The per-user cost claim is true as stated, and the metric `C-user` measures something the user actually experiences
- It is a genuine design contribution alongside the ML, and a good answer to "what did you build on-chain, and why?"
- Enforcing it in the validator means a misbehaving or buggy batcher cannot quietly revert to flat pricing

**Negative**
- The batcher's revenue becomes independent of batch size, removing an economic incentive that a real operator might want. Acceptable here: the project optimizes user outcomes, not operator revenue, and says so
- The validator must compute `network_fee(n) / n` on-chain, which costs execution units and therefore slightly reduces `n_max`. Small, but it must be included in the Gate A estimates rather than ignored

**Reporting requirement**

The report must state the fee model explicitly and note that Minswap's flat fee differs. Comparing a pass-through system against a flat-fee system on per-user cost without disclosing the difference would be misleading.

**Regression guard**

Test **T-O5** verifies the user is charged `network_fee/n + margin`, and **T-O2** verifies the slippage floor is enforced independently of the fee logic.

## Note on scope

This decision is only implementable because the project builds its own DEX (`ADR-003`). It is a concrete example of why owning the validator matters: the headline user-facing claim depends on a fee design that no third-party DEX would let this project change.
