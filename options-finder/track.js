#!/usr/bin/env node
/* Strike Finder track record. Runs once per trading day (GitHub Actions, ~2:45 PM ET), no Claude involved:
     1. marks every open pick at today's quotes and closes it when the default plan says so;
     2. logs today's top A-grade picks from the same engine the page uses.
   Usage: node track.js <scan.json> <ledger.json> <index.html> */
"use strict";
const fs = require("fs"), vm = require("vm");
const [scanPath, ledgerPath, pagePath] = process.argv.slice(2);
if (!scanPath || !ledgerPath || !pagePath) { console.error("usage: node track.js scan.json ledger.json index.html"); process.exit(2); }

// The engine is read out of the built page, so the picks are graded by exactly the code people see.
const html = fs.readFileSync(pagePath, "utf8");
const src = (html.match(/\/\* ENGINE-START[\s\S]*?\/\* ENGINE-END \*\//) || [])[0];
if (!src) { console.error("engine block not found in " + pagePath); process.exit(2); }
const sandbox = { Math, Date, JSON, Object, Array, String, Number, Float64Array, isNaN, isFinite, Infinity, NaN, parseInt, parseFloat };
vm.createContext(sandbox); vm.runInContext(src + "\n;globalThis.__E = Engine;", sandbox);
const E = sandbox.__E;
// Upcoming earnings: the daily job's options-finder/earnings.json when present, over the engine's built-in seed.
let EARN = null;
try { const j = JSON.parse(fs.readFileSync(require("path").join(__dirname, "earnings.json"), "utf8")); if (j && j.d) EARN = { asOf: j.asOf, d: Object.assign({}, E.EARNINGS_SEED.d, j.d) }; } catch (e) { /* no file: the seed */ }

const HOLIDAYS = new Set(["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
  "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"]);
const PLAN = { buy: { target: 0.5, stop: 0.5, hold: 21 }, sell: { target: 0.5, stop: 2.0, hold: 21 } };   // the page's defaults
const CATS = [{ cat: "single-buy", struct: "single", side: "buy", n: 4 }, { cat: "spread-buy", struct: "spread", side: "buy", n: 3 }, { cat: "spread-sell", struct: "spread", side: "sell", n: 3 }];
const now = Date.now();
const etDay = ms => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date(ms));
const etWeekday = ms => new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short" }).format(new Date(ms));
const etMinutes = ms => { const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "numeric", hour12: false }).formatToParts(new Date(ms));
  const g = k => +((parts.find(x => x.type === k) || {}).value || 0); return (g("hour") % 24) * 60 + g("minute"); };
const today = etDay(now), tradingDay = !/Sat|Sun/.test(etWeekday(now)) && !HOLIDAYS.has(today);
const inSession = tradingDay && etMinutes(now) >= 9 * 60 + 45 && etMinutes(now) <= 16 * 60 + 15;   // only log or mark on live quotes
const DRY = !!process.env.DRY_RUN;
const daysBetween = (a, b) => Math.round((Date.parse(b + "T12:00:00Z") - Date.parse(a + "T12:00:00Z")) / 864e5);
const r4 = x => x == null || !isFinite(x) ? null : Math.round(x * 1e4) / 1e4;

const scan = JSON.parse(fs.readFileSync(scanPath, "utf8"));
const ledger = fs.existsSync(ledgerPath) ? JSON.parse(fs.readFileSync(ledgerPath, "utf8")) : { version: 1, created: today, picks: [] };
for (const p of ledger.picks) if (p.stop == null) p.stop = p.side === "buy" ? -1 : Infinity;   // "no stop" is stored as null (JSON has no Infinity)
ledger.rules = { plan: PLAN, entry: "limit fill halfway between mid and natural", marks: "once a day at about 2:45 PM ET, same fill model", source: "Cboe delayed quotes (15 min)" };

// quotes and spot prices for marking
const quote = new Map(), spot = {};
for (const S of scan.symbols || []) {
  const A = E.analyzeSymbol(S, { now, earn: {} }); spot[S.s] = A ? A.px : +S.px;
  for (const o of S.o) quote.set(o[0], { bid: +o[1] || 0, ask: +o[2] || 0 });
}
function comboValue(p) {   // what closing would get (buy) or cost (sell) per share today, with the same fill model as entries
  let bid = 0, ask = 0;
  for (const l of p.legs) { const q = quote.get(l.occ); if (!q || !(q.ask > 0)) return null; if (l.q > 0) { bid += q.bid; ask += q.ask; } else { bid -= q.ask; ask -= q.bid; } }
  bid = Math.max(0, bid); const mid = (bid + ask) / 2, hs = (ask - bid) / 2;
  const v = p.side === "buy" ? Math.max(0, mid - E.FILL * hs) : Math.max(0, mid + E.FILL * hs);
  return p.width ? Math.min(v, p.width) : v;   // a vertical is never worth more than its width
}
function intrinsicNow(p) { const S = spot[p.sym]; if (!(S > 0)) return null; let v = 0; for (const l of p.legs) v += l.q * Math.max(0, l.isC ? S - l.K : l.K - S); return Math.max(0, v); }
function close(p, status, v) {
  p.status = status; p.exit = r4(v); p.closed = today;
  p.pl = r4(p.side === "buy" ? v - p.entry : p.entry - v); p.plPct = r4(p.risk > 0 ? p.pl / p.risk : null);
}

// 1. mark open picks
let marked = 0, closed = 0;
for (const p of ledger.picks) {
  if (p.status !== "open") continue;
  if (today > p.exp) { const v = intrinsicNow(p); close(p, "expired", v != null ? v : (p.marks.length ? p.marks[p.marks.length - 1].v : 0)); closed++; continue; }
  if (!inSession || p.date === today) continue;
  const v = comboValue(p); if (v == null) continue;
  if (!p.marks.length || p.marks[p.marks.length - 1].d !== today) p.marks.push({ d: today, v: r4(v), px: r4(spot[p.sym]) });
  marked++;
  const held = daysBetween(p.date, today), buy = p.side === "buy";
  if (buy ? v >= p.target : v <= p.target) { close(p, "target", v); closed++; }
  else if (buy ? v <= p.stop : v >= p.stop) { close(p, "stop", v); closed++; }
  else if (held >= p.hold || today >= p.closeBy) { close(p, "time", v); closed++; }
}

// 2. today's picks (also computed in a dry run, for the diagnostics)
function computePicks() {
  const earn = E.earnMap(EARN, now), syms = (scan.symbols || []).map(S => E.analyzeSymbol(S, { now, earn })).filter(Boolean);
  const openIds = new Set(ledger.picks.filter(p => p.status === "open").map(p => p.structId)), picks = [], stats = {};
  for (const C of CATS) {
    const d = E.STRUCT_DEFAULTS[C.struct + "|" + C.side];
    const f = { types: "both", dteMin: 14, dteMax: 90, dMin: d.dMin, dMax: d.dMax, maxPrice: 2000, minOI: 300, maxSpread: d.maxSpread / 100, evMode: "all" };
    let rows = [];
    for (const A of syms) { const list = C.struct === "single" ? A.legs.map(L => E.makeSingle(L, A, C.side)) : E.verticals(A, C.side, f); for (const st of list) if (E.prefilter(st, f)) rows.push(st); }
    const nFilt = rows.length;
    rows = rows.filter(st => { st.plan = null; return E.grade(st).fails.filter(k => k !== "odds").length === 0; });
    for (const st of rows) { st.plan = E.simulate(st, PLAN[C.side], 400, st.sym + "|" + st.exp + "|" + C.side); const G = E.grade(st); st.grade = G.g; }
    rows = rows.filter(st => st.grade === "A");
    stats[C.cat] = { filtered: nFilt, gradeA: rows.length };
    E.scoreRows(rows, "durable"); rows.sort((a, b) => b.score - a.score);
    const used = new Set();
    for (const st of rows) {
      if (used.size >= C.n) break; if (used.has(st.sym) || openIds.has(st.id)) continue; used.add(st.sym);
      const lv = E.planLevels(st, PLAN[C.side]), expD = etDay(st.exp), mon = new Date(st.exp).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/New_York" });
      const k = x => (x % 1 ? x.toFixed(2) : String(x));
      const label = st.kind === "single" ? `${st.sym} ${mon} $${k(st.K)} ${st.isC ? "Call" : "Put"}` : `${st.sym} ${mon} $${k(st.K)}/$${k(st.K2)} ${st.isC ? "Call" : "Put"} ${C.side === "buy" ? "debit" : "credit"} spread`;
      picks.push({ id: today + "|" + C.cat + "|" + st.id, structId: st.id, date: today, cat: C.cat, side: C.side, kind: st.kind, sym: st.sym, label, exp: expD,
        legs: st.legs.map((l, i) => ({ occ: st.raw[i].occ, q: l.q, K: l.K, isC: l.isC })), entry: r4(lv.entry), target: r4(lv.target), stop: isFinite(lv.stop) ? r4(lv.stop) : null,
        hold: PLAN[C.side].hold, closeBy: etDay(now + PLAN[C.side].hold * 864e5), risk: r4(st.risk), width: st.width || null, px: r4(st.S), grade: st.grade, score: r4(st.score),
        ev: r4(st.ev), evPct: r4(st.evPct), pWin: r4(st.plan.pWin), planEv: r4(st.plan.ev), pop: r4(st.pop), iv: r4(st.iv), sigPath: r4(st.sigPath),
        status: "open", marks: [], exit: null, pl: null, plPct: null, closed: null });
    }
  }
  return { picks, stats, syms };
}
let added = 0;
if (inSession && !ledger.picks.some(p => p.date === today)) { const r = computePicks(); r.picks.forEach(p => ledger.picks.push(p)); added = r.picks.length; }
if (DRY) {
  const r = computePicks(), pc = x => x == null ? "–" : (x * 100).toFixed(1) + "%";
  console.log("--- symbols ---");
  for (const A of r.syms) console.log(`${A.sym.padEnd(5)} $${A.px.toFixed(2)}${A.mismatch ? " (stock quote $" + A.pxQuoted.toFixed(2) + " out of sync)" : ""} · realized ${pc(A.hv)} · iv30 ${pc(A.iv30)} · ${A.legs.length} legs${A.dropped ? " (" + A.dropped + " dropped)" : ""} · trend ${A.trend} · event ${A.ev ? (A.ev.src === "iv" ? etDay(A.ev.from) + "→" + etDay(A.ev.to) : "earnings " + etDay(A.ev.at)) + " ±" + pc(A.ev.move) : "none"}`);
  console.log("--- would log ---", JSON.stringify(r.stats));
  for (const p of r.picks) console.log(`${p.cat.padEnd(12)} ${p.label.padEnd(46)} entry ${p.entry} · EV ${pc(p.evPct)} · plan win ${pc(p.pWin)} · plan EV $${(p.planEv * 100).toFixed(0)} · P(profit) ${pc(p.pop)}`);
}
ledger.updated = new Date(now).toISOString();
const out = JSON.stringify(ledger, (k, v) => (v === Infinity ? null : v), 1);
if (!DRY) fs.writeFileSync(ledgerPath, out + "\n");
console.log(`${today}${inSession ? "" : " (outside market hours: nothing logged or marked)"}${DRY ? " [dry run, ledger not written]" : ""}: ${scan.symbols ? scan.symbols.length : 0} symbols · marked ${marked} · closed ${closed} · added ${added} · ${ledger.picks.length} picks total`);

