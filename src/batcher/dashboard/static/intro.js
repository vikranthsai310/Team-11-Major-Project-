"use strict";
/* Opening sequence: the project told in six short canvas scenes before the pages —
   one order → thousands arrive → the pool lock → 92 days of mainnet → an AI decides →
   Adaptive Batcher, whose mark flares into the live site. Plays on every page load
   (?intro=15 starts at a given second) and can be skipped with the button, Enter, Space
   or Escape. Every figure is the project's own. */
(() => {
  const root = document.getElementById("intro");
  if (!root) return;
  // ?intro=15 starts at 15 s — handy for rehearsing a single scene
  const startAt = Math.max(0, Number(new URLSearchParams(location.search).get("intro")) || 0);
  document.body.classList.add("intro-playing");

  const LEAVE = 17.4, END = 18.3;
  const MONO = '"Cascadia Mono", ui-monospace, Consolas, monospace';
  const TAU = Math.PI * 2;
  const canvas = root.querySelector("canvas");
  const ctx = canvas.getContext("2d");
  const captionBox = root.querySelector(".intro-captions");
  const live = root.querySelector(".intro-live");
  const bar = root.querySelector(".intro-progress i");
  let W = 0, H = 0, dpr = 1, raf = null, t0 = 0, current = -2, leaving = false, done = false;
  let G = { cx: 0, cy: 0, hz: 0, u: 1 };

  const CAPTIONS = [
    { from: 0.35, to: 2.75, eyebrow: "Team 11 · VBIT presents", main: "It starts with one order", sub: "a user locks funds at the order contract" },
    { from: 3.1, to: 5.5, main: "Then thousands arrive", sub: "10,158 orders settled in a single test day", count: true },
    { from: 5.9, to: 8.45, main: "One pool · one batch per block", sub: "every other order waits behind the lock" },
    { from: 8.95, to: 11.35, main: "We measured the chain", sub: "388,781 mainnet blocks · the median is only 2.95 % full", count: true },
    { from: 11.8, to: 14.3, main: "An AI decides every block", sub: "wait for a fuller batch — or submit now" },
    { from: 14.9, to: 99, eyebrow: "AI-driven · Major Project", main: "Adaptive Batcher", sub: "Transaction batching for Cardano DEXes", meta: "0 capacity violations · 19 % lower cost per user · live on Cardano preprod", title: true },
  ];

  /* ---------- helpers ---------- */
  let seed = 7;
  const rand = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
  const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  const prog = (t, a, b) => clamp((t - a) / (b - a));
  const easeOut = (x) => 1 - Math.pow(1 - x, 3);
  const easeInOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
  const fade = (t, a, b, f) => Math.min(prog(t, a, a + f), 1 - prog(t, b - f, b));
  const bez = (p, t) => {
    const u = 1 - t;
    return [u * u * u * p[0] + 3 * u * u * t * p[2] + 3 * u * t * t * p[4] + t * t * t * p[6],
      u * u * u * p[1] + 3 * u * u * t * p[3] + 3 * u * t * t * p[5] + t * t * t * p[7]];
  };

  const ORDERS = Array.from({ length: 72 }, () => ({
    y: rand() - 0.5, side: rand() < 0.72 ? -1 : 1, ts: 2.9 + rand() * 2.0,
    ang: rand() * TAU, rad: 0.35 + rand() * 0.65, spin: 0.25 + rand() * 0.35, blue: rand() > 0.7,
  }));
  const DUST = Array.from({ length: 90 }, () => ({ x: rand(), y: rand(), r: 0.4 + rand() * 1.3, s: 0.003 + rand() * 0.01, ph: rand() * TAU }));
  // illustrative block fills: almost all nearly empty, as measured, with the rare full one
  const BLOCKS = Array.from({ length: 40 }, (_, k) => ({ fill: k === 9 || k === 24 ? 0.6 + rand() * 0.3 : 0.015 + rand() * 0.06 }));
  const STREAKS = Array.from({ length: 34 }, () => ({ x: rand(), speed: 0.2 + rand() * 0.5, ph: rand(), a: 0.2 + rand() * 0.6 }));
  const MARK = ["M3 16 C11 16 14 5 29 3", "M3 16 C11 16 15 10 29 10", "M3 16 H29", "M3 16 C11 16 15 22 29 22", "M3 16 C11 16 14 27 29 29"].map((d) => new Path2D(d));
  const DECISIONS = [[11.95, "WAIT"], [12.45, "WAIT"], [12.95, "WAIT"], [13.4, "SUBMIT"]];

  function spark(x, y, size, alpha, tint = "240,201,198") {
    if (alpha <= 0.01) return;
    const r = size * 9;
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, `rgba(255,255,255,${alpha})`);
    g.addColorStop(0.12, `rgba(${tint},${alpha * 0.75})`);
    g.addColorStop(1, `rgba(${tint},0)`);
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.fill();
  }
  function trail(pts, alpha, width, tint = "240,201,198") {
    for (let k = 1; k < pts.length; k += 1) {
      const f = k / pts.length;
      ctx.strokeStyle = `rgba(${tint},${alpha * f})`;
      ctx.lineWidth = width * (0.3 + 0.7 * f);
      ctx.beginPath(); ctx.moveTo(pts[k - 1][0], pts[k - 1][1]); ctx.lineTo(pts[k][0], pts[k][1]); ctx.stroke();
    }
  }
  function ring(x, y, r, color, width, dash = [], offset = 0) {
    ctx.setLineDash(dash); ctx.lineDashOffset = offset;
    ctx.strokeStyle = color; ctx.lineWidth = width;
    ctx.beginPath(); ctx.arc(x, y, Math.max(0.1, r), 0, TAU); ctx.stroke();
    ctx.setLineDash([]);
  }
  function polygon(x, y, r, sides, rot, color, dash = []) {
    ctx.beginPath();
    for (let k = 0; k <= sides; k += 1) {
      const an = rot + (k * TAU) / sides - Math.PI / 2;
      const px = x + Math.cos(an) * r, py = y + Math.sin(an) * r;
      if (k) ctx.lineTo(px, py); else ctx.moveTo(px, py);
    }
    ctx.setLineDash(dash); ctx.strokeStyle = color; ctx.lineWidth = 1.4 * G.u; ctx.stroke(); ctx.setLineDash([]);
  }
  function label(str, x, y, color, size) {
    ctx.save();
    ctx.globalCompositeOperation = "source-over";
    ctx.font = `600 ${Math.round(size * G.u + 3)}px ${MONO}`;
    ctx.textAlign = "center";
    if ("letterSpacing" in ctx) ctx.letterSpacing = "0.2em";
    ctx.fillStyle = color;
    ctx.fillText(str, x, y);
    ctx.restore();
  }
  function beam(x, y, grow, fadeOut, a) {
    if (grow <= 0 || fadeOut <= 0) return;
    const x2 = x + (W - x + 40) * easeOut(grow);
    const g = ctx.createLinearGradient(x, 0, x2, 0);
    g.addColorStop(0, "rgba(240,201,198,0)");
    g.addColorStop(1, `rgba(255,255,255,${0.95 * a * fadeOut})`);
    ctx.strokeStyle = g; ctx.lineWidth = 3 * G.u;
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x2, y); ctx.stroke();
    spark(x2, y, 2.4 * G.u, a * fadeOut);
  }
  function sweep(t, from, to, a) {
    const p = prog(t, from, to);
    if (p <= 0 || p >= 1) return;
    const env = Math.sin(p * Math.PI) * a;
    [[0, 0.1, 0.9], [0.35, -0.12, 0.5]].forEach(([off, tilt, strength]) => {
      ctx.save();
      ctx.translate((-0.3 + p * 1.6 - off) * W, G.hz * 0.5);
      ctx.rotate(-0.38 + tilt);
      const w = 46 * G.u;
      const g = ctx.createLinearGradient(-w, 0, w, 0);
      g.addColorStop(0, "rgba(240,201,198,0)");
      g.addColorStop(0.5, `rgba(250,232,230,${0.5 * env * strength})`);
      g.addColorStop(1, "rgba(240,201,198,0)");
      ctx.fillStyle = g; ctx.fillRect(-w, -H * 1.5, w * 2, H * 3);
      ctx.restore();
    });
  }

  /* ---------- stage ---------- */
  function background(t) {
    ctx.globalCompositeOperation = "source-over";
    const bg = ctx.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, "#4d2529"); bg.addColorStop(0.55, "#3a1a1d"); bg.addColorStop(1, "#1f0d0f");
    ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
    const v = ctx.createRadialGradient(G.cx, G.cy, 0, G.cx, G.cy, Math.max(W, H) * 0.75);
    v.addColorStop(0, "rgba(142,74,78,0.30)");
    v.addColorStop(0.45, "rgba(92,42,46,0.10)");
    v.addColorStop(1, "rgba(31,13,15,0)");
    ctx.fillStyle = v; ctx.fillRect(0, 0, W, H);
    ctx.globalCompositeOperation = "lighter";
    for (const d of DUST) {
      const tw = 0.3 + 0.7 * Math.abs(Math.sin(t * 0.8 + d.ph));
      ctx.fillStyle = `rgba(240,201,198,${0.3 * tw})`;
      ctx.beginPath(); ctx.arc(((d.x + t * d.s) % 1) * W, d.y * H, d.r * G.u, 0, TAU); ctx.fill();
    }
  }
  function floor() {
    ctx.globalCompositeOperation = "source-over";
    // mirror everything above the horizon onto a glossy floor
    const sh = Math.round(G.hz * dpr), hh = Math.min(sh, canvas.height - sh);
    if (hh > 0) {
      ctx.save();
      ctx.setTransform(dpr, 0, 0, -dpr, 0, 2 * G.hz * dpr);
      ctx.globalAlpha = 0.22;
      ctx.drawImage(canvas, 0, sh - hh, canvas.width, hh, 0, G.hz - hh / dpr, W, hh / dpr);
      ctx.restore();
    }
    const f = ctx.createLinearGradient(0, G.hz, 0, H);
    f.addColorStop(0, "rgba(31,13,15,0.2)");
    f.addColorStop(1, "rgba(31,13,15,0.96)");
    ctx.fillStyle = f; ctx.fillRect(0, G.hz, W, H - G.hz);
    const line = ctx.createLinearGradient(0, 0, W, 0);
    line.addColorStop(0, "rgba(227,174,176,0)");
    line.addColorStop(0.5, "rgba(240,201,198,0.3)");
    line.addColorStop(1, "rgba(227,174,176,0)");
    ctx.fillStyle = line; ctx.fillRect(0, G.hz, W, 1);
  }

  /* ---------- scene 1: one order ---------- */
  function sceneSpark(t) {
    const a = 1 - prog(t, 2.7, 3.2);
    if (a <= 0) return;
    const P = [-0.06 * W, G.cy + 0.22 * H, 0.22 * W, G.cy + 0.26 * H, 0.34 * W, G.cy - 0.16 * H, G.cx, G.cy];
    const p = easeInOut(prog(t, 0.1, 2.6));
    const pts = [];
    for (let k = 0; k <= 36; k += 1) pts.push(bez(P, Math.max(0, p - 0.42 + (0.42 * k) / 36)));
    trail(pts, 0.9 * a, 2.2 * G.u);
    const [x, y] = bez(P, p);
    spark(x, y, 2.6 * G.u, a);
    if (p > 0.12) label("ORDER", x + 30 * G.u, y - 14 * G.u, `rgba(246,222,220,${0.75 * a * prog(p, 0.12, 0.3)})`, 8);
  }

  /* ---------- scenes 2–3: thousands arrive, then collapse into the pool ---------- */
  function orderPos(o, t) {
    const R = (0.07 * W + 0.11 * H) * o.rad;
    const ang = o.ang + (t - o.ts) * o.spin;
    const ox = G.cx + Math.cos(ang) * R, oy = G.cy + Math.sin(ang) * R * 0.42;
    const k = easeOut(prog(t, o.ts, o.ts + 1.25)), ik = 1 - k;
    const sx = o.side < 0 ? -0.05 * W : 1.05 * W, sy = G.cy + o.y * H * 0.9;
    const mx = (sx + ox) / 2, my = sy + (oy - sy) * 0.15 - 0.06 * H * Math.sign(o.y);
    let x = ik * ik * sx + 2 * ik * k * mx + k * k * ox;
    let y = ik * ik * sy + 2 * ik * k * my + k * k * oy;
    const collapse = easeInOut(prog(t, 5.9 + o.rad * 0.5, 7.0 + o.rad * 0.4));
    x += (G.cx - x) * collapse; y += (G.cy - y) * collapse;
    return [x, y, collapse];
  }
  function sceneOrders(t) {
    if (t < 2.85 || t > 7.6) return;
    for (const o of ORDERS) {
      if (t < o.ts) continue;
      const pts = [];
      for (let k = 8; k >= 0; k -= 1) { const [x, y] = orderPos(o, t - k * 0.028); pts.push([x, y]); }
      const [x, y, collapse] = orderPos(o, t);
      const a = prog(t, o.ts, o.ts + 0.2) * (1 - collapse);
      const tint = o.blue ? "232,180,182" : "240,201,198";
      trail(pts, 0.55 * a, 1.4 * G.u, tint);
      spark(x, y, 1.5 * G.u, a, tint);
    }
  }
  function scenePool(t) {
    const a = fade(t, 5.5, 9.3, 0.5);
    if (a <= 0) return;
    const R = 30 * G.u * (0.4 + 0.6 * easeOut(prog(t, 5.5, 6.3)));
    const locked = t > 7.05 && t < 8.75;
    const tint = locked ? "240,201,106" : "227,174,176";
    ring(G.cx, G.cy, R, `rgba(${tint},${0.9 * a})`, 2 * G.u);
    ring(G.cx, G.cy, R * 1.55, `rgba(${tint},${0.35 * a})`, 1.2 * G.u, [4 * G.u, 9 * G.u], -t * 30 * G.u);
    if (locked) {
      const pulse = ((t - 7.05) % 0.8) / 0.8;
      ring(G.cx, G.cy, R * (1 + pulse * 1.4), `rgba(240,201,106,${0.5 * (1 - pulse) * a})`, 1.5 * G.u);
    }
    spark(G.cx, G.cy, (2.2 + 2.4 * prog(t, 6.2, 7.0)) * G.u * (locked ? 0.8 : 1), a, tint);
    label(locked ? "LOCKED" : "POOL", G.cx, G.cy + R * 1.55 + 24 * G.u, locked ? `rgba(240,201,106,${a})` : `rgba(236,211,209,${0.85 * a})`, 9);
    beam(G.cx + R, G.cy, prog(t, 7.0, 7.4), 1 - prog(t, 7.5, 8.3), a);
    // new orders queue behind the lock, and flow in once it opens
    const release = easeInOut(prog(t, 8.75, 9.2));
    for (let k = 0; k < 10; k += 1) {
      const appear = prog(t, 7.3 + k * 0.12, 7.6 + k * 0.12);
      if (appear <= 0) continue;
      const dist = R * 2.3 + k * 22 * G.u;
      spark(G.cx - dist * (1 - release), G.cy, 1.5 * G.u, a * appear * (1 - release));
    }
  }

  /* ---------- scene 4: the chain we measured ---------- */
  function sceneChain(t) {
    const a = fade(t, 8.8, 11.9, 0.5);
    if (a <= 0) return;
    const s = 44 * G.u, gap = s * 1.8, local = t - 8.8;
    const offset = W * 0.62 - local * gap * 1.5;
    ctx.lineWidth = 1.3 * G.u;
    for (let k = 0; k < BLOCKS.length; k += 1) {
      const x = offset + k * gap;
      if (x < -gap || x > W + gap) continue;
      const e = easeOut(clamp((W + gap * 0.2 - x) / (gap * 1.2)));
      const alpha = a * e, y = G.cy - s / 2 + (1 - e) * 12 * G.u;
      if (k > 0) {
        ctx.strokeStyle = `rgba(227,174,176,${0.35 * alpha})`;
        ctx.beginPath(); ctx.moveTo(x - gap + s, G.cy); ctx.lineTo(x, G.cy); ctx.stroke();
      }
      ctx.fillStyle = `rgba(201,133,131,${0.07 * alpha})`;
      ctx.strokeStyle = `rgba(240,201,198,${0.75 * alpha})`;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(x, y, s, s, 8 * G.u); else ctx.rect(x, y, s, s);
      ctx.fill(); ctx.stroke();
      const fill = BLOCKS[k].fill, inner = s - 10 * G.u, fh = Math.max(2 * G.u, inner * fill);
      ctx.fillStyle = fill > 0.5 ? `rgba(240,201,106,${0.7 * alpha})` : `rgba(227,174,176,${0.85 * alpha})`;
      ctx.fillRect(x + 5 * G.u, y + s - 5 * G.u - fh, inner, fh);
    }
    spark(((local * 0.45) % 1) * W, G.cy, 1.8 * G.u, a * 0.9);
  }

  /* ---------- scene 5: an AI decides ---------- */
  function sceneDecide(t) {
    const a = fade(t, 11.5, 14.9, 0.45);
    if (a <= 0) return;
    const ai = [G.cx - 0.13 * W, G.cy], pool = [G.cx + 0.13 * W, G.cy];
    const rush = easeInOut(prog(t, 13.4, 14.0));
    const count = 1 + Math.floor(prog(t, 11.6, 13.3) * 13);
    for (let j = 0; j < count; j += 1) {
      const qx = ai[0] - 70 * G.u - (j % 5) * 22 * G.u, qy = G.cy + (Math.floor(j / 5) - 1) * 22 * G.u;
      let x = qx, y = qy;
      const pj = clamp(rush * 1.6 - j * 0.04);
      if (pj > 0 && pj < 0.5) { const k = pj * 2; x = qx + (ai[0] - qx) * k; y = qy + (ai[1] - qy) * k; }
      if (pj >= 0.5) { const k = (pj - 0.5) * 2; x = ai[0] + (pool[0] - ai[0]) * k; y = ai[1]; }
      const alpha = a * (1 - prog(pj, 0.9, 1));
      ctx.strokeStyle = `rgba(227,174,176,${0.2 * alpha * (1 - rush)})`; ctx.lineWidth = G.u;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(ai[0], ai[1]); ctx.stroke();
      spark(x, y, 1.4 * G.u, alpha);
    }
    ctx.setLineDash([6 * G.u, 8 * G.u]); ctx.lineDashOffset = -t * 60 * G.u;
    ctx.strokeStyle = `rgba(240,201,198,${0.4 * a})`; ctx.lineWidth = 1.2 * G.u;
    ctx.beginPath(); ctx.moveTo(ai[0] + 32 * G.u, ai[1]); ctx.lineTo(pool[0] - 32 * G.u, pool[1]); ctx.stroke();
    ctx.setLineDash([]);
    polygon(ai[0], ai[1], 30 * G.u, 6, t * 0.6, `rgba(240,201,198,${0.55 * a})`, [3 * G.u, 5 * G.u]);
    polygon(ai[0], ai[1], 14 * G.u, 4, 0, `rgba(251,241,240,${0.9 * a})`);
    spark(ai[0], ai[1], 2.2 * G.u, a);
    ring(pool[0], pool[1], 26 * G.u, `rgba(184,111,114,${0.85 * a})`, 2 * G.u);
    spark(pool[0], pool[1], 2 * G.u, a, "232,180,182");
    label("AI", ai[0], ai[1] + 56 * G.u, `rgba(236,211,209,${0.85 * a})`, 9);
    label("POOL", pool[0], pool[1] + 56 * G.u, `rgba(236,211,209,${0.85 * a})`, 9);
    let word = null, since = 0;
    for (const [at, text] of DECISIONS) if (t >= at) { word = text; since = t - at; }
    if (word) {
      const submit = word === "SUBMIT";
      const la = a * Math.min(1, since * 6) * (submit ? 1 : 1 - prog(since, 0.32, 0.48));
      label(submit ? "▲ SUBMIT" : "WAIT", ai[0], ai[1] - 50 * G.u, submit ? `rgba(143,208,168,${la})` : `rgba(251,241,240,${la})`, 12);
    }
    beam(pool[0] + 26 * G.u, pool[1], prog(t, 13.85, 14.2), 1 - prog(t, 14.3, 14.9), a);
    sweep(t, 13.9, 14.9, a);
  }

  /* ---------- scene 6: the mark ---------- */
  function sceneTitle(t) {
    const a = prog(t, 14.5, 15.1);
    if (a <= 0) return;
    for (const s of STREAKS) {
      const x = s.x * W, tw = 0.5 + 0.5 * Math.sin(t * 2 + s.ph * TAU);
      const g = ctx.createLinearGradient(0, 0, 0, G.hz);
      g.addColorStop(0, "rgba(201,133,131,0)");
      g.addColorStop(1, `rgba(227,174,176,${0.16 * s.a * a * tw})`);
      ctx.strokeStyle = g; ctx.lineWidth = G.u;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, G.hz); ctx.stroke();
      spark(x, ((t * s.speed + s.ph) % 1) * G.hz, 1.1 * G.u, 0.8 * a * s.a);
    }
    const k = 3.4 * G.u, ox = G.cx - 16 * k, oy = H * 0.3 - 16 * k;
    ctx.save();
    ctx.translate(ox, oy); ctx.scale(k, k);
    ctx.lineCap = "round"; ctx.lineWidth = 1.3;
    const g = ctx.createLinearGradient(3, 0, 29, 0);
    g.addColorStop(0, "#ffffff"); g.addColorStop(0.5, "#f0c9c6"); g.addColorStop(1, "#b86f72");
    ctx.strokeStyle = g; ctx.shadowColor = "rgba(201,133,131,0.9)"; ctx.shadowBlur = 14 * G.u;
    MARK.forEach((path, j) => {
      const p = easeInOut(prog(t, 14.8 + j * 0.1, 15.9 + j * 0.1));
      if (p <= 0) return;
      ctx.setLineDash([40 * p, 40]);
      ctx.stroke(path);
    });
    ctx.restore();
    const fx = ox + 3 * k, fy = oy + 16 * k;
    const ignite = easeOut(prog(t, 15.8, 16.4));
    spark(fx, fy, (2 + 2.5 * ignite) * G.u, a * (0.3 + 0.7 * ignite));
    const flare = prog(t, LEAVE - 0.25, END);
    if (flare > 0) {
      const r = easeInOut(flare) * Math.hypot(W, H) + 1;
      const f = ctx.createRadialGradient(fx, fy, 0, fx, fy, r);
      f.addColorStop(0, `rgba(251,241,240,${0.55 * (1 - flare)})`);
      f.addColorStop(0.6, `rgba(201,133,131,${0.3 * (1 - flare)})`);
      f.addColorStop(1, "rgba(201,133,131,0)");
      ctx.fillStyle = f; ctx.fillRect(0, 0, W, H);
    }
  }

  /* ---------- captions: tracked letters on the horizon, with a reflection ---------- */
  function letters(str, cls, delay) {
    const el = document.createElement("div");
    el.className = cls;
    const words = str.split(" ");
    let i = 0;
    words.forEach((word, w) => {
      const span = document.createElement("span");
      span.className = "w";
      for (const ch of word) {
        const c = document.createElement("span");
        c.className = "ch"; c.textContent = ch;
        c.style.animationDelay = `${delay + i * 0.03}s`;
        span.appendChild(c); i += 1;
      }
      el.appendChild(span);
      if (w < words.length - 1) { el.appendChild(document.createTextNode(" ")); i += 1; }
    });
    return el;
  }
  function showCaption(c) {
    const cap = document.createElement("div");
    cap.className = `cap${c.title ? " title" : ""}`;
    const top = document.createElement("div");
    top.className = "cap-top";
    const mainDelay = c.eyebrow ? 0.3 : 0;
    if (c.eyebrow) top.appendChild(letters(c.eyebrow, "cap-eyebrow", 0));
    top.appendChild(letters(c.main, "cap-main", mainDelay));
    const bottom = document.createElement("div");
    bottom.className = "cap-bottom";
    bottom.appendChild(letters(c.main, "cap-main cap-reflect", mainDelay));
    if (c.sub) {
      const sub = document.createElement("div");
      sub.className = "cap-sub"; sub.textContent = c.sub;
      bottom.appendChild(sub);
      if (c.count && typeof FX !== "undefined") setTimeout(() => FX.countUp(sub, 1300), 650);
    }
    if (c.meta) {
      const meta = document.createElement("div");
      meta.className = "cap-meta"; meta.textContent = c.meta;
      bottom.appendChild(meta);
    }
    cap.append(top, bottom);
    captionBox.appendChild(cap);
    live.textContent = [c.eyebrow, c.main, c.sub, c.meta].filter(Boolean).join(". ");
  }
  function captionsAt(t) {
    const i = CAPTIONS.findIndex((c) => t >= c.from && t < c.to);
    if (i === current) return;
    current = i;
    captionBox.querySelectorAll(".cap:not(.out)").forEach((old) => {
      old.classList.add("out");
      setTimeout(() => old.remove(), 650);
    });
    if (i >= 0) showCaption(CAPTIONS[i]);
  }

  /* ---------- lifecycle ---------- */
  function resize() {
    dpr = Math.min(2, devicePixelRatio || 1);
    W = innerWidth; H = innerHeight;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
  }
  function frame(now) {
    if (!t0) t0 = now - startAt * 1000;
    const t = (now - t0) / 1000;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    G = { cx: W / 2, cy: H * 0.4, hz: H * 0.6, u: Math.max(0.55, Math.min(W / 1000, H / 640)) };
    background(t);
    ctx.globalCompositeOperation = "lighter";
    sceneSpark(t); sceneOrders(t); scenePool(t); sceneChain(t); sceneDecide(t); sceneTitle(t);
    floor();
    captionsAt(t);
    bar.style.width = `${Math.min(100, (t / END) * 100)}%`;
    if (t >= LEAVE) leave();
    if (t >= END) { finish(); return; }
    raf = requestAnimationFrame(frame);
  }
  let leftAt = 0;
  function leave() {
    if (leaving) return;
    leaving = true;
    leftAt = performance.now();
    root.classList.add("leaving");
    document.body.classList.remove("intro-playing");
    dispatchEvent(new Event("intro:done"));
  }
  function finish() {
    if (done) return;
    done = true;
    cancelAnimationFrame(raf);
    removeEventListener("keydown", onKey);
    removeEventListener("resize", resize);
    leave();
    // remove the overlay once its 0.9 s fade-out has run, however the exit started
    setTimeout(() => root.remove(), Math.max(0, 950 - (performance.now() - leftAt)));
  }
  function skip() {
    if (leaving) return;
    leave();
    setTimeout(finish, 900);
  }
  function onKey(e) {
    const enter = e.key === "Enter" || e.code === "Enter" || e.code === "NumpadEnter" || e.keyCode === 13;
    if (enter || e.key === "Escape" || e.key === " ") { e.preventDefault(); skip(); }
  }

  root.querySelector(".intro-skip").addEventListener("click", skip);
  addEventListener("keydown", onKey);
  addEventListener("resize", resize);
  resize();
  raf = requestAnimationFrame(frame);
})();
