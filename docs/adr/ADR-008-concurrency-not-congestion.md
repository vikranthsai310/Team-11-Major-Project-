# ADR-008 · Motivate the work by concurrency, not by congestion

**Status:** Accepted · Phase 1 · figures restated from the full 92-day window
**Overturns:** `01-PRD.md` §2.4 ("Evidence the problem is real"), and the congestion framing in the README and the proposed-system deck

## Context

`01-PRD.md` §2.4 motivated the project on a claim taken from Input Output's public
statements: Cardano blocks reach **80–90 % of capacity** during peak activity, so a
~30-order batch (~11 % of a block) fails to fit precisely in that regime. Phase 1
existed to quantify that claim. It did, and the claim does not survive.

Measured on D1 — the full window, 388,781 blocks over 92 days
(2026-06-13 to 2026-09-13), `sha256 48cd6f8b9a9e`:

| Statistic | Measured |
|---|---|
| Mean block fill | 6.83 % |
| Median block fill | 2.95 % |
| 95th percentile | 25.39 % |
| Blocks above 80 % | **0.564 %** |
| Blocks above 90 % | 0.395 % |
| Transactions per block | 3.76 |

Gate B binds on a 30-order batch only above roughly 89 % fill — about one block in
180. **The sustained 80–90 % regime the project was framed around does not appear
in 92 days of mainnet.** This is the failure signature F1 and F2 were specified to
detect (`17-UI-SPEC.md` Part B), detected as intended.

**Congestion is interleaved, not sustained.** The share statistic alone would not
settle this, so episode structure was measured separately:

| | |
|---|---|
| Congested blocks (>80 %) | 2,193 |
| Contiguous episodes | **1,679** — mean run 1.3 blocks |
| Longest unbroken run | **10 blocks (5 minutes)** |
| Runs of 50+ blocks | 0 |
| Days with any congested block | 73 of 93 |
| Share falling in the busiest 5 days | 64 % |
| Busiest single day (2026-07-03) | 11.2 % of its blocks above 80 % |

So a batcher never faces a *run* of blocks it cannot enter; it faces isolated ones
it can wait out, clustered into busy days. A five-minute worst case cannot carry
the motivation for this project.

*(Methodological note, recorded because it nearly produced the opposite
conclusion: F1's detail panel originally plotted 5-minute **maxima**, which paints
the series at 100 % for any window containing one full block and reads as hours of
saturation. The episode measurement contradicted the figure, and the figure was
wrong. It now plots range and median.)*

The predictability gate is weak on the same data, though the headline number badly
misrepresents why:

```
autocorrelation lag 1     0.3724      (still 0.2723 at lag 20)
MAE lag-1 persistence     0.06069
MAE global mean           0.06065
MAE rolling mean k=20     0.05157
lag-1 improvement        -0.1 %   ->  "close to a random walk" by the documented rule
```

Lag-1 persistence ties a global mean, yet a rolling mean beats it by **15.0 %**
and autocorrelation is still 0.27 at lag 20. Those are consistent: on a spiky,
right-skewed series scored by MAE, a persistence predictor copies each spike
forward and is penalised twice, while smoothing is not. **There is real
exploitable structure** — the decision rule in `12-ROADMAP.md` simply chose a naive
predictor poorly matched to this distribution. The rule was followed as written,
and this reading is recorded rather than the rule being rewritten after the fact.

The practical consequence is that E4, the moving-average baseline, is *strong*.
Success metric S1 asks P1 to beat E4, not to beat a global mean, and that remains a
genuinely open question for Phase 3.

**What the data does not touch.** A DEX pool is a single UTXO and can be consumed
once per block. That is a property of the eUTXO ledger, not of how full blocks
are. A submitted batch holds the pool UTXO until it confirms, and every order
queued behind it waits — head-of-line blocking (`ADR-004`). This mechanism is
fully present on an empty chain.

## Decision

Motivate the project by **concurrency under a single-writer resource**, not by
block congestion.

| | Before | After |
|---|---|---|
| Motivating problem | Blocks run 80–90 % full, so batches do not fit | A pool UTXO admits one batch per block, so orders queue behind an in-flight batch |
| Role of the forecaster | Central — the system's intelligence | Secondary and defensive — it avoids the rare full block |
| Role of Gate B | Frequently binding constraint | Rarely binding; **how rarely is itself a reported result** |
| Objective | Latency and amortized per-user cost | **Unchanged** |
| Goals G1–G6, non-goal N1 | — | **Unchanged** |

This is the fallback `11-RISK-REGISTER.md` R4 pre-authorised: *"the project pivots
to queue-aware rather than congestion-aware batching — still adaptive, still beats
static baselines on latency through the pool-lock mechanism, and the negative
forecasting result is reported as a finding about Cardano block dynamics."* It is
executed here as written, not improvised.

The congestion measurement is **not** discarded. It is promoted from background
motivation to a first-class empirical result: a characterisation of Cardano
mainnet block occupancy over 90 days, with the observation that the ecosystem's
widely-repeated congestion claim does not describe the chain as it currently runs.

## Consequences

**Positive**
- The premise now matches measured data rather than a quoted claim, which is the
  stronger position in a viva by a wide margin
- The contribution no longer depends on the chain being busy, so the result does
  not expire when activity changes in either direction
- D1 plus this finding is publishable on its own merits
- The ORACLE ablation (A1) now quantifies something genuinely interesting: how
  little a *perfect* forecast is worth when the constraint rarely binds

**Negative**
- The headline weakens from "AI predicts congestion" to "policy manages a lock
  under uncertain service time". Less marketable, more defensible
- Phase 3 may show the forecaster contributing little to policy performance. That
  is now an expected outcome to be reported, not a failure
- Reviewers arriving from the earlier decks will expect the congestion story;
  Chapter 1 must perform the pivot explicitly and early (see `X-13`)

**Trigger to revisit**

A deliberately chosen historical window covering a known congestion episode, showing
**sustained** fill in the 80–90 % band, restores congestion as a co-equal
motivation. "Sustained" is now defined rather than left to judgement: runs of 50+
consecutive blocks above 80 %, or a day spending 25 %+ of its blocks there. The
full window contains neither — the longest run is 10 blocks and the busiest day
reaches 11.2 %.

Do not restore it on the strength of isolated spikes. F1 shows hourly maxima
reaching 100 % regularly while the median sits near 3 %, and a motivation built on
maxima would be the same overstatement being corrected here — as the 5-minute-maxima
panel demonstrated in the course of writing this ADR.

**Regression guard**

`T-S5` is the guard: head-of-line blocking must be observable in the simulator
with congestion held low. If the project's central mechanism cannot be
demonstrated on a quiet chain, this reframing is unsupported and the claim must be
withdrawn. Additionally, no congestion figure may appear in the report that is not
produced by `congestion_shares()` from a checksummed dataset — the quoted
80–90 % claim entered the project unsourced, and that is the error being fixed.

## Alternatives considered

| Alternative | Rejected because |
|---|---|
| Keep the congestion framing | The measured data contradicts it. Presenting it anyway is the one thing that would genuinely fail a viva |
| Collect a historical congested window and study that regime instead | Defensible and still open as future work, but it answers a question about 2021 Cardano rather than about Cardano. It also doubles the collection and analysis effort mid-project |
| Abandon the project premise entirely | Unwarranted. The concurrency constraint is real, load-bearing and unaddressed by deployed batchers, which still trigger on constants |
| Switch chains to one where congestion does bind | The eUTXO pool-lock mechanism is the subject; an account-model chain does not have it |
