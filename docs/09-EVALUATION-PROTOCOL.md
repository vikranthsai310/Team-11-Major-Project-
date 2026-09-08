# 09 · Evaluation Protocol

How the claim is tested. Written before results exist, so the protocol cannot be adjusted to fit an outcome.

---

## 1. Claim under test

> An adaptive, congestion-aware batching policy reduces confirmation latency and per-user cost relative to static batching, without increasing order expiry, and without ever violating Cardano capacity limits.

Falsifiable, and falsified by any of: no significant latency improvement; improvement bought with higher expiry; any Gate A violation.

## 2. Metrics

### Primary

| ID | Metric | Definition | Direction |
|---|---|---|---|
| **L-mean** | Mean confirmation latency | `mean(confirm_slot - arrival_slot)` over settled orders, in slots | lower |
| **L-p95** | Tail latency | 95th percentile of the same | lower |
| **C-user** | Mean per-user cost | `mean(fee_lovelace / n)` over batches, weighted by orders | lower |

L-p95 is the headline. Mean latency can be improved by favouring easy periods; the tail is where a badly timed batcher actually hurts users.

### Secondary

| ID | Metric | Definition | Direction |
|---|---|---|---|
| **X-rate** | Expiry rate | orders expiring before inclusion / orders arrived | lower |
| **R-rate** | Mempool rejection rate | rejected submissions / submissions | lower |
| **TP** | Throughput | orders settled per 1000 slots | higher |
| **F-jain** | Fairness | Jain index over per-order waiting times | higher |
| **W-max** | Worst-case wait | `max(confirm_slot - arrival_slot)` | lower |
| **S-slip** | Slippage proxy | mean relative pool-price drift between arrival and execution | lower |
| **LOCK** | Lock occupancy | share of slots with `pool_locked = True` | context |
| **BATCH-n** | Mean batch size | mean `n` over submissions | context |

LOCK and BATCH-n are diagnostic, not scored. They explain *why* a policy wins or loses.

### Forecaster metrics

| ID | Metric | Direction |
|---|---|---|
| **MAE** | Mean absolute error on `fill_pct` | lower |
| **DIR** | Directional accuracy — sign of change predicted correctly | higher |

DIR matters more than MAE for the policy, since the decision is a threshold comparison.

### Fairness definition

```
Jain(w) = (sum w_i)^2 / (n * sum w_i^2)
```

over per-order waiting times. 1.0 means every order waited equally; lower means some waited far longer. Included because a policy can improve mean latency by systematically sacrificing a minority of orders, and that must be visible.

## 3. Policies compared

| ID | Policy | Configuration |
|---|---|---|
| E1 | Fixed size | `M` tuned on validation |
| E2 | Fixed interval | `T` tuned on validation |
| E3 | Greedy | none |
| P2 | Constrained optimizer | `D_MAX`, `N_MIN`, horizon tuned on validation |
| P3 | RL agent | checkpoint selected on validation |
| **ORACLE** | P2 with true next-block fullness | ablation, upper bound |
| **NULL** | Never submits | sanity floor |

Baselines are **tuned**, not guessed. An untuned baseline is a straw man and invalidates the comparison. Report the tuned values in the results table.

ORACLE bounds what any forecaster could achieve. The gap between P2 and ORACLE is the honest measure of forecast quality — more informative than MAE alone.

## 4. Experimental design

**Paired episodes.** Every policy is evaluated on an identical set of episodes: identical D1 window, identical order stream, identical seed. Differences are therefore attributable to the decision logic.

| Factor | Levels |
|---|---|
| Policy | 7 (five plus two references) |
| Arrival rate | 3 — light (0.5x), matched (1.0x), heavy (2.0x) |
| Episodes | 100 per cell |
| RL seeds | 5 for P3 |

Total: 2,100 episodes plus 4 additional P3 seeds x 300. At under 2 seconds per episode, the full evaluation runs in about 20 minutes (`02-TECH-SPEC.md` §10).

**Arrival-rate sweep is required.** A policy that wins only at the rate it was tuned for has not learned congestion adaptation; it has memorised a queue length. The sweep is designed to expose exactly that.

## 5. Statistics

Paired design, so paired tests.

| Question | Test |
|---|---|
| Does P beat E on metric m? | Wilcoxon signed-rank on per-episode paired differences |
| How large is the effect? | Median paired difference with a 95 % bootstrap CI (10,000 resamples) |
| Is it robust across seeds? | Report mean and standard deviation across 5 RL seeds |

**Rules**
- Non-parametric tests. Latency distributions are heavy-tailed and not normal
- Effect size and confidence interval always reported alongside any p-value. A significant but negligible improvement is reported as negligible
- Multiple comparisons: Holm–Bonferroni across the primary metrics
- `alpha = 0.05`
- The test split is used **once**. Every tuning decision happens on validation

## 6. Result presentation

### Main table

| Policy | L-mean | L-p95 | C-user | X-rate | TP | F-jain |
|---|---|---|---|---|---|---|
| NULL | — | — | — | — | — | — |
| E1 (M=?) | | | | | | |
| E2 (T=?) | | | | | | |
| E3 greedy | | | | | | |
| P2 | | | | | | |
| P3 | | | | | | |
| ORACLE | | | | | | |

Each cell: median with 95 % CI. Best value per column in bold. Statistically significant improvements over the best static baseline marked.

### Required figures

| # | Figure | Shows |
|---|---|---|
| F1 | D1 congestion over time with the 80–90 % band shaded | The problem is real |
| F2 | Distribution of block fill percentage | How often congestion actually binds |
| F3 | Amortization curve, per-user cost against `n` | Why huge batches do not pay |
| F4 | Forecast against actual fill on a test window | Forecaster quality, visually |
| F5 | **Pareto scatter: L-p95 against C-user, all policies** | The headline result |
| F6 | Latency CDF per policy | Where in the distribution the gain lives |
| F7 | Action distribution over congestion deciles for P3 | That the agent actually adapts |
| F8 | Metrics across the three arrival rates | Robustness |

F5 is the headline. F7 is what distinguishes a learned policy from a lucky one: it must show the agent submitting more in quiet periods and waiting during predicted congestion. If F7 shows a flat action distribution, the agent has not learned congestion adaptation regardless of what F5 says.

## 7. Ablations

| # | Ablation | Question |
|---|---|---|
| A1 | P2 with forecast against P2 with ORACLE | How much does forecast error cost? |
| A2 | P2 with E4 moving average against P2 with P1 | Does the learned forecaster help the policy, or only the MAE? |
| A3 | P3 without `fill_hat` in the state | Does the agent use the forecast at all? |
| A4 | P3 with a linear rather than quadratic latency penalty | Does the tail penalty do the work? |
| A5 | Estimation error injected at ±10 % | How brittle is Gate A in practice? |

A2 and A3 are the ones a reviewer will ask for. If A3 shows no degradation, the agent is not using the forecast and the "congestion-aware" claim weakens to "queue-aware" — which must then be reported honestly.

## 8. Acceptance thresholds

| ID | Criterion | Threshold |
|---|---|---|
| S1 | P1 MAE below E4 on test | Significant, paired |
| S2 | Gate A violations | Exactly zero across all runs |
| S3 | L-p95 below best static baseline | Significant, with CI excluding zero |
| S4 | X-rate not worse than baseline | CI overlapping or lower |
| S5 | Pareto dominance on (L-p95, C-user) | Visible in F5 |
| S6 | F-jain not worse than baseline | CI overlapping or higher |

S5 failing while S3 holds is still a publishable result: it means latency was improved at some cost, and the trade-off is stated rather than hidden. **S2 failing is a defect and blocks the release.**

## 9. Threats to validity

| Threat | Mitigation |
|---|---|
| Synthetic order arrivals | Diurnal shape fitted to real D1 tx counts; three-rate sensitivity sweep |
| Counterfactual injection (A1 in the simulator spec) | Conservative direction; stated explicitly |
| Overfitting to the test period | Test split touched once; chronological split enforced by test |
| Baseline straw man | Baselines tuned on validation; tuned values reported |
| Single-seed RL result | Five seeds, standard deviation reported |
| Estimator inaccuracy | Calibrated against preprod; ablation A5 |
| Cherry-picked episodes | Paired design across a fixed 100-episode set; no episode selection |

## 10. What would falsify the thesis

Stated plainly, because a hypothesis that cannot be falsified is not being tested:

- P3 and P2 fail to beat the best tuned static baseline on L-p95 across all three arrival rates
- Ablation A3 shows the forecast contributes nothing
- ORACLE barely beats the static baselines, meaning congestion is not actually predictable enough to exploit at this horizon

Any of these is a legitimate, reportable outcome. The project's value lies in a rigorous answer, not a favourable one.
