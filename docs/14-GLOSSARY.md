# 14 · Glossary

Terms used across the specification. Cardano concepts first, then the project's own vocabulary, then machine learning.

---

## Cardano

**Active slot coefficient (`f`)** — the probability that a given slot produces a block. On Cardano it is 0.05, so with 1-second slots blocks arrive every 20 seconds *on average*, with geometric spacing. Long and short gaps are both normal.

**Aiken** — a modern smart-contract language for Cardano. Minswap V2 is written in it. Used here for the optional order and pool validators.

**Batcher** — an off-chain program that scans the chain for pending order UTXOs, aggregates many into one transaction, and submits it. Server-side infrastructure, not a wallet. The subject of this project.

**Blockfrost** — a hosted Cardano API. Used here as a fallback data source and for transaction submission.

**CIP-30** — the wallet–web connector standard. A user's wallet signs an order through it. This project does not implement or modify it.

**Datum** — arbitrary data attached to a UTXO. An order's datum states the swap terms, slippage floor and return address.

**Deterministic fees** — Cardano's fee is a fixed function of transaction size and script execution cost. It does **not** rise with network demand. This single property redirects the entire project: congestion costs time, not money. See `adr/ADR-001`.

**eUTXO** — Extended Unspent Transaction Output. Cardano's ledger model: Bitcoin-style discrete outputs extended with a datum and a validator script. Validation is local and deterministic, so a transaction's success and cost are known before submission.

**Execution units (ExUnits)** — the metered cost of running a Plutus script, in two dimensions: memory and CPU steps. Capped per transaction *and* per block, at different values. The per-transaction memory cap is what actually bounds batch size here.

**Koios** — a free, community-run Cardano REST API requiring no key. The primary data source for D1.

**Lovelace** — the smallest ADA unit. 1 ADA = 1,000,000 lovelace. All fee arithmetic in this project is in lovelace.

**Leios (Ouroboros Leios)** — a Cardano upgrade raising base-layer throughput. Addresses congestion at the *protocol* level; this project is an *application*-layer optimization and is positioned as complementary, since block limits and pool concurrency persist regardless of throughput.

**Mempool** — the buffer of submitted-but-unincluded transactions. A transaction waits here; it is **not** rejected for arriving during a full block. Central to the corrected failure model in `adr/ADR-004`.

**Minswap** — the largest Cardano DEX. The inspiration and benchmark for this project, but **not** an integration target: its order UTXOs are locked to its own validator and its batchers must be whitelisted and hold a license token.

**Min-ADA** — the minimum ADA a UTXO must hold. Every user output in a batch must satisfy it.

**Preprod** — a Cardano test network with valueless tokens. All live work in this project targets preprod; mainnet is unreachable by configuration guard.

**Protocol parameters** — chain-wide constants (size caps, execution-unit caps, fee coefficients) changeable by governance. Held in exactly one module here.

**Redeemer** — the argument supplied when spending a script UTXO, carrying the declared execution-unit budget.

**Rollback** — a short fork reverting an already-included transaction. Rare; modelled but not optimized for.

**Slot** — Cardano's one-second time unit. `abs_slot` is the absolute slot number and serves as this project's simulation clock.

**TTL (time to live)** — the slot after which a transaction is no longer valid. A batch that is never included expires at its TTL — one of the three genuine failure modes.

**UTXO** — an unspent transaction output. Consumable exactly once. A DEX liquidity pool is a single UTXO, which is why concurrent swaps require batching.

**Validator** — the on-chain script governing how a UTXO may be spent. The order validator protects users' slippage terms, so a misbehaving batcher cannot short-change them.

---

## Project vocabulary

**Gate A** — the feasibility constraint. A batch must fit within *per-transaction* limits: 16,384 B, 14 M execution memory, 10 G steps. Always binding, independent of congestion. A violation is a defect.

**Gate B** — the inclusion constraint. A batch must fit in the *block* being produced: 90,112 B, 62 M memory, 40 G steps. Congestion-dependent. Failing it means waiting, not failing.

**Head-of-line blocking** — the real cost of a mistimed submission. While a batch is in flight it holds the pool UTXO, so no further batch can be built and every queued order waits. Replaces the "bounce penalty" of the original design.

**Pool lock** — the state variable tracking whether a batch is in flight. At most one batch per pool at a time.

**Amortization curve** — per-user cost as a function of batch size, `FLAT/n + MARGINAL`. Flattens near `n ≈ 10` because only the flat fee component amortizes; execution cost scales linearly with order count. Explains why huge batches are not worth waiting for.

**Pass-through fee** — an order-validator fee design charging `network_fee/n + margin` rather than a flat amount, so amortization savings reach the **user** rather than the batcher. See `adr/ADR-006`.

**D_MAX** — the hard deadline in slots. Once the oldest queued order reaches it, the WAIT action is masked and submission is forced. The starvation guarantee.

**n_max** — the largest feasible batch size under Gate A. Roughly 20–40 orders, bound by per-transaction execution memory.

**Oracle ablation** — running the optimizer with the *true* next-block fullness instead of a forecast. Bounds what any forecaster could achieve, and the gap to it measures forecast quality more usefully than MAE.

**Paired episode** — an evaluation episode presenting an identical block window and order stream to every policy, so differences are attributable to the decision logic rather than to sampling noise.

**D1–D4** — the datasets: block congestion history, order stream, decision log, preprod submission log. See `05-DATA-SPEC.md`.

**M1–M7, E1–E4, P1–P3** — modules, baselines and proposed components. See `04-MODULE-SPECS.md` and `06-ML-SPEC.md`.

---

## Machine learning

**Action masking** — making illegal actions unavailable rather than penalising them. Used here so a learned agent is structurally incapable of violating a ledger rule or starving an order.

**Chronological split** — dividing a time series by time rather than at random. Shuffling would leak future congestion into training and inflate every result. Enforced by test.

**Directional accuracy** — whether a forecast correctly predicts the *sign* of change. More relevant here than MAE, because the policy compares against a threshold rather than using the exact value.

**DQN (Deep Q-Network)** — value-based RL for discrete action spaces. The primary choice here, since the action space is roughly ten discrete options.

**Jain's fairness index** — `(Σw)² / (n·Σw²)` over waiting times. 1.0 means all orders waited equally. Included because a policy can improve mean latency by sacrificing a minority of orders.

**LightGBM** — gradient-boosted trees. The primary forecaster: strong on tabular lag features, trains in minutes on CPU.

**LSTM** — a recurrent network for sequences. The deep-learning forecaster variant, reported whether or not it beats LightGBM.

**MDP (Markov Decision Process)** — the state/action/reward/transition formalism underlying the RL policy. Specified in `06-ML-SPEC.md` §5.

**Paired test (Wilcoxon signed-rank)** — a non-parametric test on per-episode differences. Used because latency distributions are heavy-tailed and not normal.

**Pareto dominance** — being better on every objective at once. The headline claim: the adaptive policy dominates static baselines on both tail latency and per-user cost.

**PPO** — a policy-gradient RL algorithm. The alternative to DQN; `MaskablePPO` supports action masking natively.

**Policy collapse** — an agent degenerating to a single action (always wait, or always maximum). Detected by action-distribution entropy, not by the return curve, which can look healthy while it happens.

**Reward shaping** — designing the reward so the agent optimizes what is actually wanted. Here the terms must be scale-calibrated, or the cost term becomes numerically invisible against latency.
