// Builds docs/report/Team11_Project_Report_Draft.docx from the specs and recorded results.
// Usage: npm install docx  (once, anywhere on the module path), then: node docs/report/build_report.js
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell,
  WidthType, ShadingType, BorderStyle, ImageRun, PageBreak, TableOfContents, Footer, PageNumber,
  LevelFormat, TabStopType, PageOrientation,
} = require("docx");

const REPO = path.resolve(__dirname, "../..");
const DIAG = path.join(__dirname, "diagrams");
const D = (i) => path.join(DIAG, fs.readdirSync(DIAG).find((f) => f.startsWith(`${i}-`)));
const FIG = path.join(REPO, "figures");
const OUT = path.join(REPO, "docs/report/Team11_Project_Report_Draft.docx");

const FONT = "Times New Roman";
const MONO = "Consolas";
const CONTENT_W = 9026; // A4 width minus 1" margins, DXA
const ACCENT = "1F4E79";

// ---------- inline markup: **bold**, `code`, [[EDIT: ...]] highlighted ----------
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|\[\[[^\]]+\]\])/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), font: FONT, ...base }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, font: FONT, ...base }));
    else if (t.startsWith("*")) out.push(new TextRun({ text: t.slice(1, -1), italics: true, font: FONT, ...base }));
    else if (t.startsWith("`")) out.push(new TextRun({ text: t.slice(1, -1), font: MONO, size: 20, ...base }));
    else out.push(new TextRun({ text: t.slice(2, -2), highlight: "yellow", font: FONT, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), font: FONT, ...base }));
  return out;
}

const P = (text, opts = {}) =>
  new Paragraph({ children: runs(text), alignment: AlignmentType.JUSTIFIED, spacing: { after: 120, line: 336 }, ...opts });
const H1 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun(text)] });
const H2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(text)] });
const H3 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(text)] });
const B = (text) => new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: runs(text), spacing: { after: 60, line: 312 } });
const N = (text, ref = "numbers") => new Paragraph({ numbering: { reference: ref, level: 0 }, children: runs(text), spacing: { after: 60, line: 312 } });
const Center = (text, o = {}) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: runs(text, o) });
const Blank = () => new Paragraph({ children: [] });

function Callout(title, lines) {
  const border = { style: BorderStyle.SINGLE, size: 12, color: ACCENT, space: 6 };
  const mk = (children, first, lastOne) =>
    new Paragraph({
      children,
      shading: { type: ShadingType.CLEAR, fill: "EAF1F8", color: "auto" },
      border: { left: border, ...(first ? { top: { ...border, size: 4 } } : {}), ...(lastOne ? { bottom: { ...border, size: 4 } } : {}) },
      spacing: { after: 0, line: 312 },
      indent: { left: 200, right: 200 },
      alignment: AlignmentType.JUSTIFIED,
    });
  const out = [mk([new TextRun({ text: title, bold: true, font: FONT, color: ACCENT })], true, false)];
  lines.forEach((l, i) => out.push(mk(runs(l), false, i === lines.length - 1)));
  out.push(new Paragraph({ children: [], spacing: { after: 120 } }));
  return out;
}

function Code(lines) {
  return lines.map((l, i) =>
    new Paragraph({
      children: [new TextRun({ text: l.length ? l : " ", font: MONO, size: 16 })],
      shading: { type: ShadingType.CLEAR, fill: "F4F4F4", color: "auto" },
      spacing: { after: i === lines.length - 1 ? 160 : 0, line: 240 },
      indent: { left: 200 },
    }));
}

let tableNo = 0, figNo = 0;
const chapterOf = () => currentChapter;
let currentChapter = 0;
function Caption(kind, text, keepNext = false) {
  const no = kind === "Table" ? ++tableNo : ++figNo;
  return new Paragraph({
    keepNext,
    alignment: AlignmentType.CENTER,
    spacing: { before: 60, after: 200 },
    children: [new TextRun({ text: chapterOf() ? `${kind} ${chapterOf()}.${no}: ` : `${kind} ${no}: `, bold: true, font: FONT, size: 22 }), new TextRun({ text, italics: true, font: FONT, size: 22 })],
  });
}

function Tbl(caption, headers, rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  const scale = CONTENT_W / total;
  const w = widths.map((x) => Math.floor(x * scale));
  w[w.length - 1] += CONTENT_W - w.reduce((a, b) => a + b, 0);
  const border = { style: BorderStyle.SINGLE, size: 4, color: "808080" };
  const borders = { top: border, bottom: border, left: border, right: border };
  const cell = (text, i, head) =>
    new TableCell({
      width: { size: w[i], type: WidthType.DXA },
      borders,
      shading: head ? { type: ShadingType.CLEAR, fill: "D9E2F3", color: "auto" } : undefined,
      margins: { top: 40, bottom: 40, left: 80, right: 80 },
      children: [new Paragraph({ children: runs(String(text), { size: 20, ...(head ? { bold: true } : {}) }), spacing: { after: 0 } })],
    });
  const table = new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: w,
    rows: [
      new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, i, true)) }),
      ...rows.map((r) => new TableRow({ children: r.map((c, i) => cell(c, i, false)) })),
    ],
  });
  // A table caption must never be stranded at the foot of a page.
  return [Caption("Table", caption, true), table, new Paragraph({ children: [], spacing: { after: 160 } })];
}

function pngSize(file) {
  const b = fs.readFileSync(file);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
}
function Fig(file, caption, maxW = 600, maxH = 720, landscape = false) {
  const { w, h } = pngSize(file);
  let width = maxW, height = Math.round((h / w) * maxW);
  if (height > maxH) { height = maxH; width = Math.round((w / h) * maxH); }
  if (landscape) return [{ __landscape: Fig(file, caption, maxW, maxH, false) }];
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER, spacing: { before: 120 }, keepNext: true,
      children: [new ImageRun({ type: "png", data: fs.readFileSync(file), transformation: { width, height }, altText: { title: caption, description: caption, name: path.basename(file) } })],
    }),
    Caption("Figure", caption),
  ];
}
const Chapter = (no, title) => { currentChapter = no; tableNo = 0; figNo = 0; return H1(`Chapter ${no}: ${title}`); };

// =====================================================================================
const content = [];
const add = (...xs) => xs.flat().forEach((x) => content.push(x));

// ---------------- Title page ----------------
add(
  Blank(), Blank(),
  Center("A Major Project Report on", { size: 28 }),
  Center("**AI-DRIVEN ADAPTIVE TRANSACTION BATCHING FOR CARDANO DECENTRALIZED EXCHANGES**", { size: 36, color: ACCENT }),
  Blank(),
  Center("Submitted in partial fulfilment of the requirements for the award of the degree of", { size: 24 }),
  Center("**BACHELOR OF TECHNOLOGY**", { size: 28 }),
  Center("in", { size: 24 }),
  Center("**COMPUTER SCIENCE AND ENGINEERING (DATA SCIENCE)**", { size: 26 }),
  Blank(),
  Center("Submitted by", { size: 24 }),
  Center("[[Vikranth Sai (23P61A67F1)]]", { size: 24 }),
  Center("[[Ganesh (23P61A67F0)]]", { size: 24 }),
  Center("[[Sowmya (23P61A67H8)]]", { size: 24 }),
  Center("[[EDIT: confirm team member names and roll numbers]]", { size: 20 }),
  Blank(),
  Center("Under the guidance of", { size: 24 }),
  Center("**Ms. B. Mamatha**", { size: 26 }),
  Center("[[EDIT: guide designation]]", { size: 22 }),
  Blank(), Blank(),
  Center("**Department of Computer Science and Engineering (Data Science)**", { size: 24 }),
  Center("**VIGNANA BHARATHI INSTITUTE OF TECHNOLOGY**", { size: 26 }),
  Center("[[EDIT: affiliation, accreditation line, address]]", { size: 22 }),
  Center("Academic Year 2026–27", { size: 24 }),
);

// ---------------- Certificate / Declaration / Acknowledgement ----------------
add(
  H1("Certificate"),
  P("This is to certify that the project report entitled **“AI-Driven Adaptive Transaction Batching for Cardano Decentralized Exchanges”** is a bonafide record of work carried out by [[team member names and roll numbers]] in partial fulfilment of the requirements for the award of the degree of Bachelor of Technology in Computer Science and Engineering (Data Science) at Vignana Bharathi Institute of Technology during the academic year 2026–27."),
  Blank(), Blank(),
  new Paragraph({ tabStops: [{ type: TabStopType.RIGHT, position: CONTENT_W }], children: [new TextRun({ text: "Project Guide", bold: true, font: FONT }), new TextRun({ text: "\tHead of the Department", bold: true, font: FONT })] }),
  new Paragraph({ tabStops: [{ type: TabStopType.RIGHT, position: CONTENT_W }], children: [new TextRun({ text: "Ms. B. Mamatha", font: FONT }), new TextRun({ text: "\tEDIT: HoD name", font: FONT, highlight: "yellow" })] }),
  Blank(), Blank(),
  new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "External Examiner", bold: true, font: FONT })] }),

  H1("Declaration"),
  P("We hereby declare that the project report entitled **“AI-Driven Adaptive Transaction Batching for Cardano Decentralized Exchanges”** submitted to Vignana Bharathi Institute of Technology is a record of original work done by us under the guidance of Ms. B. Mamatha. The results embodied in this report have not been submitted to any other university or institute for the award of any degree or diploma."),
  P("Every quantitative result in this report is produced by a script in the project repository from a checksummed dataset, and can be regenerated from the run manifest recorded alongside it."),
  Blank(),
  P("[[EDIT: names, roll numbers and signatures]]"),

  H1("Acknowledgement"),
  P("We express our sincere gratitude to our guide, **Ms. B. Mamatha**, for her guidance, patience and critical feedback throughout this project. We thank the Head of the Department and the project review committee of the Department of Computer Science and Engineering (Data Science) for their evaluation and suggestions at each review."),
  P("We also thank the maintainers of the Koios community API, whose free and open access to Cardano chain data made the 92-day block dataset at the centre of this work possible, and the developers of the open-source libraries on which the implementation is built."),
  P("[[EDIT: personalise as required]]"),
);

// ---------------- Abstract ----------------
add(
  H1("Abstract"),
  P("Decentralized exchanges on Cardano store each liquidity pool as a single unspent transaction output (UTXO), which can be consumed by only one transaction per block. Exchanges therefore rely on off-chain **batchers** that collect many user orders and settle them together in one transaction. Batchers deployed today trigger on constants — a fixed batch size, a fixed interval, or greedily — and never read the chain before deciding."),
  P("This project designs, implements and evaluates an adaptive batcher that decides, at every block, whether to wait or to submit a batch of *n* orders. Because Cardano fees are deterministic and do not rise with demand, the objective is **confirmation latency and amortized per-user cost**, not fees. Batch size is bounded by per-transaction limits (Gate A), while block capacity governs only inclusion (Gate B). A submitted batch holds the pool UTXO until it confirms, so every order behind it waits: head-of-line blocking is the real cost of a poor decision."),
  P("A dataset of **388,781 mainnet blocks over 92 days** was collected from the Koios API. It overturned the project’s original premise: median block fill is 2.95 %, only 0.564 % of blocks exceed 80 %, and the longest congested run is ten blocks. The work was therefore reframed around concurrency rather than congestion. A deterministic, slot-accurate simulator replays the recorded blocks against a synthetic order stream fitted to the chain’s diurnal activity. Against it we evaluate three tuned static baselines, a LightGBM congestion forecaster, a constrained optimizer (P2) and a Deep Q-Network agent (P3) with structural action masking, using paired episodes, Wilcoxon signed-rank tests, bootstrap confidence intervals and Holm–Bonferroni correction."),
  P("The forecaster beats a moving-average baseline by 11.2 % in MAE but lags the series it predicts. Every policy, including the learned agent, produced **zero** capacity violations. An ablation shows the DQN agent is queue-aware rather than congestion-aware."),
  P("On the held-out test split — 100 paired episodes at three arrival rates, evaluated once — **no adaptive policy beats greedy batching on tail latency**: where capacity rarely binds, greedy is latency-optimal. The result is therefore a trade-off frontier rather than dominance. At the matched rate the optimizer with a minimum batch of four cuts per-user cost by 19 % for 5 % more tail latency and Pareto-dominates the tuned fixed-interval baseline by median; the DQN agent cuts cost by 43 % with the best fairness of any proposed policy, but one of its five seeds breaks down under heavy load."),
  P("The project also delivers a minimal on-chain DEX for the Cardano preprod test network: Aiken validators that enforce each user’s slippage floor and a **pass-through batcher fee**, so the amortization the policies optimise reaches users rather than the operator, together with a live batcher that runs the simulator’s decision loop against the chain. The DEX is deployed on preprod, where the live batcher has settled its first end-to-end swap."),
  P("**Keywords:** Cardano, eUTXO, decentralized exchange, transaction batching, reinforcement learning, DQN, LightGBM, discrete-event simulation, Aiken, Plutus."),
);

// ---------------- TOC & abbreviations ----------------
add(
  H1("Table of Contents"),
  new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }),
  P("[[Right-click the table above and choose Update Field if page numbers are missing.]]"),

  H1("List of Abbreviations"),
  ...Tbl("Abbreviations used in this report", ["Abbreviation", "Meaning"], [
    ["ADA", "The native currency of Cardano (1 ADA = 1,000,000 lovelace)"],
    ["ADR", "Architecture Decision Record"],
    ["AMM", "Automated Market Maker"],
    ["CDF", "Cumulative Distribution Function"],
    ["CI", "Confidence Interval"],
    ["CIP-30", "Cardano wallet–web connector standard"],
    ["C-user", "Mean per-user cost, in lovelace"],
    ["DEX", "Decentralized Exchange"],
    ["DFD", "Data Flow Diagram"],
    ["DQN", "Deep Q-Network"],
    ["eUTXO", "Extended Unspent Transaction Output"],
    ["ExUnits", "Plutus execution units (memory and CPU steps)"],
    ["F-jain", "Jain’s fairness index over waiting times"],
    ["L-mean / L-p95", "Mean / 95th-percentile confirmation latency, in slots"],
    ["MAE / RMSE", "Mean Absolute Error / Root Mean Square Error"],
    ["MDP", "Markov Decision Process"],
    ["MEV", "Maximal Extractable Value"],
    ["NFT", "Non-Fungible Token (here, the token that identifies the pool)"],
    ["Plutus V3", "The Cardano smart-contract execution language targeted by Aiken"],
    ["PPO", "Proximal Policy Optimization"],
    ["RL", "Reinforcement Learning"],
    ["TTL", "Time To Live (transaction validity bound)"],
    ["UTXO", "Unspent Transaction Output"],
    ["X-rate", "Order expiry rate"],
  ], [2200, 6800]),
);

// =====================================================================================
// Chapter 1
add(
  Chapter(1, "Introduction"),
  H2("1.1 Domain: Cardano and the eUTXO Model"),
  P("Cardano is a proof-of-stake blockchain whose ledger follows the **extended UTXO (eUTXO)** model [1]. Value lives in discrete outputs; each output can be spent exactly once, and may carry a *datum* (arbitrary data) and be guarded by a *validator* script. Validation is local and deterministic, so the success and cost of a transaction are known before it is submitted."),
  P("Cardano’s Ouroboros consensus [3] divides time into one-second **slots**. Each slot produces a block with probability *f* = 0.05, so blocks arrive every 20 seconds on average, with geometrically distributed gaps. Blocks and transactions are each bounded in serialized size and in script execution units (memory and CPU steps)."),
  H2("1.2 Why Batching Exists — the Concurrency Constraint"),
  P("A decentralized exchange (DEX) keeps each liquidity pool as **a single UTXO**. Because that UTXO can be consumed once per block, a hundred users swapping against the same pool at the same moment cannot all succeed: only one transaction can spend the pool, and the rest conflict."),
  P("The ecosystem’s answer is **batching**. A user does not swap directly. They place an *order* — funds locked at the DEX script address with a datum stating the swap terms, a minimum acceptable output and a return address. An off-chain **batcher** scans the chain, collects pending orders and settles many of them in a single transaction against the pool. Batching exists to solve concurrency; cost amortization is a secondary benefit."),
  H2("1.3 Problem Statement"),
  P("Batchers deployed today decide using constants: submit when the queue reaches *M* orders, submit every *T* seconds, or submit whatever is queued immediately. None reads the chain before deciding. The decision matters because a submitted batch **holds the pool UTXO until it confirms**: while it is in flight no second batch can be built, and every order that arrives meanwhile waits behind it."),
  P("The problem addressed by this project is therefore: **at each block, decide whether to WAIT or to SUBMIT a batch of n orders, so as to minimise confirmation latency and per-user cost, without ever constructing a transaction that violates Cardano’s capacity limits and without allowing any order to starve.**"),
  H2("1.4 The Latency-Not-Fees Insight"),
  ...Callout("The intellectual pivot of this project", [
    "Cardano transaction fees are **deterministic**: `fee = 44·size + 155,381 + 0.0577·mem + 0.0000721·steps` lovelace. There is no gas auction and no priority bidding; an identical transaction costs the same on an idle chain and on a busy one.",
    "**Waiting on Cardano therefore does not cost money — it costs time.** A batch that does not confirm promptly keeps every user inside it waiting and, because it holds the pool UTXO, every order behind it too.",
    "The objective is consequently **confirmation latency and amortized per-user cost**, not fee reduction. Any framing that promises “lower gas fees during congestion” is technically wrong on Cardano. The contrast with Ethereum’s demand-responsive EIP-1559 base fee [10] is what justifies this objective.",
  ]),
  P("This argument does not require blocks to be full, and — as Chapter 8 shows — on the current mainnet they almost never are. The waiting that matters is caused by the pool lock, not by block capacity."),
  H2("1.5 Objectives"),
  ...Tbl("Project goals", ["ID", "Goal"], [
    ["G1", "Reduce mean and 95th-percentile confirmation latency for user orders versus static batchers"],
    ["G2", "Reduce average per-user cost by amortizing the flat fee component across larger batches"],
    ["G3", "Never construct a transaction that violates Cardano capacity limits"],
    ["G4", "Guarantee that no order starves, regardless of congestion"],
    ["G5", "Produce a reproducible, publishable evaluation against static baselines"],
    ["G6", "Require no change to wallets, to CIP-30, or to the Cardano protocol"],
  ], [900, 8100]),
  H2("1.6 Scope and Limitations"),
  P("The following are explicitly **out of scope**:"),
  B("Reducing Cardano fees during congestion — fees are demand-independent, so the premise does not exist."),
  B("A wallet, browser extension or consumer web application — a wallet sees only its owner’s funds and has nothing to aggregate."),
  B("Integration with Minswap or another deployed DEX — their validators require whitelisted, licensed batchers."),
  B("Multi-pool routing, order-book matching and cross-DEX arbitrage."),
  B("Mainnet deployment — all live work targets the preprod test network, enforced by a configuration guard."),
  B("Security audit, MEV protection and batcher decentralisation."),
  P("Every reported result is produced in a simulator that replays real mainnet blocks. Its assumptions are stated in Section 5.9 and their effect on validity is discussed in Section 8.13."),
  H2("1.7 Organisation of the Report"),
  P("Chapter 2 surveys the literature and identifies the research gap. Chapter 3 analyses the existing and proposed systems and their feasibility. Chapter 4 lists hardware, software and protocol requirements. Chapter 5 presents the system design, including the two capacity gates, the cost model, the pool-lock failure model and the learning formulations. Chapter 6 describes the implementation, Chapter 7 the testing and simulator validation, and Chapter 8 the results. Chapter 9 concludes and outlines future work."),
);

// Chapter 2
add(
  Chapter(2, "Literature Survey"),
  H2("2.1 eUTXO Foundations"),
  P("Chakravarty et al. [1] formally define the extended UTXO model that underlies Cardano. Extending Bitcoin-style outputs with datums and validator scripts gives expressive smart contracts while keeping validation local and deterministic. Two consequences are foundational to this project: fees and execution costs are known before submission, and a contract’s state — here a liquidity pool — lives in a single output that only one transaction can consume. The paper defines the concurrency problem but does not solve it. Its multi-asset extension [2] provides the native tokens that a DEX exchanges."),
  H2("2.2 Batching for eUTXO Concurrency"),
  P("MELD’s technical report [5] establishes batching as the accepted solution to eUTXO concurrency: orders are placed as separate UTXOs and a batcher later settles them deterministically. Brühwiler [6] gives an academic treatment of the same problem with a working concurrent-DEX prototype on Cardano, and Hryniuk [7] describes fan-out, batching and order-book patterns for contention. All three are concerned with **correctness** of concurrent settlement. The batching they describe is **static and rule-based**: none addresses *when* to submit or *how many* orders to include."),
  H2("2.3 Transaction Fee Mechanism Design"),
  P("Roughgarden [10] analyses Ethereum’s EIP-1559, in which a base fee rises as blocks fill, making congestion expensive in money. This work is cited as a **contrast**: Cardano has no such mechanism. It establishes precisely what Cardano does not do, and therefore why the objective of this project is latency rather than fees."),
  H2("2.4 Learned Resource Scheduling"),
  P("Mao et al.’s DeepRM [15] trains a reinforcement-learning agent in simulation to pack arriving jobs with multi-dimensional resource demands into capacity-limited slots. Structurally this is the same problem as packing orders with size, memory and step costs into capacity-limited transactions and blocks, and DeepRM serves as the method template for this project. Decima [16] extends the approach to learned scheduling for data-processing clusters. Neither knows anything about eUTXO, block limits or the latency–cost trade-off."),
  H2("2.5 Supporting Work"),
  B("**Ouroboros** [3] — the source of the one-second slot and active-slot coefficient, hence the geometric block cadence the simulator replays."),
  B("**Ouroboros Leios** [4] — a protocol-level throughput upgrade; this project is a complementary application-layer optimisation."),
  B("**Constant-function market makers** [8], [9] — the theory behind the `x·y = k` pool and the endogenous slippage model."),
  B("**Transaction reordering** [11] — supports the fairness discussion and independently states that a pool admits one interaction per block."),
  B("**Methods** — Sutton and Barto [12] for the MDP formulation, DQN [13], PPO [14] and LSTM [17]."),
  H2("2.6 Comparison of Existing Work"),
  ...Tbl("Comparison of the core literature", ["Ref.", "Work", "Supplies", "Leaves open"], [
    ["[1]", "Extended UTXO Model", "The platform, deterministic fees, the single-pool-UTXO bottleneck", "Defines the concurrency problem; does not solve it"],
    ["[5]", "MELD batching", "Batching as the accepted solution", "Batching is static and rule-based"],
    ["[6]", "Concurrent DEX thesis", "Academic validation and a prototype", "Targets correctness, not timing"],
    ["[10]", "EIP-1559 analysis", "Demand-responsive fees on account-based chains", "Does not apply to Cardano — which is the point"],
    ["[15]", "DeepRM", "RL for resource packing under capacity limits, trained in simulation", "No eUTXO, block limits or latency–cost trade-off"],
  ], [700, 1900, 3400, 3000]),
  P("[[EDIT: merge in the rows of the existing literature-survey comparison table from the Review 1 deck if required]]"),
  H2("2.7 Research Gap"),
  ...Callout("Research gap", [
    "[5] and [6] establish batching but batch statically; [15] shows that this class of packing problem is learnable in simulation; [10] shows why the objective on Cardano must be latency rather than fees; and [1] explains why the constraint exists. **No existing work applies a learned or forecast-driven policy to the timing and sizing of eUTXO batches, evaluated against tuned static baselines on replayed mainnet data.** That is the contribution of this project.",
  ]),
);

// Chapter 3
add(
  Chapter(3, "System Analysis"),
  H2("3.1 Existing System: Static Batching"),
  P("Deployed batchers follow one of three fixed rules. In this report they are implemented as baselines E1–E3 and subjected to exactly the same structural rules as the proposed policies: they cannot submit while the pool is locked, and cannot exceed the per-transaction capacity limit."),
  ...Code([
    "E1  fixed size       if len(Q) >= M:                submit(Q[0:M])",
    "E2  fixed interval   if slot - last_submit >= T:    submit(Q[0:n_max])",
    "E3  greedy           if len(Q) > 0:                 submit(Q[0:n_max])",
  ]),
  P("*M* and *T* are **tuned on the validation split** rather than guessed, because comparing against a badly configured baseline would invalidate the comparison. The tuned values are E1 *M* = 16 and E2 *T* = 20 slots."),
  H2("3.2 Limitations of the Existing System"),
  B("**The chain is never read before deciding.** A static batcher cannot react to queue depth, block cadence or the rare full block."),
  B("**The pool lock is ignored.** A fixed rule does not account for the fact that every submission blocks the pool until confirmation."),
  B("**A single operating point.** Each rule fixes one point on the latency–cost trade-off; greedy minimises latency at the highest per-user cost, large fixed sizes do the opposite."),
  B("**No explicit starvation guarantee.** A fixed-size rule can leave a small queue waiting indefinitely in a quiet period unless a deadline is imposed externally."),
  H2("3.3 Proposed System"),
  P("The proposed system is an event-driven control loop wrapped around a forecast-then-decide pipeline, with an offline simulator that can substitute for the live chain. At each block it observes the order queue and a forecast of block fill, and a policy decides WAIT or SUBMIT(*n*). Three properties drive the design:"),
  N("**The environment is partially observable** — the batcher cannot know how full the next block will be or how long its batch will take to confirm."),
  N("**There is one shared resource** — the pool UTXO; the system is fundamentally a lock manager under uncertain service time."),
  N("**Constraints are hard and external** — capacity limits come from the protocol and are enforced structurally by the environment, never learned by the policy."),
  P("Two decision-makers are proposed: **P2**, an explainable constrained optimizer, and **P3**, a DQN agent with action masking. A LightGBM forecaster (P1) supplies predicted block fill to both."),
  H2("3.4 Comparison: Existing versus Proposed"),
  ...Tbl("Existing and proposed systems compared", ["Aspect", "Existing (static)", "Proposed (adaptive)"], [
    ["Decision input", "A constant (M, T) or nothing", "Queue depth, oldest wait, predicted fill, pool-lock state, feasible batch size"],
    ["Capacity handling", "Implicit or by hand", "Gate A enforced by the environment; Gate B checked against a forecast"],
    ["Starvation", "Not guaranteed", "Deadline D_MAX masks WAIT once reached"],
    ["Trade-off", "One fixed point", "Tunable frontier (P2) or learned (P3)"],
    ["Evaluation", "Rarely measured", "Paired episodes, non-parametric tests, confidence intervals"],
  ], [2000, 3200, 3800]),
  H2("3.5 Feasibility Study"),
  H3("3.5.1 Technical feasibility"),
  P("All components are free and run on a laptop CPU. The capacity limits were verified against the Cardano protocol parameter guide. Per-transaction execution memory bounds a batch at 24 orders under the cost estimates used, so the action space is small and discrete, making DQN genuinely tractable. Training five agents took about three hours of CPU time in total."),
  H3("3.5.2 Economic feasibility"),
  P("The project has zero monetary cost. The Koios API requires no key, Blockfrost has a free tier, no GPU or Cardano node is required, and preprod test tokens have no value."),
  H3("3.5.3 Operational feasibility"),
  P("The batcher is a single background process with no inbound ports, no database server and no user-facing surface. Users continue to place orders from any Cardano wallet; the batcher is invisible to them."),
  H2("3.6 Requirements"),
  H3("3.6.1 Functional requirements"),
  ...Tbl("Functional requirements", ["ID", "Requirement", "Priority"], [
    ["FR-1", "Collect per-block congestion data from public APIs", "Must"],
    ["FR-2", "Persist collected data as a versioned, reproducible dataset", "Must"],
    ["FR-3", "Forecast next-block fill percentage from recent history", "Must"],
    ["FR-4", "Maintain a queue of pending orders with arrival slot, size and execution cost", "Must"],
    ["FR-5", "Decide each block whether to WAIT or SUBMIT(n), n bounded by capacity", "Must"],
    ["FR-6", "Reject any batch violating per-transaction limits before construction", "Must"],
    ["FR-7", "Force submission when the oldest order reaches the deadline D_MAX", "Must"],
    ["FR-8", "Refuse to submit while a previous batch holds the pool UTXO", "Must"],
    ["FR-9", "Record every decision to a structured log (D3)", "Must"],
    ["FR-10", "Replay historical blocks in a discrete-event simulator", "Must"],
    ["FR-11", "Provide baselines E1–E3 and forecaster baseline E4", "Must"],
    ["FR-12", "Compute the full metric set with paired statistical comparison", "Must"],
    ["FR-13", "Build, sign and submit a real batch via PyCardano", "Should"],
    ["FR-14", "Deploy Aiken order and pool validators on preprod", "Could"],
    ["FR-15", "Provide a local dashboard of the decision loop", "Could"],
  ], [900, 6800, 1300]),
  H3("3.6.2 Non-functional requirements"),
  ...Tbl("Non-functional requirements", ["ID", "Requirement", "Target"], [
    ["NFR-1", "Decision latency", "< 1 s per decision"],
    ["NFR-2", "RL training on a laptop CPU", "< 6 h per agent"],
    ["NFR-3", "Experiments reproducible from a seed", "Bit-identical metric output"],
    ["NFR-4", "Protocol limits defined in exactly one module", "Single source of truth, enforced by test"],
    ["NFR-5", "Data collection inside free API tiers", "No paid plan"],
    ["NFR-6", "No secrets committed to the repository", "Enforced by .gitignore and a pre-commit scan"],
    ["NFR-7", "Testnet keys only", "Hard network guard in configuration"],
  ], [1000, 5000, 3000]),
);

// Chapter 4
add(
  Chapter(4, "System Requirements"),
  H2("4.1 Hardware Requirements"),
  ...Tbl("Hardware requirements", ["Component", "Requirement", "Notes"], [
    ["Processor", "Any modern multi-core x86-64 CPU", "No GPU required (NFR-2)"],
    ["Memory", "8 GB RAM", "16 GB comfortable for RL training"],
    ["Disk", "~2 GB free", "D1 parquet, models, experiment outputs"],
    ["Network", "Internet access", "Only for one-off data collection"],
  ], [2000, 3500, 3500]),
  P("[[EDIT: add the exact specification of the machine used for the reported runs]]"),
  H2("4.2 Software Requirements"),
  ...Tbl("Software and libraries, with the reason for each choice", ["Layer", "Choice", "Why this and not the alternative"], [
    ["Language", "Python 3.11", "One language across data, ML and transaction building; PyCardano exists"],
    ["Chain data", "Koios REST (primary), Blockfrost (fallback)", "Free, no node required; cardano-db-sync needs hundreds of GB and days of synchronisation"],
    ["Dataframes", "pandas + pyarrow", "Parquet keeps D1 compact and typed"],
    ["Forecaster", "LightGBM", "Gradient boosting suits tabular lag features and trains in minutes on CPU"],
    ["RL", "Stable-Baselines3 + Gymnasium", "Standard, maintained implementations of DQN with a standard environment API"],
    ["Statistics", "SciPy", "Wilcoxon signed-rank test"],
    ["Simulator", "Hand-written event loop", "SimPy adds an unneeded process abstraction; the loop must be exactly auditable"],
    ["Plots", "Matplotlib", "Deterministic output for the report"],
    ["Testing", "pytest, hypothesis, pytest-cov", "Unit and property tests, coverage enforced in CI"],
    ["Tooling", "uv, ruff, pre-commit, GitHub Actions", "Reproducible environments, linting and continuous integration"],
    ["Tx building (Phase 7)", "PyCardano 0.14", "Builds, balances and signs transactions in pure Python and submits through Blockfrost; no Cardano node required"],
    ["On-chain (Phase 7)", "Aiken v1.1.23, stdlib v3.1.0", "Compiles to Plutus V3 with a built-in unit-test runner; the language Minswap V2 itself is written in"],
  ], [1800, 2800, 4400]),
  H2("4.3 Protocol Parameters"),
  P("The design is built against these exact Cardano mainnet values, which makes them a requirement rather than a design choice. Each appears in exactly one source module, `src/batcher/config/protocol.py`, and a test fails if any is written as a literal elsewhere."),
  ...Tbl("Cardano protocol parameters used", ["Parameter", "Value", "Meaning"], [
    ["maxTxSize", "16,384 B", "Maximum serialized size of one transaction"],
    ["maxTxExecutionUnits.memory", "14,000,000", "Plutus memory units per transaction"],
    ["maxTxExecutionUnits.steps", "10,000,000,000", "Plutus CPU steps per transaction"],
    ["maxBlockBodySize", "90,112 B", "Maximum block body size"],
    ["maxBlockExecutionUnits.memory", "62,000,000", "Plutus memory units per block"],
    ["maxBlockExecutionUnits.steps", "40,000,000,000", "Plutus CPU steps per block"],
    ["minFeeA / minFeeB", "44 lovelace/B / 155,381 lovelace", "Size coefficient / flat component"],
    ["priceMemory / priceSteps", "0.0577 / 0.0000721 lovelace", "Execution unit prices"],
    ["Slot duration / active slot coefficient", "1 s / 0.05", "Blocks every 20 s on average, geometric gaps"],
  ], [3200, 2600, 3200]),
);

// Chapter 5
add(
  Chapter(5, "System Design"),
  H2("5.1 Architecture Overview"),
  P("The system is organised in four layers. **L1**, on-chain, holds order UTXOs and the pool UTXO on Cardano preprod. **L2**, the off-chain batcher, is the deliverable: a forecaster and an order queue feed a policy, which drives a batch builder. **L3**, data, collects block history into dataset D1. **L4**, offline training and evaluation, replays D1 through the simulator to train and score every policy. L2 is the product, L3 supplies the signal, and L4 is where every reported result is produced."),
  ...Code([
    "L4  OFFLINE     M6 Simulator -> Baselines E1-E3 -> Metrics, statistics, figures",
    "L3  DATA        Koios -> M1 Collector -> D1 block history",
    "L2  BATCHER     M2 Forecaster + M3 Queue -> M4 Policy -> M5 Builder -> outcome",
    "L1  ON-CHAIN    User wallet -> Order UTXOs -> Pool UTXO (one spend per block)",
  ]),
  H2("5.2 Module Design"),
  ...Tbl("Modules and responsibilities", ["ID", "Module", "Responsibility", "Owns"], [
    ["M1", "Chain Data Collector", "Poll block endpoints, normalise, persist resumably", "D1"],
    ["M2", "Congestion Forecaster", "Predict fill for blocks t+1..t+3", "P1, E4"],
    ["M3", "Order Queue Manager", "Strict FIFO queue with ages, sizes, execution costs, expiry", "Queue state"],
    ["M4", "Adaptive Batching Policy", "Decide WAIT or SUBMIT(n)", "E1–E3, P2, P3"],
    ["M5", "Batch Builder / Estimator", "Estimate size, execution units and fee; enforce Gate A", "Transaction construction"],
    ["M6", "Simulator and Evaluation", "Replay blocks, model mempool and pool lock, score policies", "D2, D3, metrics"],
    ["M7", "On-chain DEX (optional)", "Order and pool validators on preprod", "D4"],
  ], [700, 2200, 4400, 1700]),
  P("The queue is strictly FIFO: a batch is always the prefix `Q[0:n]`, never a chosen subset. This is a deliberate fairness property that removes order-selection manipulation from the design space."),
  H2("5.3 The Two Capacity Gates"),
  P("A batch is one transaction submitted into one block, and two independent constraint sets apply. Conflating them is the most consequential error available in this design, and it was present in the project’s early material."),
  ...Code([
    "Gate A - feasibility (per transaction, always binding)",
    "  tx_size(n)  = TX_OVERHEAD + sum(order_size[i])  <= 16,384",
    "  tx_mem(n)   = POOL_MEM    + sum(order_mem[i])   <= 14,000,000",
    "  tx_steps(n) = POOL_STEPS  + sum(order_steps[i]) <= 10,000,000,000",
    "",
    "Gate B - inclusion (per block, congestion dependent)",
    "  blk.size  + tx_size(n)  <= 90,112",
    "  blk.mem   + tx_mem(n)   <= 62,000,000",
    "  blk.steps + tx_steps(n) <= 40,000,000,000",
  ]),
  ...Tbl("Gate A and Gate B contrasted", ["", "Gate A", "Gate B"], [
    ["Bounds", "Maximum batch size", "Whether the batch fits now"],
    ["Depends on congestion", "No", "Yes"],
    ["Violation means", "Invalid transaction — a defect", "Wait for a later block — normal"],
    ["Enforced by", "Environment clamp and builder assertion", "Forecast at decision time; the real block at inclusion"],
  ], [2200, 3400, 3400]),
  P("**An empty block does not permit a larger batch.** A formulation such as `capacity = (1 − fill_hat) × 90,112` would propose invalid transactions on an idle chain. With per-order estimates of 300 B, 0.5 M memory units and 200 M steps, execution memory binds first and Gate A caps a batch at **24 orders**."),
  H2("5.4 Cost Model and Amortization"),
  P("The fee decomposes into a flat part, paid once per batch, and a marginal part paid for every order:"),
  ...Code([
    "fee(n)          = FLAT + n * MARGINAL",
    "FLAT            = 155,381 + 44*TX_OVERHEAD + 0.0577*POOL_MEM + 0.0000721*POOL_STEPS",
    "                = 350,461 lovelace",
    "MARGINAL        = 44*order_bytes + 0.0577*order_mem + 0.0000721*order_steps",
    "                = 56,470 lovelace",
    "cost_per_user(n) = FLAT / n + MARGINAL",
  ]),
  ...Tbl("Amortization under the default cost estimates", ["Batch size n", "Total fee (ADA)", "Per user (ADA)"], [
    ["1", "0.407", "0.407"], ["5", "0.633", "0.127"], ["10", "0.915", "0.092"], ["20", "1.480", "0.074"], ["24 (Gate A cap)", "1.706", "0.071"],
  ], [3000, 3000, 3000]),
  ...Fig(path.join(FIG, "F3_amortization_curve.png"), "F3 — per-user cost against batch size"),
  P("Only the flat term amortizes. The curve flattens quickly: most of the saving is realised by *n* ≈ 10, and growing from 10 to 24 orders saves a further 22 %. There is therefore little economic reason to hoard orders, which is why latency dominates the objective."),
  H2("5.5 The Pool Lock and Head-of-Line Blocking"),
  P("A batch consumes the pool UTXO and produces a new one. Until the batch confirms, the new pool output does not exist, so a second batch cannot be constructed: at most one batch per pool is in flight. A submitted transaction that does not fit the next block is **not rejected** — it waits in the mempool and is retried against each subsequent block. The real cost of a mistimed submission is therefore **head-of-line blocking**: every order queued behind the in-flight batch waits. Genuine failures come from only three sources: TTL expiry, mempool rejection and rollback. This replaced a “bounce penalty” in the original design that modelled a rejection which does not occur."),
  H2("5.6 Algorithm Design"),
  H3("5.6.1 Forecasters"),
  P("**E4**, the baseline, predicts the mean fill of the last 20 blocks, repeated across the horizon; a second naive baseline, **E4b**, decays from the current block toward that mean and was added for ablation A2 (Section 8.10). **P1**, a LightGBM regressor, uses fill lags 1–20, rolling means and standard deviations over 5, 10 and 20 blocks, slot-gap cadence features, transaction-count lags and hour-of-day encoded as sine and cosine. Data is split chronologically 70/15/15 and never shuffled. A planned LSTM variant was cut on scope grounds once the predictability analysis (Section 8.2) was complete."),
  H3("5.6.2 P2 — constrained optimizer"),
  ...Code([
    "decide(obs):",
    "    if pool_locked or queue empty:  return WAIT",
    "    n_feasible = max n satisfying Gate A",
    "    if oldest_wait >= D_MAX:         return SUBMIT(n_feasible)  # fairness",
    "    n = min(n_feasible, max n satisfying Gate B at fill_hat[t+1])",
    "    if n == 0:                       return WAIT     # predicted no room",
    "    if n < N_MIN and quieter block:  return WAIT     # wait to amortize",
    "    return SUBMIT(n)",
  ]),
  P("P2 is deterministic and explainable, cannot fail to converge, and separates how much of any gain comes from *forecasting* versus from *learning*. Its **ORACLE** variant receives the true next-block fill instead of a forecast, bounding what any forecaster could achieve."),
  H2("5.7 MDP Formulation and Reward (P3)"),
  P("**State** — an 11-dimensional vector normalised to [0, 1]: queue depth, oldest and mean wait relative to D_MAX, forecast fill for t+1..t+3, memory headroom, the Gate A maximum batch size, pool-lock flag, slots in flight, and hour of day as sine and cosine. Including the Gate A maximum lets the agent see its own feasible action range."),
  P("**Action** — WAIT, or SUBMIT(*n*) for *n* in the buckets {1, 4, 8, 12, 16, 20, 25, 30, n_max}."),
  P("**Action masking** — illegal actions are made unavailable rather than penalised: only WAIT while the pool is locked; WAIT is illegal once the oldest order reaches D_MAX; every SUBMIT(*n*) above the Gate A maximum is illegal. The mask is enforced inside the environment’s `step` as well as exposed, so an agent that ignores it still cannot act illegally."),
  ...Code([
    "r = -( w_cost    * flat_fee_share(n)",
    "     + w_latency * sum(wait_i ^ 2) / NORM",
    "     + w_slip    * slippage(n)",
    "     + w_lock    * slots_pool_locked )",
  ]),
  P("Only the flat fee share enters the reward, since the marginal part is constant per order. Waiting is penalised quadratically to encode the tail-latency objective. **There is no inclusion-failure penalty**, because no such event exists. Each term is normalised to unit scale on a reference episode before weighting: left raw, the latency term is about 19 times the cost term and cost would be numerically invisible."),
  H2("5.8 Dataset Design"),
  ...Tbl("Datasets", ["ID", "Dataset", "Content", "Source"], [
    ["D1", "Block history", "Height, absolute slot, size, fill %, transaction count; execution units on a sample", "Koios, mainnet, 388,781 blocks, 92 days"],
    ["D2", "Order stream", "Arrival slot, size, memory, steps, TTL per order", "Generated: diurnal Poisson with bursts fitted to D1"],
    ["D3", "Decision log", "One row per observed block per episode per policy", "Simulator"],
    ["D4", "Preprod log", "Live submissions and outcomes", "Optional live mode"],
  ], [700, 1600, 4000, 2700]),
  P("Execution units cannot be collected for every block within free API limits, so D1 records size for all 92 days and execution units for **two 2-day samples** (17,280 blocks) taken from a quiet and a congested window. Blocks outside the sample carry an explicit “absent” marker, never zero, because zero would make them look empty and corrupt every congestion statistic."),
  H2("5.9 Simulator Design"),
  P("The simulator replays recorded blocks on their **real slot clock** — a fixed 20-second tick would understate tail latency, the very metric the project claims to improve. At each block it admits arriving orders and evicts expired ones; if a batch is in flight it resolves it against the real block (confirm if Gate B holds, expire at TTL, otherwise head-of-line wait with no decision); otherwise it builds an observation, asks the policy, and enforces the structural rules outside the policy."),
  P("**Paired episodes** present an identical block window, identical order stream and identical seed to every policy, so differences are attributable to the decision logic. The episode set deliberately includes a 25 % share of congested windows. Stated assumptions: recorded block usage is fixed background load (conservative); one batcher and one pool; no transaction chaining (conservative); perfect execution-unit estimation (bounded by ablation A5); homogeneous order costs; rare independent rollbacks; endogenous slippage from a constant-product pool."),
  H2("5.10 UML and Flow Diagrams"),
  ...Fig(D(1), "Use case diagram — the swap user never interacts with the batcher", 600, 520),
  P("P3 is not a `Policy` subclass in the class diagram that follows: the DQN agent acts through `BatchingEnv`, the Gymnasium wrapper around the same event loop, and is scored through the same metrics path."),
  ...Fig(D(2), "Class diagram — every policy reads the same Observation and returns the same Action", 900, 520, true),
  ...Fig(D(3), "Sequence diagram — one order from placement to settlement", 900, 520, true),
  ...Fig(D(4), "Activity diagram — the control loop for one block", 520, 700),
  ...Fig(D(5), "Data flow diagram, level 0", 600, 300),
  ...Fig(D(6), "Data flow diagram, level 1", 520, 640),
  ...Fig(D(7), "State diagram — the pool lock. There is no rejected or bounced state", 900, 520, true),
  P("The state diagram is where the mechanism that makes the project non-trivial becomes visible. While the pool is in the InFlight state no decision exists, and orders accumulate behind the batch. The deadline D_MAX bounds when a *decision* is forced, not how long an order waits: an order can pass D_MAX and wait until the next moment a block arrives and the pool is free — an overshoot of up to 114 slots was measured."),
  ...Fig(D(8), "Deployment diagram — research mode and optional live mode", 600, 460),
);

// Chapter 5, section 5.11 — on-chain design (Phase 7)
add(
  H2("5.11 On-Chain DEX Design"),
  P("Deployed DEXes bind their orders to their own validators and license their batchers, so a third-party batcher cannot serve them (ADR-003). The project therefore defines the smallest DEX that lets a batcher be demonstrated on the preprod test network: two Aiken validators compiled to Plutus V3, both parameterised by the batcher’s key hash. The batcher is **untrusted for correctness**: the validators, not the batcher, decide whether a user was treated fairly."),
  ...Tbl("Rules enforced on chain", ["Validator", "Rule", "Test"], [
    ["order.ak — Cancel", "The order’s owner has signed; they can always reclaim an unbatched order", "T-O1"],
    ["order.ak — Execute", "Only the authorised batcher key executes", "T-O3"],
    ["order.ak — Execute", "The user is paid at least `min_out` of the output asset, at the return address in the datum", "T-O2"],
    ["order.ak — Execute", "At most `fee / n + margin` lovelace is kept back from the user, where `n` is the number of orders in the batch", "T-O5"],
    ["order.ak — Execute", "The payout carries the order’s own output reference as its datum, so one payment cannot satisfy two orders", "Double satisfaction"],
    ["pool.ak", "Batcher-signed; exactly one continuing pool output, still holding the pool NFT; pool parameters unchanged", "T-O4"],
    ["pool.ak", "After fees on each asset’s net inflow, the constant product does not decrease", "T-O4"],
  ], [2200, 5200, 1600]),
  H3("5.11.1 The pass-through fee"),
  P("On a flat-fee DEX each order pays a fixed batcher fee, so a larger batch lowers the operator’s cost but not the user’s. Here the order validator reads the actual transaction fee and counts the order inputs, and allows the batcher to keep only `fee / n + margin` from each user (ADR-006). **The amortization that the policies optimise is thereby delivered to users by the ledger, not by the operator’s goodwill**, and the per-user cost C-user measures something a user actually pays."),
  H3("5.11.2 The pool invariant"),
  ...Code([
    "inflow_x   = max(x_new - x, 0)        inflow_y   = max(y_new - y, 0)",
    "adjusted_x = x_new * 10000 - inflow_x * fee_bps",
    "adjusted_y = y_new * 10000 - inflow_y * fee_bps",
    "valid      = adjusted_x * adjusted_y >= x * y * 10000 * 10000",
  ]),
  P("The fee is charged on the **net** inflow of each asset, so a batch can net buy and sell orders together and still never extract value from the pool."),
  H3("5.11.3 A pool identity that cannot be forged"),
  P("The pool token and the pool NFT are minted under a native-script policy that requires the batcher’s signature **and** a validity bound: nothing can be minted after a slot fixed at deployment. Once that slot passes, no second pool NFT can exist, so the NFT that identifies the pool is unique by construction rather than by the batcher’s good behaviour."),
);

// Chapter 6
add(
  Chapter(6, "Implementation"),
  H2("6.1 Repository Structure"),
  ...Code([
    "src/batcher/",
    "  config/    protocol.py (constants), params.py (tunables), settings.py (preprod guard)",
    "  data/      sources.py (Koios client), collector.py (resumable M1), features.py",
    "  build/     estimator.py (fee, Gate A, Gate B), submitter.py, tx_builder.py",
    "  queue/     manager.py (FIFO order queue, M3)",
    "  forecast/  baseline.py (E4), lgbm.py (P1), evaluate.py",
    "  policy/    base.py (interfaces), static.py (E1-E3, NULL), optimizer.py (P2, ORACLE)",
    "  sim/       env.py (event loop), mempool.py, orders.py (D2), episodes.py, gym_env.py",
    "  eval/      metrics.py, stats.py, plots.py, manifest.py, rl_diagnostics.py",
    "scripts/     collect, verify_dataset, analyze_congestion, train_forecaster,",
    "             tune_baselines, evaluate, train_rl, evaluate_rl,",
    "             final_evaluation, run_stats, make_figures, ...",
    "  onchain/   datums.py, blueprint.py, deployment.py (Phase 7)",
    "  live/      chain.py, daemon.py (Phase 7 live batcher)",
    "onchain/     Aiken: validators/order.ak, validators/pool.ak, plutus.json",
    "tests/       339 Python tests in 26 files; 16 Aiken tests in onchain/",
  ]),
  P("Every number in this report is produced by a script under `scripts/` that writes a **run manifest** recording the seed, git revision, configuration hash and dataset checksum. No result reaches the report through a notebook."),
  H2("6.2 Protocol Constants Module"),
  P("All capacity limits and fee coefficients live in `config/protocol.py` and nowhere else (NFR-4). Test T-C2 walks the source tree and fails if any of these literals appears outside that module, so a governance change to a parameter is a one-line edit that cannot be missed. A companion settings module refuses to load any network other than preprod, so mainnet key material cannot be used by configuration error."),
  H2("6.3 Data Collection (M1)"),
  P("The collector pages through Koios block endpoints, requesting only the needed fields. It is **resumable** — interrupted runs continue from the last written height and produce a byte-identical file — and it retries transient failures, including truncated HTTP responses that surfaced during the 92-day collection. The block range is pinned by explicit start and end heights so the dataset can be regenerated exactly. The final dataset of 388,781 blocks has SHA-256 checksum `48cd6f8b9a9e…`, verified to have no height gaps and strictly increasing slots."),
  H2("6.4 Feature Engineering"),
  P("Features are lags of fill 1–20, rolling means and standard deviations over 5, 10 and 20 blocks, slot gap and its rolling mean, transaction-count lags and hour of day as sine and cosine. The anti-leakage rule is that every feature at block *t* must be computable from data at or before *t*; a test asserts it. A defect found here is instructive: the evaluation script originally did not build features before calling the forecaster, which silently fell back to the moving average. Missing feature columns now raise an error instead of degrading quietly."),
  H2("6.5 P1 Forecaster"),
  P("LightGBM is trained with an L1 objective on the training split, with early stopping on validation MAE. The model is frozen after training and wrapped with a cache so the simulator can query forecasts cheaply during thousands of episodes. If the model artifact fails to load, prediction falls back to E4 and reports that it has done so."),
  H2("6.6 Gate Implementation"),
  P("The gates embody the ADR-002 decision in their signatures: **Gate A cannot see a block at all**, and the fee function takes no block or congestion argument, so the corrected errors are not even expressible."),
  ...Code([
    "def fee_lovelace(size: int, mem: int, steps: int) -> int:",
    "    \"\"\"The Cardano fee formula. Deterministic; no congestion term.\"\"\"",
    "    return int(MIN_FEE_A * size + MIN_FEE_B + PRICE_MEM * mem + PRICE_STEPS * steps)",
    "",
    "def gate_a(n, sizes=None, mems=None, steps=None) -> bool:",
    "    \"\"\"Feasibility. Always binding, and independent of congestion.\"\"\"",
    "    return (tx_size(n, sizes) <= MAX_TX_SIZE",
    "            and tx_mem(n, mems) <= MAX_TX_EX_MEM",
    "            and tx_steps(n, steps) <= MAX_TX_EX_STEPS)",
    "",
    "def gate_b(n, block_size, block_mem, block_steps,",
    "           sizes=None, mems=None, steps=None) -> bool:",
    "    \"\"\"Inclusion. Congestion dependent; evaluated against a forecast or a block.\"\"\"",
    "    return (block_size + tx_size(n, sizes) <= MAX_BLOCK_SIZE",
    "            and block_mem + tx_mem(n, mems) <= MAX_BLOCK_EX_MEM",
    "            and block_steps + tx_steps(n, steps) <= MAX_BLOCK_EX_STEPS)",
  ]),
  P("Test **T-G5** asserts that the maximum batch size for a completely empty block equals the Gate A maximum. It is the permanent regression guard against the original error in which an empty block was thought to permit a larger batch, and it is marked in the source as never to be deleted."),
  H2("6.7 P2 Optimizer"),
  P("P2 follows the pseudocode of Section 5.6.2 directly. Notably it **never clamps for safety**: Gate A clamping, the pool lock and the starvation deadline are enforced by the environment, so the policy’s decisions are preferences, not permissions. Duplicating the enforcement inside the policy would hide a bug in whichever copy was wrong."),
  H2("6.8 P3 Reinforcement-Learning Agent"),
  P("The Gymnasium environment wraps the same event loop. Its action mask implements the three rules of Section 5.7 and is re-applied inside `step`:"),
  ...Code([
    "def step(self, action):",
    "    mask = self.action_masks()",
    "    # Enforced here as well as exposed: an agent that ignores the mask",
    "    # still cannot act illegally.",
    "    if not mask[action]:",
    "        self.mask_hits += 1",
    "        action = int(np.argmax(mask))",
    "    n = self._action_to_n(action)",
    "    if n > 0:",
    "        taken = self.queue.take(n)",
    "        self.in_flight = build_in_flight(taken, self.current_slot, self.ttl_slots)",
    "    # Move past this block before seeking the next decision point,",
    "    # or the episode never advances on WAIT.",
    "    self.index += 1",
    "    locked_slots = self._seek_decision()",
    "    ...",
  ]),
  P("The last comment records a real defect the environment tests caught: the first implementation did not advance on WAIT, so an episode looped on one block indefinitely. DQN (Stable-Baselines3) was trained for **200,000 steps on each of five seeds** — a tenth of the 2,000,000 steps originally specified. The reduction was a recorded team decision: five seeds is non-negotiable, and at roughly six hours per seed the full budget would have required about 30 hours of CPU time. Results must therefore be read as a lower bound on what DQN could achieve."),
  H2("6.9 Simulator"),
  P("The event loop in `sim/env.py` advances on recorded absolute slots. Each episode uses one seeded random generator passed explicitly; there is no global random state and no wall-clock time in any decision path, so two runs with the same seed produce byte-identical metrics. Order conservation — orders in equal settled plus expired plus still queued — is asserted at the end of every episode, so an accounting leak fails the run rather than silently corrupting throughput."),
  H2("6.10 Statistical Evaluation"),
  P("`eval/stats.py` implements the paired analysis: the Wilcoxon signed-rank test on per-episode differences, the median paired difference with a seeded 10,000-resample bootstrap 95 % confidence interval, and Holm–Bonferroni correction across the primary metrics. An improvement is declared significant only if its adjusted p-value is below 0.05 **and** its confidence interval excludes zero."),
  H2("6.11 On-Chain Validators"),
  P("The validators are written in Aiken v1.1.23 against stdlib v3.1.0 and compile to Plutus V3 scripts of 944 bytes (order) and 864 bytes (pool). The core of the order validator is short enough to read in full:"),
  ...Code([
    "Execute -> {",
    "  expect Some(own_input) = transaction.find_input(self.inputs, own_ref)",
    "  let own_credential = own_input.output.address.payment_credential",
    "  let n = list.count(self.inputs,",
    "            fn(input) { input.output.address.payment_credential == own_credential })",
    "  let charge = self.fee / n + request.margin      // ADR-006: pass-through fee",
    "",
    "  let tag: Data = own_ref                           // against double satisfaction",
    "  expect Some(payout) = list.find(self.outputs, fn(output) {",
    "    output.address == request.return_address && output.datum == InlineDatum(tag) })",
    "",
    "  let user_made_whole = when request.direction is {",
    "    AtoB -> paid_token >= request.min_out",
    "              && paid_lovelace >= deposit - request.amount_in - charge",
    "    BtoA -> paid_lovelace >= deposit + request.min_out - charge",
    "  }",
    "  and { list.has(self.extra_signatories, batcher), user_made_whole }",
    "}",
  ]),
  P("The compiler writes a blueprint, `plutus.json`, describing every datum and redeemer. The Python side mirrors those types as PyCardano Plutus data, and a test checks every constructor index and field order against the blueprint, so the two cannot drift: a mis-encoded datum is not a type error anywhere, only a transaction rejected on chain without explanation. A second test checks that PyCardano derives the same script hashes the compiler recorded. Parameters — the batcher key, the pool token — are applied with `aiken blueprint apply`, the compiler that produced the code, rather than by editing scripts in Python."),
  P("One defect is worth recording. The first order validator bound its datum to a local variable named `order`, the validator’s own name. It failed to compile with **no diagnostic at all**, because the compiler prints errors only to an interactive terminal; the cause was found by compiling halves of the file."),
  H2("6.12 Transaction Building"),
  P("Live batching is **planned before it is built**. `plan_batch` takes queued orders oldest first, quotes each against the pool with the constant-product formula, and drops any order the pool cannot fill at its `min_out` — then recomputes everyone’s fee share for the smaller batch, since `n` has changed. It re-checks Gate A and raises on a violation, and it imports `gate_a` and `fee_lovelace` from the same estimator the simulator uses, a property tested by object identity (T-N6)."),
  P("Building the transaction with PyCardano adds one subtlety. Users are charged for the fee the plan assumed, but `order.ak` checks against the fee the transaction **actually** carries; if the built fee came in lower, users would have been overcharged and the batch rejected. Settling the fee after the build is not enough on its own, as the first live batch showed (Section 8.12): the node evaluates the scripts *during* the build, against a fee not yet known. The builder therefore works in two passes — a probe that charges margins only, valid at any fee, to obtain execution units; then a final build with those units fixed, charging users for the fee the transaction really carries:"),
  ...Code([
    "probe_plan = plan_batch(queued, x, y, deployment.fee_bps, network_fee=0)  # margins only",
    "probe = _assemble(context, batcher_skey, deployment, scripts, pool_utxo, by_ref, probe_plan, ttl)",
    "units = _probe_units(probe)                  # the node evaluates exactly once, here",
    "",
    "plan = plan_batch(queued, x, y, deployment.fee_bps, network_fee=probe.transaction_body.fee)",
    "for _ in range(MAX_FEE_ROUNDS):",
    "    tx = _assemble(context, batcher_skey, deployment, scripts, pool_utxo, by_ref, plan, ttl, units)",
    "    fee = tx.transaction_body.fee",
    "    if plan.network_fee <= fee <= plan.network_fee + FEE_TOLERANCE_LOVELACE:",
    "        return _measure(tx, plan, ttl)",
    "    # Charge users for the fee this transaction actually carries, then rebuild.",
    "    plan = plan_batch(queued, x, y, deployment.fee_bps, network_fee=fee)",
  ]),
  P("Deployment is derived deterministically from the batcher key and the minting deadline. The committed deployment record holds hashes only; on load the scripts are re-derived and checked against it, so rebuilding the validators with different code after deploying fails loudly instead of producing scripts that cannot spend the deployed pool. Every script that can submit a transaction is a **dry run unless `--submit` is given**."),
  H2("6.13 The Live Batcher"),
  P("`scripts/run_batcher.py` runs the simulator’s control loop against preprod through a narrow chain interface, so the whole loop is testable against a fake. Each new block it resolves any batch in flight (included, expired, or still waiting); while the pool is held **no decision is made**; otherwise it reads the queue and the pool, forms the same `Observation` the simulator builds, asks the policy, and repairs the decision with the simulator’s own structural rules — the very function object, not a copy. The forecast in live mode is E4 over real recent blocks: the learned forecaster needs a 20-block feature history the first version of the loop does not maintain. Since ablation A2 found LightGBM does help P2 on cost, running it live is listed as future work."),
  B("**Shadow mode** is the default: the batcher decides and builds and signs the exact batch it would send, then logs it without submitting. A policy can be watched on live traffic before it is trusted with the key."),
  B("**A lagging API** can still show the pool UTxO that the batcher’s own confirmed batch spent; the loop recognises it and waits rather than building a transaction that would be rejected."),
  B("**Rejected submissions** are logged and counted, and leave the pool free; a Gate A violation, being a defect, stops the daemon."),
  B("**Shutdown** is only clean with the pool free: a stop request waits for any batch in flight to resolve and starts no new batch."),
  B("**Safety:** the settings guard makes mainnet unreachable, keys are generated outside the repository and refused inside it, and the pre-commit secret scan was extended to the JSON key files PyCardano writes, proven on a real generated key."),
);

// Chapter 7
add(
  Chapter(7, "Testing"),
  H2("7.1 Strategy and Coverage"),
  P("In a research codebase the main danger is not a crash but a **quietly wrong number** that survives into the report. The test suite targets that: every number that reaches the report is produced by code covered by a test that would fail if the number were wrong. The suite contains **339 Python tests in 26 files** and **16 Aiken tests** for the validators; the Python suite runs on every push in GitHub Actions and enforces a minimum of 90 % line coverage, and measured coverage is 94.6 %."),
  ...Tbl("Test levels", ["Level", "Scope", "Tooling"], [
    ["Unit", "Estimator, gates, fee, metrics, queue, statistics", "pytest"],
    ["Property", "Invariants that must hold for all inputs", "hypothesis"],
    ["Integration", "Collector to D1, D1 to features, policy to simulator", "pytest with API fixtures"],
    ["System", "Full episodes, every policy, determinism", "pytest"],
    ["Validation", "Simulator behaviour against known-correct expectations", "pytest and scripts"],
  ], [1800, 4700, 2500]),
  H2("7.2 Invariant Tests"),
  ...Tbl("Critical invariants — any failure invalidates the results", ["ID", "Invariant", "Result"], [
    ["T-I1", "No submitted transaction violates Gate A", "Pass — also zero violations across every evaluation run"],
    ["T-I2", "No decision opportunity past D_MAX results in WAIT", "Pass (restated; see Section 7.4)"],
    ["T-I3", "No submission while the pool is locked", "Pass"],
    ["T-I4", "The chronological split never leaks", "Pass"],
    ["T-I5", "Same seed twice gives byte-identical metrics", "Pass"],
  ], [900, 5000, 3100]),
  H2("7.3 Unit and Property Tests"),
  ...Tbl("Selected unit and property tests", ["ID", "Test", "Expected", "Result"], [
    ["T-C2", "No protocol literal outside the constants module", "Only protocol.py matches", "Pass"],
    ["T-C3", "Network guard", "Non-preprod settings raise", "Pass"],
    ["T-F2", "Fee for a known transaction", "Matches hand computation to the lovelace", "Pass"],
    ["T-F3", "Fee function takes no block state (ADR-001)", "Enforced across the cost model", "Pass"],
    ["T-F5", "Amortization flattens", "cost(10)−cost(30) < cost(1)−cost(10)", "Pass"],
    ["T-G1", "Gate A independent of block state", "Same result for empty and 90 %-full block", "Pass"],
    ["T-G3", "Memory binds before size", "Memory is the limiting dimension", "Pass"],
    ["T-G5", "Empty block does not raise the Gate A cap (ADR-002)", "max_n(fill=0) = max_n_gate_a", "Pass"],
    ["T-Q1/Q2", "FIFO; returned orders keep their arrival slot", "Oldest first, no age reset", "Pass"],
    ["T-M1/M2", "Jain bounds; p95 against numpy.percentile", "1.0 for equal waits; exact match", "Pass"],
    ["T-P3", "Conservation: in = settled + expired + queued", "Holds on random episodes", "Pass"],
    ["T-N2", "Collector resumability", "Resumed run byte-identical", "Pass"],
    ["T-L1", "Leakage check on identical rows", "Leaked features help (+2.6 %); clean pipeline does not leak", "Pass"],
    ["T-L3", "Random agent over 10,000 steps", "No illegal action executed", "Pass"],
    ["T-L4", "Reward terms commensurable", "Comparable magnitude after normalisation", "Pass"],
    ["T-L6", "Collapse detector", "Always-WAIT entropy 0.0; trained agent 0.68", "Pass"],
    ["T-L5", "Checkpoint reproducibility", "Reloaded checkpoint reproduces metrics", "Pass — unit test, and all 5 committed P3 checkpoints reproduce every recorded metric exactly"],
  ], [1000, 3400, 3200, 1400]),
  H2("7.4 Simulator Validation"),
  P("A simulation-based result is only as credible as the simulator. This section answers the question a reviewer will ask: **why should the simulator be believed?**"),
  ...Tbl("Simulator validation checks V1–V4", ["Check", "Expected", "Outcome"], [
    ["V1 / T-S2 — NULL policy never submits", "Zero throughput; every order expires", "Pass"],
    ["V2 / T-S3 — greedy shape", "E3 gives the lowest latency and highest per-user cost", "Pass in unit tests and on replayed D1 at all three arrival rates"],
    ["V3 / T-S4 — E1 with M above n_max", "Behaves like NULL until D_MAX forces submission", "Pass"],
    ["V4 / T-F6 — fee replay on 200 real mainnet transactions", "Formula never exceeds the actual fee", "Pass on 200/200; median residual 0.39 % on simple transactions"],
    ["T-S5 — head-of-line blocking (ADR-004, ADR-008)", "Queue grows monotonically while locked, on a quiet and a congested fixture", "Pass"],
    ["T-S6 — real slot clock (ADR-007)", "Episode duration equals the recorded slot span", "Pass"],
  ], [3300, 3200, 2500]),
  P("**V2 is the strongest single check.** Greedy producing the lowest latency and the highest per-user cost follows directly from the cost model; had it failed, something upstream of every result would have been wrong, and the project would have stopped there."),
  P("**V4 found a real gap.** On script-bearing transactions the formula under-estimates the actual fee by a median of 29 %, almost certainly the Conway-era reference-script surcharge, which the fee formula predates. DEX batches are script-bearing, so absolute per-user costs in this report are understated. Policy *comparisons* are unaffected because every policy is priced by the same estimator, and because the missing term is charged per transaction it is a flat component that would strengthen, not weaken, the amortization argument."),
  P("**A specification gap.** Invariant I2 and goal G4 read as though D_MAX bounds how long an order waits. It bounds the *decision*: a decision exists only when a block arrives and the pool is free, so an order can pass D_MAX and wait for the next such moment — up to 114 slots of overshoot was measured. The invariant that actually holds, and is tested, is that no decision opportunity past the deadline results in WAIT."),
  H2("7.5 On-Chain and Live-Mode Tests"),
  P("Phase 7 moves the batcher from a simulator onto a real ledger, where a mistake costs a rejected transaction or, worse, a user short-changed by a buggy batcher. Everything that can be checked without submitting a transaction is checked offline: the validators in Aiken’s own test runner, and the Python side against a fake chain context on which PyCardano still performs its real coin selection, balancing and fee calculation."),
  ...Tbl("On-chain and live-mode tests", ["ID", "Test", "Result"], [
    ["T-O1", "The owner can cancel an order; a stranger or the batcher cannot", "Pass (Aiken)"],
    ["T-O2", "A payout below `min_out`, or paid to any other address, is rejected", "Pass (Aiken)"],
    ["T-O3", "A batch signed by any key but the batcher’s is rejected", "Pass (Aiken)"],
    ["T-O4", "A fair swap is accepted; ignoring the fee, losing the NFT, rewriting pool parameters or a non-batcher signer is rejected", "Pass (Aiken)"],
    ["T-O5", "`fee / n + margin` is accepted, one lovelace more is rejected, and the allowed share halves when n = 2", "Pass (Aiken)"],
    ["—", "One payout cannot satisfy two orders (double satisfaction)", "Pass (Aiken)"],
    ["—", "Every Python datum matches the compiled blueprint; PyCardano’s script hashes match the compiler’s", "Pass"],
    ["T-N6", "The live planner uses the simulator’s `gate_a` and `fee_lovelace` — the same objects", "Pass"],
    ["—", "Property test: 200 random mixes of buy and sell orders never break the pool invariant", "Pass"],
    ["—", "A built batch satisfies the order validator’s fee rule for the fee it actually pays", "Pass"],
    ["P7-5", "Keys are refused inside the repository and never overwritten; the secret scan blocks a real generated key file", "Pass"],
    ["P7-8", "Live loop: one decision per block, none while locked, expiry retried, rejection counted, stale API view, clean shutdown", "Pass"],
    ["T-O6", "One end-to-end swap settles on preprod", "Pass — batch `b5201c0a…c73af1`, verified on chain"],
  ], [900, 6100, 2000]),
  H2("7.6 Defects Found by Testing"),
  ...Tbl("Defects caught before they reached a result", ["Defect", "Effect had it survived", "Fix and guard"], [
    ["Queue admission cap silently dropped orders", "Throughput and expiry both wrong", "Queue made unbounded; conservation asserted per episode"],
    ["Arrival process ran 4.5× hot", "E1 appeared to fail catastrophically (68 % expiry)", "Bursts expressed as onsets per day"],
    ["Decision log recorded post-action queue depth", "Deadline assertion silently defeated", "Log records what the policy observed"],
    ["Forecaster silently fell back to moving average", "LightGBM results would have been E4’s", "Missing features raise an error"],
    ["RL environment never advanced on WAIT", "Episodes looped forever", "Act, advance, seek next decision; regression test"],
    ["Leakage check compared different rows", "False “leaking” verdict", "Both models scored on identical rows"],
    [".gitignore rule hid src/batcher/build", "CI import failure on a clean checkout", "Anchored rule; test that no source file is ignored"],
    ["Live: Blockfrost’s raw-CBOR datums unreadable", "Every real order silently skipped", "Accept raw CBOR; regression test with datums as Blockfrost returns them"],
    ["Live: users charged for the estimated fee", "First batch rejected by order.ak during evaluation", "Two-pass build; fake chain enforcing the fee rule during evaluation"],
  ], [3000, 3000, 3000]),
  H2("7.7 Regression Guards for Corrected Assumptions"),
  ...Tbl("Permanent guards for each architecture decision", ["Decision", "Guard", "Status"], [
    ["ADR-001 latency, not fees", "Cost model takes no block state", "Live"],
    ["ADR-002 transaction limits, not block limits", "T-G5", "Live"],
    ["ADR-004 pool-lock failure model", "T-S5; no bounce outcome exists", "Live"],
    ["ADR-005 sampled execution units", "Absent values are null, never zero", "Live"],
    ["ADR-006 pass-through fee", "T-O5 in the order validator’s Aiken tests", "Live"],
    ["ADR-007 real slot clock", "T-S6", "Live"],
    ["ADR-008 concurrency, not congestion", "T-S5 on a quiet fixture", "Live"],
  ], [3400, 3800, 1800]),
);

// Chapter 8
add(
  Chapter(8, "Results and Discussion"),
  ...Callout("Status of this chapter", [
    "Sections 8.5–8.9 and 8.11 report the **held-out test split, evaluated exactly once**: 8 policies × 3 arrival rates × 100 paired episodes, with P3 run for all five seeds and seed-averaged per episode before pairing. Every configuration was fixed on validation beforehand. Validation tables from Phases 4 and 5 are retained for context and labelled as such.",
  ]),
  H2("8.1 Congestion Analysis"),
  P("The project was originally motivated by a widely repeated claim that Cardano blocks run 80–90 % full at peak, leaving no room for a batch. D1 was collected to quantify that claim. **It does not hold on the current chain.**"),
  ...Tbl("Block occupancy over 92 days of mainnet (388,781 blocks)", ["Statistic", "Measured"], [
    ["Mean block fill", "6.83 %"], ["Median block fill", "2.95 %"], ["95th percentile", "25.39 %"],
    ["Blocks above 80 % / 90 %", "0.564 % / 0.395 %"], ["Transactions per block", "3.76"],
    ["Congested blocks (>80 %)", "2,193 in 1,679 separate episodes"], ["Longest unbroken congested run", "10 blocks (5 minutes)"],
    ["Share of congestion in the busiest 5 of 93 days", "64 %"], ["Busiest single day", "11.2 % of its blocks above 80 %"],
  ], [5000, 4000]),
  ...Fig(path.join(FIG, "F1_congestion_over_time.png"), "F1 — block fill over the 92-day window, with the 80–90 % band shaded"),
  ...Fig(path.join(FIG, "F2_fill_distribution.png"), "F2 — distribution of block fill"),
  P("Congestion is real but **rare and interleaved, never sustained**. A batcher never faces a run of blocks it cannot enter, only isolated ones it can wait out. Gate B binds on a 30-order batch only above about 89 % fill — roughly one block in 180. An early version of F1 plotted 5-minute maxima, which painted the series at 100 % for any window containing a single full block and read as hours of saturation; the episode measurement contradicted it, and the figure now plots range and median."),
  ...Callout("Reframing (ADR-008)", [
    "The problem that is real is **concurrency, not congestion**. The pool lock binds on every batch regardless of how full blocks are. The project was reframed accordingly, following a fallback pre-authorised in the risk register; the objective and goals G1–G6 were unchanged. The congestion measurement is retained as a first-class empirical result about the chain.",
  ]),
  P("The size-based fill is a valid proxy for execution-unit fill: correlation is **0.912** in the congested sample, 0.588 in the quiet one (where half the blocks run no scripts) and 0.852 pooled. Execution steps never exceeded 49.9 % of the block budget in 17,280 sampled blocks."),
  H2("8.2 Predictability of Congestion"),
  ...Tbl("Predictability on the full window", ["Measure", "Value"], [
    ["Autocorrelation at lag 1 / 5 / 20", "0.372 / 0.322 / 0.272"],
    ["MAE, lag-1 persistence", "0.06069"], ["MAE, global mean", "0.06065"], ["MAE, rolling mean (k = 20)", "0.05157 — 15.0 % better than the global mean"],
  ], [4500, 4500]),
  P("Lag-1 persistence ties the global mean, yet a rolling mean beats it by 15 % and autocorrelation persists to lag 20. On a spiky right-skewed series scored by MAE, persistence copies each spike forward and is penalised twice, while smoothing is not. The series has exploitable structure — at the level of slowly varying congestion, not individual spikes."),
  H2("8.3 Forecaster Results"),
  ...Tbl("Forecaster performance on the test split (58,316 rows, touched once)", ["Model", "MAE", "RMSE", "Directional accuracy"], [
    ["**P1 LightGBM**", "**0.04578**", "0.08364", "**0.742**"], ["E4 moving average", "0.05157", "**0.08355**", "0.710"],
    ["Global mean", "0.06065", "0.08867", "0.662"], ["Lag-1 persistence", "0.06069", "0.10044", "0.000"],
  ], [3000, 2000, 2000, 2000]),
  ...Fig(path.join(FIG, "F4_forecast_vs_actual.png"), "F4 — forecast against actual fill on a test window"),
  P("**S1 passes**: LightGBM beats E4 by 11.2 % in MAE and 3.1 points in directional accuracy, though E4 is marginally better on RMSE, as expected from training on an L1 objective. The pass does not mean what it appears to: the forecast correlates **0.399** with the value it predicts and **0.616** with the value before it. It is a smoothed lag that learns the level of congestion and exploits mean reversion, but never anticipates a spike — and spikes are all that Gate B cares about."),
  H2("8.4 Amortization Curve"),
  P("Figure F3 (Section 5.4) shows per-user cost falling from 0.407 ADA for a single order to 0.092 ADA at *n* = 10 and 0.071 ADA at the Gate A cap of 24. Beyond about 15 orders a policy pays latency for a saving that has already flattened out, which is why the latency-optimal and cost-optimal policies sit at opposite ends of a frontier rather than at one point."),
  H2("8.5 Policy Comparison"),
  P("Tables 8.4–8.6 give the median over 100 paired test episodes with its 95 % bootstrap confidence interval for the primary metrics. L-p95 and L-mean are in slots, C-user in lovelace, TP in orders settled per 1,000 slots. P2 with N_MIN = 1 was byte-identical to greedy on every metric at every rate and is shown as one row."),
  ...Tbl("Test split, matched arrival rate", ["Policy", "L-mean", "L-p95 [95 % CI]", "C-user [95 % CI]", "X-rate", "TP", "F-jain"], [
    ["NULL (deadline only)", "116.7", "191.0 [188.0, 193.0]", "79,451 [79,341, 79,580]", "0.00", "117.2", "0.86"],
    ["E1 (M=16)", "106.0", "183.3 [183.0, 185.0]", "**82,906** [82,812, 83,001]", "0.00", "117.3", "**0.83**"],
    ["E2 (T=20)", "63.4", "130.5 [125.5, 137.0]", "129,729 [128,962, 131,007]", "0.00", "117.3", "0.78"],
    ["E3 greedy ≡ P2 (N=1)", "**55.8**", "**119.0** [117.2, 121.0]", "157,445 [156,022, 159,366]", "0.00", "**117.4**", "0.75"],
    ["P2 (D=120, N=4)", "60.9", "125.0 [123.0, 126.0]", "127,738 [125,776, 129,084]", "0.00", "117.3", "0.77"],
    ["P3 DQN, 5 seeds", "88.9", "158.6 [158.0, 160.0]", "89,704 [89,273, 92,374]", "0.00", "116.5", "**0.83**"],
    ["ORACLE (N=4)", "59.8", "124.0 [122.0, 125.0]", "124,567 [123,005, 125,696]", "0.00", "117.4", "0.76"],
  ], [2000, 900, 1700, 2100, 800, 800, 800]),
  ...Tbl("Test split, light arrival rate", ["Policy", "L-mean", "L-p95 [95 % CI]", "C-user [95 % CI]", "X-rate", "TP", "F-jain"], [
    ["NULL (deadline only)", "114.1", "188.0 [187.0, 189.8]", "97,556 [97,156, 99,099]", "0.00", "58.2", "0.86"],
    ["E1 (M=16)", "107.7", "185.0 [183.4, 185.5]", "**99,080** [98,552, 100,436]", "0.00", "58.2", "0.84"],
    ["E2 (T=20)", "61.0", "123.0 [122.0, 124.0]", "184,974 [183,392, 190,218]", "0.00", "58.3", "0.79"],
    ["E3 greedy ≡ P2 (N=1)", "**56.5**", "**120.6** [119.0, 122.0]", "210,933 [209,227, 215,863]", "0.00", "58.3", "0.75"],
    ["P2 (D=120, N=4)", "67.8", "140.0 [139.0, 141.9]", "158,255 [156,602, 164,282]", "0.00", "58.3", "0.77"],
    ["P3 DQN, 5 seeds", "97.9", "170.5 [169.4, 171.1]", "117,670 [116,359, 121,019]", "0.00", "58.2", "**0.85**"],
    ["ORACLE (N=4)", "64.2", "133.3 [132.0, 135.0]", "154,965 [153,372, 157,793]", "0.00", "58.3", "0.76"],
  ], [2000, 900, 1700, 2100, 800, 800, 800]),
  ...Tbl("Test split, heavy arrival rate", ["Policy", "L-mean", "L-p95 [95 % CI]", "C-user [95 % CI]", "X-rate", "TP", "F-jain"], [
    ["NULL (deadline only)", "132.3", "260.0 [212.5, 363.0]", "72,098 [72,066, 72,153]", "0.00", "236.0", "0.81"],
    ["E1 (M=16)", "253.5", "1,202.8 [851.0, 1,466.0]", "**78,638** [78,612, 78,650]", "0.00", "234.9", "0.38"],
    ["E2 (T=20)", "88.7", "253.5 [192.0, 342.0]", "95,427 [94,849, 95,861]", "0.00", "236.1", "0.62"],
    ["E3 greedy ≡ P2 (N=1)", "**66.2**", "**162.0** [128.0, 234.0]", "116,556 [114,987, 117,637]", "0.00", "**236.2**", "0.66"],
    ["P2 (D=120, N=4)", "68.0", "164.5 [129.0, 234.0]", "103,022 [101,644, 104,387]", "0.00", "**236.2**", "0.67"],
    ["P3 DQN, 5 seeds", "220.9", "863.3 [444.0, 925.7]", "85,187 [80,508, 96,383]", "0.07 [0.03, 0.10]", "214.0", "**0.68**"],
    ["ORACLE (N=4)", "67.9", "161.5 [129.0, 234.0]", "101,506 [100,807, 102,353]", "0.00", "236.2", "0.67"],
  ], [2000, 900, 1700, 2100, 800, 800, 800]),
  P("Bold marks the best value among non-reference policies. **NULL** is labelled “deadline only” because in the final environment it never chooses to submit, but the environment forces a submission once the oldest order reaches D_MAX; it therefore behaves as pure deadline batching, which is why it settles orders at all."),
  P("Three patterns hold across the tables. **Greedy has the lowest latency at every rate**, and E1 the lowest cost among the non-reference policies. **No policy expires orders** except P3 at the heavy rate. And **E1, tuned at the matched rate, collapses at the heavy rate** — tail latency of 1,203 slots and fairness 0.38 — which is precisely the over-fitting to a single arrival rate that the three-rate sweep was designed to expose."),
  ...Tbl("Paired differences on the test split — median of per-episode differences (candidate − reference) with 95 % bootstrap CI", ["Comparison", "Metric", "Light", "Matched", "Heavy"], [
    ["P2 (N=4) − greedy", "L-p95", "+19.0 [+18.2, +20.3] *", "+6.0 [+5.5, +6.0] *", "+1.0 [0.0, +1.0]"],
    ["P3 − greedy", "L-p95", "+50.2 [+49.4, +50.8] *", "+40.2 [+39.4, +41.1] *", "+547.2 [+31.7, +591.0] *"],
    ["P2 (N=4) − E2", "L-p95", "+17.0 [+15.0, +18.0] *", "−5.1 [−14.5, +0.5]", "−60.5 [−74.0, −41.0] *"],
    ["P2 (N=4) − E2", "C-user", "−28,120 [−30,797, −25,968] *", "−2,894 [−3,442, −2,112] *", "+7,441 [+7,087, +7,903] *"],
    ["P3 − E1", "L-p95", "−14.2 [−14.7, −13.5] *", "−23.2 [−24.6, −22.2] *", "−392.2 [−714.6, −95.0] *"],
    ["P3 − E1", "C-user", "+18,509 [+17,603, +20,584] *", "+6,884 [+6,385, +8,530] *", "+6,547 [+1,880, +17,776] *"],
    ["P3 − E2", "C-user", "−68,378 [−71,805, −66,362] *", "−40,500 [−41,662, −40,051] *", "−8,479 [−14,432, +2,232]"],
    ["ORACLE − P2 (N=4)", "L-p95", "−7.0 [−7.2, −6.0] *", "−1.0 [−1.0, −1.0] *", "0.0 [0.0, 0.0]"],
  ], [1900, 900, 2100, 2100, 2000]),
  P("* significant: Wilcoxon signed-rank with Holm–Bonferroni adjustment within its family, adjusted p < 0.05 **and** a confidence interval excluding zero. The comparisons against greedy are the pre-registered family (every proposed policy against the best static baseline on each primary metric); the others are a supplementary family chosen to locate each policy on the frontier. Negative is better for both metrics."),
  P("For context, the validation split (matched arrival rate, ten paired episodes) swept P2’s minimum batch size and traced this frontier, which is what fixed the configurations evaluated above:"),
  ...Tbl("Validation frontier — P2 on LightGBM against tuned static baselines", ["Policy", "L-p95 (slots)", "C-user (lovelace)", "Mean batch", "Lock share"], [
    ["p2(N=1) ≡ greedy", "120.0", "160,439", "3.4", "0.69"], ["**p2(N=4)**", "**127.0**", "**127,469**", "4.9", "0.46"],
    ["p2(N=8)", "142.0", "113,604", "6.1", "0.37"], ["p2(N=12)", "156.0", "108,876", "6.7", "0.34"], ["p2(N=20)", "165.0", "106,920", "7.0", "0.32"],
    ["e2(T=20), tuned", "133.0", "131,593", "4.7", "0.50"], ["e1(M=16), tuned", "181.5", "82,986", "13.2", "0.17"],
  ], [2400, 1600, 2000, 1500, 1500]),
  P("**S2 — zero Gate A violations — passed** across every policy, arrival rate and episode, by construction. Tuning P2 on tail latency alone selects `p2(N=1)`, which is byte-identical to greedy: with Gate B binding about once in 180 blocks, nothing is left to decide. **On a chain where capacity does not bind, the latency-optimal batcher is greedy.** The informative artefact is therefore the frontier: `p2(N=4)` dominates the tuned `e2(T=20)` on both axes, and no static baseline dominates any P2 point."),
  H2("8.6 Pareto Analysis"),
  ...Fig(path.join(FIG, "F5_pareto.png"), "F5 — tail latency against per-user cost, test split, matched rate, with 95 % CIs on both axes"),
  P("At the matched rate the static and proposed policies do not collapse onto one line; they spread along a frontier running from greedy (fastest, most expensive) to E1 (cheapest, slowest). **P2 with N_MIN = 4 Pareto-dominates the tuned E2 by median** — 125.0 against 130.5 slots and 127,738 against 129,729 lovelace. Paired, the cost saving is significant (−2,894 lovelace) but the latency difference is not (−5.1 slots, CI [−14.5, +0.5]), so the defensible statement is that P2 is **cheaper and no slower** than E2, not strictly better on both axes. The dominance does not carry to the other rates: at the light rate E2 is 17 slots faster and P2 28,120 lovelace cheaper, and at the heavy rate P2 is 60.5 slots faster but 7,441 lovelace dearer — trade-offs, not dominance."),
  P("**P3 occupies an operating point no static rule reaches.** Against E1 it is significantly faster at every rate (23.2 slots at matched) for a modest extra cost (6,884 lovelace); against E2 it is 40,500 lovelace cheaper for 35.8 more slots. Nothing dominates it at the light or matched rate. The ORACLE point sits almost on top of P2: a perfect next-block forecast is worth 1 slot at the matched rate and nothing measurable at the heavy rate — the fourth independent confirmation that forecasting congestion has little to offer *latency* on this chain. Ablation A2 (Section 8.10) shows where a forecast does matter: in how cheaply P2 can buy larger batches."),
  P("The comparison of P3 against the whole P2 sweep below was made on validation; configurations N = 8, 12 and 20 were not carried into the one-shot test run, so that claim is not re-tested here."),
  ...Tbl("P3 (DQN) against the P2 frontier, validation split", ["Policy", "L-p95 (slots)", "C-user (lovelace)"], [
    ["e3(greedy) ≡ p2(N=1)", "114.0", "150,168"], ["p2(N=4)", "121.5", "116,759"], ["p2(N=8)", "131.0", "102,729"],
    ["p2(N=12)", "150.3", "98,062"], ["p2(N=20)", "156.3", "96,457"], ["**P3, mean of 5 seeds**", "**149.0 ± 13.1**", "**87,669 ± 6,211**"],
  ], [3600, 2700, 2700]),
  P("On validation, P3 dominated `p2(N=12)` and `p2(N=20)` on both axes and was dominated by nothing, reaching a per-user cost 9 % below any P2 configuration. It thus extends the achievable frontier, at a tenth of the specified training budget. Every seed produced zero Gate A violations and zero expired orders, and none collapsed. Seed variance is real: seed 0 behaves like a different policy (L-p95 123.5, mean batch 8.9 against about 13 for the others)."),
  H2("8.7 Latency Distributions"),
  ...Fig(path.join(FIG, "F6_latency_cdf.png"), "F6 — confirmation latency CDF, test split, matched rate"),
  P("F6 pools the settled orders of all 100 matched-rate episodes, so its p95 readings (greedy 118, P2 124, E2 143, P3 164 slots) are quantiles of the pooled distribution and differ slightly from the medians of per-episode p95 in Table 8.4. The curves of greedy, P2 and E2 nearly coincide across the whole distribution; the gain of P2 over E2 is a tail effect, consistent with the non-significant paired latency difference. P3’s curve is shifted right at every quantile — it waits deliberately to build larger batches, 11.1 orders on average against 4.9 for P2 — and it carries a thin long tail: 0.73 % of its orders wait more than 600 slots, up to 3,677, close to the 3,600-slot order lifetime. The quantile table behind the figure is written to `tables/F6_latency_quantiles.csv`."),
  H2("8.8 Does the Agent Adapt?"),
  ...Fig(path.join(FIG, "F7_action_distribution.png"), "F7 — P3 action distribution across congestion deciles"),
  P("F7 is not flat: the submit rate climbs from 7 % in the emptiest decile to 53 % in the fullest. On its own that would suggest congestion reasoning. It is not. Zeroing the forecast inputs at inference time changes L-p95 by a mean of only **2.3 %**, and four of five seeds are slightly *better* without the forecast. The rising profile is a queue-depth confound: fuller blocks coincide with busier periods, longer slot gaps and deeper queues."),
  ...Callout("Finding", [
    "**The agent is queue-aware, not congestion-aware.** This is the third independent route to the ADR-008 conclusion, after the F4 lag diagnostic and the ORACLE gap. Retraining the agent without the forecast (A3, Section 8.10) costs about 4 % of tail latency and nothing in cost — a small, consistent contribution from the forecast, not congestion reasoning.",
  ]),
  H2("8.9 Robustness Across Arrival Rates"),
  ...Fig(path.join(FIG, "F8_robustness.png"), "F8 — tail latency across arrival rates on one shared scale, test split"),
  P("At the light and matched rates every policy stays within a narrow band. At the heavy rate greedy (162.0) and P2 with N_MIN = 4 (164.5) barely move, E2 degrades to 253.5 slots and E1 to 1,203 — the two fixed rules tuned at one rate are the brittle ones. **The adaptive optimizer is the most robust policy across load**: it tracks greedy’s latency at every rate while costing 12–25 % less."),
  P("P3’s heavy-rate median of 863 slots is not the behaviour of the agent in general but of **one seed**. Seed 3 reaches a median tail latency of 3,604 slots and lets 34 % of orders expire, with expiry in 65 of 100 episodes; at the matched rate the same seed behaves normally. The other four seeds, pooled, give a tail latency of 186.5 slots [152.5, 253.9], **zero expiry**, fairness 0.77 and a per-user cost of 77,916 lovelace — cheaper than E1 (78,638) at a sixth of its tail latency. Checkpoints were selected on validation at the matched rate, and seed 3 was not distinguishable there, so this is reported as a genuine finding about training brittleness under the reduced budget rather than excluded after the fact."),
  H2("8.10 Ablations"),
  H3("A1 — what forecast error costs"),
  ...Tbl("P2 on LightGBM against P2 with the true next-block fill (validation)", ["N_MIN", "L-p95, forecast", "L-p95, oracle", "Gap"], [
    ["4", "127.0", "126.0", "0.8 %"], ["8", "142.0", "134.0", "5.6 %"], ["12", "156.0", "143.0", "8.3 %"], ["20", "165.0", "151.0", "8.5 %"],
  ], [2000, 2400, 2400, 2200]),
  P("A perfect forecast is worth 5–9 % of tail latency at equal cost, and the gap widens as the policy leans on the forecast."),
  H3("A2 — naive versus learned forecaster, re-specified"),
  P("As first run, A2 was confounded. P2 driven by E4 was identical to greedy at every N_MIN, because a moving average is flat across the forecast horizon and the “quieter block predicted” condition compares equal numbers, so it never fires. That compared a flat forecast with a varying one, not a naive forecast with a learned one."),
  P("A2 was therefore re-specified with a second naive baseline, **E4b (mean-reverting)**: `fill_hat(t+h) = m_t + φ^h · (fill_t − m_t)`, where `m_t` is E4’s 20-block rolling mean and φ the lag-1 autocorrelation of the deviation from it, fitted on the training split. It is as naive as E4 — one fitted number — but varies across the horizon. The configuration was committed before the run, and it used the same 12 validation episodes at the matched rate as the original Phase 4 ablations."),
  ...Tbl("Forecasters on the validation split — whether each can make P2’s quieter-block branch fire", ["Forecaster", "Branch fires", "MAE t+1", "Directional accuracy"], [
    ["E4 moving average (flat)", "**0.0 %**", "0.0586", "0.712"],
    ["E4b mean-reverting (φ = 0.084)", "36.2 %", "0.0582", "0.712"],
    ["P1 LightGBM", "67.4 %", "**0.0530**", "**0.740**"],
    ["ORACLE", "64.7 %", "0", "1.000"],
  ], [3300, 1900, 1900, 1900]),
  P("The zero for E4 confirms the confound directly. The fitted φ is small — deviations from the recent level barely persist — so E4b’s forecasts stay close to the level, but they still vary enough for the branch to fire on about a third of blocks."),
  ...Tbl("P2 by forecaster across N_MIN — median over 12 paired validation episodes (L-p95 slots / C-user lovelace)", ["N_MIN", "E4b naive", "P1 LightGBM", "ORACLE", "E4 flat"], [
    ["1", "120.5 / 151,557", "120.5 / 151,557", "120.0 / 151,557", "120.5 / 151,557"],
    ["4", "123.5 / 137,596", "127.0 / 120,945", "124.5 / 120,608", "120.5 / 151,557"],
    ["8", "134.3 / 127,523", "142.5 / 108,672", "135.0 / 108,217", "120.5 / 151,557"],
    ["12", "143.4 / 124,229", "156.5 / 103,841", "143.5 / 103,184", "120.5 / 151,557"],
    ["20", "149.5 / 122,915", "165.5 / 101,747", "148.5 / 101,064", "120.5 / 151,557"],
  ], [1000, 2000, 2000, 2000, 2000]),
  ...Tbl("A2 — P2 on LightGBM minus P2 on E4b, paired over 12 episodes, Holm–Bonferroni across the family", ["N_MIN", "L-p95 difference [95 % CI]", "C-user difference [95 % CI]"], [
    ["1", "0.0 [0.0, 0.0]", "0 [0, 0]"],
    ["4", "+2.0 [+1.5, +3.0] *", "−17,186 [−20,785, −14,489] *"],
    ["8", "+7.2 [+6.0, +9.0] *", "−21,348 [−25,858, −17,395] *"],
    ["12", "+13.0 [+10.4, +15.7] *", "−22,582 [−27,817, −18,148] *"],
    ["20", "+15.0 [+12.0, +18.5] *", "−23,332 [−28,872, −18,627] *"],
  ], [1400, 3800, 3800]),
  P("**At equal N_MIN the two forecasters do not produce a better and a worse policy; they produce different operating points.** LightGBM lets the branch fire about twice as often, so P2 waits more, builds batches 26–47 % larger, and trades 2–15 slots of tail latency for 17,000–23,000 lovelace less per user — every difference significant. Equal N_MIN is therefore not a like-for-like comparison, and the question A2 asks is answered by the frontier instead."),
  P("**On the frontier, the learned forecaster helps the policy.** LightGBM at N_MIN = 4 (127.0 slots, 120,945 lovelace) is at least as fast and cheaper than E4b at N_MIN = 8, 12 and 20, so it dominates three of E4b’s five points; no LightGBM point is dominated by E4b. E4b cannot reach below about 123,000 lovelace at any setting, because its weak reversion rarely justifies a long wait, while LightGBM reaches 101,747. LightGBM also matches ORACLE on per-user cost at every N_MIN, to within 0.7 %; its gap to ORACLE is in tail latency (up to 17 slots at N_MIN = 20), consistent with the lagging forecast of F4."),
  P("The answer to A2 is therefore **yes, but only for cost**: a learned forecaster lets P2 buy larger batches more cheaply than a naive one, while contributing nothing to latency — the same division A1, A3 and the test-split ORACLE gap each point to. The frontier comparison rests on medians over 12 validation episodes and is descriptive; the equal-N_MIN paired tests are the formal result."),
  H3("A3 and A4 — agent ablations"),
  P("Both ablations retrain five DQN seeds from scratch with the Phase 5 configuration — 200,000 steps, the same training windows and reward calibration — changing one thing each: **A3** removes the forecast from the state (the three `fill_hat` inputs are constant zero), and **A4** replaces the quadratic latency penalty with a linear one, recalibrated to unit scale. All ten agents are scored through the standard metric path on the same four validation episodes as Phase 5; the test split is not used again."),
  ...Tbl("Ablations A3 and A4 against the Phase 5 agent, per seed, validation split", ["Seed", "L-p95 P3", "L-p95 A3", "L-p95 A4", "C-user P3", "C-user A3", "C-user A4"], [
    ["0", "123.5", "134.5", "120.5", "99,886", "97,643", "105,808"],
    ["1", "157.5", "170.0", "169.5", "83,869", "88,197", "84,495"],
    ["2", "152.0", "156.5", "147.0", "84,089", "82,843", "84,104"],
    ["3", "152.0", "154.0", "152.0", "86,786", "85,285", "87,122"],
    ["4", "160.0", "160.5", "155.0", "83,717", "83,147", "86,219"],
    ["**Mean ± sd**", "**149.0 ± 13.1**", "**155.1 ± 11.7**", "**148.8 ± 16.0**", "**87,669 ± 6,211**", "**87,423 ± 5,457**", "**89,550 ± 8,204**"],
  ], [1300, 1200, 1200, 1200, 1400, 1400, 1300]),
  P("Every one of the ten agents produced zero Gate A violations and zero expired orders, and none collapsed (action entropy 0.30–0.97)."),
  P("**A3 — the forecast contributes a little, and only to latency.** Retrained without a forecast, the agent’s tail latency is 4.1 % higher on average (155.1 against 149.0 slots) at an unchanged per-user cost (−0.3 %). The direction is consistent — all five seeds are slower without the forecast, by 0.5 to 12.5 slots — but the mean effect is smaller than the seed-to-seed standard deviation and rests on four validation episodes, so it is suggestive rather than established. The retrained result reverses the sign of the inference-time test in Section 8.8, where zeroing the forecast on an agent trained with it made four of five seeds slightly faster; the retrained comparison is the one the protocol specifies, because an agent trained with the input has never learned to act without it. Either way the effect is a few percent: the verdict remains **queue-aware**, with the forecast as a minor secondary input."),
  P("**A4 — the quadratic penalty is not what controls the tail.** With a linear latency penalty, tail latency is unchanged (148.8 against 149.0 slots) and per-user cost is 2.1 % higher, both well inside seed variation. The tail is already bounded structurally by the D_MAX mask, which forbids waiting past the deadline, so reshaping the latency term leaves little for the reward to do. The quadratic form is retained as specified, but the report does not credit it with the agent’s tail behaviour."),
  H3("A5 — estimation error against Gate A"),
  ...Tbl("Effect of estimation error, validation split at heavy arrival rate (21,359 batches)", ["True cost vs estimate", "Real Gate A cap", "Invalid batches"], [
    ["−10 %, −5 %, 0 %", "24", "0"], ["**+5 %**", "22", "**8.1 %**"], ["**+10 %**", "21", "**8.2 %**"],
  ], [3000, 3000, 3000]),
  P("S2’s zero is exact only under perfect estimation. Over-estimation is harmless, but a 5 % under-estimate invalidates about one batch in twelve, because heavy-rate batches sit at the cap. A **safety margin of three orders** below the estimated cap would have kept every batch valid and should be applied in live operation until the estimator is calibrated. The fee replay already showed under-estimation on script-bearing transactions, so this direction of error is not hypothetical."),
  H2("8.11 Success Metrics"),
  ...Tbl("Success metrics S1–S6", ["ID", "Criterion", "Measured", "Verdict"], [
    ["S1", "P1 MAE below E4 on test", "0.04578 vs 0.05157 (+11.2 %)", "Pass"],
    ["S2", "Zero Gate A violations", "0 across 8 policies × 3 rates × 100 episodes, P3 over 5 seeds", "Pass"],
    ["S3", "L-p95 below best static baseline, significant", "Best static on L-p95 is greedy at every rate. P2 (N=1) identical (diff 0); P2 (N=4) +6.0 slots; P3 +40.2 slots (matched)", "Fail at all rates"],
    ["S4", "Expiry not worse than baseline", "P2 zero at all rates; P3 zero at light and matched, 0.07 [0.03, 0.10] at heavy (one seed)", "Pass for P2; P3 fails at heavy"],
    ["S5", "Pareto dominance on (L-p95, C-user)", "P2 (N=4) dominates E2 by median at matched (latency difference not significant); none at light or heavy", "Partial — matched only"],
    ["S6", "Fairness not worse than baseline", "P3 0.85 / 0.83 / 0.68 overlaps or exceeds best static; P2 (N=4) 0.77 vs E1 0.84 / 0.83 at light / matched", "Pass for P3; P2 fails at light and matched"],
  ], [700, 2600, 4000, 1700]),
  P("Read together, the verdicts describe a **trade-off result, not a dominance result**. The one safety criterion, S2, holds without exception. The latency criterion S3 fails for a reason the data predicted: Phase 1 found capacity binding about once in 180 blocks, and in a system where capacity does not bind the latency-optimal batcher is greedy, which no policy can beat by waiting. What the adaptive policies deliver instead is controllable movement along the latency–cost frontier — robustly for the optimizer, with a better fairness profile but seed-level brittleness for the learned agent. S3 failing while S2 holds is, in the evaluation protocol’s own terms, a publishable outcome stated rather than hidden."),
  H2("8.12 On-Chain Demonstration"),
  ...Callout("Status", [
    "**The DEX is deployed on the Cardano preprod test network and has settled its first end-to-end swap (T-O6).** A user order was placed from a separate key, the live batcher running P2 found it on chain, submitted a batch, held the pool lock until inclusion, and stopped cleanly; the result was verified on chain. Every submission was made only with the team’s explicit approval. The D4 calibration rests on this single one-order batch and is reported as a first measurement, not a calibration.",
  ]),
  ...Tbl("Preprod deployment", ["Item", "Value"], [
    ["Deployment transaction", "`555ee19bd06d2151931035039dac883b560d9f93bb35b3fd1efa24a30f767372`"],
    ["Block / slot", "5,178,709 / 133,767,575"],
    ["Network fee", "181,913 lovelace (0.18 tADA), 603 bytes"],
    ["Minted", "10,000,000 TEAM11 and one POOL NFT; minting closed after slot 133,774,747"],
    ["Pool, verified on chain", "100 tADA + 1,000,000 TEAM11 + 1 POOL NFT, inline datum equal to the recorded deployment (fee 30 bps)"],
    ["Pool script hash", "`2c9aee89dbbc6c7e30f720c2e0e76d7850b1eaf1bb5b53a517a96475`"],
    ["Order script hash", "`1676fbd256ca880594c30dc1e024439748dca693788786ac54f98567`"],
  ], [2600, 6400]),
  P("**The first live read found a defect the offline tests could not.** Blockfrost returns inline datums as raw CBOR bytes, whereas locally built outputs carry typed Plutus data. The order reader handled only the latter, so every real order would have been treated as undecodable and silently skipped: the live batcher would have watched an apparently empty queue indefinitely. It was caught while verifying the deployed pool’s datum, before any order was placed, fixed, and pinned with a regression test that feeds the builders datums in the form Blockfrost delivers them."),
  ...Tbl("The first end-to-end swap on preprod, verified on chain", ["Item", "Value"], [
    ["Order transaction", "`6ffd8101fa74be32c6729f255b7f29e5f6b11edab050d3fc0f07c220a525ac41`"],
    ["Order", "Sell 10 tADA for at least 85,000 TEAM11; margin 1 tADA; 15 tADA locked"],
    ["Batch transaction", "`b5201c0a0843f5e258a7c9d9dba4b9b7cb66f88f1c0810baa2e6ad7337c73af1`"],
    ["Submitted → included", "slot 133,785,075 → slot 133,785,125 (block 5,179,501): 50 slots with the pool locked"],
    ["Network fee", "322,697 lovelace, 2,681 bytes"],
    ["User received", "90,661 TEAM11 and 3.679758 tADA, in an output tagged with the order’s reference"],
    ["User’s charge", "1 tADA margin + 0.320242 tADA fee share (n = 1) — at or below the 322,697-lovelace fee the transaction carries, as `order.ak` requires"],
    ["Pool after", "110 tADA and 909,339 TEAM11, NFT carried; no orders left at the order script"],
  ], [2600, 6400]),
  P("**The first live batch then found a second defect** — and the order validator caught it. The batch was planned with the estimator’s fee of 406,931 lovelace, but the real fee was 320,242; users were therefore overcharged, and `order.ak` refused the transaction during the node’s script evaluation. The fee-settling loop of Section 6.12 could not recover, because evaluation happens *inside* the build, before any fee is known. Nothing was submitted: the order stayed safely at its script. The builder now works in two passes — a probe charging margins only, which is valid at any fee, to obtain execution units, then a final build with those units fixed and users charged for the real fee — and the daemon logs a failed build instead of stopping. A fake chain that enforces the fee rule during evaluation reproduces the failure and pins the fix. **The validator doing exactly its job against the project’s own batcher is the clearest evidence in the report that the batcher is untrusted for correctness by design.**"),
  P("The demonstration is scripted as five steps, each a dry run until explicitly submitted: deploy the pool and mint its NFT; run the batcher in shadow mode to confirm its decisions on live chain state; place an order from a separate user key; run the batcher live until that order settles; and compare estimated with actual transaction size and execution units from the D4 log."),
  ...Tbl("Phase 7 exit criteria", ["Criterion", "Status"], [
    ["T-O1 … T-O5, including the security tests T-O2 and T-O3", "Pass — Aiken unit tests"],
    ["T-O6 — one swap settles on preprod, transaction hash recorded", "Pass"],
    ["Estimator within ±5 % on size and ±10 % on execution units against D4", "Not met on the one sample — see the calibration table below"],
    ["`07-CONSTRAINTS-COST-MODEL.md` §4 per-order costs updated from measurement", "Not yet — needs multi-order batches"],
  ], [6000, 3000]),
  ...Tbl("First estimator calibration against D4 — one batch, n = 1", ["Quantity", "Estimated", "Actual", "Error"], [
    ["Transaction size", "800 B", "2,682 B", "actual 3.4× the estimate"],
    ["Execution memory", "2,500,000", "473,756", "estimate 5.3× the actual"],
    ["Execution steps", "1,000,000,000", "166,037,580", "estimate 6.0× the actual"],
    ["Network fee", "406,931 lovelace", "322,697 lovelace", "estimate 26 % high"],
  ], [2400, 2200, 2200, 2200]),
  P("The ±5 % / ±10 % criterion is **not met**, and one one-order batch could not calibrate per-order costs even if it were — the flat and marginal components cannot be separated from a single `n`. The direction of each error is nonetheless informative. **Execution units are over-estimated about fivefold**, the safe direction for Gate A: the simulator’s cap of 24 orders is conservative on memory, which ADR-006 had feared the on-chain `fee / n` computation would tighten. **Size is under-estimated 3.4-fold**, the unsafe direction — ablation A5 showed a 5 % size under-estimate already invalidates one heavy-rate batch in twelve. The cause is known: the estimator models order and pool bytes but not the roughly 1.8 KB of validator scripts attached to every batch, nor the batcher’s fee input and change output. Referencing the scripts from an on-chain UTxO instead of attaching them removes most of the gap, and multi-order live batches are then needed to fit the marginal cost per order. Until that is done, live batch sizes should be capped with the A5 safety margin."),
  H2("8.13 Threats to Validity"),
  ...Tbl("Threats to validity and their mitigation", ["Threat", "Mitigation and residual risk"], [
    ["Synthetic order arrivals", "Diurnal shape fitted to real D1 transaction counts; sweep across three arrival rates. Absolute latencies depend on the modelled rate"],
    ["Counterfactual injection into recorded blocks", "Recorded usage treated as fixed background; conservative direction"],
    ["No transaction chaining", "Pool lock stricter than reality; measured latency is an upper bound"],
    ["Perfect estimation assumed", "Bounded by A5: a 5 % under-estimate invalidates 8 % of heavy-rate batches"],
    ["Fee model omits the reference-script surcharge", "Absolute costs understated; rankings unaffected (V4)"],
    ["Reduced RL training budget", "200k instead of 2M steps; P3 results are a lower bound"],
    ["Overfitting to the test period", "Chronological split enforced by test; test split used exactly once"],
    ["Straw-man baselines", "E1 and E2 tuned on validation; values reported"],
    ["Single-seed RL result", "Five seeds; mean and standard deviation reported"],
    ["Cherry-picked episodes", "Fixed paired episode set, 25 % congested share, fixed before evaluation"],
    ["Code provenance of manifests", "Earlier experiments ran from uncommitted code, so their manifests record the parent revision. The test run was launched before its tooling was committed, and its manifest records the revision current when it finished (0a5c7d5, clean tree), not at launch; the evaluated source is believed identical apart from automatic formatting, but the manifest cannot prove it. Data and parameters are pinned by checksum and configuration hash. It is stated rather than re-run, since re-running would spend the test split twice"],
    ["Checkpoint selection at one arrival rate", "P3 checkpoints were chosen on validation at the matched rate; one of five seeds fails at the heavy rate. Reported with all five seeds included"],
    ["Rollback asymmetry", "Simulator models rollback (p = 0.0005 per block); the RL training environment does not"],
  ], [3200, 5800]),
);

// Chapter 9
add(
  Chapter(9, "Conclusion and Future Work"),
  H2("9.1 Summary of Contributions"),
  N("**A measured characterisation of Cardano mainnet block occupancy** over 92 days and 388,781 blocks, showing that the widely repeated 80–90 % congestion claim does not describe the current chain: median fill is 2.95 %, and the longest congested run is ten blocks.", "contrib"),
  N("**A corrected constraint and cost model** for eUTXO batching: batch size bounded by per-transaction limits rather than block capacity; latency and amortized cost, not fees, as the objective; head-of-line blocking rather than rejection as the failure model — each guarded by a permanent regression test.", "contrib"),
  N("**A validated, deterministic, slot-accurate simulator** that replays recorded mainnet blocks, with paired episodes, conservation checks and four validation checks including a fee replay against real transactions.", "contrib"),
  N("**A constrained optimizer and a masked DQN agent** that never violated a capacity limit, together with an honest analysis showing what drives their behaviour.", "contrib"),
  N("**A reproducible evaluation pipeline** with run manifests, checksummed data and pre-registered non-parametric statistics.", "contrib"),
  N("**A minimal on-chain DEX whose validator enforces a pass-through batcher fee**, so amortization reaches users, with each user’s slippage floor and batcher authorisation checked by the ledger; and a live batcher that reuses the simulator’s own decision rules, with a shadow mode for watching a policy on live traffic before it submits.", "contrib"),
  H2("9.2 Objectives Revisited"),
  ...Tbl("Goals G1–G6 against the evidence", ["Goal", "Status", "Evidence"], [
    ["G1 Reduce mean and p95 latency vs static batchers", "Partially achieved", "Not against greedy, which is latency-optimal when capacity rarely binds (S3 fails). P2 (N=4) is 60.5 slots faster than tuned E2 at heavy load; P3 is significantly faster than E1 at every rate"],
    ["G2 Reduce per-user cost by amortization", "Achieved, as a trade-off", "Test, matched rate: P2 (N=4) −19 % and P3 −43 % per-user cost against greedy, for +5 % and +33 % tail latency; E1 remains cheapest"],
    ["G3 Never violate capacity limits", "Achieved, with a stated condition", "Zero Gate A violations across the whole test evaluation; exact only under perfect estimation (A5)"],
    ["G4 No order starves", "Partially achieved", "No decision past D_MAX results in WAIT; the wait itself can overshoot D_MAX by up to 114 slots"],
    ["G5 Reproducible evaluation", "Partially achieved", "Seeds, checksums and configuration hashes pinned; all five P3 checkpoints reproduce their recorded metrics exactly (T-L5); earlier manifests record the parent code revision"],
    ["G6 No change to wallets, CIP-30 or protocol", "Achieved", "The batcher interacts only with order UTXOs on chain"],
  ], [2900, 2000, 4100]),
  H2("9.3 Limitations"),
  B("**Single pool, single batcher** — multi-pool scheduling is a different and harder problem."),
  B("**Modelled order arrivals** — no DEX publishes per-order data; mitigated by fitting to D1 and sweeping three rates."),
  B("**No transaction chaining** — conservative, but real batchers can exploit it."),
  B("**Estimator not yet calibrated against live transactions** — per-order costs are estimates, and the fee formula omits the reference-script surcharge."),
  B("**Under-trained and brittle agent** — P3 was trained at a tenth of the specified budget, and one of five seeds fails under heavy load."),
  B("**One live batch is not a calibration** — the end-to-end swap settled on preprod, but a single one-order batch cannot separate flat from per-order costs, and the estimator under-estimates transaction size 3.4-fold while scripts are attached inline."),
  B("**No latency gain over greedy** — on the current chain no adaptive policy beat greedy on tail latency; the benefit is cost and fairness at a stated latency price."),
  B("**Replay of the recent past** — Ouroboros Leios and changing activity will alter block dynamics."),
  H2("9.4 Future Work"),
  B("Checkpoint selection across all three arrival rates, the full 2M-step training budget, and seed ensembling to remove the heavy-load failure of a single seed."),
  B("Transaction chaining, relaxing the pool lock (simulator assumption A3)."),
  B("Joint, end-to-end training of forecaster and policy, or giving the agent raw history instead of a forecast."),
  B("Multi-pool scheduling across a DEX."),
  B("Fairness-aware and MEV-resistant order selection."),
  B("Re-evaluation under Ouroboros Leios block dynamics, and on a historical window with sustained congestion."),
  B("Heterogeneous order costs, already supported by the dataset schema."),
  B("Calibrate the estimator from multi-order live batches on preprod, separating flat from per-order size and execution costs, and fold in the reference-script fee term."),
  B("Reference scripts for the validators, removing roughly 1.8 KB of script bytes from every batch transaction and so raising the Gate A cap."),
  B("The LightGBM forecaster in the live loop, which ablation A2 found lets P2 buy larger batches more cheaply than a naive forecast."),
  H2("9.5 Concluding Remarks"),
  P("This project set out to build an AI batcher that predicts congestion. Measurement showed that the congestion it was meant to predict is almost absent from the current chain, while the constraint that makes batching hard — a pool that admits one batch at a time — is present on every block. Reframing around that constraint, and following the evidence where it led, produced results that are more modest in headline but considerably more defensible: a batcher that never breaks a ledger rule, a clear latency–cost frontier that adaptive policies extend, and an honest account of what the learned agent does and does not use. On held-out data the adaptive policies did not beat greedy batching on latency — the expected consequence of capacity that rarely binds — but they gave an operator a controllable, statistically characterised trade-off between latency and per-user cost, and the optimizer held that trade-off across traffic levels at which the fixed rules tuned for one level broke down."),
);

// References
add(
  H1("References"),
  ...[
    "M. M. T. Chakravarty, J. Chapman, K. MacKenzie, O. Melkonian, M. Peyton Jones, and P. Wadler, “The Extended UTXO Model,” in Financial Cryptography and Data Security (FC 2020) Workshops, Springer, 2020.",
    "M. M. T. Chakravarty et al., “Native Custom Tokens in the Extended UTXO Model,” in ISoLA 2020, Springer, 2020.",
    "A. Kiayias, A. Russell, B. David, and R. Oliynykov, “Ouroboros: A Provably Secure Proof-of-Stake Blockchain Protocol,” in CRYPTO 2017, Springer, pp. 357–388.",
    "Input Output Research, “Ouroboros Leios: Design Goals and Concepts,” technical report.",
    "H. Nguyen Quang, “Concurrent & Deterministic Batching on the UTXO Ledger,” MELD technical report, 2021.",
    "P. Brühwiler, “A Concurrent DEX on Cardano: How to Write Scalable Apps on a UTXO Blockchain,” BSc thesis, University of Bern, 2021.",
    "O. Hryniuk, “Concurrency and all that: Cardano smart contracts and the EUTXO model,” IOHK, 2021.",
    "G. Angeris and T. Chitra, “Improved Price Oracles: Constant Function Market Makers,” in ACM AFT ’20, 2020, pp. 80–91.",
    "G. Angeris, H.-T. Kao, R. Chiang, C. Noyes, and T. Chitra, “An Analysis of Uniswap Markets,” Cryptoeconomic Systems, 2020.",
    "T. Roughgarden, “Transaction Fee Mechanism Design for the Ethereum Blockchain: An Economic Analysis of EIP-1559,” arXiv:2012.00854, 2020.",
    "“SoK: Preventing Transaction Reordering Manipulations in Decentralized Finance,” arXiv:2203.11520, 2022.",
    "R. S. Sutton and A. G. Barto, Reinforcement Learning: An Introduction, 2nd ed. MIT Press, 2018.",
    "V. Mnih et al., “Human-level Control through Deep Reinforcement Learning,” Nature, vol. 518, pp. 529–533, 2015.",
    "J. Schulman, F. Wolski, P. Dhariwal, A. Radford, and O. Klimov, “Proximal Policy Optimization Algorithms,” arXiv:1707.06347, 2017.",
    "H. Mao, M. Alizadeh, I. Menache, and S. Kandula, “Resource Management with Deep Reinforcement Learning,” in ACM HotNets ’16, 2016, pp. 50–56.",
    "H. Mao, M. Schwarzkopf, S. B. Venkatakrishnan, Z. Meng, and M. Alizadeh, “Learning Scheduling Algorithms for Data Processing Clusters,” in ACM SIGCOMM ’19, 2019, pp. 270–288.",
    "S. Hochreiter and J. Schmidhuber, “Long Short-Term Memory,” Neural Computation, vol. 9, no. 8, pp. 1735–1780, 1997.",
    "Cardano Foundation, “Protocol parameters guide,” docs.cardano.org.",
    "Koios, “Koios API documentation,” api.koios.rest.",
  ].map((r, i) => new Paragraph({ children: [new TextRun({ text: `[${i + 1}]  `, font: FONT, bold: true }), ...runs(r)], spacing: { after: 100, line: 300 }, indent: { left: 540, hanging: 540 } })),
  P("[[EDIT: verify every entry against the publisher before submission]]"),
);

// =====================================================================================
const doc = new Document({
  creator: "Team 11",
  title: "AI-Driven Adaptive Transaction Batching for Cardano Decentralized Exchanges",
  features: { updateFields: true },
  styles: {
    default: { document: { run: { font: FONT, size: 24 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: FONT, color: ACCENT }, paragraph: { spacing: { before: 240, after: 240 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: FONT }, paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1, keepNext: true } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, italics: true, font: FONT }, paragraph: { spacing: { before: 160, after: 80 }, outlineLevel: 2, keepNext: true } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "contrib", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ],
  },
  sections: splitSections(content),
});

// Wide diagrams sit on their own landscape pages; everything else is portrait.
function splitSections(items) {
  const footer = () => ({ default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 20 })] })] }) });
  const margin = { top: 1440, right: 1440, bottom: 1440, left: 1440 };
  const portrait = (children) => ({ properties: { page: { size: { width: 11906, height: 16838 }, margin } }, footers: footer(), children });
  const land = (children) => ({ properties: { page: { size: { width: 11906, height: 16838, orientation: PageOrientation.LANDSCAPE }, margin } }, footers: footer(), children });
  const sections = [];
  let run = [], group = [];
  const flushGroup = () => { if (group.length) { sections.push(land(group)); group = []; } };
  for (const item of items) {
    if (item && item.__landscape) {
      if (run.length) { sections.push(portrait(run)); run = []; }
      group.push(...item.__landscape);
    } else {
      flushGroup();
      run.push(item);
    }
  }
  flushGroup();
  if (run.length) sections.push(portrait(run));
  return sections;
}

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log("wrote", OUT, buf.length, "bytes"); });
