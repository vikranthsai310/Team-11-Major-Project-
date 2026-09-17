# 19 · Robustness review: drawbacks, real-world scenarios and fixes (Phase 8)

A read-through of everything built by the end of Phase 7, looking for the ways the idea
fails outside the simulator. Ten real-world scenarios were used to stress it; each exposed
a concrete drawback, and each drawback got a fix with tests. Numbers below come from the
**validation split** only — the test split stays evaluated exactly once (Phase 6).

---

## 1. What was built before this review

| Layer | What exists | Where |
|---|---|---|
| Data | 92 days, 388,781 mainnet blocks from Koios (Blockfrost fallback), resumable, checksummed | `src/batcher/data/` |
| Forecasting | Moving average (E4), mean-reverting (E4b), LightGBM over t+1..t+3, oracle | `src/batcher/forecast/` |
| Simulator | Replays recorded blocks; Poisson arrivals with a fitted daily shape and bursts; FIFO queue; pool lock; Gate A / Gate B; TTL expiry; rare rollbacks | `src/batcher/sim/` |
| Policies | E1 fixed size, E2 fixed interval, E3 greedy, P2 constrained optimizer, oracle, P3 masked DQN | `src/batcher/policy/`, `src/batcher/sim/gym_env.py` |
| Evaluation | Paired episodes, bootstrap CIs, Wilcoxon + Holm, manifests | `src/batcher/eval/`, `experiments/phase6-final-evaluation/` |
| On-chain | Aiken order and pool validators with a pass-through fee, deployed to preprod; one live swap settled | `onchain/`, `experiments/phase7-preprod-demo/` |
| Live batcher | Shadow/live daemon reusing the simulator's rules, two-pass fee-exact builds | `src/batcher/live/`, `src/batcher/build/` |
| Dashboard | Local read-only app: intro, Overview, Simulator, Results, Live | `src/batcher/dashboard/` |

## 2. Drawbacks of the idea (before this phase)

**The project's own findings**
- On today's chain capacity rarely binds, so **no adaptive policy beats greedy on tail latency**; the gain is cost and fairness. A perfect forecast (oracle) adds almost nothing over P2.
- **The real throughput limit is structural:** one batch per decision point (the pool lock) × a Gate A maximum of 24 orders per transaction.

**Live-path weaknesses (found by reading the code)**
- A negative `margin` in an order datum would make the batcher's own wallet pay the difference.
- A malformed address crashed the queue read.
- An unfillable or failing order was never removed: it pinned `oldest_wait`, forced a submission every block, and could stop batching altogether.
- If an order was cancelled after the batch was submitted, the pool stayed locked for the whole 600-slot TTL.
- No confirmation depth or rollback handling, and a race at TTL that could misread a late inclusion as an expiry.
- Any API error crashed the daemon, even with a batch in flight.
- Gate A used hard-coded protocol limits and an estimate 3.4× too small on size, with no learning from real transactions and no retry after an oversize build.

**Policy and simulator weaknesses**
- When a submission was forced, the DQN's mask repair sent **one** order instead of the Gate A maximum; nothing shielded it at runtime.
- `D_MAX` was enforced only after it was already missed.
- A slot missing from the forecast cache read as an empty block, which silently turns Gate B off.
- A missing LightGBM model fell back to the moving average without saying so.
- Latency counted settled orders only, so expired orders disappeared from `l_p95`.

**Fairness**
- Orders filled one after another against the pool, so later orders got worse prices. The validators only enforce `min_out`, so the batcher could also reorder orders for its own benefit.

## 3. Ten real-world scenarios and the fix for each

| # | Scenario | Drawback exposed | Fix | Code |
|---|---|---|---|---|
| 1 | **Market crash** — prices move while orders wait | Unfillable and poison orders block the queue and force submissions | **Quarantine with bisection:** strikes for unfillable orders (quarantined after 3, released after 30 blocks); a failed build is split in halves to isolate the poison order in O(log n) builds, never submitting while isolating | `live/daemon.py` |
| 2 | **Malicious user** crafts orders | A negative margin drains the batcher; a bad address crashes the loop | **Admission guard:** refuses `amount_in ≤ 0`, `min_out < 0`, `margin < 0`, a malformed owner or an undecodable address, with the reason recorded | `build/tx_builder.py` (`order_rejection`) |
| 3 | **Rival batcher, or a user cancelling** after submission | The pool is held until TTL for a batch that can never land | **Input-liveness watchdog:** a vanished input resolves the batch as `invalidated` at the next block and unlocks the pool; owners who repeatedly cancel under our batches are served last | `live/daemon.py` |
| 4 | **Blockfrost outage or rate limit** on a busy day | An API error crashes the daemon | **Resilient chain:** retries with capped jittered backoff, a circuit breaker with a half-open trial, failover to secondary providers; the daemon records `api_unavailable`, decides nothing on a stale view and keeps any batch in flight. Submission is never retried blindly | `live/resilience.py` |
| 5 | **Chain rollback** | The first sighting counted as final; the TTL race misread late inclusions | **Settlement depth** (default 3 blocks), a grace re-check at TTL, and a rolled-back batch keeps the pool locked until its TTL because the transaction can come back from the mempool | `live/daemon.py` |
| 6 | **Protocol parameters change** (governance, Leios), or real transactions are larger than modelled | Static limits; size under-estimated 3.4×; no learning; no retry | **Self-calibrating capacity gate:** effective limit = min(live, configured); per-dimension correction learned from measured transactions (raised at once, lowered only after 5 consistent readings, floor 0.5), seeded from D4; shrink-and-retry halves n on an oversize build and never submits one | `build/calibration.py`, `live/daemon.py` |
| 7 | **Token-launch rush** — load beyond what the agent was trained on | The DQN's forced submission sends 1 order; no runtime safety | **Safety shield:** a forced submission always uses the Gate A maximum; out-of-range inputs hand the decision to P2; the env's mask repair can pick the largest legal batch | `policy/shield.py`, `sim/gym_env.py` (`illegal_action="largest"`) |
| 8 | **Network-wide rush or congestion** — backlog beyond one batch per block | Deadline overshoot at heavy load; one batch per block × 24 orders | **Transaction chaining:** a new batch spends the pool output of the batch still in the mempool, so several batches can go out at one decision point. They resolve in order, share block space, and a parent's rollback or expiry takes its children down too. Also `DeadlineAwarePolicy` submits before `D_MAX` from learned block gaps | `sim/env.py` (`chain_depth`), `policy/shield.py` |
| 9 | **Whale order beside retail orders** / MEV | Later orders get worse prices; the batcher can reorder | **Uniform clearing:** all same-direction orders in a batch share one price; opposite-direction orders net against each other and only the imbalance touches the pool; order-independent by construction and the pool invariant is checked | `build/submitter.py` (`clearing="uniform"`, default) |
| 10 | **Fresh machine or data gap** at demo time | A missing model falls back silently; a missing forecast reads as an empty block; expiries are hidden from latency | **Fail-safe forecasting:** a missing slot returns a conservative high fill; a missing model is an explicit, logged `MovingAverageFallback` the dashboard names. **Honest latency:** `l_mean_all`, `l_p95_all`, `w_max_all` count expired orders at their wait until expiry | `forecast/base.py`, `forecast/lgbm.py`, `eval/metrics.py`, `dashboard/data.py` |

Also added: CI now runs `ruff format --check` and the secret scan, so those protections do
not depend on someone having installed the pre-commit hooks.

## 4. Evidence

**Scenario 7 — safety shield** (`experiments/phase8-robustness/`, 10 validation episodes, medians)

| Rate | Policy | L-p95 | Expired orders (median / max) | Cost per user |
|---|---|---|---|---|
| heavy | DQN seed 3 as recorded | 3,605 | **35.7 % / 58.6 %** | 116,445 |
| heavy | DQN + largest-batch repair | 255.0 | 0 / 0 | 106,861 |
| heavy | **Shield(DQN → P2)** | **245.5** | **0 / 0** | **79,487** |
| heavy | P2 (N=4) | 245.5 | 0 / 0 | 100,662 |

The shield intervenes often (about 40 % of decisions are forced or delegated), so the agent
alone is still not trustworthy at heavy load; with the shield it is safe and the cheapest.

**Scenario 8 — chaining** (`experiments/phase8-chaining/`, 10 validation episodes, medians)

| Rate | Policy | Chain depth | L-p95 | Worst overshoot past D_MAX | Settled after D_MAX | Cost per user |
|---|---|---|---|---|---|---|
| heavy | P2 (N=4) | 1 (recorded) | 245.5 | 300 | 16.4 % | 100,662 |
| heavy | P2 (N=4) | **2** | **120.0** | **96** | **5.0 %** | 101,868 |
| heavy | P2 (N=4) | 3 | 113.0 | 96 | 3.7 % | 102,061 |
| matched | P2 (N=4) | 1 → 2 | 127.0 → 124.5 | 84 → 84 | 6.3 % → 5.7 % | +0.1 % |

A diagnosis on validation days found **no** batch expired behind a full block at heavy load,
while 7–10 % of submissions left a backlog beyond one Gate A batch. So the ceiling was one
batch per decision point, not congestion. That is why `DeadlineAwarePolicy` alone did not help
at heavy load (245.5 either way) and chaining did.

**Reproducibility:** every fix is opt-in or leaves the recorded paths unchanged.
`run_episode` output on three validation days × two rates × three policies has the same
SHA-256 before and after this phase, so every Phase 6 number stays reproducible.

## 5. What remains unsolved

- **Chaining exists in the simulator only.** The live daemon still locks the pool until settlement. Chaining live needs the daemon to build on its own unconfirmed pool output and handle a parent failing mid-chain.
- **The calibrator's error matching is text-based** and not yet tested against real Ogmios or Blockfrost error bodies. Multi-order live batches are still needed for a real calibration.
- **One hard-wired batcher key** in both validators: no rotation or hot standby without redeploying the pool. No on-chain order deadline; users rely on cancel.
- **Uniform clearing redistributes price impact:** orders ahead of a whale now share its impact instead of trading before it. That is the defining property of a fair batch auction, but it is a choice.
- **Single pool, synthetic arrivals, one 92-day window,** as before.
