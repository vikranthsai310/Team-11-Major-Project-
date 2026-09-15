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

  /* ---------- overview background: living light strands ----------
     Strands fan out of a bright point, glowing orbs drift through them, and as the page
     scrolls the whole bundle changes shape: fan → pinched thread → twisted hourglass →
     looping ribbon → rising burst. Every shape is a set of points along each strand, so
     any two shapes blend smoothly into each other. */
  function mulberry(seed) {
    return () => {
      seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function fibers(canvas) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const rand = mulberry(11);
    const TAU = Math.PI * 2, K = 40, SHAPES = 5;
    const P = new Float64Array(2), Q = new Float64Array(2), pts = new Float64Array((K + 1) * 2);
    // where each shape is brightest (x, y as fractions of the screen) and how hot that point glows
    const HOT = [[0.04, 0.5, 1], [0.5, 0.5, 0.8], [0.43, 0.5, 0.55], [0.17, 0.65, 0.3], [0.5, 0.97, 0.9]];
    const DIM = [1, 0.8, 0.75, 0.85, 0.8];
    // overall light level of the strands, sparks, orbs and glow (1 = full); 0.98 is 2 % dimmer
    const BRIGHTNESS = 0.98;
    // on the data pages the strands move between two signature shapes as the page scrolls,
    // and sit dimmer behind the tables and charts
    const ROUTES = { run: [1, 2], compare: [3, 4], live: [2, 1] };
    const PAGE_DIM = 0.35;
    let w = 0, h = 0, strands = [], pulses = [], orbs = [], stops = [0, 1, 2, 3, 4], page = "how", end = 1;
    let raf = null, last = performance.now(), stage = 0, pageDim = 1, mx = 0, my = 0, mxT = 0, myT = 0;
    const t0 = performance.now();

    function build() {
      const n = w < 700 ? 120 : 200;
      strands = Array.from({ length: n }, () => {
        const u = rand() - 0.5;
        return {
          spread: Math.sign(u) * Math.pow(Math.abs(u) * 2, 1.3) * 0.5,
          bend: rand() - 0.5, phase: rand() * TAU, speed: 0.12 + rand() * 0.3,
          width: 0.4 + rand() * 1.3, rose: rand() > 0.7, alpha: 0.16 + rand() * 0.55, reach: rand(), lane: rand(),
        };
      });
      pulses = Array.from({ length: Math.round(n * 0.2) }, () => ({ s: (rand() * n) | 0, p: rand(), v: 0.06 + rand() * 0.14 }));
      orbs = Array.from({ length: w < 700 ? 8 : 16 }, () => ({
        x: 0.3 + rand() * 0.75, y: rand(), r: 12 + rand() * 58, depth: 0.2 + rand() * 0.8,
        ph: rand() * TAU, sp: 0.05 + rand() * 0.12, a: 0.07 + rand() * 0.2,
      }));
    }

    // which page is showing, and on the overview the scroll positions at which each shape is
    // fully formed: the hero, then each section
    function measure() {
      const active = document.querySelector(".tab[data-active]");
      page = active ? active.id.replace("tab-", "") : "how";
      end = Math.max(1, document.documentElement.scrollHeight - innerHeight);
      if (page !== "how") return;
      const blocks = [...document.querySelectorAll("#tab-how .block")].slice(0, 3);
      const s = [0, ...blocks.map((b) => b.getBoundingClientRect().top + scrollY - innerHeight * 0.45), end];
      for (let k = 1; k < s.length; k += 1) s[k] = Math.max(s[k], s[k - 1] + 1);
      stops = s;
    }
    function targetStage() {
      const route = ROUTES[page];
      if (route) {
        const e = Math.min(1, Math.max(0, scrollY / end));
        return route[0] + (route[1] - route[0]) * e * e * (3 - 2 * e);
      }
      for (let k = 0; k < stops.length - 1; k += 1) {
        if (scrollY < stops[k + 1]) {
          const f = (scrollY - stops[k]) / (stops[k + 1] - stops[k]);
          const e = Math.min(1, Math.max(0, (f - 0.2) / 0.6)); // hold each shape, then blend
          return Math.min(SHAPES - 1, k + e * e * (3 - 2 * e));
        }
      }
      return SHAPES - 1;
    }

    function point(shape, st, s, t, out) {
      const wob = Math.sin(t * st.speed + st.phase);
      if (shape === 0) { // a fan out of a bright point on the left
        const fx = w * 0.04, fy = h * (0.5 + my * 0.03);
        const c1y = fy + st.spread * h * 0.18 + wob * h * 0.008;
        const c2y = fy + st.spread * h * (1.45 + st.bend * 0.5) + wob * h * 0.035;
        const ex = w * (0.72 + st.reach * 0.4), ey = fy + st.spread * h * 2.6 + wob * h * 0.025;
        const u = 1 - s, a = u * u * u, b = 3 * u * u * s, c = 3 * u * s * s, d = s * s * s;
        out[0] = a * fx + b * w * 0.22 + c * w * 0.48 + d * ex;
        out[1] = a * fy + b * c1y + c * c2y + d * ey;
      } else if (shape === 1) { // a bundle pinched into one thread, then fanned out again
        const g = s < 0.38 ? Math.pow(1 - s / 0.38, 2) * 1.1 : s < 0.58 ? 0.004 : Math.pow((s - 0.58) / 0.42, 1.8) * 1.6;
        out[0] = -0.05 * w + s * 1.1 * w;
        out[1] = h * 0.5 + st.spread * h * g * (1 + wob * 0.08);
      } else if (shape === 2) { // a twisted hourglass beam running diagonally
        const width = Math.min(w, h * 1.4) * 0.22 * (0.1 + Math.pow(Math.abs(s - 0.5) * 2, 1.4));
        const off = st.spread * 2 * width * Math.cos(st.phase + s * 4 + t * 0.35);
        out[0] = w * (0.18 + s * 0.5) + off * 0.92;
        out[1] = h * (-0.12 + s * 1.24) - off * 0.39;
      } else if (shape === 3) { // one glowing ribbon looping across the page
        const a = s * TAU * 1.25 + 0.6 + t * 0.12;
        const off = st.spread * 22 * (0.6 + 0.4 * Math.sin(s * 9 + st.phase));
        out[0] = w * (0.06 + 0.88 * s) + w * 0.13 * Math.cos(a) + off * Math.sin(a);
        out[1] = h * 0.52 + h * 0.24 * Math.sin(a) * (1 - 0.35 * s) + off * Math.cos(a);
      } else { // rays rising from the bottom edge, like an iris
        const theta = Math.PI * (1.04 + st.lane * 0.92);
        const r = h * (0.04 + s * (0.5 + st.reach * 0.25)) * (1 + wob * 0.02);
        out[0] = w * 0.5 + Math.cos(theta) * r * 1.25;
        out[1] = h * 0.97 + Math.sin(theta) * r;
      }
    }
    function blended(st, s, t, a, b, m, out) {
      point(a, st, s, t, out);
      if (m > 0.001) {
        point(b, st, s, t, Q);
        out[0] += (Q[0] - out[0]) * m;
        out[1] += (Q[1] - out[1]) * m;
      }
    }

    function frame(now, still = false) {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const t = (now - t0) / 1000;
      mx += (mxT - mx) * 0.05; my += (myT - my) * 0.05;
      const target = targetStage();
      stage = still ? target : stage + (target - stage) * 0.08;
      const a = Math.min(SHAPES - 1, Math.floor(stage)), b = Math.min(SHAPES - 1, a + 1), m = stage - a;
      const mix = (i) => HOT[a][i] + (HOT[b][i] - HOT[a][i]) * m;
      pageDim += ((page === "how" ? 1 : PAGE_DIM) - pageDim) * (still ? 1 : 0.06);
      const light = BRIGHTNESS * pageDim;
      const hx = w * mix(0), hy = h * mix(1), heat = mix(2) * light, dim = (DIM[a] + (DIM[b] - DIM[a]) * m) * light;

      ctx.clearRect(0, 0, w, h);
      ctx.globalCompositeOperation = "lighter";
      const R = Math.max(w, h) * 0.95;
      const warm = ctx.createRadialGradient(hx, hy, 0, hx, hy, R);
      warm.addColorStop(0, "rgba(255,245,244,1)");
      warm.addColorStop(0.07, "#f0c9c6");
      warm.addColorStop(0.3, "#c98583");
      warm.addColorStop(0.65, "#8e4a4e");
      warm.addColorStop(1, "rgba(142,74,78,0.05)");
      const rose = ctx.createRadialGradient(hx, hy, 0, hx, hy, R);
      rose.addColorStop(0, "rgba(255,236,234,1)");
      rose.addColorStop(0.08, "#e3aeb0");
      rose.addColorStop(0.35, "#8e4a4e");
      rose.addColorStop(0.75, "#5c2a2e");
      rose.addColorStop(1, "rgba(142,74,78,0.05)");
      ctx.lineCap = "round";
      for (const st of strands) {
        for (let j = 0; j <= K; j += 1) {
          blended(st, j / K, t, a, b, m, P);
          pts[j * 2] = P[0]; pts[j * 2 + 1] = P[1];
        }
        ctx.strokeStyle = st.rose ? rose : warm;
        ctx.globalAlpha = st.alpha * dim;
        ctx.lineWidth = st.width;
        ctx.beginPath();
        ctx.moveTo(pts[0], pts[1]);
        for (let j = 1; j <= K; j += 1) ctx.lineTo(pts[j * 2], pts[j * 2 + 1]);
        ctx.stroke();
      }

      // sparks travel along the strands toward the bright point: orders flowing into a batch
      for (const p of pulses) {
        if (!still) p.p += p.v * dt;
        if (p.p > 1) { p.p = 0; p.s = (Math.random() * strands.length) | 0; }
        const st = strands[p.s];
        if (!st) continue;
        blended(st, 1 - p.p, t, a, b, m, P);
        const al = Math.sin(p.p * Math.PI) * dim;
        ctx.globalAlpha = 0.16 * al;
        ctx.fillStyle = "#f0c9c6";
        ctx.beginPath(); ctx.arc(P[0], P[1], 5, 0, TAU); ctx.fill();
        ctx.globalAlpha = 0.95 * al;
        ctx.fillStyle = "#ffffff";
        ctx.beginPath(); ctx.arc(P[0], P[1], 1.3, 0, TAU); ctx.fill();
      }

      // soft glowing orbs drifting at different depths, with scroll and mouse parallax
      const orbVis = 1 - Math.min(1, stage) * 0.35, span = h + 240;
      ctx.globalAlpha = 1;
      for (const o of orbs) {
        const x = (o.x + Math.sin(t * o.sp + o.ph) * 0.03) * w + mx * o.depth * 24;
        let y = (o.y * span - scrollY * o.depth * 0.3 + Math.cos(t * o.sp * 0.8 + o.ph) * 14) % span;
        if (y < 0) y += span;
        y -= 120;
        const r = o.r * (w < 700 ? 0.7 : 1), al = o.a * orbVis * light;
        const g = ctx.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0, `rgba(255,238,236,${al * 1.3})`);
        g.addColorStop(0.5, `rgba(240,201,198,${al * 0.55})`);
        g.addColorStop(1, "rgba(201,133,131,0)");
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.fill();
        if (o.depth > 0.65) {
          ctx.strokeStyle = `rgba(255,240,238,${al * 0.5})`;
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.arc(x, y, r * 0.9, 0, TAU); ctx.stroke();
        }
      }

      const glow = ctx.createRadialGradient(hx, hy, 0, hx, hy, Math.max(80, h * 0.22));
      glow.addColorStop(0, `rgba(250,232,230,${0.55 * heat})`);
      glow.addColorStop(0.35, `rgba(201,133,131,${0.18 * heat})`);
      glow.addColorStop(1, "rgba(201,133,131,0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, w, h);
      ctx.globalCompositeOperation = "source-over";
    }

    function loop(now) {
      // every page has the strands; only the intro covers them
      if (!document.body.classList.contains("intro-playing")) frame(now);
      else last = now;
      raf = requestAnimationFrame(loop);
    }
    function sync() {
      const run = !document.hidden && !reduced;
      if (run && raf === null) { last = performance.now(); raf = requestAnimationFrame(loop); }
      if (!run && raf !== null) { cancelAnimationFrame(raf); raf = null; }
    }
    function resize() {
      const dpr = Math.min(2, devicePixelRatio || 1);
      w = innerWidth; h = innerHeight;
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (!strands.length) build();
      measure();
      frame(performance.now(), true);
    }

    addEventListener("resize", resize);
    // cards revealing, data loading and tab switches all move the sections
    new ResizeObserver(measure).observe(document.body);
    // switching pages moves the active tab; re-read which page's shapes to show
    new MutationObserver(measure).observe(document.querySelector("main"), { attributes: true, subtree: true, attributeFilter: ["data-active"] });
    addEventListener("scroll", () => { if (reduced) frame(performance.now(), true); }, { passive: true });
    addEventListener("pointermove", (e) => {
      mxT = (e.clientX / innerWidth - 0.5) * 2;
      myT = (e.clientY / innerHeight - 0.5) * 2;
    }, { passive: true });
    document.addEventListener("visibilitychange", sync);
    resize();
    sync();
  }

  return { scramble, countUp, drawIn, observe, moveIndicator, fibers, reduced };
})();
