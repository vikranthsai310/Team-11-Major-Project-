# 15 · References

Verified references grouped by the part of the project each supports. Peer-reviewed work is separated from technical reports, theses and specifications, because that distinction matters in an academic bibliography.

**Before final submission, verify every entry against the publisher.** Venues, page numbers and preprint versions differ across sources.

---

## Cardano and the eUTXO model

**[1]** M. M. T. Chakravarty, J. Chapman, K. MacKenzie, O. Melkonian, M. Peyton Jones, and P. Wadler, "The Extended UTXO Model," in *Financial Cryptography and Data Security (FC 2020) Workshops*, Springer, 2020.
· https://iohk.io/en/research/library/papers/the-extended-utxo-model/
· *Role:* the formal definition of Cardano's ledger. The source of deterministic fees and of the single-pool-UTXO concurrency constraint — the foundation of the problem statement.

**[2]** M. M. T. Chakravarty et al., "Native Custom Tokens in the Extended UTXO Model," in *ISoLA 2020*, Springer, 2020.
· *Role:* the multi-asset extension. Relevant because the DEX swaps native tokens.

## Consensus and scaling

**[3]** A. Kiayias, A. Russell, B. David, and R. Oliynykov, "Ouroboros: A Provably Secure Proof-of-Stake Blockchain Protocol," in *CRYPTO 2017*, Springer, pp. 357–388.
· https://eprint.iacr.org/2016/889
· *Role:* Cardano's consensus. The source of the 1-second slot and `f = 0.05`, hence the geometric block cadence the simulator replays.

**[4]** Input Output Research, "Ouroboros Leios: Design Goals and Concepts," technical report, with peer-reviewed analysis accepted to *CRYPTO 2025*.
· https://www.iog.io/papers/ouroboros-leios-design-goals-and-concepts
· *Role:* the protocol-level throughput upgrade. Cited to position this work as a complementary application-layer optimization. *Technical report.*

## eUTXO concurrency and batching — the core prior work

**[5]** H. Nguyen Quang (MELD), "Concurrent & Deterministic Batching on the UTXO Ledger," MELD technical report, 2021.
· https://meld-labs.github.io/technical/reports/2021/09/09/concurrent-deterministic-batching-utxo.html
· *Role:* the closest existing work — establishes batching as the accepted answer to eUTXO concurrency. **Its batching is static and rule-based; that is the gap this project fills.** *Technical report.*

**[6]** P. Brühwiler, "A Concurrent DEX on Cardano: How to Write Scalable Apps on a UTXO Blockchain," BSc thesis, University of Bern, 2021.
· https://crypto.unibe.ch/archive/theses/2021.bsc.peter.bruehwiler.pdf
· *Role:* academic treatment of the same concurrency problem with a working prototype. Targets correctness, not batching *timing*. *Thesis.*

**[7]** O. Hryniuk (IOHK), "Concurrency and all that: Cardano smart contracts and the EUTXO model," 2021.
· https://iohk.io/en/blog/posts/2021/09/10/concurrency-and-all-that-cardano-smart-contracts-and-the-eutxo-model/
· *Role:* background on fan-out, batching and order-book patterns for contention. *Technical article.*

## AMM and DEX design

**[8]** G. Angeris and T. Chitra, "Improved Price Oracles: Constant Function Market Makers," in *ACM AFT '20*, 2020, pp. 80–91.
· https://arxiv.org/abs/2003.10001
· *Role:* the theory behind the `x·y = k` pool validator and the endogenous slippage model.

**[9]** G. Angeris, H.-T. Kao, R. Chiang, C. Noyes, and T. Chitra, "An Analysis of Uniswap Markets," *Cryptoeconomic Systems*, 2020.
· https://arxiv.org/abs/1911.03380
· *Role:* foundational constant-product market analysis.

## Transaction fee mechanisms — the contrast that justifies the premise

**[10]** T. Roughgarden, "Transaction Fee Mechanism Design for the Ethereum Blockchain: An Economic Analysis of EIP-1559," arXiv:2012.00854, 2020. Extended version: arXiv:2106.01340 (*EC '21*).
· https://arxiv.org/abs/2012.00854
· *Role:* **the pivot citation.** Models demand-responsive fee pricing — a base fee that rises as blocks fill. Cited to establish precisely what Cardano does *not* do, and therefore why the objective here is latency rather than fees. See `adr/ADR-001`.

## Transaction reordering and fairness

**[11]** "SoK: Preventing Transaction Reordering Manipulations in Decentralized Finance," arXiv:2203.11520, 2022.
· https://arxiv.org/abs/2203.11520
· *Role:* supports the fairness and batcher-trust discussion, and independently states the eUTXO constraint that a pool permits only one interaction per block.

## Machine learning — method

**[12]** R. S. Sutton and A. G. Barto, *Reinforcement Learning: An Introduction*, 2nd ed. MIT Press, 2018.
· *Role:* standard reference for the MDP formulation. The authors' free copy is available from Sutton's university page.

**[13]** V. Mnih et al., "Human-level Control through Deep Reinforcement Learning," *Nature*, vol. 518, pp. 529–533, 2015.
· https://www.nature.com/articles/nature14236
· *Role:* DQN, the primary agent for the discrete action space.

**[14]** J. Schulman, F. Wolski, P. Dhariwal, A. Radford, and O. Klimov, "Proximal Policy Optimization Algorithms," arXiv:1707.06347, 2017.
· https://arxiv.org/abs/1707.06347
· *Role:* PPO, the policy-gradient alternative; `MaskablePPO` provides native action masking.

**[15]** H. Mao, M. Alizadeh, I. Menache, and S. Kandula, "Resource Management with Deep Reinforcement Learning," in *ACM HotNets '16*, 2016, pp. 50–56.
· https://www.microsoft.com/en-us/research/publication/resource-management-deep-reinforcement-learning/
· *Role:* **the method template.** DeepRM learns to pack arriving jobs with multi-dimensional resource demands into capacity-limited slots, trained in a simulator. Structurally the same problem as packing orders into capacity-limited blocks.

**[16]** H. Mao, M. Schwarzkopf, S. B. Venkatakrishnan, Z. Meng, and M. Alizadeh, "Learning Scheduling Algorithms for Data Processing Clusters" (Decima), in *ACM SIGCOMM '19*, 2019, pp. 270–288.
· https://dl.acm.org/doi/10.1145/3341302.3342080
· *Role:* a more advanced sibling of DeepRM; RL scheduling policies learned from simulation.

**[17]** S. Hochreiter and J. Schmidhuber, "Long Short-Term Memory," *Neural Computation*, vol. 9, no. 8, pp. 1735–1780, 1997.
· https://direct.mit.edu/neco/article/9/8/1735/6109
· *Role:* the recurrent forecaster variant P1b.

---

## Primary technical sources

Not academic papers, but load-bearing for specific factual claims. Cite them where the claim is made.

| Source | Claim it supports |
|---|---|
| Cardano protocol parameters guide — https://docs.cardano.org/about-cardano/explore-more/parameter-guide | Every capacity limit and fee coefficient in `07-CONSTRAINTS-COST-MODEL.md` |
| Minswap V2 contract specification | Batchers must be whitelisted; stableswap requires a license token — the basis of `adr/ADR-003` |
| Minswap Laminar whitepaper | Prior work on decentralizing batching; positions this project's differentiator as *learned timing*, not decentralization |
| Aiken language documentation — https://aiken-lang.org | The optional on-chain layer |
| Koios API documentation — https://api.koios.rest | D1 collection |
| Blockfrost API documentation — https://docs.blockfrost.io | Fallback collection and submission |
| Input Output statements on block capacity | The 80–90 % peak congestion figure |

---

## How the literature supports the argument

The five deck papers form a single arc, and it is worth being able to state it in one breath at the review:

| # | Paper | Supplies | Leaves open |
|---|---|---|---|
| [1] | Extended UTXO Model | The platform, deterministic fees, the single-pool-UTXO bottleneck | Defines the concurrency problem; does not solve it |
| [5] | MELD batching | Batching as the accepted solution | Batching is static and rule-based |
| [6] | Concurrent DEX thesis | Academic validation of the problem and a prototype | Targets correctness, not timing |
| [10] | EIP-1559 analysis | Demand-responsive fees on account-based chains | Does not apply to Cardano — which is exactly the point |
| [15] | DeepRM | RL for resource packing under capacity limits, trained in simulation | Knows nothing of eUTXO, block limits, or the latency–cost trade-off |

The gap: **[5] and [6] establish batching but batch statically; [15] shows this class of problem is learnable; [10] proves the objective must be latency rather than fees; [1] explains why.** No existing work applies a learned, congestion-aware policy to eUTXO batch timing. That is the contribution.
