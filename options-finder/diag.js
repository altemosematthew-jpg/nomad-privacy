#!/usr/bin/env node
/* Strike Finder diagnostics: runs the page's engine (read out of the built page, as track.js does) over one scan and prints
   distributions, the top picks with every input, and anything that looks like a data artifact. Read-only: writes nothing.
   Usage: node diag.js <scan.json> <index.html> */
"use strict";
const fs = require("fs"), vm = require("vm");
const [scanPath, pagePath] = process.argv.slice(2);
if (!scanPath || !pagePath) { console.error("usage: node diag.js scan.json index.html"); process.exit(2); }
const html = fs.readFileSync(pagePath, "utf8");
const src = (html.match(/\/\* ENGINE-START[\s\S]*?\/\* ENGINE-END \*\//) || [])[0];
if (!src) { console.error("engine block not found in " + pagePath); process.exit(2); }
const sandbox = { Math, Date, JSON, Object, Array, String, Number, Float64Array, isNaN, isFinite, Infinity, NaN, parseInt, parseFloat };
vm.createContext(sandbox); vm.runInContext(src + "\n;globalThis.__E = Engine;", sandbox);
const E = sandbox.__E;
const scan = JSON.parse(fs.readFileSync(scanPath, "utf8"));
const now = process.env.NOW ? +process.env.NOW : Date.now();
const PLAN = { buy: { target: 0.5, stop: 0.5, hold: 21 }, sell: { target: 0.5, stop: 2.0, hold: 21 } };   // track.js / page defaults
const PATHS = +(process.env.PATHS || 400);

const ok = x => x != null && isFinite(x);
const pc = x => ok(x) ? (x * 100).toFixed(1) + "%" : "–";
const f2 = x => ok(x) ? (+x).toFixed(2) : "–";
const f3 = x => ok(x) ? (+x).toFixed(3) : "–";
const etDay = ms => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date(ms));
function qt(a, p) { const b = a.filter(ok).sort((x, y) => x - y); if (!b.length) return null; return b[Math.min(b.length - 1, Math.max(0, Math.floor(p * b.length)))]; }
function med(a) { return qt(a, 0.5); }
function dist(a, fmt) { fmt = fmt || pc; const b = a.filter(ok); if (!b.length) return "n=0";
  const m = b.reduce((s, x) => s + x, 0) / b.length, pos = b.filter(x => x > 0).length / b.length;
  return `n=${b.length} p5 ${fmt(qt(b, .05))} p25 ${fmt(qt(b, .25))} med ${fmt(qt(b, .5))} p75 ${fmt(qt(b, .75))} p95 ${fmt(qt(b, .95))} mean ${fmt(m)} >0: ${(pos * 100).toFixed(0)}%`; }
function sect(t) { console.log("\n=== " + t + " ==="); }
function safe(name, fn) { try { fn(); } catch (e) { console.log(`!! section ${name} failed: ${e && e.stack ? e.stack.split("\n").slice(0, 3).join(" | ") : e}`); } }

console.log(`scan generated ${scan.generated ? new Date(scan.generated * 1000).toISOString() : "?"} · now ${new Date(now).toISOString()} · ${(scan.symbols || []).length} symbols · errors ${JSON.stringify(scan.errors || {})}`);
const earn = E.earnMap(null, now), raw = {};
for (const S of scan.symbols || []) raw[S.s] = S;
const syms = (scan.symbols || []).map(S => E.analyzeSymbol(S, { now, earn })).filter(Boolean);
const bySym = {}; for (const A of syms) bySym[A.sym] = A;

/* ---------- 1. symbols: spot vs parity, realized vs implied, IV inversion vs source, term structure and events ---------- */
safe("symbols", () => {
  sect("SYMBOLS (spot, parity spot, vols, k at 30d = forecast/implied diffusive vol, event)");
  for (const A of syms) {
    const S = raw[A.sym], ps = E.paritySpot(S, now), h = A.hist || {};
    const atm30 = E.atmIVAt(A.pts, 30 / 365), k30 = A.hv > 0 && atm30 > 0 ? Math.sqrt(E.W_IV + (1 - E.W_IV) * A.hv * A.hv / (atm30 * atm30)) : null;
    const ev = A.ev ? (A.ev.src === "iv" ? `iv-bump ${etDay(A.ev.from)}→${etDay(A.ev.to)}` : `earnings ${A.ev.date} ${A.ev.timing}`) + ` move ±${pc(A.ev.move)} tEv ${f2(A.ev.tEvent * 365)}d` : "none";
    console.log(`${A.sym.padEnd(5)} px ${f2(A.px)} quoted ${f2(A.pxQuoted)} parity ${f2(ps)} (${ps ? pc(ps / A.pxQuoted - 1) : "–"})${A.mismatch ? " MISMATCH→parity" : ""} · stock chg ${f2(A.chg)}% · `
      + `hv20 ${pc(h.hv20)} hv20x ${pc(h.hv20x)} hv60 ${pc(h.hv60)} hv60x ${pc(h.hv60x)} → realized ${pc(A.hv)} · iv30 ${pc(A.iv30)} atm30 ${pc(atm30)} k30 ${f3(k30)} · legs ${A.legs.length} dropped ${A.dropped} · trend ${A.trend} · event ${ev}`);
    // inverted IV (engine, from mid) vs source IV (Cboe), near-the-money, by type and by expiry
    const rowsC = [], rowsP = [], itmP = [], itmC = [], byExp = {};
    for (const L of A.legs) {
      if (!(L.ivSrc > 0) || L.dte < 7 || L.dte > 120) continue;
      const r = L.iv / L.ivSrc - 1, ad = Math.abs(L.delta);
      if (ad >= 0.25 && ad <= 0.75) { (L.isC ? rowsC : rowsP).push(r); const k = etDay(L.exp); (byExp[k] || (byExp[k] = { C: [], P: [] }))[L.type].push(r); }
      if (!L.isC && ad > 0.75) itmP.push(r); if (L.isC && ad > 0.75) itmC.push(r);
    }
    const ex = Object.keys(byExp).sort().map(k => `${k.slice(5)} C${pc(med(byExp[k].C))}/P${pc(med(byExp[k].P))}`).join(" ");
    console.log(`      inverted/source IV −1 (|Δ| .25–.75): calls ${pc(med(rowsC))} (n${rowsC.length}) puts ${pc(med(rowsP))} (n${rowsP.length}) · ITM puts ${pc(med(itmP))} (n${itmP.length}) ITM calls ${pc(med(itmC))} (n${itmC.length}) | by exp: ${ex}`);
    let prev = 0, t0 = 0; const ts = [];
    for (const p of A.pts) { const v = p.iv * p.iv * p.T, fv = v > prev ? Math.sqrt((v - prev) / Math.max(p.T - t0, 1e-6)) : 0; ts.push(`${etDay(p.exp).slice(5)}(${(p.T * 365).toFixed(1)}d) ${pc(p.iv)} fwd ${pc(fv)}`); prev = Math.max(v, prev); t0 = p.T; }
    console.log(`      term: ${ts.join(" · ")}`);
  }
});

/* ---------- 2. every structure the tracker could pick, all four categories, with plans simulated for all ---------- */
const CATS = [{ cat: "single-buy", struct: "single", side: "buy", n: 4 }, { cat: "single-sell", struct: "single", side: "sell", n: 0 },
  { cat: "spread-buy", struct: "spread", side: "buy", n: 3 }, { cat: "spread-sell", struct: "spread", side: "sell", n: 3 }];
function build(list, paths, seedSuffix) {
  const out = {};
  for (const C of CATS) {
    const d = E.STRUCT_DEFAULTS[C.struct + "|" + C.side];
    const f = { types: "both", dteMin: 14, dteMax: 90, dMin: d.dMin, dMax: d.dMax, maxPrice: 2000, minOI: 300, maxSpread: d.maxSpread / 100, evMode: "all" };
    const rows = [];
    for (const A of list) { const l2 = C.struct === "single" ? A.legs.map(L => E.makeSingle(L, A, C.side)) : E.verticals(A, C.side, f); for (const st of l2) if (E.prefilter(st, f)) rows.push(st); }
    for (const st of rows) {
      st.plan = E.simulate(st, PLAN[C.side], paths, st.sym + "|" + st.exp + "|" + C.side + (seedSuffix || ""));
      const G = E.grade(st); st.grade = G.g; st.fails = G.fails; st.cat = C.cat;
      st.planEvPct = st.plan && st.price > 0 ? st.plan.ev / (st.risk > 0 ? st.risk : st.price) : null;
      st.skew = st.atm > 0 ? st.iv / st.atm : null;
    }
    out[C.cat] = rows;
  }
  return out;
}
const t0 = Date.now();
const ROWS = build(syms, PATHS);
console.log(`\n(simulated ${Object.values(ROWS).reduce((s, r) => s + r.length, 0)} structures × ${PATHS} paths in ${((Date.now() - t0) / 1000).toFixed(1)} s)`);

function describe(st) {
  const L = st.raw.map((r, i) => `${r.occ} b/a ${f2(r.bid)}/${f2(r.ask)} iv ${pc(r.iv)} src ${pc(r.ivSrc)} Δ ${f2(r.delta)} oi ${r.oi} vol ${r.vol} sigF ${pc(st.legs[i].sigF)}`).join(" || ");
  const sp = st.kind === "spread" ? ` width ${f2(st.width)} maxGain ${f2(st.maxGain)} maxLoss ${f2(st.maxLoss)} rr ${f2(st.rr)}${st.creditPct != null ? " credit% " + pc(st.creditPct) : ""}` : "";
  const ev = st.evt ? ` EVENT(${st.evt.src} move ${pc(st.evt.move)})` : "";
  const p = st.plan || {};
  return `${st.sym} ${st.cat} ${st.type}${st.K}${st.K2 != null ? "/" + st.K2 : ""} ${etDay(st.exp)} (${f2(st.dte)}d) S ${f2(st.S)}${bySym[st.sym] && bySym[st.sym].mismatch ? "(parity; quoted " + f2(bySym[st.sym].pxQuoted) + ")" : ""}`
    + ` | bid/ask ${f2(st.bid)}/${f2(st.ask)} mid ${f2(st.mid)} fill ${f3(st.price)} fair ${f3(st.fair)} EV ${f3(st.ev)} EV% ${pc(st.evPct)}${sp}`
    + ` | iv ${pc(st.iv)} atm ${pc(st.atm)} realized ${pc(st.hv)} sigPath ${pc(st.sigPath)} k ${f3(st.k)}${ev}`
    + ` | plan win ${pc(p.pWin)} tgt ${pc(p.pTarget)} stop ${pc(p.pStop)} time ${pc(p.pTime)} planEV ${f3(p.ev)} (${pc(st.planEvPct)}) | pop ${pc(st.pop)} theoEdge ${pc(st.theoEdge)} spr% ${pc(st.spreadPct)} θ% ${pc(st.thetaPct)} trendFit ${st.trendFit} grade ${st.grade}${st.fails.length ? " fails " + st.fails.join(",") : ""}`
    + `\n        legs: ${L}`;
}

/* ---------- 3. distributions ---------- */
safe("distributions", () => {
  sect("DISTRIBUTIONS (prefiltered as track.js: DTE 14–90, delta per STRUCT_DEFAULTS, OI ≥ 300; plan simulated for all)");
  for (const C of CATS) {
    const rows = ROWS[C.cat], g = { A: 0, B: 0, C: 0, "–": 0 }, fails = {};
    for (const st of rows) { g[st.grade]++; for (const k of st.fails) fails[k] = (fails[k] || 0) + 1; }
    console.log(`\n## ${C.cat}: ${rows.length} rows · grades ${JSON.stringify(g)} · fails ${JSON.stringify(fails)}`);
    console.log(`  EV%        ${dist(rows.map(r => r.evPct))}`);
    console.log(`  plan EV%   ${dist(rows.map(r => r.planEvPct))}`);
    console.log(`  plan win   ${dist(rows.map(r => r.plan && r.plan.pWin))}`);
    console.log(`  k          ${dist(rows.map(r => r.k), f3)}`);
    for (const T of ["C", "P"]) { const s = rows.filter(r => r.type === T);
      console.log(`  [${T}] n${s.length} EV% med ${pc(med(s.map(r => r.evPct)))} · planEV% med ${pc(med(s.map(r => r.planEvPct)))} · win med ${pc(med(s.map(r => r.plan && r.plan.pWin)))} · A ${s.filter(r => r.grade === "A").length}`); }
    for (const [a, b] of [[14, 30], [30, 60], [60, 91]]) { const s = rows.filter(r => r.dte >= a && r.dte < b);
      console.log(`  [${a}-${b}d] n${s.length} EV% med ${pc(med(s.map(r => r.evPct)))} · planEV% med ${pc(med(s.map(r => r.planEvPct)))} · win med ${pc(med(s.map(r => r.plan && r.plan.pWin)))} · A ${s.filter(r => r.grade === "A").length}`); }
    for (const [a, b] of [[0, 0.9], [0.9, 1.0], [1.0, 1.1], [1.1, 1.3], [1.3, 9]]) { const s = rows.filter(r => r.skew >= a && r.skew < b);
      console.log(`  [iv/atm ${a}-${b}] n${s.length} EV% med ${pc(med(s.map(r => r.evPct)))} · planEV% med ${pc(med(s.map(r => r.planEvPct)))} · win med ${pc(med(s.map(r => r.plan && r.plan.pWin)))} · A ${s.filter(r => r.grade === "A").length}`); }
    const per = {};
    for (const st of rows) (per[st.sym] || (per[st.sym] = [])).push(st);
    console.log("  per symbol: " + Object.keys(per).sort().map(s => { const a = per[s];
      return `${s} n${a.length} EV ${pc(med(a.map(r => r.evPct)))} pEV ${pc(med(a.map(r => r.planEvPct)))} win ${pc(med(a.map(r => r.plan && r.plan.pWin)))} A${a.filter(r => r.grade === "A").length}`; }).join(" | "));
  }
});

/* ---------- 4. the sim's own calibration: the same structures with forecast vol forced equal to implied (k = 1) ---------- */
safe("k1", () => {
  sect("SIM CALIBRATION (k forced to 1: static EV is exactly −quarter spread; a consistent sim should give plan EV ≈ the same cost)");
  for (const C of CATS) {
    const rows = ROWS[C.cat], out = [];
    for (const st of rows) {
      const s2 = Object.assign({}, st); s2.legs = st.legs.map(l => Object.assign({}, l)); s2.hv = Math.sqrt(Math.max(st.atmDiff * st.atmDiff, 1e-8));
      E.volModel(s2); const p = E.simulate(s2, PLAN[C.side], PATHS, st.sym + "|" + st.exp + "|" + C.side);
      if (!p) continue; out.push({ st, pev: p.ev / (st.risk > 0 ? st.risk : st.price), win: p.pWin, cost: -(st.hs * E.FILL) / (st.risk > 0 ? st.risk : st.price) });
    }
    console.log(`## ${C.cat}: plan EV% at k=1 ${dist(out.map(o => o.pev))} · win ${dist(out.map(o => o.win))} · entry cost% med ${pc(med(out.map(o => o.cost)))}`);
    for (const T of ["C", "P"]) for (const [a, b] of [[0, 0.95], [0.95, 1.05], [1.05, 1.2], [1.2, 9]]) {
      const s = out.filter(o => o.st.type === T && o.st.skew >= a && o.st.skew < b); if (!s.length) continue;
      console.log(`   [${T} iv/atm ${a}-${b}] n${s.length} planEV%@k1 med ${pc(med(s.map(o => o.pev)))} win@k1 med ${pc(med(s.map(o => o.win)))}`);
    }
  }
});

/* ---------- 5. top 10 per category, built the way track.js builds its picks ---------- */
safe("top", () => {
  sect("TOP 10 PER CATEGORY (grade A, scored on the 'durable' lens among A rows, as track.js does; * = would be logged)");
  for (const C of CATS) {
    const rows = ROWS[C.cat].filter(st => st.grade === "A");
    E.scoreRows(rows, "durable"); rows.sort((a, b) => b.score - a.score);
    const used = new Set();
    console.log(`\n## ${C.cat}: ${rows.length} grade-A`);
    rows.slice(0, 10).forEach((st, i) => {
      let star = ""; if (used.size < C.n && !used.has(st.sym)) { used.add(st.sym); star = "*"; }
      console.log(`${star}${i + 1}. score ${f3(st.score)} ` + describe(st));
    });
    const cnt = {}; for (const st of rows) cnt[st.sym] = (cnt[st.sym] || 0) + 1;
    console.log(`   A by symbol: ${JSON.stringify(cnt)} · A by type: C ${rows.filter(r => r.isC).length} P ${rows.filter(r => !r.isC).length}`);
  }
});

/* ---------- 6. outliers ---------- */
safe("outliers", () => {
  sect("|EV%| > 15% (all categories)");
  for (const C of CATS) {
    const s = ROWS[C.cat].filter(r => ok(r.evPct) && Math.abs(r.evPct) > 0.15).sort((a, b) => Math.abs(b.evPct) - Math.abs(a.evPct));
    const cnt = {}; for (const st of s) { const k = st.sym + ":" + st.type; cnt[k] = (cnt[k] || 0) + 1; }
    console.log(`## ${C.cat}: ${s.length} rows · by symbol:type ${JSON.stringify(cnt)} · grades ${JSON.stringify(s.reduce((o, r) => (o[r.grade] = (o[r.grade] || 0) + 1, o), {}))}`);
    s.slice(0, 8).forEach(st => console.log("  " + describe(st)));
  }
  sect("INVERTED IV FAR FROM SOURCE IV (|iv/src −1| > 20%, legs with DTE 7–120 and |Δ| .1–.8; > 60% were already dropped)");
  const far = [];
  for (const A of syms) for (const L of A.legs) if (L.ivSrc > 0 && L.dte >= 7 && L.dte <= 120 && Math.abs(L.delta) >= 0.1 && Math.abs(L.delta) <= 0.8 && Math.abs(L.iv / L.ivSrc - 1) > 0.2) far.push(L);
  const cnt = {}; for (const L of far) { const k = L.sym + ":" + L.type + (L.iv > L.ivSrc ? "+" : "-"); cnt[k] = (cnt[k] || 0) + 1; }
  console.log(`${far.length} legs · ${JSON.stringify(cnt)} · dropped per symbol ${JSON.stringify(syms.reduce((o, A) => (A.dropped && (o[A.sym] = A.dropped), o), {}))}`);
  far.sort((a, b) => Math.abs(b.iv / b.ivSrc - 1) - Math.abs(a.iv / a.ivSrc - 1)).slice(0, 25).forEach(L =>
    console.log(`  ${L.occ} S ${f2(L.S)} K ${L.K} ${f2(L.dte)}d b/a ${f2(L.bid)}/${f2(L.ask)} last ${f2(L.last)} theo ${f2(L.theo)} iv ${pc(L.iv)} src ${pc(L.ivSrc)} Δ ${f2(L.delta)} oi ${L.oi} vol ${L.vol}`));
});

/* ---------- 7. spreads with inconsistent prices ---------- */
safe("spreads", () => {
  sect("SPREAD CONSISTENCY");
  const bad = [];
  for (const cat of ["spread-buy", "spread-sell"]) for (const st of ROWS[cat]) {
    const a = st.raw[0], b = st.raw[1], why = [];
    const intr = E.intrinsic(st.legs, st.S), lo = Math.max(0, intr * Math.exp(-E.R * st.T)), w = st.width;
    if (st.bid > st.ask + 1e-9) why.push("bid>ask");
    if (st.mid < st.bid - 1e-9 || st.mid > st.ask + 1e-9) why.push("mid outside");
    if (st.price > w + 1e-9 || st.price < 0) why.push("price outside [0,width]");
    if (st.maxGain < 0 || st.maxLoss < 0) why.push("negative maxGain/maxLoss");
    if (Math.abs(st.maxGain + st.maxLoss - w) > 1e-6) why.push("gain+loss≠width");
    if (st.fair < -1e-6 || st.fair > w + 1e-6) why.push("fair outside [0,width]");
    if (st.ask < lo - 0.02) why.push(`ask ${f2(st.ask)} < discounted intrinsic ${f2(lo)}`);
    if (st.bid > w * Math.exp(-E.R * st.T) + 0.02) why.push("bid > PV(width)");
    if (a.bid > a.ask || b.bid > b.ask) why.push("crossed leg");
    if (st.side === "sell" && st.creditPct > 0.5 && intr <= 0) why.push(`OTM credit ${pc(st.creditPct)} of width`);
    if (st.side === "buy" && st.price < 0.2 * w && intr > 0.5 * w) why.push("ITM debit spread under 20% of width");
    if (why.length) bad.push({ st, why });
  }
  console.log(`${bad.length} inconsistent of ${ROWS["spread-buy"].length + ROWS["spread-sell"].length}`);
  const cnt = {}; for (const x of bad) for (const w of x.why) { const k = w.replace(/[\d.]+/g, "#"); cnt[k] = (cnt[k] || 0) + 1; }
  console.log(JSON.stringify(cnt));
  bad.slice(0, 15).forEach(x => console.log(`  [${x.why.join("; ")}] ` + describe(x.st)));
  // A-grade spreads where the static EV and the simulated plan disagree in sign by a lot
  const dis = [];
  for (const cat of ["spread-buy", "spread-sell", "single-buy", "single-sell"]) for (const st of ROWS[cat]) if (st.grade === "A" && ok(st.planEvPct) && ok(st.evPct) && st.planEvPct - st.evPct > 0.10) dis.push(st);
  console.log(`A-grade with plan EV% − static EV% > 10 points: ${dis.length}`);
  dis.sort((a, b) => (b.planEvPct - b.evPct) - (a.planEvPct - a.evPct)).slice(0, 8).forEach(st => console.log("  " + describe(st)));
});

/* ---------- 8. events per symbol vs the earnings calendar ---------- */
safe("events", () => {
  sect("EVENTS");
  console.log("calendar (future only): " + JSON.stringify(Object.keys(earn).map(s => s + " " + earn[s].date + " " + earn[s].timing)));
  for (const A of syms) {
    const S = raw[A.sym], noE = !!E.NO_EARNINGS[A.sym];
    const det = E.detectEvent(A.pts, null, now);   // what the IV detector alone would say
    console.log(`${A.sym.padEnd(5)} used: ${A.ev ? A.ev.src + " " + (A.ev.src === "iv" ? etDay(A.ev.from) + "→" + etDay(A.ev.to) : A.ev.date) + " ±" + pc(A.ev.move) : "none"}${noE ? " (fund: detector off)" : ""} · IV detector alone: ${det ? etDay(det.from) + "→" + etDay(det.to) + " ±" + pc(det.move) : "none"} · stock chg ${f2(S.chg)}% ivchg ${f2(S.ivchg)}%`);
  }
});
console.log("\ndone");
/* ---------- 9. the same scan with the stock price replaced by the options' own parity spot ---------- */
safe("parity", () => {
  sect("RE-RUN WITH PARITY SPOT FORCED FOR EVERY SYMBOL (isolates the stock-quote/option-quote mismatch)");
  const syms2 = (scan.symbols || []).map(S => { const ps = E.paritySpot(S, now); return E.analyzeSymbol(Object.assign({}, S, { px: ps || S.px }), { now, earn }); }).filter(Boolean);
  console.log("inverted/source IV −1, |Δ| .25–.75, calls/puts: " + syms2.map(A => { const c = [], p = [];
    for (const L of A.legs) if (L.ivSrc > 0 && L.dte >= 7 && L.dte <= 120 && Math.abs(L.delta) >= .25 && Math.abs(L.delta) <= .75) (L.isC ? c : p).push(L.iv / L.ivSrc - 1);
    return `${A.sym} ${pc(med(c))}/${pc(med(p))} drop${A.dropped}`; }).join(" | "));
  const R2 = build(syms2, PATHS);
  for (const C of CATS) {
    const rows = R2[C.cat], g = { A: 0, B: 0, C: 0, "–": 0 }; for (const st of rows) g[st.grade]++;
    console.log(`## ${C.cat}: ${rows.length} rows · grades ${JSON.stringify(g)} · EV% med ${pc(med(rows.map(r => r.evPct)))} · planEV% med ${pc(med(rows.map(r => r.planEvPct)))}`);
    for (const T of ["C", "P"]) { const s = rows.filter(r => r.type === T);
      console.log(`  [${T}] n${s.length} EV% med ${pc(med(s.map(r => r.evPct)))} · planEV% med ${pc(med(s.map(r => r.planEvPct)))} · win med ${pc(med(s.map(r => r.plan && r.plan.pWin)))} · A ${s.filter(r => r.grade === "A").length}`); }
    const A = rows.filter(st => st.grade === "A"); E.scoreRows(A, "durable"); A.sort((a, b) => b.score - a.score);
    const cnt = {}; for (const st of A) cnt[st.sym] = (cnt[st.sym] || 0) + 1;
    console.log(`  A by symbol ${JSON.stringify(cnt)}`);
    A.slice(0, 5).forEach((st, i) => console.log(`  ${i + 1}. ${st.sym} ${st.type}${st.K}${st.K2 != null ? "/" + st.K2 : ""} ${etDay(st.exp)} S ${f2(st.S)} fill ${f3(st.price)} fair ${f3(st.fair)} EV% ${pc(st.evPct)} iv ${pc(st.iv)} atm ${pc(st.atm)} win ${pc(st.plan.pWin)} planEV% ${pc(st.planEvPct)}`));
  }
  // what happened to the main run's top picks
  for (const C of CATS) {
    const A = ROWS[C.cat].filter(st => st.grade === "A"); E.scoreRows(A, "durable"); A.sort((a, b) => b.score - a.score);
    const by = new Map(R2[C.cat].map(st => [st.id, st]));
    console.log(`  ${C.cat} main-run top 6 under parity spot: ` + A.slice(0, 6).map(st => { const t = by.get(st.id);
      return `${st.sym} ${st.type}${st.K}${st.K2 != null ? "/" + st.K2 : ""} ${etDay(st.exp).slice(5)}: EV ${pc(st.evPct)}→${t ? pc(t.evPct) : "gone"} win ${pc(st.plan.pWin)}→${t ? pc(t.plan.pWin) : "–"} planEV ${pc(st.planEvPct)}→${t ? pc(t.planEvPct) : "–"} grade A→${t ? t.grade : "–"}`; }).join(" | "));
  }
});

/* ---------- 10. Monte Carlo noise in the plan numbers that grade and rank the picks ---------- */
safe("noise", () => {
  sect("PLAN NOISE: main-run top 8 A per category re-simulated with 4 other seeds (400 paths) and once with 8000 paths");
  for (const C of CATS) {
    const A = ROWS[C.cat].filter(st => st.grade === "A"); E.scoreRows(A, "durable"); A.sort((a, b) => b.score - a.score);
    const thr = C.side === "sell" ? E.ODDS.sell : C.struct === "spread" ? E.ODDS.spreadBuy : E.ODDS.singleBuy;
    let flips = 0;
    const lines = A.slice(0, 8).map(st => {
      const den = st.risk > 0 ? st.risk : st.price, w = [], e = [];
      for (let k = 1; k <= 4; k++) { const p = E.simulate(st, PLAN[C.side], 400, st.sym + "|" + st.exp + "|" + C.side + "#" + k); w.push(p.pWin); e.push(p.ev / den); }
      const big = E.simulate(st, PLAN[C.side], 8000, st.id + "|big");
      if (big.pWin < thr) flips++;
      return `${st.sym} ${st.type}${st.K}${st.K2 != null ? "/" + st.K2 : ""} ${etDay(st.exp).slice(5)} win ${pc(st.plan.pWin)} [${w.map(pc).join(" ")}] 8k ${pc(big.pWin)} · planEV ${pc(st.planEvPct)} [${e.map(pc).join(" ")}] 8k ${pc(big.ev / den)}`;
    });
    console.log(`## ${C.cat} (odds threshold ${pc(thr)}; ${flips} of ${lines.length} fall below it at 8000 paths)`);
    lines.forEach(l => console.log("  " + l));
  }
});
console.log("\ndone2");
/* ---------- 11. A grades by symbol and expiry (calendar cross-check) ---------- */
safe("byexp", () => {
  sect("A GRADES BY SYMBOL|EXPIRY");
  for (const C of CATS) { const cnt = {}; for (const st of ROWS[C.cat]) if (st.grade === "A") { const k = st.sym + "|" + etDay(st.exp).slice(5); cnt[k] = (cnt[k] || 0) + 1; }
    console.log(`## ${C.cat}: ${JSON.stringify(cnt)}`); }
  const mu = []; for (const C of CATS) for (const st of ROWS[C.cat]) if (st.sym === "MU" && st.grade === "A" && etDay(st.exp) >= "2026-12-16") mu.push(st);
  console.log(`MU A-grade rows expiring on/after 2026-12-16 (earnings.json date; engine seed says 12-23): ${mu.length}`);
  mu.slice(0, 6).forEach(st => console.log("  " + describe(st).split("\n")[0]));
});
console.log("\ndone3");


