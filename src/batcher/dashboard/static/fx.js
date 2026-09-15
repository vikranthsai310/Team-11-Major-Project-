"use strict";
/* Visual effects for the dashboard: the hero light strands, text decoding, number
   count-ups, scroll reveals and the sliding nav indicator. Nothing here reads data;
   app.js calls these after it renders. Every effect respects prefers-reduced-motion. */
const FX = (() => {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789#%&*+<>/";

  /* ---------- decode a heading: glyphs settle left to right ---------- */
  function scramble(el, duration = 850) {
    if (!el) return;
    const lines = el.querySelectorAll(".line").length ? [...el.querySelectorAll(".line")] : [el];
    lines.forEach((node) => { if (!node.dataset.text) node.dataset.text = node.textContent; });
    if (!el.hasAttribute("aria-label")) el.setAttribute("aria-label", lines.map((n) => n.dataset.text).join(" "));
    lines.forEach((node, li) => {
      const final = node.dataset.text;
      cancelAnimationFrame(node._raf);
      if (reduced) { node.textContent = final; return; }
      const start = performance.now() + li * 180;
      const step = (now) => {
        const t = Math.max(0, (now - start) / duration);
        const settled = Math.floor(t * final.length);
        let out = "";
        for (let i = 0; i < final.length; i += 1) {
          const ch = final[i];
          out += i < settled || ch === " " ? ch : GLYPHS[(Math.random() * GLYPHS.length) | 0];
        }
        node.textContent = t >= 1 ? final : out;
        if (t < 1) node._raf = requestAnimationFrame(step);
      };
      node._raf = requestAnimationFrame(step);
    });
  }

  /* ---------- count the first number in an element up from zero ---------- */
  function countUp(el, duration = 1200) {
    if (!el || reduced) return;
    const final = el.dataset.final || el.textContent;
    el.dataset.final = final;
    const m = final.match(/\d[\d,]*(\.\d+)?/);
    if (!m) return;
    const target = parseFloat(m[0].replace(/,/g, ""));
    const decimals = m[1] ? m[1].length - 1 : 0;
    const commas = m[0].includes(",");
    const before = final.slice(0, m.index), after = final.slice(m.index + m[0].length);
    const fmt = (v) => (commas
      ? v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
      : v.toFixed(decimals));
    const t0 = performance.now();
    cancelAnimationFrame(el._count);
    const step = (now) => {
      const p = Math.min(1, (now - t0) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = p >= 1 ? final : before + fmt(target * eased) + after;
      if (p < 1) el._count = requestAnimationFrame(step);
    };
    el._count = requestAnimationFrame(step);
  }

  /* ---------- draw an SVG polyline in from left to right ---------- */
  function drawIn(polyline, duration = 1100, delay = 0) {
    const full = polyline.getAttribute("points") || "";
    if (reduced || !full) return;
    const pts = full.trim().split(/\s+/);
    const t0 = performance.now() + delay;
    polyline.setAttribute("points", pts[0]);
    const step = (now) => {
      const p = Math.max(0, Math.min(1, (now - t0) / duration));
      const eased = 1 - Math.pow(1 - p, 3);
      polyline.setAttribute("points", pts.slice(0, Math.max(1, Math.ceil(eased * pts.length))).join(" "));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  /* ---------- reveal on scroll ---------- */
  const io = "IntersectionObserver" in window
    ? new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("in");
        entry.target.querySelectorAll("[data-count]").forEach((n) => countUp(n));
        io.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -30px 0px" })
    : null;
  function observe(root = document) {
    root.querySelectorAll(".reveal:not(.in)").forEach((n) => (io && !reduced ? io.observe(n) : n.classList.add("in")));
  }

  /* ---------- nav ---------- */
  function moveIndicator() {
    const nav = document.querySelector(".tabs");
    const indicator = nav && nav.querySelector(".tab-indicator");
    const selected = nav && nav.querySelector('button[aria-selected="true"]');
    if (!indicator || !selected) return;
    // on narrow screens the tab strip scrolls; bring the selected tab into view
    const overflowLeft = selected.offsetLeft - nav.scrollLeft;
    if (overflowLeft < 0 || overflowLeft + selected.offsetWidth > nav.clientWidth) {
      nav.scrollTo({ left: selected.offsetLeft - (nav.clientWidth - selected.offsetWidth) / 2, behavior: reduced ? "auto" : "smooth" });
    }
    indicator.style.width = `${selected.offsetWidth}px`;
    indicator.style.transform = `translateX(${selected.offsetLeft}px)`;
    indicator.style.opacity = "1";
  }
  addEventListener("resize", moveIndicator);
  addEventListener("scroll", () => document.querySelector(".nav")?.classList.toggle("scrolled", scrollY > 8), { passive: true });

  /* ---------- hero: many orders converging into one batch ---------- */
  function mulberry(seed) {
    return () => {
      seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function bezier(p, t) {
    const u = 1 - t, a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t;
    return [a * p[0] + b * p[2] + c * p[4] + d * p[6], a * p[1] + b * p[3] + c * p[5] + d * p[7]];
  }

  function fibers(canvas) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const rand = mulberry(11);
    let w = 0, h = 0, strands = [], pulses = [], gradA = null, gradB = null;
    let raf = null, visible = true, last = performance.now(), mouse = 0, mouseTarget = 0;
    const t0 = performance.now();

    function build() {
      const n = w < 700 ? 120 : 210;
      strands = Array.from({ length: n }, () => {
        const u = rand();
        return {
          spread: (u - 0.5) * (0.4 + rand() * 0.9),
          bend: rand() - 0.5, phase: rand() * Math.PI * 2, speed: 0.12 + rand() * 0.3,
          width: 0.4 + rand() * 1.4, blue: rand() > 0.7, alpha: 0.18 + rand() * 0.6, reach: rand(),
          pts: null,
        };
      });
      pulses = Array.from({ length: Math.round(n * 0.22) }, () => ({ s: (rand() * n) | 0, p: rand(), v: 0.07 + rand() * 0.16 }));
    }

    function resize() {
      const dpr = Math.min(2, devicePixelRatio || 1);
      const r = canvas.getBoundingClientRect();
      if (!r.width || !r.height) return;
      w = r.width; h = r.height;
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const fx = w * 0.04;
      gradA = ctx.createLinearGradient(fx, 0, w, 0);
      gradA.addColorStop(0, "rgba(250,247,255,1)");
      gradA.addColorStop(0.07, "#c4b5fd");
      gradA.addColorStop(0.3, "#9f67ff");
      gradA.addColorStop(0.65, "#6d28d9");
      gradA.addColorStop(1, "rgba(76,29,149,0.04)");
      gradB = ctx.createLinearGradient(fx, 0, w, 0);
      gradB.addColorStop(0, "rgba(236,246,255,1)");
      gradB.addColorStop(0.08, "#a5b4fc");
      gradB.addColorStop(0.35, "#6366f1");
      gradB.addColorStop(0.75, "#3730a3");
      gradB.addColorStop(1, "rgba(14,165,233,0.04)");
      if (!strands.length) build();
      frame(performance.now(), true);
    }

    function frame(now, still = false) {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const t = (now - t0) / 1000;
      mouse += (mouseTarget - mouse) * 0.04;
      ctx.clearRect(0, 0, w, h);
      ctx.globalCompositeOperation = "lighter";
      const fx = w * 0.04, fy = h * (0.5 + mouse * 0.04);
      for (const s of strands) {
        const wob = Math.sin(t * s.speed + s.phase);
        const ex = w * (0.72 + s.reach * 0.4);
        const ey = fy + s.spread * h * 1.7 + wob * h * 0.025;
        const c1x = w * 0.22, c1y = fy + s.spread * h * 0.12 + wob * h * 0.008;
        const c2x = w * 0.48, c2y = fy + s.spread * h * (0.95 + s.bend * 0.35) + wob * h * 0.035;
        s.pts = [fx, fy, c1x, c1y, c2x, c2y, ex, ey];
        ctx.strokeStyle = s.blue ? gradB : gradA;
        ctx.globalAlpha = s.alpha;
        ctx.lineWidth = s.width;
        ctx.beginPath();
        ctx.moveTo(fx, fy);
        ctx.bezierCurveTo(c1x, c1y, c2x, c2y, ex, ey);
        ctx.stroke();
      }
      // pulses travel inward: orders flowing into a single batch
      for (const p of pulses) {
        if (!still) p.p += p.v * dt;
        if (p.p > 1) { p.p = 0; p.s = (Math.random() * strands.length) | 0; }
        const s = strands[p.s];
        if (!s || !s.pts) continue;
        const [x, y] = bezier(s.pts, 1 - p.p);
        const a = Math.sin(p.p * Math.PI);
        ctx.globalAlpha = 0.16 * a;
        ctx.fillStyle = s.blue ? "#93c5fd" : "#c4b5fd";
        ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill();
        ctx.globalAlpha = 0.95 * a;
        ctx.fillStyle = "#ffffff";
        ctx.beginPath(); ctx.arc(x, y, 1.3, 0, Math.PI * 2); ctx.fill();
      }
      const glow = ctx.createRadialGradient(fx, fy, 0, fx, fy, Math.max(80, h * 0.22));
      glow.addColorStop(0, "rgba(237,233,254,0.55)");
      glow.addColorStop(0.35, "rgba(139,92,246,0.18)");
      glow.addColorStop(1, "rgba(139,92,246,0)");
      ctx.globalAlpha = 1;
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, w, h);
      ctx.globalCompositeOperation = "source-over";
    }

    function loop(now) {
      frame(now);
      raf = requestAnimationFrame(loop);
    }
    function sync() {
      const run = visible && !document.hidden && !reduced;
      if (run && raf === null) { last = performance.now(); raf = requestAnimationFrame(loop); }
      if (!run && raf !== null) { cancelAnimationFrame(raf); raf = null; }
    }

    new ResizeObserver(resize).observe(canvas);
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(([e]) => { visible = e.isIntersecting; sync(); }).observe(canvas);
    }
    document.addEventListener("visibilitychange", sync);
    canvas.parentElement.addEventListener("pointermove", (e) => {
      const r = canvas.getBoundingClientRect();
      mouseTarget = ((e.clientY - r.top) / r.height - 0.5) * 2;
    });
    sync();
  }

  return { scramble, countUp, drawIn, observe, moveIndicator, fibers, reduced };
})();
