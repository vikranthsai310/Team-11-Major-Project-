"use strict";

/* ---------- helpers ---------- */
const $ = (sel, root = document) => root.querySelector(sel);
const NS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs = {}, parent = null, text = null) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== null) node.textContent = text;
  if (parent) parent.appendChild(node);
  return node;
}
function htmlEl(tag, attrs = {}, text = null) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== null) node.textContent = text;
  return node;
}
const nf = new Intl.NumberFormat("en-US");
const num = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (v, d = 1) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(d)} %`);
const ada = (lovelace, d = 3) => (lovelace === null || lovelace === undefined ? "–" : `${(lovelace / 1e6).toFixed(d)} ADA`);
const secs = (s) => (s === null || s === undefined ? "–" : `${nf.format(Math.round(s))} s`);
const hms = (s) => {
  const t = Math.max(0, Math.round(s));
  return [Math.floor(t / 3600), Math.floor((t % 3600) / 60), t % 60].map((x) => String(x).padStart(2, "0")).join(":");
};
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const short = (s, head = 10, tail = 8) => (s && s.length > head + tail + 1 ? `${s.slice(0, head)}…${s.slice(-tail)}` : s);

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  let body = {};
  try { body = await response.json(); } catch (_) { /* non-JSON error */ }
  if (!response.ok) {
    const error = new Error(body.error || `${response.status} ${response.statusText}`);
    error.status = response.status;
    throw error;
  }
  return body;
}
function setStatus(node, text, isError = false) {
  node.textContent = text;
  node.classList.toggle("error", isError);
}
function percentile(sorted, p) {
  if (!sorted.length) return null;
  const rank = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(rank), hi = Math.ceil(rank);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (rank - lo);
}

/* ---------- tabs ---------- */
function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  document.querySelectorAll(".tab").forEach((t) => t.toggleAttribute("data-active", t.id === `tab-${name}`));
  if (name !== "run") Run.pause();
  if (name === "compare") Compare.ensure();
  if (name === "live") Live.refresh();
  if (name === "run") Run.ensure();
  history.replaceState(null, "", `#${name}`);
  window.scrollTo({ top: 0, behavior: "instant" });
  document.body.classList.toggle("on-overview", name === "how");
  if (typeof FX !== "undefined") {
    FX.moveIndicator();
    FX.scramble(document.querySelector(`#tab-${name} .scramble`));
    requestAnimationFrame(() => FX.observe(document.querySelector(`#tab-${name}`)));
  }
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.goto)));

/* ================================================================== RUN ================================================================== */
const Run = {
  started: false, data: null, col: {}, i: 0, playing: false, timer: null, carry: 0,

  async ensure() {
    if (this.started) return;
    this.started = true;
    this.bind();
    await this.pollCatalogue();
  },

  bind() {
    $("#run-load").addEventListener("click", () => this.load());
    $("#run-play").addEventListener("click", () => (this.playing ? this.pause() : this.play()));
    $("#run-back").addEventListener("click", () => { this.pause(); this.go(this.i - 1); });
    $("#run-fwd").addEventListener("click", () => { this.pause(); this.go(this.i + 1); });
    $("#run-scrub").addEventListener("input", (e) => this.go(Number(e.target.value)));
    document.addEventListener("keydown", (e) => {
      if (!$("#tab-run").hasAttribute("data-active") || !this.data) return;
      if (["INPUT", "SELECT"].includes(document.activeElement.tagName) && e.key !== " ") return;
      if (e.key === " ") { e.preventDefault(); this.playing ? this.pause() : this.play(); }
      if (e.key === "ArrowRight") { this.pause(); this.go(this.i + 1); }
      if (e.key === "ArrowLeft") { this.pause(); this.go(this.i - 1); }
    });
  },

  async pollCatalogue() {
    const status = $("#run-status");
    $("#run-load").disabled = true;
    if (location.protocol === "file:") {
      setStatus(status, "This page was opened as a file. Start it with: python scripts/dashboard.py — then use http://127.0.0.1:8050", true);
      return;
    }
    // A failed request is retried rather than treated as final: the browser can open
    // before the server answers, and a restarted server should be picked up again.
    for (let failures = 0; ;) {
      let cat;
      try {
        cat = await getJSON("/api/catalogue");
        failures = 0;
      } catch (e) {
        failures += 1;
        setStatus(status, `Waiting for the dashboard server… (${e.message}; retry ${failures})`, failures > 3);
        await new Promise((r) => setTimeout(r, Math.min(1000 * failures, 5000)));
        continue;
      }
      if (cat.state === "ready") {
        this.fillSelects(cat);
        $("#run-load").disabled = false;
        setStatus(status, "Pick a policy and a test day, then Load.");
        return;
      }
      if (cat.state === "error") { setStatus(status, `Cannot load the dataset — ${cat.message}`, true); return; }
      setStatus(status, `Preparing replay data… ${cat.message || ""} (about a minute, once)`);
      await new Promise((r) => setTimeout(r, 1500));
    }
  },

  fillSelects(cat) {
    const policy = $("#run-policy"), rate = $("#run-rate"), episode = $("#run-episode");
    policy.replaceChildren(...cat.policies.map((p) => { const o = htmlEl("option", { value: p.key }, p.label); return o; }));
    const rateNames = { light: "light (½×)", matched: "normal (1×)", heavy: "heavy (2×)" };
    rate.replaceChildren(...cat.rates.map((r) => htmlEl("option", { value: r }, rateNames[r] || r)));
    rate.value = "matched";
    episode.replaceChildren(...cat.episodes.map((e) => htmlEl("option", { value: e.index }, `${e.id} · ${(e.congested * 100).toFixed(1)} % of blocks >80 % full`)));
  },

  async load() {
    const status = $("#run-status");
    const q = new URLSearchParams({ policy: $("#run-policy").value, rate: $("#run-rate").value, episode: $("#run-episode").value });
    this.pause();
    setStatus(status, "Replaying the day through the simulator…");
    $("#run-load").disabled = true;
    try {
      const data = await getJSON(`/api/replay?${q}`);
      this.data = data;
      this.col = Object.fromEntries(data.columns.map((c, k) => [c, k]));
      this.prepare();
      $("#run-body").hidden = false;
      $("#run-title").textContent = data.policy_label;
      const rateNames = { light: "light traffic", matched: "normal traffic", heavy: "heavy traffic" };
      $("#run-sub").textContent = ` · ${data.episode_id} · ${rateNames[data.rate]} · ${nf.format(data.rows.length)} blocks`;
      $("#run-scrub").max = String(data.rows.length - 1);
      $("#q-dmax").textContent = secs(data.d_max);
      this.go(0);
      setStatus(status, "Loaded. Press ▶ (or space) to play.");
    } catch (e) {
      setStatus(status, e.status === 503 ? `Still preparing: ${e.message}` : `Replay failed: ${e.message}`, true);
    } finally {
      $("#run-load").disabled = false;
    }
  },

  prepare() {
    const rows = this.data.rows, c = this.col;
    this.submitCum = new Int32Array(rows.length);
    this.lockedSlotsCum = new Float64Array(rows.length);
    // A submitted batch holds the pool from its slot until the first later block at
    // which it is no longer in flight — the same slots the report's LOCK metric counts.
    let submits = 0, lockedSlots = 0, inFlight = false;
    rows.forEach((r, k) => {
      if (inFlight && k > 0) {
        lockedSlots += r[c.slot] - rows[k - 1][c.slot];
        if (!r[c.locked]) inFlight = false;
      }
      if (r[c.submit]) inFlight = true;
      submits += r[c.submit];
      this.submitCum[k] = submits;
      this.lockedSlotsCum[k] = lockedSlots;
    });
    this.confirms = this.data.settled.map((p) => p[1]);
  },

  get(k) {
    const r = this.data.rows[k], c = this.col;
    return { slot: r[c.slot], height: r[c.height], fill: r[c.fill], forecast: r[c.forecast], depth: r[c.depth], oldest: r[c.oldest],
      locked: r[c.locked] === 1, submit: r[c.submit] === 1, n: r[c.n], gateA: r[c.gate_a], gateB: r[c.gate_b], resolution: r[c.resolution] };
  },

  play() {
    if (!this.data) return;
    if (this.i >= this.data.rows.length - 1) this.go(0);
    this.playing = true;
    $("#run-play").textContent = "❚❚";
    $("#run-play").setAttribute("aria-label", "Pause");
    let last = performance.now();
    const tick = (now) => {
      if (!this.playing) return;
      const speed = Number($("#run-speed").value);
      this.carry += ((now - last) / 1000) * speed;
      last = now;
      const steps = Math.floor(this.carry);
      if (steps > 0) {
        this.carry -= steps;
        this.go(this.i + steps);
        if (this.i >= this.data.rows.length - 1) { this.pause(); return; }
      }
      this.timer = requestAnimationFrame(tick);
    };
    this.timer = requestAnimationFrame(tick);
  },

  pause() {
    this.playing = false;
    if (this.timer) cancelAnimationFrame(this.timer);
    const b = $("#run-play");
    if (b) { b.textContent = "▶"; b.setAttribute("aria-label", "Play"); }
  },

  go(k) {
    if (!this.data) return;
    this.i = Math.max(0, Math.min(this.data.rows.length - 1, k));
    $("#run-scrub").value = String(this.i);
    $("#run-scrub").style.setProperty("--pos", `${(this.i / Math.max(1, this.data.rows.length - 1)) * 100}%`);
    this.render();
  },

  reason(r) {
    const policy = this.data.policy;
    if (r.resolution === "expired") return "The batch passed its time-to-live — its orders go back to the queue.";
    if (r.resolution === "rolled_back") return "A short fork reverted the batch — orders return to the queue.";
    if (r.locked) return "A batch is still waiting to confirm and holds the pool. No decision is possible.";
    if (r.submit) return r.oldest >= this.data.d_max
      ? "Deadline reached — waiting is not allowed, submission is forced."
      : `Submitting ${r.n} order${r.n === 1 ? "" : "s"} in one transaction.`;
    if (r.depth === 0) return "No orders in the queue.";
    if (r.gateB === 0) return "The next block is predicted full — waiting for room.";
    if (policy === "p2" || policy === "oracle") return "Batch still small and a quieter block is coming — waiting so the fee is shared by more users.";
    if (policy === "e1") return "Fixed rule: wait until 16 orders are queued.";
    if (policy === "e2") return "Fixed rule: submit only every 20 slots.";
    return "Waiting.";
  },

  render() {
    const d = this.data, r = this.get(this.i);
    $("#run-slot").textContent = nf.format(r.slot);
    $("#run-height").textContent = r.height ? nf.format(r.height) : "–";
    $("#run-elapsed").textContent = hms(r.slot - d.start_slot);

    // queue
    $("#q-depth").textContent = nf.format(r.depth);
    $("#q-oldest").textContent = secs(r.oldest);
    const ratio = Math.min(1, r.oldest / d.d_max);
    const meter = $("#q-meter");
    meter.style.width = `${ratio * 100}%`;
    meter.classList.toggle("near", ratio >= 0.8);

    // pool
    const pState = $("#p-state"), pDetail = $("#p-detail");
    if (r.resolution === "expired") {
      pState.className = "state expired"; pState.textContent = "✕ EXPIRED"; pDetail.textContent = "orders returned to the queue";
    } else if (r.locked) {
      let k = this.i, inFlight = 0;
      while (k >= 0 && this.get(k).locked) { inFlight += 1; k -= 1; }
      const batch = k >= 0 && this.get(k).submit ? this.get(k).n : null;
      pState.className = "state locked"; pState.textContent = "⏳ LOCKED";
      pDetail.textContent = `${batch ? `batch of ${batch} · ` : ""}in flight for ${inFlight} block${inFlight === 1 ? "" : "s"} — the queue waits behind it`;
    } else {
      pState.className = "state free"; pState.textContent = "○ FREE"; pDetail.textContent = "ready to batch";
    }

    // decision
    const dAction = $("#d-action");
    if (r.locked) { dAction.className = "state wait"; dAction.textContent = "— no decision"; }
    else if (r.submit) {
      const forced = r.oldest >= d.d_max;
      dAction.className = forced ? "state forced" : "state submit";
      dAction.textContent = `${forced ? "⚠" : "⏵"} SUBMIT  n = ${r.n}`;
    } else { dAction.className = "state wait"; dAction.textContent = "⏸ WAIT"; }
    $("#d-reason").textContent = this.reason(r);
    $("#d-gatea").textContent = r.gateA === null ? "–" : nf.format(r.gateA);
    $("#d-gateb").textContent = r.gateB === null ? "–" : nf.format(r.gateB);
    $("#d-forecast").textContent = r.forecast === null ? "–" : pct(r.forecast);

    this.renderChart();
    this.renderTiles(r);
    this.renderLog();
  },

  renderChart() {
    const svg = $("#run-chart");
    svg.replaceChildren();
    const W = 960, H = 220, left = 38, right = 10, top = 10, bottom = 26;
    const from = Math.max(0, this.i - 119), span = 120;
    const x = (k) => left + ((k - from) / (span - 1)) * (W - left - right);
    const y = (v) => top + (1 - v) * (H - top - bottom);

    svgEl("rect", { x: left, y: y(0.9), width: W - left - right, height: y(0.8) - y(0.9), fill: cssVar("--band") }, svg);
    svgEl("text", { x: W - right - 4, y: y(0.9) - 4, "text-anchor": "end" }, svg, "80–90 % band: a 30-order batch may not fit");
    for (const v of [0, 0.25, 0.5, 0.75, 1]) {
      svgEl("line", { x1: left, x2: W - right, y1: y(v), y2: y(v), stroke: cssVar("--grid"), "stroke-width": 1 }, svg);
      svgEl("text", { x: left - 6, y: y(v) + 4, "text-anchor": "end" }, svg, `${v * 100}%`);
    }

    const actual = [], forecast = [];
    for (let k = from; k <= this.i; k += 1) {
      const r = this.get(k);
      actual.push(`${x(k).toFixed(1)},${y(r.fill).toFixed(1)}`);
      if (r.forecast !== null) forecast.push(`${x(k).toFixed(1)},${y(r.forecast).toFixed(1)}`);
      if (r.locked) svgEl("rect", { x: x(k) - 3.5, y: H - bottom + 3, width: 7, height: 5, fill: cssVar("--warn"), opacity: 0.8 }, svg);
      if (r.submit) svgEl("text", { x: x(k), y: H - 4, "text-anchor": "middle", fill: cssVar("--good"), "font-size": 12 }, svg, "▲");
      if (r.resolution === "expired") svgEl("text", { x: x(k), y: H - 4, "text-anchor": "middle", fill: cssVar("--critical"), "font-size": 12 }, svg, "✕");
    }
    const defs = svgEl("defs", {}, svg);
    const grad = svgEl("linearGradient", { id: "fill-grad", x1: 0, x2: 0, y1: 0, y2: 1 }, defs);
    svgEl("stop", { offset: "0", "stop-color": cssVar("--accent"), "stop-opacity": 0.45 }, grad);
    svgEl("stop", { offset: "1", "stop-color": cssVar("--accent"), "stop-opacity": 0 }, grad);
    if (actual.length > 1) {
      const baseline = y(0).toFixed(1);
      const area = `${actual[0].split(",")[0]},${baseline} ${actual.join(" ")} ${actual[actual.length - 1].split(",")[0]},${baseline}`;
      svgEl("polygon", { points: area, fill: "url(#fill-grad)", stroke: "none" }, svg);
    }
    svgEl("polyline", { points: forecast.join(" "), fill: "none", stroke: cssVar("--accent-soft"), "stroke-width": 1.6, "stroke-dasharray": "5 4", opacity: 0.8 }, svg);
    svgEl("polyline", { points: actual.join(" "), fill: "none", stroke: cssVar("--accent-soft"), "stroke-width": 2, class: "line-actual" }, svg);
    svgEl("line", { x1: x(this.i), x2: x(this.i), y1: top, y2: H - bottom, stroke: cssVar("--muted"), "stroke-width": 1 }, svg);
  },

  renderTiles(r) {
    const d = this.data;
    let lo = 0, hi = this.confirms.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (this.confirms[mid] <= r.slot) lo = mid + 1; else hi = mid; }
    const latencies = d.settled.slice(0, lo).map((p) => p[1] - p[0]).sort((a, b) => a - b);
    const mean = latencies.length ? latencies.reduce((s, v) => s + v, 0) / latencies.length : null;
    let expired = 0;
    for (const t of d.expired) { if (t <= r.slot) expired += 1; else break; }
    const tiles = [
      [secs(mean), "latency · mean so far"],
      [secs(percentile(latencies, 95)), "latency · 95th pct so far"],
      [nf.format(latencies.length), "orders settled"],
      [nf.format(expired), "orders expired"],
      [nf.format(this.submitCum[this.i]), "batches submitted"],
      [pct(this.lockedSlotsCum[this.i] / Math.max(1, r.slot - d.start_slot), 0), "time the pool was locked"],
      [ada(d.metrics.c_user), "cost per user · whole day"],
    ];
    $("#run-tiles").replaceChildren(...tiles.map(([v, l]) => {
      const t = htmlEl("div", { class: "tile" });
      t.append(htmlEl("div", { class: "v num" }, v), htmlEl("div", { class: "l" }, l));
      return t;
    }));
  },

  renderLog() {
    const body = $("#run-log");
    const rows = [];
    for (let k = this.i; k >= Math.max(0, this.i - 7); k -= 1) {
      const r = this.get(k);
      const tr = htmlEl("tr");
      const note = r.resolution ? r.resolution.replace("_", " ") : r.locked ? "pool locked" : r.submit && r.oldest >= this.data.d_max ? "deadline forced" : "";
      const cells = [nf.format(r.slot), r.depth, secs(r.oldest), pct(r.fill), r.forecast === null ? "–" : pct(r.forecast), r.locked ? "LOCKED" : "free", r.locked ? "—" : r.submit ? "SUBMIT" : "WAIT", r.submit ? r.n : "", note];
      cells.forEach((v, idx) => {
        const td = htmlEl("td", {}, String(v));
        if (idx === 5 && r.locked) td.className = "tag-locked";
        if (idx === 6 && r.submit) td.className = "tag-submit";
        if (idx === 8) td.className = "note";
        tr.appendChild(td);
      });
      rows.push(tr);
    }
    body.replaceChildren(...rows);
  },
};

/* ================================================================ COMPARE ================================================================ */
const FAMILY_COLOR = { proposed: "--accent", static: "--static", reference: "--muted" };
const Compare = {
  data: null, rate: "matched", loading: false,

  async ensure() {
    if (this.data || this.loading) { if (this.data) this.render(); return; }
    this.loading = true;
    const status = $("#cmp-status");
    setStatus(status, "Computing medians and confidence intervals…");
    try {
      this.data = await getJSON("/api/compare");
      setStatus(status, `Test split · ${this.data.episodes} paired days · ${this.data.gate_a_violations} capacity violations`);
      $("#cmp-body").hidden = false;
      const seg = $("#cmp-rate");
      const names = { light: "Light ½×", matched: "Normal 1×", heavy: "Heavy 2×" };
      seg.replaceChildren(...["light", "matched", "heavy"].map((r) => {
        const b = htmlEl("button", { "aria-pressed": String(r === this.rate) }, names[r]);
        b.addEventListener("click", () => { this.rate = r; seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); this.render(); });
        return b;
      }));
      this.render();
    } catch (e) {
      setStatus(status, `Could not load results: ${e.message}`, true);
    } finally { this.loading = false; }
  },

  row(key) { return this.data.rates[this.rate].find((p) => p.key === key); },

  render() {
    this.findings();
    this.table();
    this.pareto();
    this.cdf();
  },

  findings() {
    const greedy = this.row("e3(greedy)"), p2 = this.row("p2(D=120,N=4)"), p3 = this.row("p3(dqn)"), e2 = this.row("e2(T=20)");
    const saving = (a, b) => `${Math.round((1 - a.c_user[0] / b.c_user[0]) * 100)} %`;
    const slower = (a, b) => `${Math.round((a.l_p95[0] / b.l_p95[0] - 1) * 100)} %`;
    const items = [
      ["0", "capacity violations in every run (S2)"],
      [saving(p2, greedy), `lower cost per user — P2 vs greedy, for ${slower(p2, greedy)} more tail latency`],
      [saving(p3, greedy), "lower cost per user — the DQN agent vs greedy"],
      [`${num(p2.l_p95[0])} s vs ${num(e2.l_p95[0])} s`, "tail latency, P2 vs the tuned fixed-interval rule"],
    ];
    $("#cmp-findings").replaceChildren(...items.map(([v, l]) => {
      const div = htmlEl("div", { class: "finding" });
      div.append(htmlEl("div", { class: "v num" }, v), htmlEl("div", { class: "l" }, l));
      return div;
    }));
    if (typeof FX !== "undefined") $("#cmp-findings").querySelectorAll(".v").forEach((n) => FX.countUp(n, 900));
  },

  table() {
    const rows = this.data.rates[this.rate];
    const metrics = [
      ["l_mean", "Latency mean", (v) => secs(v), true],
      ["l_p95", "Latency p95", (v) => secs(v), true],
      ["c_user", "Cost / user", (v) => ada(v, 3), true],
      ["x_rate", "Expired", (v) => pct(v, 1), true],
      ["throughput", "Throughput", (v) => num(v, 1), false],
      ["f_jain", "Fairness", (v) => num(v, 2), false],
    ];
    const contenders = rows.filter((p) => p.family !== "reference");
    const best = Object.fromEntries(metrics.map(([m, , , lower]) => {
      const vals = contenders.map((p) => p[m][0]).filter((v) => v !== null);
      return [m, lower ? Math.min(...vals) : Math.max(...vals)];
    }));
    const table = $("#cmp-table");
    const head = htmlEl("thead"); const hr = htmlEl("tr");
    hr.appendChild(htmlEl("th", {}, "Policy"));
    metrics.forEach(([, label]) => hr.appendChild(htmlEl("th", {}, label)));
    head.appendChild(hr);
    const body = htmlEl("tbody");
    rows.forEach((p) => {
      const tr = htmlEl("tr", { class: p.family === "reference" ? "ref" : "" });
      const name = htmlEl("td");
      const dot = htmlEl("span", { class: "fam" }); dot.style.background = cssVar(FAMILY_COLOR[p.family] || "--muted");
      name.append(dot, document.createTextNode(p.label));
      tr.appendChild(name);
      metrics.forEach(([m, , fmt]) => {
        const [med, lo, hi] = p[m];
        const td = htmlEl("td", {}, fmt(med));
        if (p.family !== "reference" && med !== null && Math.abs(med - best[m]) < 1e-9) td.classList.add("best");
        if (lo !== null && hi !== null && hi !== lo) td.appendChild(htmlEl("span", { class: "ci" }, `[${fmt(lo)}–${fmt(hi)}]`.replace(/ ADA|%| s/g, "")));
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    table.replaceChildren(head, body);
  },

  pareto() {
    const svg = $("#cmp-pareto");
    svg.replaceChildren();
    const W = 520, H = 380, L = 58, R = 16, T = 16, B = 44;
    const pts = this.data.rates[this.rate].filter((p) => p.l_p95[0] !== null && p.c_user[0] !== null && p.key !== "p2(D=120,N=1)");
    const xs = pts.flatMap((p) => [p.c_user[1], p.c_user[2]]).map((v) => v / 1e6);
    const ys = pts.flatMap((p) => [p.l_p95[1], p.l_p95[2]]);
    const pad = (a, b) => (b - a) * 0.08 || 1;
    let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    [x0, x1] = [x0 - pad(x0, x1), x1 + pad(x0, x1)];
    [y0, y1] = [Math.max(0, y0 - pad(y0, y1)), y1 + pad(y0, y1)];
    const sx = (v) => L + ((v - x0) / (x1 - x0)) * (W - L - R);
    const sy = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
    for (let k = 0; k <= 4; k += 1) {
      const vx = x0 + ((x1 - x0) * k) / 4, vy = y0 + ((y1 - y0) * k) / 4;
      svgEl("line", { x1: sx(vx), x2: sx(vx), y1: T, y2: H - B, stroke: cssVar("--grid") }, svg);
      svgEl("line", { x1: L, x2: W - R, y1: sy(vy), y2: sy(vy), stroke: cssVar("--grid") }, svg);
      svgEl("text", { x: sx(vx), y: H - B + 16, "text-anchor": "middle" }, svg, vx.toFixed(3));
      svgEl("text", { x: L - 6, y: sy(vy) + 4, "text-anchor": "end" }, svg, Math.round(vy));
    }
    svgEl("text", { x: (L + W - R) / 2, y: H - 8, "text-anchor": "middle" }, svg, "cost per user (ADA)  ← cheaper");
    svgEl("text", { x: 14, y: (T + H - B) / 2, "text-anchor": "middle", transform: `rotate(-90 14 ${(T + H - B) / 2})` }, svg, "tail latency p95 (s)  ← faster");

    const placed = [];
    pts.sort((a, b) => a.l_p95[0] - b.l_p95[0]).forEach((p, idx) => {
      const color = cssVar(FAMILY_COLOR[p.family] || "--muted");
      const cx = sx(p.c_user[0] / 1e6), cy = sy(p.l_p95[0]);
      const delay = `${0.15 + idx * 0.08}s`;
      const group = svgEl("g", { class: "fade-in", style: `animation-delay:${delay}` }, svg);
      svgEl("line", { x1: sx(p.c_user[1] / 1e6), x2: sx(p.c_user[2] / 1e6), y1: cy, y2: cy, stroke: color, "stroke-width": 1.2, opacity: 0.8 }, group);
      svgEl("line", { x1: cx, x2: cx, y1: sy(p.l_p95[1]), y2: sy(p.l_p95[2]), stroke: color, "stroke-width": 1.2, opacity: 0.8 }, group);
      const hollow = p.family === "reference";
      if (!hollow) svgEl("circle", { cx, cy, r: 12, fill: color, opacity: 0.18, class: "pop", style: `animation-delay:${delay}` }, svg);
      svgEl("circle", { cx, cy, r: 6, fill: hollow ? cssVar("--page") : color, stroke: color, "stroke-width": 2, class: "pop", style: `animation-delay:${delay}` }, svg);
      let ly = cy - 9;
      while (placed.some((q) => Math.abs(q.x - cx) < 120 && Math.abs(q.y - ly) < 13)) ly += 14;
      placed.push({ x: cx, y: ly });
      const anchor = cx > W - 150 ? "end" : "start";
      svgEl("text", { x: cx + (anchor === "end" ? -11 : 11), y: ly, "text-anchor": anchor, class: "ptlabel fade-in", style: `animation-delay:${delay}` }, svg,
        p.key === "e3(greedy)" ? "E3 greedy (≡ P2 N=1)" : p.label.split(" · ")[0] + (p.key === "p2(D=120,N=4)" ? " N=4" : ""));
    });
  },

  cdf() {
    const svg = $("#cmp-cdf");
    svg.replaceChildren();
    const W = 520, H = 380, L = 44, R = 16, T = 16, B = 44;
    const keys = [["p3(dqn)", "--accent", "P3 DQN", ""], ["p2(D=120,N=4)", "--accent", "P2 N=4", "6 3"], ["e2(T=20)", "--static", "E2 T=20", ""], ["e3(greedy)", "--static", "E3 greedy", "2 3"]];
    const q = this.data.cdf_matched;
    const xmax = Math.max(...keys.map(([k]) => (q[k] ? q[k][99] : 0))) * 1.05;
    const sx = (v) => L + (Math.min(v, xmax) / xmax) * (W - L - R);
    const sy = (p) => T + (1 - p) * (H - T - B);
    for (let k = 0; k <= 4; k += 1) {
      const vx = (xmax * k) / 4;
      svgEl("line", { x1: sx(vx), x2: sx(vx), y1: T, y2: H - B, stroke: cssVar("--grid") }, svg);
      svgEl("text", { x: sx(vx), y: H - B + 16, "text-anchor": "middle" }, svg, Math.round(vx));
      svgEl("line", { x1: L, x2: W - R, y1: sy(k / 4), y2: sy(k / 4), stroke: cssVar("--grid") }, svg);
      svgEl("text", { x: L - 6, y: sy(k / 4) + 4, "text-anchor": "end" }, svg, `${k * 25}%`);
    }
    svgEl("line", { x1: L, x2: W - R, y1: sy(0.95), y2: sy(0.95), stroke: cssVar("--muted"), "stroke-dasharray": "4 4" }, svg);
    svgEl("text", { x: (L + W - R) / 2, y: H - 8, "text-anchor": "middle" }, svg, "confirmation latency (s) — normal traffic");
    keys.forEach(([key, color, label, dash], idx) => {
      if (!q[key]) return;
      const points = q[key].slice(0, 100).map((v, p) => `${sx(v).toFixed(1)},${sy(p / 100).toFixed(1)}`).join(" ");
      const curve = svgEl("polyline", { points, fill: "none", stroke: cssVar(color), "stroke-width": 2.2, "stroke-dasharray": dash }, svg);
      if (typeof FX !== "undefined") FX.drawIn(curve, 1100, idx * 120);
      const ly = sy(0.55) + idx * 16;
      svgEl("line", { x1: W - R - 150, x2: W - R - 126, y1: ly - 4, y2: ly - 4, stroke: cssVar(color), "stroke-width": 2.2, "stroke-dasharray": dash }, svg);
      svgEl("text", { x: W - R - 120, y: ly, class: "ptlabel" }, svg, `${label} · p95 ${Math.round(q[key][95])} s`);
    });
  },
};

/* ================================================================== LIVE ================================================================= */
const Live = {
  busy: false, timer: null,

  async refresh() {
    if (this.busy) return;
    this.busy = true;
    const pill = $("#live-pill");
    pill.textContent = "Checking…"; pill.className = "pill";
    try {
      const d = await getJSON("/api/live");
      this.render(d);
    } catch (e) {
      pill.textContent = "server error"; pill.className = "pill off";
      $("#live-tip").textContent = e.message;
    } finally { this.busy = false; }
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { if ($("#tab-live").hasAttribute("data-active")) this.refresh(); }, 30000);
  },

  render(d) {
    const pill = $("#live-pill"), tip = $("#live-tip");
    if (d.available) {
      pill.textContent = "Connected to preprod"; pill.className = "pill ok";
      tip.textContent = `chain tip at slot ${nf.format(d.tip_slot)} · refreshes every 30 s`;
    } else {
      pill.textContent = "Offline — showing recorded transactions"; pill.className = "pill off";
      tip.textContent = d.reason || "";
    }

    const pool = $("#live-pool");
    if (d.available && d.pool) {
      const stats = [
        [`${num(d.pool.ada, 2)} tADA`, "ADA in the pool"],
        [`${nf.format(d.pool.tokens)} ${d.token}`, "tokens in the pool"],
        [`${num(d.pool.tokens_per_ada, 1)}`, `${d.token} per ADA (spot)`],
        [`${d.fee_bps / 100} %`, "swap fee"],
      ];
      const grid = htmlEl("div", { class: "stat-row" });
      stats.forEach(([v, l]) => { const t = htmlEl("div", { class: "tile" }); t.append(htmlEl("div", { class: "v num" }, v), htmlEl("div", { class: "l" }, l)); grid.appendChild(t); });
      const p = htmlEl("p", { class: "muted small" });
      p.append(document.createTextNode(d.pool.nft === 1 ? "✓ carries its unique POOL NFT · current UTXO " : "⚠ pool NFT missing · UTXO "));
      const a = htmlEl("a", { href: d.pool.url, target: "_blank", rel: "noopener" }, short(d.pool.utxo, 12, 6));
      p.appendChild(a);
      pool.replaceChildren(grid, p);
      // count up only when the pool actually changed, not on every 30 s refresh
      const signature = stats.map(([v]) => v).join("|");
      if (typeof FX !== "undefined" && signature !== this.lastPool) grid.querySelectorAll(".v").forEach((n) => FX.countUp(n, 1000));
      this.lastPool = signature;
    } else {
      pool.replaceChildren(htmlEl("div", { class: "empty" }, d.available ? "Pool not found at the pool address." : "Live pool data needs a connection to Blockfrost."));
    }

    const orders = $("#live-orders");
    if (d.available && d.orders && d.orders.length) {
      const table = htmlEl("table");
      const hr = htmlEl("tr"); ["Order", "Sells", "Minimum out", "Locked"].forEach((h) => hr.appendChild(htmlEl("th", {}, h)));
      table.appendChild(hr);
      d.orders.forEach((o) => {
        const tr = htmlEl("tr");
        const td = htmlEl("td"); td.appendChild(htmlEl("a", { href: o.url, target: "_blank", rel: "noopener", class: "hash" }, short(o.ref, 10, 4)));
        tr.appendChild(td);
        const sells = o.direction === "AtoB" ? `${num(o.amount_in / 1e6, 2)} tADA` : `${nf.format(o.amount_in)} ${d.token}`;
        const minOut = o.direction === "AtoB" ? `${nf.format(o.min_out)} ${d.token}` : `${num(o.min_out / 1e6, 2)} tADA`;
        [sells, minOut, `${num(o.locked_ada, 2)} tADA`].forEach((v) => tr.appendChild(htmlEl("td", {}, v)));
        table.appendChild(tr);
      });
      orders.replaceChildren(table);
    } else {
      orders.replaceChildren(htmlEl("div", { class: "empty" }, d.available ? "No orders waiting — the batcher has settled everything." : "Needs a connection to Blockfrost."));
    }

    const txs = $("#live-txs");
    txs.replaceChildren(...(d.transactions || []).map((t) => {
      const li = htmlEl("li");
      li.append(htmlEl("strong", {}, t.step), htmlEl("div", { class: "muted small" }, t.detail));
      const a = htmlEl("a", { href: t.url, target: "_blank", rel: "noopener", class: "hash" }, t.tx);
      li.appendChild(a);
      return li;
    }));
    if (!(d.transactions || []).length) txs.replaceChildren(htmlEl("li", {}, "No recorded transactions yet."));

    const addr = $("#live-addresses");
    if (d.available) {
      const grid = htmlEl("div", { class: "addr" });
      [["Pool contract", d.addresses.pool], ["Order contract", d.addresses.order], ["Batcher", `${d.addresses.batcher}`]].forEach(([label, value]) => {
        grid.appendChild(htmlEl("span", { class: "muted" }, label));
        const cell = htmlEl("span");
        cell.appendChild(htmlEl("a", { href: `${d.address_url}${value}`, target: "_blank", rel: "noopener", class: "hash" }, value));
        grid.appendChild(cell);
      });
      grid.appendChild(htmlEl("span", { class: "muted" }, "Batcher balance"));
      grid.appendChild(htmlEl("span", { class: "num" }, `${num(d.batcher_ada, 2)} tADA`));
      grid.appendChild(htmlEl("span", { class: "muted" }, "Token policy"));
      grid.appendChild(htmlEl("span", { class: "hash" }, d.policy_id));
      addr.replaceChildren(grid);
    } else {
      addr.replaceChildren(htmlEl("div", { class: "empty" }, "Addresses appear once connected."));
    }
  },
};
$("#live-refresh").addEventListener("click", () => Live.refresh());

/* ---------- start ---------- */
if (typeof FX !== "undefined") FX.fibers($("#fibers"));
// when the intro hands over, replay the entrance of whichever page is showing
addEventListener("intro:done", () => {
  if (typeof FX === "undefined") return;
  const active = document.querySelector(".tab[data-active]");
  FX.moveIndicator();
  FX.scramble(active && active.querySelector(".scramble"));
});
$("#replay-intro").addEventListener("click", () => { location.href = location.pathname; });
const initial = (location.hash || "#how").slice(1);
showTab(["how", "run", "compare", "live"].includes(initial) ? initial : "how");
Run.ensure(); // start preparing replay data now, so Run is ready by the time it is opened
