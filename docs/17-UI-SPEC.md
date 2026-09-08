# 17 · UI Specification — Dashboard Wireframes and Figure Specs

Fills the two design gaps in the project: the optional dashboard (FR-15), which had a requirement but no design, and figures F1–F8, which were specified in words in `09-EVALUATION-PROTOCOL.md` §6 but never drawn.

**Scope.** Two surfaces only:

| Surface | Status | Purpose |
|---|---|---|
| **Part A — Simulator dashboard** | Optional (FR-15, Could) | Demonstration and RL debugging |
| **Part B — Report figures F1–F8** | Required (Phase 6) | The evidence |

**Not in scope, and never will be.** The batcher itself has no interface. It is a headless server-side process (`01-PRD.md` non-goal N2). There is no website, no browser extension, no wallet screen and no order-entry form. Nothing in this document is part of the shipped system — Part A is a demo harness, Part B is print output.

---

# Part A · Simulator Dashboard

## A1. Purpose and constraints

**Purpose.** Make the decision loop watchable. The project's central mechanism — a batch in flight locks the pool, the queue grows behind it, latency compounds — is invisible in a metrics table and obvious in a live view. Secondary purpose: RL debugging, where a flat action distribution is spotted in seconds rather than in a post-hoc plot.

**Constraints**

| | |
|---|---|
| Runs | Locally, `localhost` only |
| Users | One, the operator |
| Auth | None — never exposed to a network |
| Data | Reads the simulator's D3 stream; no separate backend |
| Modes | Replay a completed episode, or drive a live simulation |
| Effort budget | ~1 day, at the end. First item in the scope-cut order (`12-ROADMAP.md`) |

**Explicit non-goal.** The dashboard never influences a result. It reads; it does not configure experiments. Anything reported comes from `scripts/evaluate.py`, never from this view.

## A2. Information architecture

```
Dashboard
├── Run view      ← the main screen; one episode, stepping
├── Compare view  ← policies side by side, after a run
└── Batch detail  ← modal: what went into one batch
```

Three views. No navigation chrome beyond a tab strip — the operator is one person who knows what they are looking at.

## A3. Run view — wireframe

The primary screen. Approximately 1280×800.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Adaptive Batcher   ·   Run 042   ·   policy P3   ·   seed 42                 │
│  slot 152,338,464    block 11,482,313    elapsed 00:14:20     [◀◀] [▶] [▶▶]  │
│                                                                    speed 4×  │
├──────────────────────────────────────────────────────────────────────────────┤
│  BLOCK CONGESTION                                    last 120 blocks   ⌄      │
│                                                                              │
│  100% ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
│   90% ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒ inclusion-risk band ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒  │
│   80% ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒  │
│       ▁▂▃▂▁▂▄▅▃▂▁▁▂▃▅▆▇▇▆▄▃▂▁▂▃▄▅▆▇█▇▆▅▄▃▂▂▃▄▅▆▆▅▄▃▂▁▂▃▄▄▃▂▂▃▃▄▅▆▅▄▃▂▁▂▃│  │
│    0% └──────────────────────────────────────────────────────────────────┴─  │
│         actual ──────      forecast ┄┄┄┄┄┄                          now ▲    │
│                                                                              │
│       ▲ submitted    ✕ expired                                               │
├─────────────────────────┬───────────────────────┬────────────────────────────┤
│  ORDER QUEUE            │  POOL                 │  DECISION                  │
│                         │                       │                            │
│  depth           21     │   ⏳ LOCKED           │   ⏸  WAIT                  │
│  oldest wait   38 s     │                       │                            │
│                         │   batch #14 · n = 12  │   pool is locked —         │
│  ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇  │   in flight 3 blocks  │   no decision available    │
│  oldest ↑      ↑ newest │   TTL in 87 s         │                            │
│                         │                       │   Gate A max n     28      │
│  deadline D_MAX 120 s   │   [ view batch #14 ]  │   Gate B max n     19      │
│  ████████░░░░░░░░  38/120│                      │   forecast fill  0.79      │
├─────────────────────────┴───────────────────────┴────────────────────────────┤
│  DECISION LOG                                                    ⤓ export    │
│  slot          depth  wait  f̂     action   n   incl  conf  note              │
│  152,338,496      21   38s  0.79  WAIT     –   –     –     pool locked       │
│  152,338,464      19   30s  0.84  WAIT     –   –     –     pool locked       │
│  152,338,442      11   22s  0.63  SUBMIT  12   ✓     3     batch #14         │
│  152,338,418       5   14s  0.41  WAIT     –   –     –     below N_MIN       │
│  152,338,397      14    6s  0.38  SUBMIT  14   ✓     2     batch #13         │
├──────────────────────────────────────────────────────────────────────────────┤
│  latency mean   latency p95   cost / user   settled   expired   lock occupancy│
│      41 s          118 s       0.071 ADA      312        2          34 %      │
└──────────────────────────────────────────────────────────────────────────────┘
```

## A4. Panel specifications

Every value traces to a D3 column (`05-DATA-SPEC.md`) or to simulator state. Nothing on screen is computed only for display.

### Header

| Element | Source | Notes |
|---|---|---|
| Run id, policy, seed | run manifest | Pins reproducibility — the operator can always say which run this is |
| Slot, block height | `abs_slot`, `block_height` | Tabular figures; these change every tick |
| Elapsed | `abs_slot - episode_start_slot` | **Real slot time, not tick count** (`adr/ADR-007`) |
| Transport | — | Step back, play/pause, step forward |
| Speed | — | 1× / 4× / 16× / max. 1× is real time — 20 s per block, too slow to watch |

### Congestion panel

The one chart on the screen. Form: line over time, because the job is change-over-time with a threshold that matters.

| Element | Encoding |
|---|---|
| Actual fill % | 2px solid line, sequential blue step 450 `#2a78d6` |
| Forecast `f̂` | 2px dashed line, same hue, step 250 `#86b6ef` |
| 80–90 % band | Recessive fill, gridline tone `#e1e0d9`; labelled *inclusion-risk band* |
| Submissions | ▲ marker on the axis, ≥8px, status good `#0ca30c` |
| Expiries | ✕ marker, status critical `#d03b3b` |
| Now | Right edge, muted vertical rule |

Two series → legend present, both direct-labelled at the right edge. The 80–90 % band is annotated in place, not left to the reader to infer — it is the entire reason the chart exists.

Window: last 120 blocks (~40 min), collapsible to 30.

### Queue panel

| Element | Source | Notes |
|---|---|---|
| Depth | `queue_depth` | |
| Oldest wait | `oldest_wait`, in seconds | |
| Age strip | per-order arrival slots | One tick per order, oldest left. Length is depth; **colour is not used** — position carries age |
| Deadline meter | `oldest_wait / D_MAX` | Fills as the deadline approaches; turns status-serious `#ec835a` above 80 % |

The deadline meter is the fairness guarantee made visible: when it fills, WAIT is masked and submission is forced.

### Pool panel

The most important panel, because the pool lock is the project's central mechanism.

| State | Indicator | Colour | Body |
|---|---|---|---|
| Free | ○ FREE | muted ink | "ready to batch" |
| Locked | ⏳ LOCKED | status warning `#fab219` | batch id, n, blocks in flight, TTL countdown |
| Expiring | ⚠ TTL SOON | status serious `#ec835a` | under 3 blocks of TTL remaining |
| Expired | ✕ EXPIRED | status critical `#d03b3b` | orders returned to queue |

Every state ships an **icon and a label**; the colour is redundant, never the carrier. `[view batch]` opens the batch-detail modal.

**Blocks in flight is the number to watch during a demo.** When it climbs while queue depth climbs beside it, the audience is looking directly at head-of-line blocking (`adr/ADR-004`).

### Decision panel

| Element | Source |
|---|---|
| Action | `action` — WAIT / SUBMIT(n), icon + word |
| Reason | Derived: pool locked · below N_MIN · predicted no room · deadline forced · normal submit |
| Gate A max n | `gate_a_max_n` — the feasibility ceiling, congestion-independent |
| Gate B max n | Derived from `f̂` — the inclusion ceiling, congestion-dependent |
| Forecast fill | `fill_hat` |

Showing **both gates separately, always** is deliberate. It makes `adr/ADR-002` visible on screen: Gate A does not move when the chain empties, Gate B does. A reviewer watching the demo sees the distinction rather than being told it.

### Decision log

Streaming table, newest first, ~5 rows visible, scrollable, full episode exportable to CSV. Columns map 1:1 to D3. Tabular figures so columns align.

### Metric tiles

Six stat tiles — no plots, just numbers with labels. Values update live; they are the running episode aggregate, not the final result.

`latency mean · latency p95 · cost/user · settled · expired · lock occupancy`

**Lock occupancy** is the diagnostic tile: the share of slots spent locked. High occupancy with a small mean batch size is the signature of a badly timed policy.

## A5. States

Six states. Each changes the Pool and Decision panels; the rest of the screen is unaffected.

```
IDLE          pool ○ FREE      decision: awaiting next block
DECIDING      pool ○ FREE      decision: WAIT or SUBMIT(n) + reason
LOCKED        pool ⏳ LOCKED   decision: "no decision available"          ← the mechanism
FORCED        pool ○ FREE      decision: SUBMIT(n) · deadline reached     ← fairness guarantee
EXPIRED       pool ✕ EXPIRED   decision: orders returned to queue
EPISODE END   transport stops  final metrics; [compare] enabled
```

**LOCKED** and **FORCED** are the two states worth designing carefully — they are the two mechanisms that distinguish this system from a static batcher, and they are what a viva panel should leave having seen.

The FORCED state variant:

```
├─────────────────────────┬───────────────────────┬────────────────────────────┤
│  ORDER QUEUE            │  POOL                 │  DECISION                  │
│  depth           26     │   ○ FREE              │   ⏵  SUBMIT  n = 26        │
│  oldest wait  121 s     │                       │                            │
│  ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇  │   ready to batch      │   ⚠ deadline reached —     │
│  deadline D_MAX 120 s   │                       │     WAIT is masked         │
│  ████████████████ 121/120│                      │   Gate A max n     28      │
└─────────────────────────┴───────────────────────┴────────────────────────────┘
```

## A6. Compare view — wireframe

Shown after a run, or loaded from saved episodes. This is where F5 and F6 appear interactively before they are exported for the report.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Compare   ·   100 paired episodes   ·   arrival rate: [light|matched|heavy]  │
├──────────────────────────────────────────────────────────────────────────────┤
│  policy      lat mean   lat p95   cost/user   expired   settled   fairness    │
│  ─────────────────────────────────────────────────────────────────────────   │
│  E1 (M=12)      68 s     201 s    0.074 ADA     1.2 %     4,981     0.81      │
│  E2 (T=60s)     74 s     224 s    0.081 ADA     1.8 %     4,902     0.79      │
│  E3 greedy      39 s      96 s    0.118 ADA     0.4 %     5,033     0.93      │
│  P2             44 s     121 s    0.073 ADA     0.6 %     5,024     0.89      │
│  P3             41 s     112 s    0.072 ADA     0.5 %     5,029     0.90      │
│  ORACLE         38 s     104 s    0.071 ADA     0.4 %     5,031     0.91      │
├──────────────────────────────────────────────┬───────────────────────────────┤
│  PARETO — tail latency vs per-user cost      │  LATENCY CDF                  │
│                                              │                               │
│  cost                                        │  1.0 ┤        ╭─────────      │
│  0.12 ┤        ●E3                           │      │      ╭─╯               │
│       │                                      │  0.5 ┤    ╭─╯                 │
│  0.08 ┤              ●E2                     │      │  ╭─╯                   │
│       │          ●E1                         │  0.0 ┼──╯                     │
│  0.07 ┤  ◆ORACLE ◆P3 ◆P2                     │      0    100   200    300 s  │
│       └──────────────────────────────         │                               │
│         100      150      200   p95 s        │   P3 ── P2 ── E3 ── ORACLE ┄  │
│                                              │                               │
│         ← better                             │                               │
└──────────────────────────────────────────────┴───────────────────────────────┘
```

*Numbers above are illustrative placeholders showing the expected shape, not results.*

## A7. Interaction

| Control | Behaviour |
|---|---|
| Play / pause | Space |
| Step forward / back | ← → · one block |
| Speed | 1× / 4× / 16× / max |
| Scrub | Click the congestion chart to jump to that slot |
| Hover | Crosshair + tooltip on the congestion chart: slot, actual, forecast, action taken |
| Row click | Decision-log row → jumps the run to that slot |
| Batch detail | Opens a modal: order ids, sizes, execution units, Gate A headroom, realised fee |
| Export | Decision log to CSV; charts to PNG |

Hover is not optional — an on-screen chart that does not respond to a pointer reads as an image. Filters (arrival rate, policy) sit in one row above the charts in the compare view.

## A8. Visual language

**Status colours.** Reserved, fixed, never reused as series colours, and always paired with an icon and a word.

| State | Role | Light | Dark |
|---|---|---|---|
| SUBMIT / included | good | `#0ca30c` | `#0ca30c` |
| Pool locked | warning | `#fab219` | `#fab219` |
| TTL soon / deadline near | serious | `#ec835a` | `#ec835a` |
| Expired / Gate A violation | critical | `#d03b3b` | `#d03b3b` |
| WAIT | *none* | muted ink `#898781` | `#898781` |

**WAIT carries no colour.** It is the common case; colouring it would drown the states that matter. This is the single most important rule on this screen.

**Surfaces and ink**

| Role | Light | Dark |
|---|---|---|
| Chart surface | `#fcfcfb` | `#1a1a19` |
| Page plane | `#f9f9f7` | `#0d0d0d` |
| Primary ink | `#0b0b0b` | `#ffffff` |
| Secondary ink | `#52514e` | `#c3c2b7` |
| Muted / axis | `#898781` | `#898781` |
| Gridline | `#e1e0d9` | `#2c2c2a` |

**Type.** System sans throughout. `tabular-nums` on slots, heights, log columns and comparison tables — anything that must align vertically. Proportional figures on the stat tiles.

**Dark mode** is a selected palette, not an inverted one: the dark steps in §B1 were chosen for the dark surface and validated against it.

---

# Part B · Figure Specifications F1–F8

These are the report's evidence. Each figure is specified before data exists, so that its shape is decided by what the question needs rather than by what the numbers happen to allow.

## B1. Shared conventions

### Series assignment — fixed, never cycled

Colour follows the entity. A policy has the same colour in every figure it appears in.

| Series | Slot | Light | Dark |
|---|---|---|---|
| **P3** — RL agent | 1 blue | `#2a78d6` | `#3987e5` |
| **P2** — optimizer | 2 orange | `#eb6834` | `#d95926` |
| **Best static baseline** | 3 aqua | `#1baf7a` | `#199e70` |
| **ORACLE** — reference | neutral | `#898781`, dashed | `#898781`, dashed |

**Validated.** `node scripts/validate_palette.js "#2a78d6,#eb6834,#1baf7a" --pairs all`, both modes: all checks pass. Worst all-pairs CVD ΔE 9.2 light / 9.4 dark (target ≥8); worst normal-vision ΔE 24.0 light / 20.9 dark (floor ≥15). Light-mode aqua sits at 2.74:1 against the light surface, below 3:1 — **the relief rule applies: every series carries a visible direct label, and a table view accompanies every figure.** That obligation is discharged by the per-figure specs below, not optional.

**Series cap: at most four plotted series, plus ORACLE as a neutral reference.** The full seven-policy detail lives in the results *table*, never in a chart. E1, E2 and E3 are represented in figures by whichever performs best; the individual three appear in the table and, where the comparison matters, as small multiples. This is the "fold or facet" rule, and it is also better editorial judgement — the argument is *adaptive versus static*, not a seven-way race.

### Marks and chrome

Thin marks. 2px lines. Markers ≥8px. 2px surface gap between adjacent fills, 2px surface ring where marks overlap. Recessive gridlines and axes in `#e1e0d9` / `#c3c2b7`. Selective direct labels — never a number on every point.

### Legend, labels, accessibility

Two or more series → legend always present, and with ≤4 series they are also direct-labelled, so identity is never colour-alone. A single-series figure gets no legend; the title names it. Every figure ships a table view. Texture fill (45° / 135° lines) is available for print and forced-colours.

### One axis

No figure uses two y-scales. Where two measures of different scale must be compared, the answer is two charts, small multiples, or indexing to a common base.

---

## F1 · Congestion over time

| | |
|---|---|
| **Question** | Is the congestion problem real? |
| **Form** | Line, change-over-time |
| **x** | Block time, 90 days; a 48-hour inset for detail |
| **y** | Block fill %, 0–100 |
| **Marks** | 2px line, sequential blue `#2a78d6`; 80–90 % band as a recessive fill, annotated *inclusion-risk band* |
| **Annotation** | Label the band in place. Mark one peak episode with its date |
| **Expected shape** | Diurnal oscillation with excursions into and above the band |
| **The sentence it earns** | "Cardano blocks reach 80–90 % capacity during peak periods — here is when, and how often." |
| **Failure signature** | Fill never approaches the band → the premise is weaker than assumed and the report must say so |

Single series → no legend. This is the first figure in the results chapter, because everything after it assumes the problem exists.

## F2 · Distribution of block fill

| | |
|---|---|
| **Question** | How often does congestion actually bind? |
| **Form** | Histogram |
| **x** | Fill %, 2-point bins |
| **y** | Block count |
| **Marks** | Bars, blue `#2a78d6`, 4px rounded top anchored to the baseline, 2px gap between bars; bars above 80 % in the same hue at full chroma, below in step 250 |
| **Annotation** | Direct-label the share of blocks above 80 % and above 90 % |
| **Expected shape** | Right-skewed, long thin tail into the band |
| **The sentence it earns** | "X % of blocks sit in the range where a 30-order batch cannot fit." |
| **Failure signature** | Negligible mass above 80 % → the addressable opportunity is small; report the number honestly |

F1 shows *when*; F2 shows *how much*. Together they size the problem. F2 is the figure that quantifies the project's headroom, so its number goes in the abstract.

## F3 · Amortization curve

| | |
|---|---|
| **Question** | Why not simply always batch the maximum? |
| **Form** | Line, single series |
| **x** | Batch size n, 1 → n_max |
| **y** | Per-user cost, ADA |
| **Marks** | 2px line, blue; markers at n = 1, 5, 10, 20, 30 |
| **Annotation** | Direct-label the knee near n ≈ 10; a muted rule at the marginal-cost asymptote; shade n > n_max as *infeasible (Gate A)* |
| **Expected shape** | Hyperbola `FLAT/n + MARGINAL`, flattening near n ≈ 10 |
| **The sentence it earns** | "Only the flat fee component amortizes, so the cost incentive to hoard orders vanishes past roughly ten orders — which is why latency dominates the objective." |
| **Failure signature** | A curve still falling steeply at n_max → the marginal cost estimate is wrong; recheck the estimator |

Derived analytically from `07-CONSTRAINTS-COST-MODEL.md` §5 and confirmed against measured D4 fees. This figure carries a finding that is genuinely the project's own, and it pre-empts the most obvious examiner question.

## F4 · Forecast against actual

| | |
|---|---|
| **Question** | Is the forecaster any good? |
| **Form** | Line, two series, over a representative test window |
| **x** | Slot, ~500 blocks |
| **y** | Fill % |
| **Marks** | Actual: 2px solid blue. Forecast: 2px dashed, same hue, step 250. Both direct-labelled at the right edge |
| **Annotation** | Shade the 80–90 % band; mark two or three instances where the forecast correctly anticipated a rise |
| **Expected shape** | Forecast tracking actual with a short lag and damped peaks |
| **The sentence it earns** | "The forecaster anticipates congestion rather than merely reporting it." |
| **Failure signature** | Forecast is a smoothed lag of actual with no anticipation → it has learned persistence, and the honest report is that congestion is close to a random walk at this horizon (risk R4) |

Same-hue solid-versus-dashed rather than two hues: these are the same quantity, predicted and observed, not two entities.

## F5 · Pareto — tail latency against per-user cost · **headline figure**

| | |
|---|---|
| **Question** | Does the adaptive policy dominate static batching? |
| **Form** | Scatter — all-pairs colour rules apply |
| **x** | L-p95, seconds |
| **y** | C-user, ADA |
| **Marks** | ≥8px markers. P3 blue ◆, P2 orange ◆, best static aqua ●, ORACLE neutral ◇ dashed outline. 2px surface ring where markers overlap |
| **Labels** | **Every point directly labelled** — discharges the light-mode contrast relief rule |
| **Annotation** | "← better" on both axes. Dominated region behind each proposed point lightly shaded. Error bars = 95 % bootstrap CI on both axes |
| **Expected shape** | P2 and P3 down-left of the static cluster; ORACLE just beyond them |
| **The sentence it earns** | "The adaptive policy is better on both objectives at once — it is not a trade." |
| **Failure signature** | Proposed points sit *along* the static frontier rather than inside it → no dominance; the result is a trade-off and must be reported as one (success metric S5 fails while S3 may still hold) |

Small point count, so shape plus direct labels carry identity and colour is reinforcement. The ORACLE point is the ceiling: the distance from P2 to ORACLE is the cost of forecast error, stated visually.

## F6 · Latency distribution

| | |
|---|---|
| **Question** | Where in the distribution does the gain live? |
| **Form** | CDF, up to four series |
| **x** | Confirmation latency, seconds |
| **y** | Cumulative share of orders, 0–1 |
| **Marks** | 2px lines in the fixed series colours; ORACLE dashed neutral. Direct-labelled at the right edge; legend present |
| **Annotation** | Horizontal rule at 0.95 with each curve's crossing marked — this is the p95 comparison made visible |
| **Expected shape** | Proposed curves left of the static curves, with the gap widening in the upper tail |
| **The sentence it earns** | "The improvement is concentrated in the tail — the orders that suffer most under a static rule." |
| **Failure signature** | Curves separate at the median but converge in the tail → the mean improved while the tail did not, which is the weaker claim and must be stated |

A CDF, not a histogram: the question is about quantiles, and overlapping histograms of heavy-tailed data are unreadable.

## F7 · Does the agent adapt?

| | |
|---|---|
| **Question** | Has P3 learned congestion adaptation, or just a queue-length rule? |
| **Form** | Stacked bars, one per congestion decile |
| **x** | Predicted congestion decile, 0–10 % → 90–100 % |
| **y** | Share of decisions, 0–1 |
| **Marks** | Two segments per bar — SUBMIT (status good `#0ca30c`) and WAIT (muted `#898781`) — 2px surface gap between segments. Icon + label in the legend, so state is never colour-alone |
| **Annotation** | Overlay mean batch size per decile as direct-labelled numerals above each bar — **not** a second y-axis |
| **Expected shape** | SUBMIT share falling monotonically as predicted congestion rises; mean n falling with it |
| **The sentence it earns** | "The agent submits into quiet blocks and holds back when congestion is forecast — the behaviour a static rule cannot express." |
| **Failure signature** | **A flat profile across deciles means the agent ignores the forecast**, regardless of how good F5 looks. Cross-check with ablation A3; if A3 shows no degradation, the claim weakens from congestion-aware to queue-aware and the report must say so |

This is the figure that distinguishes a learned policy from a lucky one. Mean batch size is annotated as text rather than plotted on a second scale — the one-axis rule is not negotiable, and with ten values direct labels read better than a line anyway.

## F8 · Robustness across arrival rates

| | |
|---|---|
| **Question** | Does the policy generalise, or was it tuned to one load? |
| **Form** | Small multiples — three panels, shared y-axis |
| **Panels** | light 0.5× · matched 1.0× · heavy 2.0× |
| **x** | Policy |
| **y** | L-p95, seconds — one shared scale across all three panels |
| **Marks** | Bars in the fixed series colours, 4px rounded tops on the baseline, 2px gaps; error bars = 95 % CI |
| **Annotation** | Panel titles carry the rate; direct-label each bar's value |
| **Expected shape** | Proposed policies below static in all three panels |
| **The sentence it earns** | "The advantage holds across loads; it is not an artefact of the tuning point." |
| **Failure signature** | Proposed wins only at the matched rate → overfitting to arrival rate. A real and reportable negative result |

Shared y-scale is essential. Per-panel scales would let a policy look consistent while its absolute latency tripled.

---

## B2. Production rules

| Rule | Why |
|---|---|
| Every figure is generated by `scripts/make_figures.py` | Never hand-edited; regenerable from a manifest (`13-RUNBOOK.md` §9) |
| Every figure ships a table view | Discharges the light-mode contrast relief rule; also required for the appendix |
| Every figure caption states n, the seed and the split | A figure without provenance is not evidence |
| Confidence intervals on every comparative figure | `09-EVALUATION-PROTOCOL.md` §5 |
| Dark variants exported for the slide deck | Selected steps from §B1, not an inversion |
| Render and inspect before accepting | The palette validator checks colour, not label collisions or overflow |

## B3. Build order

| Priority | Item | When |
|---|---|---|
| 1 | F1, F2 | Phase 1 — needed for Review 1 |
| 2 | F3 | Phase 1 — analytic, no results required |
| 3 | F4 | Phase 3 |
| 4 | F5, F6 | Phase 6 — the headline |
| 5 | F7, F8 | Phase 6 |
| 6 | Dashboard run view | After Phase 5, only if time allows |
| 7 | Dashboard compare view | Optional; the table plus F5 already carry it |

F3 is worth building early despite being a Phase 6 figure: it is derived analytically from the cost model and needs no experimental results, and it sharpens the objective before any policy is written.
