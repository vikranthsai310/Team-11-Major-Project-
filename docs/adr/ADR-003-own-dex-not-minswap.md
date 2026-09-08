# ADR-003 · Build a minimal own DEX rather than integrate with Minswap

**Status:** Accepted

## Context

The natural first instinct is to run the intelligent batcher against real traffic on an existing DEX such as Minswap. Two independent walls make this impossible — not difficult, impossible.

**Wall 1 — orders are bound to their creating validator.** A user's order UTXO is locked at Minswap's script address and can be spent only by a transaction satisfying Minswap's validator. A third-party batcher cannot consume it on its own terms; any such transaction is rejected by the network as invalid. Orders cannot be intercepted or rerouted.

**Wall 2 — Minswap's batching is permissioned.** The Minswap V2 specification requires a batcher to be whitelisted in the protocol's global settings, and the stableswap contracts additionally require a valid, unexpired batcher license token. Even a perfect re-implementation of their batching logic would be rejected, because the executing key is not authorised.

There is no API, hook or configuration through which an external batcher can be substituted. The marketing description of a "decentralized network of batchers" describes a permissioned, licensed set at the contract level.

The general principle: **a batcher is always bound to a specific script.** Orders are created pointing at that script, and only a batcher that script authorises can serve them. The question is therefore not "how do I connect to Minswap's orders" but "how do I obtain orders pointing at a script my batcher may serve."

## Decision

Build a **minimal own DEX** on the Cardano preprod testnet: an order validator and a pool validator written in Aiken, with this project's batcher as the authorised executor.

Minswap becomes the **inspiration and benchmark**, not an integration target.

Critically, this on-chain layer is scoped as **optional** (M7, Phase 7). Every result in the project is produced in the simulator, which needs no chain at all.

## Consequences

**Positive**
- The wallet-to-batcher path exists cleanly through the project's own order script, exactly as Minswap's exists through theirs
- Full control of the validator, so the pass-through fee design of `ADR-006` is possible — without it, the per-user cost claim would not hold
- The demonstration is self-contained and reproducible, with no dependency on a third party's deployment or goodwill

**Negative**
- Real Aiken and off-chain development effort, with a genuine learning curve. This is risk **R3**, the highest-scoring schedule risk in the register
- The demo runs on synthetic testnet traffic rather than real user orders, so the live component demonstrates mechanism rather than real-world performance

**Mitigations**
- M7 is scheduled last and is pre-authorised to be dropped if preprod deployment is not achieved within three weeks (`12-ROADMAP.md`, Phase 7)
- Production concerns — audit, MEV protection, liquidity incentives, batcher decentralization — are explicitly out of scope. This is the smallest DEX that lets an intelligent batcher be demonstrated, not a competitive one

## Alternative considered and rejected

**Find a genuinely permissionless Cardano DEX and batch for it.** Some protocols are more open than Minswap. Rejected because verifying and correctly implementing a third party's exact validator rules is a large effort with no research payoff, and a change to their contracts would break the project mid-semester. The dependency risk outweighs the realism gained.
