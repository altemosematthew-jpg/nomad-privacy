/* Strike Finder app: data (public server, or Robinhood real-time inside Claude), the ranked table, the details panel,
   positions, and the track record. All analytics live in Engine. */
(function () {
"use strict";
const E = Engine;
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (n, d = 2) => (n == null || isNaN(n)) ? "–" : Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (n, d = 1, sign = false) => (n == null || isNaN(n)) ? "–" : (sign && n > 0 ? "+" : "") + (n * 100).toFixed(d) + "%";
const money = (n, d = 2) => (n == null || isNaN(n)) ? "–" : (n < 0 ? "−$" : "$") + fmt(Math.abs(n), d);
const sgnMoney = (n, d = 0) => (n == null || isNaN(n)) ? "–" : (n > 0 ? "+" : "") + money(n, d);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const RH_CHAIN = s => "https://robinhood.com/options/chains/" + encodeURIComponent(s);
const RH_STOCK = s => "https://robinhood.com/us/en/stocks/" + encodeURIComponent(s) + "/";
const RH = "ROBINHOOD_CONNECTOR";
const PUBLIC = "https://strike-finder.onrender.com";
const IN_CLAUDE = !!(window.claude && typeof window.claude.use === "function");
const WATCH = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "NFLX", "AVGO", "COIN", "PLTR", "SOFI", "F", "BAC", "INTC", "HOOD", "MRVL", "MU", "UBER", "ARM"];
const CORE = ["SPY", "QQQ", "NVDA", "AMZN", "MSFT", "AAPL", "TSLA", "META"];
const HIST = new Map();            // occ -> this session's scan-by-scan record, for the consistency stat
const TABLE_PATHS = 400, DRAWER_PATHS = 4000;
const JOURNAL = true;              // "My trades" journal (Claude version only, needs the db + user capabilities); false switches it off everywhere

const state = {
  data: null, mode: null, syms: [], ver: 0, selected: new Set(), firstLoad: true,
  lens: "durable", side: "buy", struct: "single", type: "both", evMode: "all", quality: "ab", sortK: "score", sortDir: -1, sel: null,
  plan: { buy: Object.assign({}, E.PLAN_DEFAULTS.buy), sell: Object.assign({}, E.PLAN_DEFAULTS.sell) },
  touched: {}, earn: E.earnMap(null, Date.now()), earnVer: 0, apiBase: null,
  mcp: null, busy: false, lastTick: 0, rt: new Map(), rtLoading: null, rtFail: new Map(), rtRange: null, rtAbort: null, accounts: null, extra: [],
  simCache: new Map(), structCache: { key: null, list: [] }, rows: [], filteredCount: 0, qualityCount: 0, track: null, mcpChecked: false,
  jr: { ready: false, col: null, readonly: false, loaded: false, trades: [], quotes: new Map(), qAt: 0, qBusy: false, qErr: "", err: "", open: false, mode: {}, formRow: null }
};

/* ---------- small helpers ---------- */
function setStatus(text, kind) { $("#status-text").textContent = text; $("#dot").className = "dot" + (kind ? " " + kind : ""); }
const stamp = ts => new Date(ts).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const ago = t => { const s = Math.max(0, Math.round((Date.now() - t) / 1000)); return s < 60 ? s + "s" : s < 3600 ? Math.round(s / 60) + " min" : Math.round(s / 3600) + " h"; };
const day = ts => new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/New_York" });
const dayNum = ts => new Date(ts).toLocaleDateString("en-US", { month: "numeric", day: "numeric", year: "numeric", timeZone: "America/New_York" });
const strikeTxt = K => fmt(K, K % 1 ? 2 : 0);
function marketHours() {
  try {
    const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", hour: "numeric", minute: "numeric", hour12: false }).formatToParts(new Date());
    const g = k => (parts.find(x => x.type === k) || {}).value; const t = (+g("hour") % 24) * 60 + +g("minute");
    return !/Sat|Sun/.test(g("weekday")) && t >= 9 * 60 + 25 && t <= 16 * 60 + 20;
  } catch (e) { return true; }
}
async function pool(items, n, fn) {
  const out = new Array(items.length); let i = 0;
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => { while (i < items.length) { if (state.rtAbort) return; const k = i++; out[k] = await fn(items[k], k); } }));
  return out;
}
function loadNum(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : +v; } catch (e) { return d; } }
function saveNum(k, v) { try { localStorage.setItem(k, String(v)); } catch (e) {} }
function structName(st) {
  const kind = st.isC ? "Call" : "Put";
  if (st.kind === "single") return `${st.sym} ${dayNum(st.exp)} $${strikeTxt(st.K)} ${kind}`;
  return `${st.sym} ${dayNum(st.exp)} $${strikeTxt(st.K)}/$${strikeTxt(st.K2)} ${kind} ${st.side === "buy" ? "debit" : "credit"} spread`;
}
function evtLabel(ev) {
  if (!ev) return "";
  if (ev.src === "calendar") return "Earnings " + day(ev.at) + (ev.timing === "am" ? " before the open" : ev.timing === "pm" ? " after the close" : "") + (ev.verified ? "" : " (date not confirmed)") + (ev.move ? ` · implied move ±${pct(ev.move, 1)}` : "");
  return `Event priced in between ${day(ev.from)} and ${day(ev.to)} · implied move ±${pct(ev.move, 1)}`;
}

/* ---------- data in ---------- */
function setData(symbols, meta) {
  state.data = Object.assign({ symbols }, meta);
  const have = new Set(symbols.map(S => S.s));
  if (state.firstLoad) { state.selected = new Set(have); state.firstLoad = false; }
  else { symbols.forEach(S => { if (!state.knownSyms || !state.knownSyms.has(S.s)) state.selected.add(S.s); }); for (const s of [...state.selected]) if (!have.has(s)) state.selected.delete(s); }
  state.knownSyms = have;
  reanalyze(); renderSymbols(); build(); if (state.sel) select(state.sel, true);
  renderFooter();
}
function reanalyze() {   // per-symbol cache: only symbols whose quotes, history or earnings changed are recomputed
  const now = Date.now(), ctx = { now, earn: state.earn };
  state.syms = state.data.symbols.map(S => {
    const key = [S.fetched || 0, S.px, S.__mut || 0, S.hist ? 1 : 0, state.earnVer].join("|");
    if (S.__A && S.__key === key && now - S.__at < 60000) return S.__A;
    const A = E.analyzeSymbol(S, ctx); S.__A = A; S.__key = key; S.__at = now;
    if (A) for (const L of A.legs) recordHist(L);
    return A;
  }).filter(Boolean);
  state.ver++; state.structCache.key = null;
  if (state.simCache.size > 60000) state.simCache.clear();
}
function recordHist(L) {
  let d = HIST.get(L.occ); if (!d) { d = []; HIST.set(L.occ, d); }
  const now = Date.now(); if (d.length && now - d[d.length - 1].t < 50000) return;
  const tb = L.theo > 0 && L.ask > 0 ? (L.theo - L.ask) / L.ask : null, ts = L.theo > 0 ? (L.bid - L.theo) / L.theo : null;
  d.push({ t: now, tb, ts, sp: L.mid > 0 ? (L.ask - L.bid) / L.mid : null }); if (d.length > 36) d.shift();
}
function stabOf(A, st) {
  const occ = st.raw[0].occ, sv = A.stab && A.stab[occ], d = HIST.get(occ) || [];
  if (sv && sv[0] > d.length) return { n: sv[0], pos: st.side === "buy" ? sv[2] : sv[4], sp: sv[5], src: "server" };
  const k = st.side === "buy" ? "tb" : "ts", a = d.map(x => x[k]).filter(v => v != null);
  return { n: d.length, pos: a.length ? a.filter(v => v > 0).length / a.length : null, sp: null, src: "session" };
}
function renderFooter() {
  const d = state.data; if (!d) return;
  const src = state.mode === "rt" ? "Robinhood real-time quotes (your account, in your browser)" : state.mode === "snapshot" ? "an old built-in snapshot (Cboe delayed quotes)" : (d.source || "Cboe delayed quotes (15 min)");
  const n = state.syms.reduce((t, A) => t + A.legs.length, 0);
  $("#foot-src").textContent = `Source: ${src} · ${state.syms.length} symbols · ${n.toLocaleString()} contracts · as of ${stamp(d.generated || Date.now())}` + (d.errors && Object.keys(d.errors).length ? " · failed: " + Object.keys(d.errors).join(", ") : "");
}
function liveLabel() {
  if (state.mode === "rt") {
    const n = state.rt.size, L = state.rtLoading;
    return `Live · Robinhood real-time · ${n} symbol${n === 1 ? "" : "s"}` + (L ? ` · loading ${L.done}/${L.total}…` : "") + ` · updated ${ago(state.lastTick || Date.now())} ago` + (marketHours() ? "" : " · market closed");
  }
  if (!state.data) return "Loading…";
  if (state.mode === "snapshot") return `Old snapshot from ${stamp(state.data.generated)} · Robinhood isn't available in this view`;
  return `Live · Cboe delayed 15 min · ${state.data.symbols.length} symbols · as of ${stamp(state.data.generated)}`;
}
async function fetchJSON(url, ms) {
  const ctl = typeof AbortController !== "undefined" ? new AbortController() : null; const timer = setTimeout(() => ctl && ctl.abort(), ms);
  try { const r = await fetch(url, { cache: "no-store", mode: "cors", signal: ctl ? ctl.signal : undefined }); if (!r.ok) throw new Error("HTTP " + r.status); return await r.json(); }
  finally { clearTimeout(timer); }
}
function serverBases() { return /^https?:$/.test(location.protocol) ? ["", PUBLIC] : [PUBLIC]; }
async function loadServer() {
  for (const base of (state.apiBase != null ? [state.apiBase] : serverBases())) {
    try {
      if (base) setStatus("Waking the live server (free tier, the first load can take ~45 s)…", "snap");
      const j = await fetchJSON(base + "/api/scan", base ? 90000 : 8000);
      if (!j || !Array.isArray(j.symbols) || !j.symbols.length) throw new Error("empty");
      state.apiBase = base; state.mode = "server";
      setData(j.symbols, { generated: (j.generated || Date.now() / 1000) * 1000, source: j.source, errors: j.errors });
      setStatus(liveLabel(), "live"); return true;
    } catch (e) { /* next source */ }
  }
  setStatus(state.data ? "Refresh failed; still showing data from " + stamp(state.data.generated) : "Couldn't reach the data server. Refresh to try again (the free server can take a minute to wake).", state.data ? "snap" : "");
  return false;
}

/* ---------- Robinhood real-time (Claude version; calls run in your browser with your login) ---------- */
function unwrap(r) {
  let p = r; if (p && p.payload !== undefined) p = p.payload;
  if (typeof p === "string") { try { p = JSON.parse(p); } catch (e) {} }
  if (p && Array.isArray(p.content)) { const t = p.content.find(c => c && c.type === "text"); if (t) { try { p = JSON.parse(t.text); } catch (e) { p = t.text; } } }
  if (p && p.error) throw Object.assign(new Error(typeof p.error === "string" ? p.error : (p.error.message || JSON.stringify(p.error))), { code: "tool_error" });
  if (p && p.data !== undefined) p = p.data; return p || {};
}
const AUTH_CODES = { needs_reauth: "Reconnect Robinhood in claude.ai Settings → Connectors, then reload this page.", server_not_connected: "Add the Robinhood connector in claude.ai Settings → Connectors, then reload.",
  not_in_manifest: "Robinhood access is turned off for this page. Turn it on from the page's Permissions menu, then reload.", approval_required: "This page needs your approval to read Robinhood. Reload and choose Allow.",
  selection_required: "Choose which Robinhood connection to use when claude.ai asks, then reload.", blocked_by_policy: "Your organization's policy blocks this Robinhood tool here.",
  not_granted: "Robinhood isn't available in this view.", capability_disabled: "Robinhood isn't available in this view." };
async function rhCall(tool, input, cacheMs) {
  const opts = cacheMs === false ? { cache: false } : cacheMs ? { cache: { staleTime: cacheMs, gcTime: Math.max(cacheMs, 300000) } } : undefined;
  for (let tries = 0; ; tries++) {
    try { return unwrap(await state.mcp.callTool(RH, tool, input || {}, opts)); }
    catch (e) { if (e && e.retryable && tries < 1) { await sleep(Math.min(60000, e.retryAfterMs || 900) + Math.random() * 700); continue; } throw e; }
  }
}
function etDateMs(d) { return E.etTime(+d.slice(0, 4), +d.slice(5, 7), +d.slice(8, 10), 16, 0); }
function pickExpirations(dates, dteMin, dteMax, now) {
  const xs = dates.map(d => ({ d, t: etDateMs(d) })).map(x => Object.assign(x, { dte: (x.t - now) / 864e5 })).filter(x => x.dte >= Math.max(1, dteMin) && x.dte <= dteMax);
  const has = new Set(dates);
  const monthly = x => { const dt = new Date(x.t), dd = dt.getUTCDate(), wd = dt.getUTCDay(); if (wd === 5) return dd >= 15 && dd <= 21;
    if (wd === 4) { const fri = new Date(x.t + 864e5).toISOString().slice(0, 10); return dd + 1 >= 15 && dd + 1 <= 21 && !has.has(fri); } return false; };
  const pick = xs.filter(monthly).slice(0, 4);
  const rest = xs.filter(x => !pick.includes(x));
  while (pick.length < 6 && rest.length) {   // fill gaps: the expiry farthest from anything already picked
    let bi = 0, bd = -1; rest.forEach((x, i) => { const dmin = pick.length ? Math.min(...pick.map(p => Math.abs(p.dte - x.dte))) : x.dte; if (dmin > bd) { bd = dmin; bi = i; } });
    pick.push(rest.splice(bi, 1)[0]);
  }
  return pick.sort((a, b) => a.dte - b.dte).map(x => x.d);
}
async function rhInstruments(chainId, exp, type, lo, hi) {
  const out = []; let cursor, guard = 0;
  do {
    const r = await rhCall("get_option_instruments", Object.assign({ chain_id: chainId, expiration_dates: exp, type }, cursor ? { cursor } : {}), 12 * 3600e3);
    let maxK = -Infinity;
    for (const it of (r.instruments || r.results || [])) {
      const K = +it.strike_price; if (K > maxK) maxK = K;
      if (it.tradability === "tradable" && it.state !== "inactive" && it.expiration_date === exp && K >= lo && K <= hi) out.push({ id: it.id, K, exp: it.expiration_date, type: it.type });
    }
    cursor = r.next; if (maxK > hi) break;     // instruments arrive in strike order: stop once past the range
  } while (cursor && ++guard < 12);
  return out;
}
function thin(list, px) {   // keep a strike grid about 1.2% of the price apart (plus the strikes at the money); dense chains like SPY get thinned
  const steps = [0.5, 1, 2.5, 5, 10, 25, 50, 100], want = px * 0.012, step = steps.find(s => s >= want) || 100;
  const Ks = [...new Set(list.map(x => x.K))].sort((a, b) => a - b); if (Ks.length < 2) return list;
  let native = Infinity; for (let i = 1; i < Ks.length; i++) native = Math.min(native, Ks[i] - Ks[i - 1]);
  if (native >= step * 0.99) return list;
  return list.filter(x => Math.abs(x.K / step - Math.round(x.K / step)) < 1e-6 || Math.abs(x.K - px) < step / 2);
}
function rowFromQuote(sym, it, u) {
  const bid = +u.bid_price || 0, ask = +u.ask_price || 0; if (!(ask > 0)) return null;
  const [y, m, d] = it.exp.split("-"), occ = sym + y.slice(2) + m + d + (it.type === "call" ? "C" : "P") + String(Math.round(it.K * 1000)).padStart(8, "0");
  return [occ, bid, ask, +u.bid_size || 0, +u.ask_size || 0, +u.implied_volatility || 0, +u.open_interest || 0, +u.volume || 0, +u.delta || 0, +u.gamma || 0, +u.theta || 0, +u.vega || 0,
    +u.mark_price || 0, +u.mark_price || 0, +u.chance_of_profit_long || null, +u.chance_of_profit_short || null, it.id];
}
function lastPrice(q) {
  const a = +q.last_trade_price || 0, b = +q.last_non_reg_trade_price || 0, ta = Date.parse(q.venue_last_trade_time || 0) || 0, tb = Date.parse(q.venue_last_non_reg_trade_time || 0) || 0;
  return b && tb > ta ? b : (a || b);
}
async function rhLoadSymbol(sym, now, f) {
  const [eq, ch] = await Promise.all([rhCall("get_equity_quotes", { symbols: [sym] }, false), rhCall("get_option_chains", { underlying_symbol: sym }, 12 * 3600e3)]);
  const qq = (((eq.results || [])[0]) || {}).quote || {}, px = lastPrice(qq), pc = +qq.adjusted_previous_close || 0;
  const chain = (ch.chains || []).find(c => c.symbol === sym && c.can_open_position !== false) || (ch.chains || [])[0];
  if (!chain || !(px > 0)) return null;
  const exps = pickExpirations(chain.expiration_dates || [], f.dteMin, f.dteMax, now); if (!exps.length) return null;
  const jobs = []; exps.forEach(e => ["call", "put"].forEach(type => jobs.push({ e, type })));
  const lists = await pool(jobs, 4, j => rhInstruments(chain.id, j.e, j.type, j.type === "call" ? px * 0.85 : px * 0.75, j.type === "call" ? px * 1.25 : px * 1.15).catch(e => { if (AUTH_CODES[e && e.code]) throw e; return []; }));
  const inst = []; lists.forEach(l => { if (l) thin(l, px).forEach(x => inst.push(x)); });
  const byId = {}; inst.forEach(x => { byId[x.id] = x; });
  const batches = []; for (let i = 0; i < inst.length; i += 50) batches.push(inst.slice(i, i + 50));
  const quotes = await pool(batches, 3, b => rhCall("get_option_quotes", { instrument_ids: b.map(x => x.id) }, false).catch(e => { if (AUTH_CODES[e && e.code]) throw e; return {}; }));
  const rows = [];
  quotes.forEach(r => { ((r && r.results) || []).forEach(res => { const u = res.quote || res, it = byId[u.instrument_id]; const row = it && rowFromQuote(sym, it, u); if (row) rows.push(row); }); });
  return { s: sym, px, iv30: null, ivchg: null, chg: pc ? (px - pc) / pc * 100 : null, fetched: Date.now(), o: rows, rt: true, chainId: chain.id, exps };
}
async function rhHistory(syms) {
  const start = new Date(Date.now() - 400 * 864e5).toISOString().slice(0, 10) + "T00:00:00Z", out = {};
  for (let i = 0; i < syms.length; i += 10) {
    try { const d = await rhCall("get_equity_historicals", { symbols: syms.slice(i, i + 10), interval: "day", start_time: start }, 6 * 3600e3);
      for (const r of (d.results || [])) { const h = E.histStats((r.bars || []).filter(b => !b.interpolated).map(b => +b.close_price)); if (h) out[r.symbol] = h; } } catch (e) { if (AUTH_CODES[e && e.code]) throw e; }
  }
  return out;
}
async function rhEarnings(syms) {
  const today = new Date().toISOString().slice(0, 10);
  await pool(syms, 3, async sym => {
    try {
      const d = await rhCall("get_earnings_results", { symbol: sym }, 12 * 3600e3);
      const nxt = (d.results || []).find(e => e && e.eps && e.eps.actual == null && e.report && e.report.date >= today);
      if (nxt) { const p = nxt.report.date.split("-"), am = nxt.report.timing === "am";
        const t = E.etTime(+p[0], +p[1], +p[2], am ? 9 : 16, am ? 0 : 5);
        if (t > Date.now()) state.earn[sym] = { t, date: nxt.report.date, timing: nxt.report.timing || "pm", verified: !!nxt.report.verified, src: "robinhood" }; else delete state.earn[sym]; }
      else delete state.earn[sym];
    } catch (e) { if (AUTH_CODES[e && e.code]) throw e; }
  });
  state.earnVer++;
}
function applyRT() {
  const order = [...new Set(CORE.concat(WATCH, state.extra))];
  const syms = order.filter(s => state.rt.has(s)).map(s => state.rt.get(s));
  state.mode = "rt";
  if (syms.length) setData(syms, { generated: Date.now(), source: "Robinhood real-time" });
  else renderSymbols();
  setStatus(liveLabel(), "live");
}
async function rhLoadAll(syms) {
  if (state.rtLoading) return;
  const f = filters(), now = Date.now();
  state.rtLoading = { done: 0, total: syms.length }; state.rtAbort = null; renderSymbols(); setStatus(liveLabel(), "live");
  let timer = null; const flush = () => { if (!timer) timer = setTimeout(() => { timer = null; applyRT(); }, 900); };
  try {
    const histP = rhHistory(syms), earnP = rhEarnings(syms);
    await pool(syms, 2, async sym => {
      try { const S = await rhLoadSymbol(sym, now, f); if (S && S.o.length) { const old = state.rt.get(sym); S.hist = old ? old.hist : null; state.rt.set(sym, S); state.rtFail.delete(sym); } else state.rtFail.set(sym, "no option chain in range"); }
      catch (e) { if (AUTH_CODES[e && e.code]) { state.rtAbort = e; } state.rtFail.set(sym, (e && (e.code || e.message)) || "failed"); }
      finally { state.rtLoading.done++; state.lastTick = Date.now(); setStatus(liveLabel(), "live"); flush(); }
    });
    const H = await histP.catch(e => { if (AUTH_CODES[e && e.code]) state.rtAbort = e; return {}; });
    for (const [s, h] of Object.entries(H)) { const S = state.rt.get(s); if (S) S.hist = h; }
    await earnP.catch(e => { if (AUTH_CODES[e && e.code]) state.rtAbort = e; });
    state.rtRange = { min: f.dteMin, max: f.dteMax };
  } finally {
    clearTimeout(timer); state.rtLoading = null; state.lastTick = Date.now();
    applyRT();
    if (state.rtAbort) { const e = state.rtAbort; setStatus(AUTH_CODES[e.code] || ("Robinhood: " + (e.message || e.code)), "snap"); if (!state.rt.size) fallbackSnapshot(AUTH_CODES[e.code]); }
    else if (!state.rt.size) { setStatus("Robinhood returned no option chains. Reload to try again.", "snap"); fallbackSnapshot(); }
  }
}
/* Every minute: re-quote the contracts on screen. Every 10 minutes: re-quote everything loaded. */
async function rhRequote(all) {
  if (state.busy || state.rtLoading || state.mode !== "rt" || !state.rt.size) return;
  state.busy = true;
  try {
    const syms = [...state.rt.keys()];
    for (let i = 0; i < syms.length; i += 10) {
      try { const eq = await rhCall("get_equity_quotes", { symbols: syms.slice(i, i + 10) }, false);
        (eq.results || []).forEach(x => { const u = x.quote || x, S = state.rt.get(u.symbol), px = lastPrice(u), pc = +u.adjusted_previous_close || 0; if (S && px > 0) { S.px = px; S.chg = pc ? (px - pc) / pc * 100 : null; } }); } catch (e) {}
    }
    const want = new Set();
    if (all) state.rt.forEach(S => S.o.forEach(o => o[16] && want.add(o[16])));
    else { state.rows.forEach(st => st.raw.forEach(L => L.instId && want.add(L.instId))); const s = state.rows.find(st => st.id === state.sel); if (s) s.raw.forEach(L => L.instId && want.add(L.instId)); }
    const byInst = new Map(); state.rt.forEach(S => S.o.forEach(o => { if (o[16] && want.has(o[16])) byInst.set(o[16], o); }));
    const ids = [...byInst.keys()], batches = []; for (let i = 0; i < ids.length; i += 50) batches.push(ids.slice(i, i + 50));
    await pool(batches, 3, async b => {
      try { const r = await rhCall("get_option_quotes", { instrument_ids: b }, false);
        (r.results || []).forEach(res => { const u = res.quote || res, o = byInst.get(u.instrument_id); if (!o) return; const bid = +u.bid_price || 0, ask = +u.ask_price || 0; if (!(ask > 0)) return;
          o[1] = bid; o[2] = ask; o[3] = +u.bid_size || 0; o[4] = +u.ask_size || 0; o[5] = +u.implied_volatility || o[5]; o[6] = +u.open_interest || o[6]; o[7] = +u.volume || o[7]; o[8] = +u.delta || o[8];
          o[9] = +u.gamma || o[9]; o[10] = +u.theta || o[10]; o[11] = +u.vega || o[11]; o[12] = +u.mark_price || o[12]; o[13] = o[12]; o[14] = +u.chance_of_profit_long || o[14]; o[15] = +u.chance_of_profit_short || o[15]; }); }
      catch (e) {}
    });
    state.rt.forEach(S => { S.__mut = (S.__mut || 0) + 1; });
    state.lastTick = Date.now(); state.data.generated = Date.now(); reanalyze(); renderSymbols(); build(); if (state.sel) select(state.sel, true); setStatus(liveLabel(), "live");
  } finally { state.busy = false; }
}
function fallbackSnapshot(reason) {
  if (!window.__SNAPSHOT__ || state.rt.size) return;
  state.mode = "snapshot"; const s = window.__SNAPSHOT__;
  setData(s.symbols, { generated: s.generated * 1000, source: s.source });
  setStatus((reason ? reason + " " : "") + "Showing an OLD snapshot from " + stamp(s.generated * 1000) + ": don't trade off these prices.", "snap");
}
async function initClaude() {
  setStatus("Connecting to Robinhood…", "snap");
  let mcp = null; try { mcp = await window.claude.use("mcp"); } catch (e) { mcp = null; }
  state.mcpChecked = true;
  if (!mcp) { if (state.jr.open) jRequote(); fallbackSnapshot("Robinhood isn't available in this view."); if (!state.data) setStatus("Robinhood isn't available in this view. Open the public site, strike-finder.onrender.com, for delayed data.", ""); return; }
  state.mcp = mcp; state.mode = "rt";
  addRHButtons(); if (state.jr.open) jRequote();
  rhCall("get_accounts", {}, 3600e3).then(a => { state.accounts = (a.accounts || a.results || []).filter(x => x && x.account_number); }).catch(() => {});
  try { const x = JSON.parse(localStorage.getItem("sf:extra") || "[]"); if (Array.isArray(x)) state.extra = x.filter(s => /^[A-Z][A-Z0-9.]{0,6}$/.test(s)).slice(0, 12); } catch (e) {}
  await rhLoadAll([...new Set(CORE.concat(WATCH, state.extra))]);
  setInterval(() => { if (document.visibilityState === "visible" && marketHours()) rhRequote(false); }, 60 * 1000);
  setInterval(() => { if (document.visibilityState === "visible" && marketHours()) rhRequote(true); }, 10 * 60 * 1000);
  setInterval(() => { if (state.mode === "rt" && !state.rtLoading && !state.busy) setStatus(liveLabel(), "live"); }, 15000);
}
function addRHButtons() {
  if ($("#rh-pos")) return;
  const p = document.createElement("button"); p.type = "button"; p.className = "btn sm primary"; p.id = "rh-pos"; p.textContent = "My positions"; p.addEventListener("click", () => rhPositions());
  $("#refresh").after(p);
}

/* ---------- filters, structures, ranking ---------- */
function num(id, d) { const v = parseFloat($("#" + id).value); return isNaN(v) ? d : v; }
function filters() {
  return { types: state.type, dteMin: num("dte-min", 0), dteMax: num("dte-max", 365), dMin: num("delta-min", 0), dMax: num("delta-max", 1),
    maxPrice: num("max-price", 1e9) || 1e9, minOI: num("min-oi", 0), maxSpread: num("max-spread", 100) / 100, evMode: state.evMode };
}
function planNow(side) { const p = state.plan[side || state.side]; return { target: p.target / 100, stop: p.stop / 100, hold: p.hold }; }
function structures(f) {
  const key = [state.ver, state.side, state.struct, state.struct === "spread" ? f.dMin + "-" + f.dMax : ""].join("|");
  if (state.structCache.key === key) return state.structCache.list;
  const list = [];
  for (const A of state.syms) {
    const arr = state.struct === "single" ? A.legs.map(L => E.makeSingle(L, A, state.side)) : E.verticals(A, state.side, f);
    for (const st of arr) { st.A = A; const s = stabOf(A, st); st.stab = s; st.stabPos = s.n >= 2 ? s.pos : null; list.push(st); }
  }
  state.structCache = { key, list }; return list;
}
function planFor(st, n) {
  const p = state.plan[st.side], key = [st.id, st.side, p.target, p.stop, p.hold, n, st.price.toFixed(4), st.S.toFixed(3)].join("|");
  let r = state.simCache.get(key); if (r !== undefined) return r;
  r = E.simulate(st, planNow(st.side), n, st.sym + "|" + st.exp + "|" + st.side);   // shared paths per symbol and expiry: fair comparisons between strikes
  state.simCache.set(key, r); return r;
}
function gradeIt(st) { const G = E.grade(st); st.grade = G.g; st.fails = G.fails; st.checks = G.checks; st.win = st.plan ? st.plan.pWin : null; }
function build() {
  if (!state.data) return;
  const f = filters(), q = state.quality;
  let rows = structures(f).filter(st => state.selected.has(st.sym) && E.prefilter(st, f));
  state.filteredCount = rows.length;
  // grade without the simulation first: anything already failing too many other checks can't make the quality bar, so skip simulating it
  const maxOther = q === "a" ? 0 : q === "ab" ? 1 : 99;
  rows = rows.filter(st => { st.plan = null; const G = E.grade(st); const other = G.fails.filter(k => k !== "odds").length; return other <= maxOther; });
  for (const st of rows) { st.plan = planFor(st, TABLE_PATHS); gradeIt(st); }
  rows = rows.filter(st => q === "all" || (q === "a" ? st.grade === "A" : st.grade === "A" || st.grade === "B"));
  state.qualityCount = rows.length;
  E.scoreRows(rows, state.lens);
  const per = +$("#per-sym").value || 999;
  if (per < 999) { const by = {}; rows.sort((a, b) => b.score - a.score); rows = rows.filter(r => (by[r.sym] = (by[r.sym] || 0) + 1) <= per); }
  const k = state.sortK, dir = state.sortDir;
  rows.sort((a, b) => { const x = a[k], y = b[k]; if (typeof x === "string" || typeof y === "string") return dir * String(x).localeCompare(String(y)); return dir * ((x == null || isNaN(x) ? -Infinity : x) - (y == null || isNaN(y) ? -Infinity : y)); });
  state.rows = rows; renderRows(rows);
  const scanned = state.syms.reduce((t, A) => t + A.legs.length, 0);
  $("#count").textContent = `${rows.length} shown · ${state.qualityCount} pass quality · ${state.filteredCount} pass filters · ${scanned.toLocaleString()} contracts scanned`;
  if (state.sel && !rows.some(r => r.id === state.sel)) { state.sel = null; $("#drawer").hidden = true; }
}
function renderRows(rows) {
  const tb = $("#rows"); tb.textContent = ""; $("#empty").hidden = rows.length > 0 || !state.data;
  const frag = document.createDocumentFragment(), sp = state.struct === "spread";
  for (const r of rows) {
    const tr = document.createElement("tr"); tr.dataset.id = r.id; tr.setAttribute("aria-selected", state.sel === r.id ? "true" : "false");
    const tag = sp ? `<span class="tag ${r.isC ? "c" : "p"}">${r.isC ? "CALL" : "PUT"} ${r.side === "buy" ? "DEBIT" : "CREDIT"}</span>` : `<span class="tag ${r.isC ? "c" : "p"}">${r.isC ? "CALL" : "PUT"}</span>`;
    const cells = [
      ["l sym-cell", `<b>${r.sym}</b>${r.rt ? '<span class="rtdot" title="real-time from Robinhood">RT</span>' : ""} <span class="muted num">${fmt(r.S, 2)}</span>`],
      ["l", tag],
      ["num", `${day(r.exp)} · ${Math.ceil(r.dte)}d${r.evt ? `<span class="ev" title="${esc(evtLabel(r.evt))}">⚡</span>` : ""}`],
      ["num", sp ? `${strikeTxt(r.K)}/${strikeTxt(r.K2)}` : strikeTxt(r.K)],
      ["num", `${r.bid > 0 ? fmt(r.bid) : "–"} / ${fmt(r.ask)}`],
      ["num " + (r.spreadPct > 0.1 ? "down" : ""), pct(r.spreadPct, 1)],
      ["num", pct(r.iv, 0)],
      ["num " + (r.ivRel < 0 ? "up" : r.ivRel > 0.15 ? "down" : ""), pct(r.ivRel, 0, true)],
      ["num", fmt(r.delta, 2)],
      ["num " + (r.pop >= 0.5 ? "up" : ""), pct(r.pop, 0)],
      ["num", pct(r.moveBE, 1, true)],
      ["num", pct(r.thetaPct, 1)],
      ["num " + (r.theoEdge > 0 ? "up" : r.theoEdge < -0.05 ? "down" : ""), pct(r.theoEdge, 1, true)],
      ["num " + (r.evPct > 0 ? "up" : r.evPct < -0.05 ? "down" : ""), `<span title="${esc("Expected value holding to expiry: " + sgnMoney(r.ev * 100, 2) + " per contract")}">${pct(r.evPct, 1, true)}</span>`],
      ["num " + (r.win >= (r.side === "buy" ? 0.5 : 0.75) ? "up" : ""), r.plan ? `<span title="${esc("Plan: avg win " + money(r.plan.avgWin * 100, 0) + ", avg loss " + money(r.plan.avgLoss * 100, 0) + ", expected " + sgnMoney(r.plan.ev * 100, 0) + " per contract")}">${pct(r.win, 0)}</span>` : "–"],
      ["num", r.oiMin.toLocaleString()],
      ["num", r.volMin.toLocaleString()],
      ["num", `${(r.score * 100).toFixed(0)}<span class="bar"><i style="width:${Math.round(r.score * 100)}%"></i></span>`],
      ["l", `<span class="grade g${r.grade === "–" ? "x" : r.grade}" title="${esc(r.fails.length ? "Misses: " + r.fails.map(k => E.CHECKS[k][1]).join("; ") : "Clears every check")}">${r.grade}</span>`]
    ];
    for (const [cls, html] of cells) { const td = document.createElement("td"); td.className = cls; td.innerHTML = html; tr.appendChild(td); }
    tr.addEventListener("click", () => select(r.id));
    frag.appendChild(tr);
  }
  tb.appendChild(frag);
}

/* ---------- details panel ---------- */
function select(id, quiet) {
  const r = state.rows.find(x => x.id === id); if (!r) return;
  state.sel = id; document.querySelectorAll("#rows tr").forEach(tr => tr.setAttribute("aria-selected", tr.dataset.id === id ? "true" : "false"));
  const P = planFor(r, DRAWER_PATHS) || r.plan, plan = planNow(r.side), lv = E.planLevels(r, plan);
  const buy = r.side === "buy", sp = r.kind === "spread", isC = r.isC, name = structName(r), d = $("#drawer"); d.hidden = false;
  const closeBy = r.exp - Math.max(0, (r.dte - Math.min(plan.hold, r.dte))) * 864e5;
  const per = 100;
  let maxLossTxt, maxGainTxt;
  if (sp) { maxGainTxt = money(r.maxGain * per, 0); maxLossTxt = money(r.maxLoss * per, 0); }
  else if (buy) { maxLossTxt = money(r.price * per, 0) + " (the premium)"; maxGainTxt = isC ? "unlimited" : money((r.K - r.price) * per, 0) + " if it goes to 0"; }
  else { maxGainTxt = money(r.price * per, 0) + " (the credit)"; maxLossTxt = isC ? "unlimited unless you own 100 shares (a covered call)" : money((r.K - r.price) * per, 0) + " if it goes to 0 (cash-secured)"; }
  const H = r.hist, ev = r.evt;
  const kv = [
    ["Bid / Ask", `${r.bid > 0 ? fmt(r.bid) : "–"} / ${fmt(r.ask)}`, `mid ${fmt(r.mid)} · spread ${pct(r.spreadPct, 1)}`],
    [buy ? "Cost per contract" : "Credit per contract", money(r.price * per, 0), `assumes a limit fill at ${fmt(r.price)}, halfway from mid to ${buy ? "ask" : "bid"}`],
    ["Max gain · max loss", `${maxGainTxt} · ${maxLossTxt}`, sp ? `width $${fmt(r.width)} · reward/risk ${fmt(r.rr, 2)}` : ""],
    ["Breakeven at expiry", "$" + fmt(r.be, 2), pct(r.moveBE, 1, true) + " from $" + fmt(r.S, 2)],
    ["Expected value (hold)", `<span class="${r.ev > 0 ? "up" : r.ev < 0 ? "down" : ""}">${sgnMoney(r.ev * per, 0)} · ${pct(r.evPct, 1, true)}</span>`, `worth $${fmt(r.fair)} on the forecast vs $${fmt(r.price)} ${buy ? "paid" : "received"}`],
    ["Win % with the plan", P ? `${pct(P.pWin, 0)}` : "–", P ? `expected result ${sgnMoney(P.ev * per, 0)} per contract` : ""],
    ["P(profit) at expiry", pct(r.pop, 0), r.copL != null || r.copS != null ? "Robinhood's chance of profit" : "at market implied volatility"],
    ["Volatility", `IV ${pct(r.iv, 1)}`, `forecast ${pct(r.sigPath, 1)} · realized (jumps removed) ${r.hv ? pct(r.hv, 0) : "–"}${H && H.hv20 ? ` · raw 20d ${pct(H.hv20, 0)}` : ""}`],
    ["Event", ev ? (ev.src === "calendar" ? "Earnings " + day(ev.at) : "Event " + day(ev.from) + "–" + day(ev.to)) : "None in the window", ev ? (ev.move ? `market's implied move ±${pct(ev.move, 1)}` : "implied move not measurable from this chain") : ""],
    ["Trend", `<span class="${r.trend > 0 ? "up" : r.trend < 0 ? "down" : ""}">${r.trend > 0 ? "Up" : r.trend < 0 ? "Down" : "Mixed"}</span>${r.trendFit === 1 ? " · with this trade" : r.trendFit === -1 ? " · against this trade" : ""}`, H ? `20d $${fmt(H.sma20, 0)} · 50d $${fmt(H.sma50, 0)} · 1-mo ${pct(H.ret1m, 1, true)} · 3-mo ${pct(H.ret3m, 1, true)}` : "no price history"],
    ["Δ · Γ · Θ · V", `${fmt(r.delta, 2)} · ${fmt(r.gamma, 3)} · ${fmt(r.theta, 3)} · ${fmt(r.vega, 3)}`, `theta ${money(Math.abs(r.theta) * per, 2)}/day per contract (${pct(r.thetaPct, 1)})`],
    ["Expected move by expiry", "±$" + fmt(r.expMove, 2), pct(r.expMove / r.S, 1) + " (one standard deviation, market IV)"],
    ["Open interest · Volume", `${r.oiMin.toLocaleString()} · ${r.volMin.toLocaleString()}`, sp ? "the thinner leg" : `sizes ${r.bs} × ${r.as}`]
  ];
  if (!sp) kv.push(["Leverage", fmt(r.lever, 1) + "×", "$ of stock per $ of premium"]);
  const planBlock = P ? `<div class="plan">
      <span class="eyebrow">The plan, simulated on ${P.n.toLocaleString()} price paths</span>
      <div class="planbar" role="img" aria-label="Outcome mix"><i class="t" style="width:${(P.pTarget * 100).toFixed(1)}%"></i><i class="x" style="width:${(P.pTime * 100).toFixed(1)}%"></i><i class="s" style="width:${(P.pStop * 100).toFixed(1)}%"></i></div>
      <div class="planlegend"><span><b>${pct(P.pTarget, 0)}</b> hit the target</span><span><b>${pct(P.pTime, 0)}</b> closed at the time limit${P.days >= r.dte - 0.5 ? " (expiry)" : ""}</span><span><b>${pct(P.pStop, 0)}</b> stopped out</span><span><b>${pct(P.pWin, 0)}</b> ended in profit overall</span></div>
      <div class="planlegend"><span>Average win <b class="up">${money(P.avgWin * per, 0)}</b></span><span>Average loss <b class="down">${money(Math.abs(P.avgLoss) * per, 0)}</b></span><span>Expected result <b class="${P.ev > 0 ? "up" : "down"}">${sgnMoney(P.ev * per, 0)}</b> per contract</span><span>Typical range <b>${sgnMoney(P.p10 * per, 0)}</b> to <b>${sgnMoney(P.p90 * per, 0)}</b></span><span>Average hold <b>${fmt(P.avgDays, 0)}</b> days</span></div>
      ${P.pWin >= 0.6 && Math.abs(P.avgLoss) > P.avgWin * 1.5 ? `<div class="callout">High win rate, but each loss averages <b>${fmt(Math.abs(P.avgLoss) / Math.max(P.avgWin, 1e-9), 1)}×</b> the average win. The expected result, not the win rate, is what you keep.</div>` : ""}
      <span class="note">Forecast volatility ${pct(r.sigPath, 1)}${ev && ev.move ? `, plus the ±${pct(ev.move, 1)} event jump and the IV crush after it` : ""}. Checked once a day at the close. Fills assumed halfway between mid and natural. A model estimate: real results will differ.</span>
    </div>` : "";
  const leg = (L, act) => `${act} 1 × ${L.sym} ${dayNum(L.exp)} $${strikeTxt(L.K)} ${L.isC ? "Call" : "Put"}`;
  const tgtTxt = lv ? (buy ? `take profit at $${fmt(lv.target)} (+${pct(lv.target / lv.entry - 1, 0)})` : `buy back at $${fmt(lv.target)} (keep ${pct(1 - lv.target / lv.entry, 0)} of the credit)`) : "";
  const stpTxt = lv ? (buy ? (lv.stop > 0 ? `stop at $${fmt(lv.stop)} (−${pct(1 - lv.stop / lv.entry, 0)})` : "no stop") : (isFinite(lv.stop) ? `stop if it costs $${fmt(lv.stop)} to close (loss ${pct(lv.stop / lv.entry - 1, 0)} of the credit)` : "no stop")) : "";
  let ticket;
  if (sp) ticket = `${name}\n${buy ? leg(r.raw[0], "Buy") + " · " + leg(r.raw[1], "Sell") : leg(r.raw[0], "Sell") + " · " + leg(r.raw[1], "Buy")}\nNet ${buy ? "debit" : "credit"} limit $${fmt(r.mid)} (mid); expect fills near $${fmt(r.price)}\nMax gain ${money(r.maxGain * per, 0)} · max loss ${money(r.maxLoss * per, 0)} · breakeven $${fmt(r.be)}\nExit plan: ${tgtTxt} · ${stpTxt} · otherwise close by ${dayNum(closeBy)}`;
  else ticket = `${name}\n${buy ? "Buy" : "Sell"} to open 1 · limit $${fmt(r.mid)} (mid); expect fills near $${fmt(r.price)}\nBreakeven at expiry $${fmt(r.be)} (${pct(r.moveBE, 1, true)} from $${fmt(r.S)})\nExit plan: ${tgtTxt} · ${stpTxt} · otherwise close by ${dayNum(closeBy)}\nOCC ${r.raw[0].occ}`;
  const lvlNote = levelNote(sp, buy, isC);
  // the minute re-quote re-renders this panel: keep a half-filled "Track this trade" form (values, focus) for the same contract
  const jOld = $("#jtrack"), jKeep = jOld && jOld.dataset.id === id && jOld.dataset.wired && !state.jr.readonly ? jOld : null;
  const jFocus = jKeep && jKeep.contains(document.activeElement) ? document.activeElement : null;
  state.jr.formRow = r;
  d.innerHTML = `
  <div class="d-nav"><button class="btn sm" type="button" data-nav="results" title="Scroll back to this row in the results"><span aria-hidden="true">↑</span> Results</button><button class="btn sm" type="button" data-nav="close" title="Close the details and go back to the results">Close</button></div>
  <div class="left">
    <div class="d-head"><h2>${esc(name)}</h2><span class="grade g${r.grade === "–" ? "x" : r.grade}">${r.grade}</span><span class="muted num">${esc(sp ? r.raw.map(L => L.occ).join(" / ") : r.raw[0].occ)}</span></div>
    <div class="kv">${kv.map(([k, v, s]) => `<div><span class="k">${k}</span><span class="v num">${v}</span><span class="s">${s || ""}</span></div>`).join("")}</div>
    ${planBlock}
    <div class="why" id="why"></div>
    <div class="checks" id="checks"></div>
    ${payoffSVG(r)}
  </div>
  <div class="right">
    <p class="eyebrow">Hand-off to Robinhood</p>
    <div class="ticket" id="ticket">${esc(ticket)}</div>
    <div class="actions">
      <a class="btn primary" href="${RH_CHAIN(r.sym)}" target="_blank" rel="noopener">Open ${r.sym} chain in Robinhood</a>
      <a class="btn" href="${RH_STOCK(r.sym)}" target="_blank" rel="noopener">${r.sym} stock page</a>
      <button class="btn" type="button" id="copy-ticket">Copy ticket</button><span class="note" id="copy-note"></span>
    </div>
    <ol class="steps">${sp
      ? `<li>In Robinhood: ${r.sym} → Trade → Trade Options → <b>${dayNum(r.exp)}</b>, then select both legs (tap Select, or pick the spread from strategies): ${buy ? "buy" : "sell"} the <b>$${strikeTxt(r.K)}</b> and ${buy ? "sell" : "buy"} the <b>$${strikeTxt(r.K2)}</b> ${isC ? "calls" : "puts"}.</li><li>Set a <b>limit</b> for the whole spread at the mid (${money(r.mid)}). If it doesn't fill, move it a few cents toward ${money(buy ? r.ask : Math.max(0, r.bid))}, never all the way at once.</li>`
      : `<li>In Robinhood: ${r.sym} → Trade → Trade Options → <b>${dayNum(r.exp)}</b> → <b>${isC ? "Calls" : "Puts"}</b> → strike <b>$${strikeTxt(r.K)}</b>.</li><li>Choose <b>${buy ? "Buy" : "Sell"}</b>, set a <b>limit</b> at the mid (${money(r.mid)}); move toward ${money(buy ? r.ask : r.bid)} a few cents at a time if it doesn't fill.</li>`}
      <li>Right after it fills, set the exit: a limit order to ${buy ? "sell" : "buy back"} at <b>$${lv ? fmt(lv.target) : "–"}</b>, and a calendar note for the stop and the ${dayNum(closeBy)} time limit. Robinhood's stop orders on options can trigger on a brief wide quote, so many people check the stop at the close instead.</li>
      <li>${r.rt ? "These quotes are real-time from Robinhood." : "These quotes are about 15 minutes delayed: check the live bid/ask first."} You place every order; this page never does.</li>
    </ol>
    ${lvlNote ? `<div class="callout">${lvlNote}</div>` : ""}
    <div class="sizer">
      <div class="f"><label for="acct">Account size ($)</label><input id="acct" type="number" min="0" step="100" value="${loadNum("sf:acct", 5000)}"></div>
      <div class="f"><label for="risk">Max risk per trade (%)</label><input id="risk" type="number" min="0.1" max="100" step="0.5" value="${loadNum("sf:risk", 2)}"></div>
      <div class="note" id="sizing"></div>
    </div>
    ${trackFormHTML(r)}
  </div>`;
  if (jKeep && $("#jtrack")) {
    $("#jtrack").replaceWith(jKeep);
    const ent = $("#jt-entry"); if (ent && !ent.dataset.edited) ent.value = r.price.toFixed(2);
    if (jFocus) { try { jFocus.focus({ preventScroll: true }); } catch (e) {} }
  }
  wireTrackForm();
  const why = [], parts = r.parts || {};
  const lbl = { ev: "expected value", planEv: "plan's expected result", win: "plan win rate", theoEdge: "price vs fair value", spread: "spread", liq: "liquidity", theta: "theta", ivRel: "IV vs 30d", ivTrend: "IV trend", pop: "P(profit)", lever: "leverage", flow: "volume/OI", volRank: "volume", trendFit: "trend fit", stab: "consistency" };
  Object.entries(parts).sort((a, b) => b[1] - a[1]).forEach(([k, v]) => why.push(`<span><b>${lbl[k] || k}</b>: better than ${(v * 100).toFixed(0)}% of what's in this view</span>`));
  if (ev) why.push(`<span class="warn">⚡ ${esc(evtLabel(ev))}. ${buy ? "Buying through it bets on a move bigger than the implied one; IV drops right after the report." : "Selling through it collects the elevated IV but carries the whole gap risk: size for the implied move."}</span>`);
  if (!buy && !sp && isC) why.push(`<span class="down">Robinhood only lets you sell a call you can cover with 100 shares (a covered call).</span>`);
  $("#why").innerHTML = `<span class="eyebrow">Why it ranks here (${E.LENSES.find(l => l.id === state.lens).name})</span>` + why.join("");
  const st = r.stab && r.stab.n >= 2 ? `Seen in ${r.stab.n} scans${r.stab.src === "server" ? " on the server" : " this session"} · priced under fair in ${pct(r.stab.pos, 0)} of them` : "Consistency builds as the page keeps scanning.";
  $("#checks").innerHTML = `<span class="eyebrow" style="grid-column:1/-1">Grade ${r.grade} · ${r.fails.length ? r.fails.length + " of " + Object.keys(r.checks).length + " checks missed" : "clears every check"}</span>` +
    Object.entries(r.checks).map(([k, ok]) => `<span class="${ok ? "ok" : "no"}">${ok ? "✓" : "✗"} ${E.CHECKS[k][ok ? 0 : 1]}</span>`).join("") + `<span class="muted" style="grid-column:1/-1">${st}</span>`;
  $("#copy-ticket").addEventListener("click", () => { const t = $("#ticket").textContent, n = $("#copy-note");
    const fb = () => { try { const rg = document.createRange(); rg.selectNodeContents($("#ticket")); const s = getSelection(); s.removeAllRanges(); s.addRange(rg); n.textContent = "Selected: press Cmd/Ctrl+C."; } catch (e) { n.textContent = "Select the text to copy it."; } };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t).then(() => { n.textContent = "Copied."; }, fb); else fb(); });
  const sizing = () => {
    const acct = +$("#acct").value || 0, risk = (+$("#risk").value || 0) / 100; saveNum("sf:acct", acct); saveNum("sf:risk", risk * 100);
    let perC, what;
    if (buy) { perC = r.price * per; what = "the full premium"; }
    else if (sp) { perC = r.maxLoss * per; what = "the max loss"; }
    else if (!isC) { perC = Math.max(r.price * Math.min(plan.stop, 5) * per, 1); what = "the plan's stop loss"; }
    else { $("#sizing").textContent = "Covered calls need 100 shares per contract; size by the shares you own."; return; }
    const n = Math.floor((acct * risk) / perC);
    $("#sizing").textContent = `${n} contract${n === 1 ? "" : "s"} keeps ${what} (${money(perC, 0)} each) within ${money(acct * risk, 0)}.` + (!buy && !sp && !isC ? ` Cash to secure each: ${money((r.K - r.price) * per, 0)}.` : "");
  };
  $("#acct").addEventListener("input", sizing); $("#risk").addEventListener("input", sizing); sizing();
  // "↑ Results" / "Close": one delegated listener on #drawer itself, wired once (the minute re-quote only swaps its innerHTML)
  if (!d.dataset.wired) { d.dataset.wired = "1"; d.addEventListener("click", e => {
    const b = e.target.closest("[data-nav]"); if (!b || !d.contains(b)) return;
    const tr = document.querySelector('#rows tr[aria-selected="true"]');
    if (b.dataset.nav === "close") { state.sel = null; d.hidden = true; document.querySelectorAll('#rows tr[aria-selected="true"]').forEach(x => x.setAttribute("aria-selected", "false")); }
    if (tr) tr.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
  }); }
  if (!quiet) d.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
function levelNote(sp, buy, isC) {
  if (!state.accounts || !state.accounts.length || (!sp && buy)) return "";
  const lv = a => +String(a.option_level || "").replace(/\D/g, "") || 0;
  const name = a => (a.nickname || (a.brokerage_account_type || a.type || "account").replace(/_/g, " ")) + " ••" + String(a.account_number).slice(-4);
  const need = sp ? 3 : 2, okA = state.accounts.filter(a => lv(a) >= need), noA = state.accounts.filter(a => lv(a) < need);
  const what = sp ? "Spreads need Robinhood options level 3." : isC ? "Selling calls needs 100 shares (covered) and level 2." : "Selling puts needs level 2 and the cash to secure them.";
  return `<b>${what}</b> ${okA.length ? "Allowed in: " + esc(okA.map(name).join(", ")) + "." : ""} ${noA.length ? "Not allowed in: " + esc(noA.map(name).join(", ")) + "." : ""}`;
}
function payoffSVG(r) {
  const buy = r.side === "buy", W = 560, H = 170, pad = 28;
  let lo = r.S * 0.8, hi = r.S * 1.2; [r.K, r.K2, r.be].forEach(x => { if (x > 0) { lo = Math.min(lo, x * 0.95); hi = Math.max(hi, x * 1.05); } });
  const pl = S => (buy ? E.intrinsic(r.legs, S) - r.price : r.price - E.intrinsic(r.legs, S)) * 100;
  const pts = []; for (let i = 0; i <= 80; i++) { const S = lo + (hi - lo) * i / 80; pts.push([S, pl(S)]); }
  const ys = pts.map(p => p[1]), ymin = Math.min(...ys, 0), ymax = Math.max(...ys, 0);
  const X = S => pad + (S - lo) / (hi - lo) * (W - 2 * pad), Y = v => H - pad - (v - ymin) / ((ymax - ymin) || 1) * (H - 2 * pad);
  const path = pts.map((p, i) => (i ? "L" : "M") + X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join(" ");
  return `<p class="note payoffcap">P/L at expiry per contract · breakeven $${fmt(r.be, 2)} · max ${money(ymax, 0)} / min ${money(ymin, 0)} in this range</p>
  <svg class="payoff" viewBox="0 0 ${W} ${H}" role="img" aria-label="Profit and loss at expiry across stock prices">
    <line x1="${pad}" y1="${Y(0)}" x2="${W - pad}" y2="${Y(0)}" stroke="currentColor" stroke-opacity=".35"/>
    <line x1="${X(r.S)}" y1="${pad - 6}" x2="${X(r.S)}" y2="${H - pad}" stroke="currentColor" stroke-opacity=".25" stroke-dasharray="3 3"/>
    <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2.2"/>
    <circle cx="${X(Math.min(hi, Math.max(lo, r.be)))}" cy="${Y(0)}" r="4" fill="var(--fg)"/>
    <text x="${X(r.S)}" y="${pad - 10}" font-size="11" text-anchor="middle" fill="currentColor" fill-opacity=".7">now $${fmt(r.S, 2)}</text>
    <text x="${pad}" y="${H - 8}" font-size="11" fill="currentColor" fill-opacity=".7">$${fmt(lo, 0)}</text>
    <text x="${W - pad}" y="${H - 8}" font-size="11" text-anchor="end" fill="currentColor" fill-opacity=".7">$${fmt(hi, 0)}</text>
  </svg>`;
}

/* ---------- My positions: hold or sell, by the numbers ---------- */
async function rhPositions() {
  if (!state.mcp) return;
  setStatus("Robinhood: loading accounts…", "live");
  try {
    if (!state.accounts) { const a = await rhCall("get_accounts", {}, 3600e3); state.accounts = (a.accounts || a.results || []).filter(x => x && x.account_number); }
    const accts = state.accounts; if (!accts.length) throw new Error("no brokerage accounts returned");
    const pos = [];
    for (const a of accts) { let cursor, guard = 0;
      do { const d = await rhCall("get_option_positions", Object.assign({ account_number: a.account_number, nonzero: true }, cursor ? { cursor } : {}), false);
        (d.positions || d.results || []).forEach(p => pos.push(Object.assign({}, p, { acct: a }))); cursor = d.next; } while (cursor && ++guard < 10); }
    if (!pos.length) { renderPositions([], accts); setStatus(`Robinhood: no open option positions in ${accts.length} account${accts.length === 1 ? "" : "s"}.`, "live"); return; }
    setStatus(`Robinhood: pricing ${pos.length} position${pos.length === 1 ? "" : "s"}…`, "live");
    const ids = [...new Set(pos.map(p => p.option_id))], inst = {}, q = {}, px = {}, chg = {};
    for (let i = 0; i < ids.length; i += 40) { const d = await rhCall("get_option_instruments", { ids: ids.slice(i, i + 40).join(",") }, 12 * 3600e3); (d.instruments || d.results || []).forEach(x => { inst[x.id] = x; }); }
    for (let i = 0; i < ids.length; i += 50) { const d = await rhCall("get_option_quotes", { instrument_ids: ids.slice(i, i + 50) }, false); (d.results || []).forEach(x => { const u = x.quote || x; q[u.instrument_id] = u; }); }
    const syms = [...new Set(pos.map(p => p.chain_symbol))];
    for (let i = 0; i < syms.length; i += 10) { const eq = await rhCall("get_equity_quotes", { symbols: syms.slice(i, i + 10) }, false);
      (eq.results || []).forEach(x => { const u = x.quote || x, last = lastPrice(u), pc = +u.adjusted_previous_close || 0; px[u.symbol] = last; chg[u.symbol] = pc && last ? (last - pc) / pc : null; }); }
    const hist = await rhHistory(syms.filter(s => !(state.rt.get(s) && state.rt.get(s).hist)));
    await rhEarnings(syms.filter(s => !state.rt.has(s)));
    const now = Date.now();
    const rows = pos.map(p => {
      const it = inst[p.option_id] || {}, u = q[p.option_id] || {}, isC = String(it.type || "").toLowerCase() === "call", long = (p.type || "long") !== "short";
      const qty = +p.quantity || 0, mult = +p.trade_value_multiplier || 100, cost = (+p.average_price || 0) / mult;
      const bid = +u.bid_price || 0, ask = +u.ask_price || 0, mark = +u.mark_price || ((bid + ask) / 2) || 0, K = +it.strike_price || 0;
      const expD = it.expiration_date || p.expiration_date, exp = etDateMs(expD), T = Math.max((exp - now) / E.YEAR_MS, 0.5 / 365), S = px[p.chain_symbol] || 0, iv = +u.implied_volatility || 0.3;
      // the symbol's own analysis when it's loaded (term structure, event size, realized vol); otherwise a minimal one
      const A0 = state.syms.find(A => A.sym === p.chain_symbol);
      const h = (state.rt.get(p.chain_symbol) || {}).hist || hist[p.chain_symbol] || null;
      const A = A0 ? Object.assign({}, A0, { px: S || A0.px }) : { sym: p.chain_symbol, px: S, pts: [{ exp, T, iv }], ev: E.detectEvent([], state.earn[p.chain_symbol] || null, now), hist: h, hv: E.realizedVol(h), trend: E.trendOf(S, h), iv30: iv, ivchg: null, rt: true, legs: [] };
      const L = { sym: p.chain_symbol, S, occ: p.option_id, type: isC ? "C" : "P", isC, exp, T, dte: T * 365, K, bid, ask, mid: mark, bs: +u.bid_size || 0, as: +u.ask_size || 0, iv, oi: +u.open_interest || 0, vol: +u.volume || 0,
        delta: +u.delta || 0, gamma: +u.gamma || 0, theta: +u.theta || 0, vega: +u.vega || 0, theo: 0, last: 0, copL: +u.chance_of_profit_long || null, copS: +u.chance_of_profit_short || null };
      const st = E.makeSingle(L, A, long ? "buy" : "sell");
      const fair = st.fair, holdEV = long ? fair - bid : ask - fair;            // vs closing right now at the bid (long) / ask (short)
      const back = S > 0 ? E.simulateLevels(st, long ? "buy" : "sell", long ? bid : ask, cost, long ? -1 : Infinity, T * 365, 3000, "pos" + p.option_id) : null;
      const intrinsic = S ? Math.max(0, isC ? S - K : K - S) : 0, beCost = isC ? K + cost : K - cost, need = S ? (isC ? (beCost - S) / S : (S - beCost) / S) : null;
      const pend = ["pending_buy_quantity", "pending_sell_quantity", "pending_exercise_quantity", "pending_assignment_quantity", "pending_expiration_quantity"].reduce((t, k) => t + (+p[k] || 0), 0);
      return { sym: p.chain_symbol, acct: p.acct, long, isC, qty, mult, cost, mark, bid, ask, K, exp, dte: T * 365, S, chg: chg[p.chain_symbol], iv, theta: +u.theta || 0, delta: +u.delta || 0,
        cop: long ? (+u.chance_of_profit_long || null) : (+u.chance_of_profit_short || null), sig: iv * Math.sqrt(T), need, beCost, intrinsic, tv: Math.max(0, mark - intrinsic), pend, evt: st.evt,
        pl: (mark - cost) * qty * mult * (long ? 1 : -1), plPct: cost ? (mark - cost) / cost * (long ? 1 : -1) : null, fair, holdEV, back: back ? back.pTarget : null, sigF: st.sigPath, hv: A.hv };
    });
    renderPositions(rows, accts); setStatus(`Robinhood positions loaded · ${rows.length} open · real-time`, "live");
  } catch (e) { setStatus("Positions: " + (AUTH_CODES[e && e.code] || ((e && (e.code ? e.code + " " : "")) + (e && e.message || e))), "snap"); }
}
function verdictFor(p) {
  let tag, cls;
  if (p.dte <= 0) { tag = "Expired"; cls = "bad"; }
  else if (p.dte <= 5) { tag = "Expires in " + Math.ceil(p.dte) + "d"; cls = p.intrinsic > 0 ? "warn" : "bad"; }
  else if (p.cop == null) { tag = "No quote"; cls = "warn"; }
  else if (p.cop >= .5) { tag = "On track"; cls = "good"; } else if (p.cop >= .35) { tag = "Fair bet"; cls = "fair"; } else if (p.cop >= .2) { tag = "Needs a move"; cls = "warn"; } else { tag = "Long shot"; cls = "bad"; }
  const otm = Math.abs(p.isC ? p.K - p.S : p.S - p.K), decay = p.mark ? Math.abs(p.theta) / p.mark : 0, lines = [];
  lines.push(`<b>${p.sym} $${fmt(p.S, 2)}</b>${p.chg != null ? ` (${pct(p.chg, 1, true)} today)` : ""} · ${p.intrinsic > 0 ? `in the money by $${fmt(p.intrinsic)}: $${fmt(p.intrinsic)} intrinsic + $${fmt(p.tv)} time value` : `out of the money by $${fmt(otm)}: the whole $${fmt(p.mark)} is time value`}. Decay about ${money(Math.abs(p.theta))}/share a day (${pct(decay, 1)}/day).`);
  if (p.need != null) lines.push(`Needs ${p.sym} ${p.need > 0 ? `to ${p.isC ? "rise" : "fall"} ${pct(p.need, 1)} (to $${fmt(p.beCost, 2)})` : `to stay ${p.isC ? "above" : "below"} $${fmt(p.beCost, 2)}`} by expiry to profit from your cost; the market's 1σ move by then is ±${pct(p.sig, 1)}.`);
  if (p.back != null) lines.push(`Chance it trades back to your cost ($${fmt(p.cost)}) at some close before expiry: <b>${pct(p.back, 0)}</b>.`);
  lines.push(`Holding to expiry vs ${p.long ? "selling at the bid" : "buying back at the ask"} now: <b class="${p.holdEV > 0 ? "up" : "down"}">${sgnMoney(p.holdEV * p.qty * p.mult, 0)}</b> expected for the position (forecast vol ${pct(p.sigF, 0)} vs IV ${pct(p.iv, 0)}). ${p.holdEV < 0 ? "Negative means the market is paying more for it than the forecast says it's worth." : "Positive means the forecast says it's worth more than the market will pay now."}`);
  if (p.evt) lines.push(`<span class="warn">⚡ ${esc(evtLabel(p.evt))} before expiry: expect a large move either way, then an IV drop.</span>`);
  if (p.bid && p.ask && p.mark && (p.ask - p.bid) / p.mark > 0.08) lines.push(`<span class="warn">Wide market (${fmt(p.bid)} / ${fmt(p.ask)}): use a limit near the mid if you trade it.</span>`);
  if (p.pend > 0) lines.push(`<span class="warn">Pending quantity on this position: an order, exercise or assignment is in progress.</span>`);
  lines.push(`Decision test: would you buy this today at $${fmt(p.mark)} for the reason you bought it at $${fmt(p.cost)}? What you paid doesn't change the odds from here.`);
  return { tag, cls, lines };
}
function renderPositions(rows, accts) {
  const sec = $("#pos"); sec.hidden = false; const box = $("#posbox");
  const head = extra => `<div class="poshead"><h2>My positions <span class="muted" style="font-weight:500;font-size:13px">· ${extra}</span></h2><div class="actions" style="margin:0"><button class="btn sm" type="button" id="pos-refresh">Refresh</button><button class="btn sm" type="button" id="pos-close">Hide</button></div></div>`;
  const acctLabel = a => (a.nickname || (a.brokerage_account_type || a.type || "account").replace(/_/g, " ")) + " ••" + String(a.account_number || "").slice(-4);
  if (!rows.length) box.innerHTML = head("Robinhood") + `<p class="note">No open option positions in ${accts.length} account${accts.length === 1 ? "" : "s"}.</p>`;
  else {
    rows.sort((a, b) => a.dte - b.dte);
    const tot = rows.reduce((t, p) => { const s = p.long ? 1 : -1; t.cost += p.cost * p.qty * p.mult * s; t.val += p.mark * p.qty * p.mult * s; t.theta += Math.abs(p.theta) * p.qty * p.mult * (p.long ? -1 : 1); t.ev += p.holdEV * p.qty * p.mult; return t; }, { cost: 0, val: 0, theta: 0, ev: 0 });
    const trs = rows.map(p => { const v = verdictFor(p);
      return `<tr class="main"><td class="l">${esc(acctLabel(p.acct))}</td>
        <td class="l"><b>${esc(p.sym)}</b> ${day(p.exp)} $${strikeTxt(p.K)} <span class="tag ${p.isC ? "c" : "p"}">${p.isC ? "CALL" : "PUT"}</span>${p.long ? "" : ' <span class="tag p">SHORT</span>'}${p.evt ? ` <span class="ev" title="${esc(evtLabel(p.evt))}">⚡</span>` : ""}</td>
        <td class="num">${p.qty}</td><td class="num">${fmt(p.cost)}</td><td class="num">${fmt(p.mark)}</td>
        <td class="num ${p.pl >= 0 ? "up" : "down"}">${money(p.pl, 0)}<br><span class="muted">${pct(p.plPct, 0, true)}</span></td>
        <td class="num">${Math.ceil(p.dte)}d</td><td class="num">${fmt(p.delta, 2)}</td><td class="num">${money(Math.abs(p.theta) * p.mult * p.qty, 0)}</td>
        <td class="num">${p.need == null ? "–" : pct(p.need, 1, true)}</td><td class="num">${pct(p.cop, 0)}</td><td class="num">${p.back == null ? "–" : pct(p.back, 0)}</td>
        <td class="num ${p.holdEV > 0 ? "up" : "down"}">${sgnMoney(p.holdEV * p.qty * p.mult, 0)}</td>
        <td class="l"><span class="verdict ${v.cls}">${v.tag}</span></td></tr>
        <tr class="noterow"><td colspan="14"><div class="posnotes">${v.lines.map(l => `<span>${l}</span>`).join("")}</div></td></tr>`; }).join("");
    box.innerHTML = head(`${rows.length} open · Robinhood real-time · ${new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`) +
      `<div class="totals"><span>Cost basis <b>${money(tot.cost, 0)}</b></span><span>Value now <b>${money(tot.val, 0)}</b></span><span>Open P/L <b class="${tot.val - tot.cost >= 0 ? "up" : "down"}">${money(tot.val - tot.cost, 0)} (${pct(tot.cost ? (tot.val - tot.cost) / Math.abs(tot.cost) : 0, 1, true)})</b></span><span>Decay <b>${money(tot.theta, 0)}/day</b></span><span>Hold vs close now <b class="${tot.ev >= 0 ? "up" : "down"}">${sgnMoney(tot.ev, 0)}</b> expected</span></div>
      <div class="postable"><table><thead><tr><th class="l">Account</th><th class="l">Contract</th><th>Qty</th><th>Paid</th><th>Mark</th><th>P/L</th><th>DTE</th><th>Δ</th><th>Θ/day</th><th>Need</th><th>CoP</th><th>Back to cost</th><th>Hold EV</th><th class="l">Read</th></tr></thead><tbody>${trs}</tbody></table></div>
      <p class="note">"Need" is the move to your cost-basis breakeven by expiry. "CoP" is Robinhood's chance of profit at today's mark. "Back to cost" is the simulated chance the option trades at or above what you paid at some close before expiry. "Hold EV" is the expected value of holding to expiry versus closing at the bid/ask right now, on the forecast volatility. These are odds, not instructions; you decide and you place every order.</p>`;
  }
  $("#pos-close").addEventListener("click", () => { sec.hidden = true; });
  $("#pos-refresh").addEventListener("click", () => rhPositions());
  sec.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- My trades: a private journal of the trades you actually took (Claude version: db + user capabilities) ----------
   Each trade is one document at data/users/<your id>/journal/trades/<trade id>, private to you. Values come from Robinhood
   quotes of the legs, combined like the engine's combos: long legs add, short legs subtract. */
async function initJournal() {
  if (!JOURNAL || !IN_CLAUDE) return;
  let db = null, user = null;
  try { [db, user] = await Promise.all([window.claude.use("db"), window.claude.use("user")]); } catch (e) { return; }
  if (!db || !user) return;
  let uid = null; try { uid = await user.id(); } catch (e) { uid = null; }
  if (!uid) return;                                  // no identity here = no private subtree: no journal this visit
  const J = state.jr;
  try { J.col = db.doc("data/users/" + uid + "/journal").collection("trades"); } catch (e) { return; }
  J.ready = true;
  const box = $("#jbox");
  box.addEventListener("click", e => { const b = e.target.closest("[data-act]"); if (b) jAction(b.dataset.act, b.dataset.id || "", b); });
  box.addEventListener("input", e => { const id = e.target.dataset ? e.target.dataset.exit : null; if (id && J.mode[id]) J.mode[id].exit = e.target.value; });
  box.addEventListener("keydown", e => { const id = e.target.dataset ? e.target.dataset.exit : null; if (id && e.key === "Enter") jAction("close-save", id, null); });
  J.col.onSnapshot(snap => {
    J.trades = snap.docs.filter(d => d.exists).map(d => Object.assign({}, d.data(), { id: d.id })).sort((a, b) => (b.created || 0) - (a.created || 0));
    J.loaded = true; J.err = "";
    renderJournal();
    if (J.open && J.trades.some(t => t.status !== "closed" && (t.legs || []).some(L => L.instId && !J.quotes.has(L.instId)))) jRequote();
  }, e => { J.err = jErrText(e); J.loaded = true; renderJournal(); });
  addJournalButton();
  if (state.sel) select(state.sel, true);
  let wasOpen = false; try { wasOpen = localStorage.getItem("sf:journal") === "1"; } catch (e) {}
  if (wasOpen) openJournal(false);
  setInterval(() => { if (J.open && document.visibilityState === "visible" && marketHours()) jRequote(); }, 60 * 1000);
}
function jErrText(e) {
  const c = e && e.code;
  if (c === "quota_exceeded") return "Your journal is full. Delete some old trades, then save again.";
  if (c === "invalid_argument") return "Saving trades isn't allowed at your access level on this page.";
  if (c === "resource_exhausted") return "Too many saves at once. Wait a moment and try again.";
  if (c === "revoked" || c === "not_granted" || c === "capability_disabled" || c === "capability_removed") return "Saving trades isn't available in this view.";
  return "Couldn't reach your journal just now. Try again in a moment.";
}
async function jWrite(fn) {                          // one write; a transient failure is retried once after a short random delay
  for (let tries = 0; ; tries++) {
    try { return await fn(); }
    catch (e) { if (e && e.code === "unavailable" && tries < 1) { await sleep(400 + Math.random() * 800); continue; } if (e && e.code === "invalid_argument") state.jr.readonly = true; throw e; }
  }
}
function addJournalButton() {
  if ($("#jr-btn")) return;
  const b = document.createElement("button"); b.type = "button"; b.className = "btn sm"; b.id = "jr-btn"; b.textContent = "My trades";
  b.addEventListener("click", () => { if (state.jr.open) closeJournal(); else openJournal(true); });
  ($("#rh-pos") || $("#refresh")).after(b);
}
function openJournal(scroll) {
  const J = state.jr; if (!J.ready) return;
  J.open = true; $("#journal").hidden = false; try { localStorage.setItem("sf:journal", "1"); } catch (e) {}
  renderJournal(); jRequote();
  if (scroll) $("#journal").scrollIntoView({ behavior: "smooth", block: "start" });
}
function closeJournal() { state.jr.open = false; $("#journal").hidden = true; try { localStorage.setItem("sf:journal", "0"); } catch (e) {} }
async function jRequote() {
  const J = state.jr; if (!J.ready || J.qBusy) return;
  const ids = [...new Set(J.trades.filter(t => t.status !== "closed").flatMap(t => (t.legs || []).map(L => L.instId)).filter(Boolean))];
  if (!ids.length) return;
  if (!state.mcp) { J.qErr = state.mcpChecked ? "Live values need the Robinhood connector, which isn't available in this view." : ""; renderJournal(); return; }
  J.qBusy = true; renderJournal();
  let fails = 0;
  try {
    for (let i = 0; i < ids.length; i += 50) {
      try { const r = await rhCall("get_option_quotes", { instrument_ids: ids.slice(i, i + 50) }, false);
        (r.results || []).forEach(res => { const u = res && (res.quote || res); if (u && u.instrument_id) J.quotes.set(u.instrument_id, { bid: +u.bid_price || 0, ask: +u.ask_price || 0, mark: +u.mark_price || 0, at: Date.now() }); }); }
      catch (e) { fails++; J.qErr = AUTH_CODES[e && e.code] || "Robinhood quotes failed: " + ((e && (e.message || e.code)) || "error"); }
    }
    if (!fails) { J.qErr = ""; J.qAt = Date.now(); }
  } finally { J.qBusy = false; renderJournal(); }
}
/* Value per share of the combo now: long legs add their bid/ask, short legs subtract their ask/bid (as the engine builds spreads).
   "value" is the expected fill to close, halfway from the mid to the natural price: what selling (buys) or buying back (sales) gets. */
function jValue(t) {
  let bid = 0, ask = 0, mark = 0;
  for (const L of t.legs || []) {
    const u = state.jr.quotes.get(L.instId); if (!u) return null;
    const q = +L.q || 0, m = u.mark > 0 ? u.mark : (u.bid + u.ask) / 2;
    if (q > 0) { bid += q * u.bid; ask += q * u.ask; } else { bid += q * u.ask; ask += q * u.bid; }
    mark += q * m;
  }
  bid = Math.max(0, bid); if (!(ask > 0) && !(mark > 0)) return null;
  ask = Math.max(ask, bid); const mid = Math.min(ask, Math.max(bid, mark));
  const value = t.side === "buy" ? mid - E.FILL * (mid - bid) : mid + E.FILL * (ask - mid);
  return { bid, ask, mid, value: Math.max(0, value) };
}
function jPL(t, v) {
  if (v == null || !(t.entry > 0)) return null;
  const per = t.side === "buy" ? v - t.entry : t.entry - v;
  return { per, usd: per * 100 * (t.qty || 1), pct: per / t.entry };
}
function jHow(t) {               // how a closed trade ended, measured against its own plan
  const buy = t.side === "buy", x = t.exit; if (x == null) return "";
  if (t.target != null && (buy ? x >= t.target - 0.005 : x <= t.target + 0.005)) return "target";
  if (t.stop != null && (buy ? x <= t.stop + 0.005 : x >= t.stop - 0.005)) return "stop";
  if (t.closeBy && t.closed >= t.closeBy) return "time";
  return "early";
}
function jStatus(t, v, now) {
  const buy = t.side === "buy";
  if (t.status === "closed") { const h = jHow(t); return { tag: "Closed", cls: "x", sub: ({ target: "at the target", stop: "at the stop", time: "at the time limit", early: "before any exit level" })[h] || "" }; }
  if (v != null && t.target != null && (buy ? v >= t.target : v <= t.target)) return { tag: "Target reached", cls: "good", sub: "the plan says take the profit" };
  if (v != null && t.stop != null && (buy ? v <= t.stop : v >= t.stop)) return { tag: "Stop reached", cls: "bad", sub: "the plan says close it" };
  if (t.exp && now >= t.exp) return { tag: "Expired", cls: "bad", sub: "record how it ended" };
  if (t.closeBy && now >= t.closeBy) return { tag: "Past time limit", cls: "warn", sub: "the plan says close it" };
  return { tag: "Open", cls: "fair", sub: v == null ? "no quote yet" : "within the plan" };
}
function jStats(closed) {
  const rows = closed.map(t => ({ t, pl: jPL(t, t.exit) })).filter(x => x.pl); const n = rows.length; if (!n) return null;
  const w = rows.filter(x => x.pl.per > 0).length, total = rows.reduce((s, x) => s + x.pl.usd, 0), pw = rows.filter(x => x.t.pWin != null);
  return { n, w, rate: w / n, avgUsd: total / n, avgPct: rows.reduce((s, x) => s + x.pl.pct, 0) / n, total,
    model: pw.length ? pw.reduce((s, x) => s + x.t.pWin, 0) / pw.length : null, byPlan: rows.filter(x => jHow(x.t) !== "early").length };
}
function renderJournal() {
  const J = state.jr; if (!J.ready) return;
  const open = J.trades.filter(t => t.status !== "closed"), closed = J.trades.filter(t => t.status === "closed"), now = Date.now();
  const btn = $("#jr-btn"); if (btn) btn.textContent = "My trades" + (open.length ? ` (${open.length})` : "");
  if (!J.open) return;
  const box = $("#jbox"), ae = document.activeElement, keepFocus = ae && box.contains(ae) && ae.id ? ae.id : null;
  let openPL = 0, priced = 0;
  const trs = J.trades.map(t => {
    const isClosed = t.status === "closed", v = isClosed ? null : jValue(t), val = isClosed ? t.exit : v ? v.value : null, pl = jPL(t, val), s = jStatus(t, val, now), m = J.mode[t.id] || {};
    if (!isClosed && pl) { openPL += pl.usd; priced++; }
    const sp = t.kind === "spread", tag = `<span class="tag ${t.isC ? "c" : "p"}">${t.isC ? "CALL" : "PUT"}${sp ? (t.side === "buy" ? " DEBIT" : " CREDIT") : ""}</span>${!sp && t.side === "sell" ? ' <span class="tag p">SHORT</span>' : ""}`;
    const now$ = isClosed ? `${fmt(t.exit)}<br><span class="muted">exit ${t.closed ? day(t.closed) : ""}</span>` : v ? `${fmt(v.value)}<br><span class="muted">${fmt(v.bid)} / ${fmt(v.ask)}</span>` : "–";
    let act;
    if (m.k === "close") act = `<span class="jform"><label class="muted" for="jx-${esc(t.id)}">Exit $/share</label><input id="jx-${esc(t.id)}" data-exit="${esc(t.id)}" type="number" min="0" step="0.01" value="${esc(m.exit)}"><button class="btn sm primary" type="button" data-act="close-save" data-id="${esc(t.id)}">Record close</button><button class="btn sm" type="button" data-act="cancel" data-id="${esc(t.id)}">Cancel</button>${m.msg ? `<span class="warn">${esc(m.msg)}</span>` : ""}</span>`;
    else if (m.k === "delete") act = `<span class="jform"><span class="warn">Delete this trade for good?</span><button class="btn sm" type="button" data-act="delete-yes" data-id="${esc(t.id)}">Delete</button><button class="btn sm" type="button" data-act="cancel" data-id="${esc(t.id)}">Keep it</button></span>`;
    else act = `<span class="jform">${isClosed ? "" : `<button class="btn sm" type="button" data-act="close" data-id="${esc(t.id)}">Close</button>`}<button class="btn sm" type="button" data-act="delete" data-id="${esc(t.id)}">Delete</button></span>`;
    if (J.readonly) act = "";
    return `<tr class="${t.note ? "main" : ""}"><td class="l">${t.created ? day(t.created) : "–"}</td>
      <td class="l"><b>${esc(t.label || t.sym)}</b> ${tag} ${t.grade ? `<span class="grade g${t.grade === "–" ? "x" : esc(t.grade)}">${esc(t.grade)}</span>` : ""}</td>
      <td class="num">${esc(t.qty)}</td><td class="num">${fmt(t.entry)}<br><span class="muted">${t.side === "buy" ? "paid" : "credit"}</span></td><td class="num">${now$}</td>
      <td class="num ${pl ? (pl.usd >= 0 ? "up" : "down") : ""}">${pl ? sgnMoney(pl.usd, 0) + `<br><span class="muted">${pct(pl.pct, 0, true)}</span>` : "–"}</td>
      <td class="num">${t.target == null ? "–" : fmt(t.target)}</td><td class="num">${t.stop == null ? "none" : fmt(t.stop)}</td><td class="num">${t.closeBy ? day(t.closeBy) : "–"}</td>
      <td class="num">${pct(t.pWin, 0)}</td>
      <td class="l"><span class="verdict ${s.cls}">${s.tag}</span>${s.sub ? `<span class="jsub">${s.sub}</span>` : ""}</td><td class="l">${act}</td></tr>` +
      (t.note ? `<tr class="noterow"><td colspan="12"><div class="posnotes"><span>Note: ${esc(t.note)}</span></div></td></tr>` : "");
  }).join("");
  const S = jStats(closed);
  const stats = S ? `<div class="totals jstats"><span>Closed <b>${S.n}</b></span><span>Win rate <b>${pct(S.rate, 0)}</b> (${S.w} of ${S.n})</span><span>Model's average predicted win <b>${pct(S.model, 0)}</b></span>
      <span>Average result <b class="${S.avgUsd >= 0 ? "up" : "down"}">${sgnMoney(S.avgUsd, 0)}</b> per trade (${pct(S.avgPct, 1, true)} of the entry price)</span><span>Total <b class="${S.total >= 0 ? "up" : "down"}">${sgnMoney(S.total, 0)}</b></span><span>Closed by the plan <b>${S.byPlan} of ${S.n}</b></span></div>
      ${S.n < 20 ? `<p class="note">Fewer than 20 closed trades: the gap between your win rate and the model's is still mostly luck.</p>` : ""}`
    : J.trades.length ? `<p class="note">Close a trade here when you exit it in Robinhood. Win rate and average result build from the closed ones, next to the win rate the model predicted.</p>` : "";
  const qInfo = J.qBusy ? "updating quotes…" : J.qAt ? "quotes " + new Date(J.qAt).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) : "";
  box.innerHTML = `<div class="poshead"><h2>My trades <span class="muted" style="font-weight:500;font-size:13px">· ${open.length} open · ${closed.length} closed${priced ? ` · open P/L <span class="${openPL >= 0 ? "up" : "down"}">${sgnMoney(openPL, 0)}</span>` : ""}${qInfo ? " · " + qInfo : ""}</span></h2>
      <div class="actions" style="margin:0"><button class="btn sm" type="button" data-act="refresh">Refresh</button><button class="btn sm" type="button" data-act="hide">Hide</button></div></div>
    ${J.err ? `<p class="note warn">${esc(J.err)}</p>` : ""}${J.qErr ? `<p class="note warn">${esc(J.qErr)}</p>` : ""}
    ${!J.loaded ? `<p class="note">Loading your trades…</p>` : !J.trades.length ? `<p class="note">No trades tracked yet. After you place one in Robinhood, open its row here and use <b>Track this trade</b> in the details panel. Your journal is private to you.</p>` : ""}
    ${stats}
    ${J.trades.length ? `<div class="postable"><table><thead><tr><th class="l">Logged</th><th class="l">Trade</th><th>Qty</th><th>Entry</th><th>Now / exit</th><th>P/L</th><th>Target</th><th>Stop</th><th>Close by</th><th>Model win %</th><th class="l">Vs the plan</th><th class="l"></th></tr></thead><tbody>${trs}</tbody></table></div>
    <p class="note">Prices are per share; P/L is for all contracts. "Now" is what closing would get you at a limit halfway from the mid to the bid (buys) or the ask (sales), from Robinhood real-time quotes${marketHours() ? ", refreshed every minute" : ""}. Target, stop and close-by are the plan's exit levels from your entry. Your journal is private to you.</p>` : ""}`;
  if (keepFocus) { const el = document.getElementById(keepFocus); if (el) { try { el.focus({ preventScroll: true }); } catch (e) {} } }
}
async function jAction(act, id, btn) {
  const J = state.jr;
  if (act === "refresh") return jRequote();
  if (act === "hide") return closeJournal();
  const t = J.trades.find(x => x.id === id); if (!t || J.readonly) return;
  if (act === "close") { const v = jValue(t); J.mode[id] = { k: "close", exit: (v ? v.value : t.entry).toFixed(2) }; renderJournal(); const el = document.getElementById("jx-" + id); if (el) el.focus(); return; }
  if (act === "delete") { J.mode[id] = { k: "delete" }; return renderJournal(); }
  if (act === "cancel") { delete J.mode[id]; return renderJournal(); }
  if (act === "close-save") {
    const m = J.mode[id]; if (!m || m.busy) return;
    const x = parseFloat(m.exit); if (!(x >= 0)) { m.msg = "Enter the exit price per share."; return renderJournal(); }
    m.busy = true; if (btn) btn.disabled = true;
    try { await jWrite(() => J.col.doc(id).update({ status: "closed", exit: +x.toFixed(4), closed: Date.now() })); delete J.mode[id]; J.err = ""; }
    catch (e) { m.busy = false; J.err = jErrText(e); }
    return renderJournal();
  }
  if (act === "delete-yes") {
    const m = J.mode[id]; if (!m || m.busy) return; m.busy = true; if (btn) btn.disabled = true;
    try { await jWrite(() => J.col.doc(id).delete()); delete J.mode[id]; J.err = ""; }
    catch (e) { m.busy = false; J.err = jErrText(e); }
    return renderJournal();
  }
}
/* "Track this trade" in the details panel */
function trackFormHTML(r) {
  const J = state.jr; if (!JOURNAL || !J.ready) return "";
  const head = `<div class="jtrack" id="jtrack" data-id="${esc(r.id)}"><p class="eyebrow">Track this trade</p>`;
  if (J.readonly) return head + `<p class="note">Saving trades isn't allowed at your access level on this page.</p></div>`;
  if (!r.raw.every(L => L.instId)) return head + `<p class="note">Tracking needs Robinhood real-time quotes for this contract, and they aren't loaded in this view.</p></div>`;
  return head + `<p class="note">Placed it in Robinhood? Save it here to follow its live P/L against this plan, and to compare your results with the model's win rate. Private to you.</p>
    <div class="jfields">
      <div class="f"><label for="jt-qty">Contracts</label><input id="jt-qty" type="number" min="1" step="1" value="1"></div>
      <div class="f"><label for="jt-entry">${r.side === "buy" ? "Paid" : "Credit"} per share ($)</label><input id="jt-entry" type="number" min="0" step="0.01" value="${r.price.toFixed(2)}"></div>
      <div class="f jnote"><label for="jt-note">Note (optional)</label><input id="jt-note" type="text" maxlength="200" placeholder="Why you took it"></div>
      <button class="btn primary" type="button" id="jt-save">Track this trade</button>
    </div>
    <span class="note" id="jt-msg" role="status"></span></div>`;
}
function wireTrackForm() {
  const box = $("#jtrack"); if (!box || box.dataset.wired) return; box.dataset.wired = "1";
  const ent = $("#jt-entry"); if (ent) ent.addEventListener("input", () => { ent.dataset.edited = "1"; });
  const btn = $("#jt-save"); if (btn) btn.addEventListener("click", () => saveTrade(box.dataset.id, btn));
}
async function saveTrade(id, btn) {
  const J = state.jr, msg = $("#jt-msg"); if (!J.ready || J.readonly || btn.disabled) return;
  const r = state.rows.find(x => x.id === id) || (J.formRow && J.formRow.id === id ? J.formRow : null);
  if (!r) { msg.textContent = "This contract is no longer in the list. Open it again and retry."; return; }
  const qty = Math.round(+$("#jt-qty").value), entry = +(+$("#jt-entry").value).toFixed(4), note = String($("#jt-note").value || "").trim().slice(0, 200);
  if (!(qty >= 1 && qty <= 100000)) { msg.textContent = "Contracts must be a whole number, 1 or more."; return; }
  if (!(entry > 0)) { msg.textContent = "Enter the price per share you got, for example 1.25."; return; }
  const plan = planNow(r.side), lv = E.planLevels(Object.assign({}, r, { price: entry }), plan), P = planFor(r, DRAWER_PATHS) || r.plan;   // the plan's levels, from your own entry
  if (!lv) { msg.textContent = "Couldn't work out the plan's exit levels for that price."; return; }
  const fin = x => (typeof x === "number" && isFinite(x)) ? x : null;
  const closeBy = r.exp - Math.max(0, (r.dte - Math.min(plan.hold, r.dte))) * 864e5;
  const tid = "t" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  const body = { id: tid, created: Date.now(), sym: r.sym, label: structName(r), kind: r.kind, side: r.side, isC: !!r.isC, exp: r.exp,
    legs: r.raw.map((L, i) => ({ occ: L.occ, instId: L.instId, K: L.K, isC: !!L.isC, q: r.legs[i] ? r.legs[i].q : (i ? -1 : 1) })),
    qty, entry, note, status: "open",
    target: fin(lv.target), stop: (r.side === "buy" ? lv.stop > 0 : isFinite(lv.stop)) ? fin(lv.stop) : null, hold: fin(lv.hold), closeBy: fin(closeBy),
    plan: Object.assign({}, state.plan[r.side]), pWin: fin(P && P.pWin), planEv: fin(P && P.ev), ev: fin(r.ev), evPct: fin(r.evPct), grade: r.grade || null,
    fillEst: fin(r.price), S: fin(r.S), lens: state.lens };
  btn.disabled = true; msg.textContent = "Saving…";
  try {
    await jWrite(() => J.col.doc(tid).set(body));
    msg.innerHTML = `Saved to My trades. <button class="btn sm" type="button" id="jt-open">Open My trades</button>`;
    $("#jt-open").addEventListener("click", () => openJournal(true)); $("#jt-note").value = "";
  } catch (e) { msg.textContent = jErrText(e); }
  finally { btn.disabled = false; }
}

/* ---------- track record (public site and Mac; the Claude version can't load it) ---------- */
/* Server mode: upcoming earnings from the daily GitHub job (earnings.json via /api/earnings) replace the built-in dates. */
async function loadEarnings() {
  if (state.mode !== "server") return;
  try {
    const j = await fetchJSON(state.apiBase + "/api/earnings", 30000);
    if (!j || !j.d) return;
    const m = E.earnMap(j, Date.now()); let changed = false;
    for (const s in m) { const o = state.earn[s]; if (o && o.src === "robinhood") continue;
      if (!o || o.t !== m[s].t || o.verified !== m[s].verified) { state.earn[s] = m[s]; changed = true; } }
    if (changed && state.data) { state.earnVer++; reanalyze(); renderSymbols(); build(); if (state.sel) select(state.sel, true); }
  } catch (e) { /* keep the built-in dates */ }
}
async function loadTrack() {
  const box = $("#trackbox");
  if (IN_CLAUDE) { box.innerHTML = `<div class="trackhead"><h2>Track record</h2></div><p class="note">A scheduled job logs the top A-grade picks every trading day and scores how they actually did. Claude's security rules stop this page from loading it here; it's on the public site at <b>strike-finder.onrender.com</b>, near the bottom.</p>`; return; }
  for (const base of (state.apiBase != null ? [state.apiBase] : serverBases())) {
    try { const j = await fetchJSON(base + "/api/track", base ? 90000 : 8000); if (j && Array.isArray(j.picks)) { state.track = j; renderTrack(j); return; } } catch (e) {}
  }
  box.innerHTML = `<div class="trackhead"><h2>Track record</h2></div><p class="note">Couldn't load the track record right now.</p>`;
}
function renderTrack(L) {
  const box = $("#trackbox"), picks = L.picks || [], closed = picks.filter(p => p.status !== "open"), open = picks.filter(p => p.status === "open");
  const cats = { "single-buy": "Single options, bought", "spread-buy": "Debit spreads", "spread-sell": "Credit spreads" };
  const stat = arr => { const n = arr.length, w = arr.filter(p => p.pl > 0).length, avg = n ? arr.reduce((t, p) => t + (p.plPct || 0), 0) / n : null, sum = arr.reduce((t, p) => t + (p.pl || 0) * 100, 0),
    exp = n ? arr.reduce((t, p) => t + (p.pWin || 0), 0) / n : null; return { n, w, rate: n ? w / n : null, avg, sum, exp }; };
  const all = stat(closed);
  const card = (k, v, s) => `<div class="card"><span class="k">${k}</span><span class="v">${v}</span><span class="s">${s}</span></div>`;
  let html = `<div class="trackhead"><h2>Track record</h2><span class="note">${picks.length} picks logged since ${picks.length ? esc(picks[0].date) : "—"} · updated ${L.updated ? stamp(Date.parse(L.updated)) : "—"} · one contract per pick, default plan</span></div>`;
  if (!picks.length) html += `<p class="note">No picks logged yet. The job runs every trading day at about 2:45 PM ET; give it a few weeks before reading anything into the numbers.</p>`;
  else {
    html += `<div class="cards">` + card("Closed picks", all.n, `${open.length} still open`) +
      card("Win rate", all.rate == null ? "–" : pct(all.rate, 0), all.exp == null ? "" : `model expected ${pct(all.exp, 0)}`) +
      card("Average result", all.avg == null ? "–" : pct(all.avg, 1, true), "per trade, on the money at risk") +
      card("Total, 1 contract each", sgnMoney(all.sum, 0), "after the modeled fills") +
      Object.entries(cats).map(([c, label]) => { const s = stat(closed.filter(p => p.cat === c)); return card(label, s.n ? pct(s.rate, 0) + " win" : "–", s.n ? `${s.n} closed · avg ${pct(s.avg, 1, true)} · ${sgnMoney(s.sum, 0)}` : "none closed yet"); }).join("") + `</div>`;
    if (all.n < 30) html += `<p class="note">Fewer than 30 closed picks: these numbers are still mostly noise.</p>`;
    const recent = picks.slice(-40).reverse();
    html += `<div class="tracktable"><table><thead><tr><th class="l">Logged</th><th class="l">Pick</th><th class="l">Grade</th><th>Entry</th><th>Latest / exit</th><th>P/L</th><th>Model win %</th><th class="l">Status</th></tr></thead><tbody>` +
      recent.map(p => { const last = p.exit != null ? p.exit : (p.marks && p.marks.length ? p.marks[p.marks.length - 1].v : null);
        const plv = p.pl != null ? p.pl : last != null ? (p.side === "buy" ? last - p.entry : p.entry - last) : null;
        return `<tr><td class="l">${esc(p.date)}</td><td class="l">${esc(p.label)}</td><td class="l"><span class="grade g${esc(p.grade)}">${esc(p.grade)}</span></td><td class="num">${fmt(p.entry)}</td><td class="num">${fmt(last)}</td>
          <td class="num ${plv > 0 ? "up" : plv < 0 ? "down" : ""}">${plv == null ? "–" : sgnMoney(plv * 100, 0)}</td><td class="num">${pct(p.pWin, 0)}</td><td class="l">${esc(({ open: "open", target: "hit target", stop: "stopped", time: "time limit", expired: "expired" })[p.status] || p.status)}</td></tr>`; }).join("") + `</tbody></table></div>`;
  }
  box.innerHTML = html;
}

/* ---------- controls ---------- */
function renderSymbols() {
  const w = $("#symstrip"); w.textContent = "";
  const shown = new Map((state.data ? state.data.symbols : []).map(S => [S.s, S]));
  let order = [...shown.keys()];
  if (state.mode === "rt" || (IN_CLAUDE && state.mcp)) order = [...new Set(CORE.concat(WATCH, state.extra))];
  for (const s of order) {
    const S = shown.get(s), A = state.syms.find(x => x.sym === s);
    const b = document.createElement("button"); b.type = "button"; b.className = "sym";
    const loading = !S && state.rtLoading, failed = !S && state.rtFail.has(s);
    if (!S) b.classList.add(loading ? "loading" : "stale");
    b.setAttribute("aria-pressed", S && state.selected.has(s) ? "true" : "false");
    const chg = S && S.chg != null ? S.chg / 100 : null;
    if (A && A.mismatch) b.title = `The stock quote ($${fmt(A.mismatch.quoted, 2)}) and the option quotes (which imply $${fmt(A.mismatch.implied, 2)}) are out of sync; prices use the options' $${fmt(A.mismatch.implied, 2)}.`;
    b.innerHTML = S ? `<b>${s}</b>${S.rt ? '<span class="rtdot" title="real-time from Robinhood">RT</span>' : ""}${A && A.mismatch ? ' <span class="warn" title="quotes out of sync">≠</span>' : ""}<span class="px num">${fmt(A ? A.px : S.px, 2)} <span class="${chg > 0 ? "up" : chg < 0 ? "down" : ""}">${chg != null ? pct(chg, 1, true) : ""}</span></span><span class="iv num">${A && A.hv ? "HV " + (A.hv * 100).toFixed(0) + "%" : A && A.iv30 ? "IV30 " + (A.iv30 * 100).toFixed(0) + "%" : "–"}${A && A.trend > 0 ? ' <span class="up">▲</span>' : A && A.trend < 0 ? ' <span class="down">▼</span>' : ""}${A && A.ev ? ' <span class="warn">⚡</span>' : ""} · ${S.o.length} opts</span>`
      : `<b>${s}</b><span class="px num muted">${loading ? "loading…" : failed ? "not loaded" : "tap to load"}</span><span class="iv num">${failed ? esc(String(state.rtFail.get(s)).slice(0, 22)) : "&nbsp;"}</span>`;
    if (!S) b.title = failed ? "Tap to retry loading from Robinhood" : "";
    b.addEventListener("click", () => {
      if (!S) { if (state.mcp && !state.rtLoading) rhLoadAll([s]); return; }
      if (state.selected.has(s)) state.selected.delete(s); else state.selected.add(s); b.setAttribute("aria-pressed", state.selected.has(s) ? "true" : "false"); build();
    });
    w.appendChild(b);
  }
  const add = document.createElement("div"); add.className = "addsym";
  add.innerHTML = `<input id="addsym" placeholder="Add: MRNA" maxlength="8" aria-label="Add symbol"><button class="btn sm" type="button" id="addbtn">Add</button><button class="btn sm" type="button" id="allbtn">All</button><button class="btn sm" type="button" id="nonebtn">None</button>`;
  w.appendChild(add);
  $("#addbtn").addEventListener("click", () => addSymbol($("#addsym").value));
  $("#addsym").addEventListener("keydown", e => { if (e.key === "Enter") addSymbol($("#addsym").value); });
  $("#allbtn").addEventListener("click", () => { (state.data ? state.data.symbols : []).forEach(S => state.selected.add(S.s)); renderSymbols(); build(); });
  $("#nonebtn").addEventListener("click", () => { state.selected.clear(); renderSymbols(); build(); });
}
async function addSymbol(raw) {
  const sym = String(raw || "").toUpperCase().replace(/[^A-Z0-9.]/g, ""); if (!sym || !state.data) return;
  if (state.data.symbols.some(S => S.s === sym)) { state.selected.add(sym); renderSymbols(); build(); return; }
  if (state.mcp) { if (!state.extra.includes(sym)) { state.extra.push(sym); try { localStorage.setItem("sf:extra", JSON.stringify(state.extra)); } catch (e) {} } await rhLoadAll([sym]); return; }
  setStatus("Fetching " + sym + "…", "live");
  try { const S = await fetchJSON((state.apiBase || "") + "/api/chain?symbol=" + encodeURIComponent(sym), 60000); if (S.error) throw new Error(S.error);
    state.data.symbols.push(S); state.selected.add(sym); setData(state.data.symbols, state.data); setStatus(liveLabel(), "live"); }
  catch (e) { setStatus("Couldn't load " + sym + ": " + (e.message || e), "snap"); }
}
function renderLenses() {
  const w = $("#lenses"); w.textContent = "";
  E.LENSES.forEach(L => { const b = document.createElement("button"); b.type = "button"; b.className = "lens"; b.id = "lens-" + L.id; b.textContent = L.name; b.setAttribute("aria-pressed", state.lens === L.id ? "true" : "false");
    b.addEventListener("click", () => { state.lens = L.id; state.sortK = "score"; state.sortDir = -1; renderLenses(); markSort(); build(); if (state.sel) select(state.sel, true); }); w.appendChild(b); });
  $("#lens-desc").textContent = E.LENSES.find(l => l.id === state.lens).desc;
}
function seg(id, onchange) { $("#" + id).querySelectorAll("button").forEach(b => b.addEventListener("click", () => { $("#" + id).querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x === b ? "true" : "false")); onchange(b.dataset.v); })); }
function markSort() { document.querySelectorAll("#tbl thead th").forEach(th => { th.removeAttribute("aria-sort"); if (th.dataset.k === state.sortK) th.setAttribute("aria-sort", state.sortDir < 0 ? "descending" : "ascending"); }); }
/* Side and structure change the sensible defaults (delta band, spread limit, plan); fields you've edited keep your value. */
function applyDefaults() {
  const d = E.STRUCT_DEFAULTS[state.struct + "|" + state.side];
  if (!state.touched["delta-min"]) $("#delta-min").value = d.dMin.toFixed(2);
  if (!state.touched["delta-max"]) $("#delta-max").value = d.dMax.toFixed(2);
  if (!state.touched["max-spread"]) $("#max-spread").value = d.maxSpread;
  const p = state.plan[state.side]; $("#plan-target").value = p.target; $("#plan-stop").value = p.stop; $("#plan-hold").value = p.hold;
  const buy = state.side === "buy";
  $("#plan-target-label").textContent = buy ? "Take profit at +%" : "Take profit when kept %";
  $("#plan-stop-label").textContent = buy ? "Stop loss at −%" : "Stop when loss reaches % of credit";
  $("#delta-label").textContent = state.struct === "spread" ? (buy ? "|Delta| of the bought leg" : "|Delta| of the sold leg") : "|Delta|";
  $("#price-label").textContent = buy ? "Max cost / contract ($)" : state.struct === "spread" ? "Max loss / contract ($)" : "Max cost / contract ($)";
  planHint();
}
function planHint() {
  const p = state.plan[state.side], buy = state.side === "buy";
  $("#plan-hint").textContent = buy
    ? `Plan: sell when the position is up ${p.target}%, ${p.stop >= 100 ? "no stop" : "cut it if it's down " + p.stop + "%"}, otherwise close after ${p.hold} days (or at expiry if sooner). Win % and the expected result in the table follow this plan.`
    : `Plan: buy it back once you've kept ${p.target}% of the credit, ${p.stop >= 2000 ? "no stop" : "stop if the loss reaches " + p.stop + "% of the credit"}, otherwise close after ${p.hold} days. Win % and the expected result follow this plan.`;
}
function init() {
  seg("side", v => { state.side = v; applyDefaults(); build(); if (state.sel) select(state.sel, true); });
  seg("struct", v => { state.struct = v; state.sel = null; $("#drawer").hidden = true; applyDefaults(); build(); });
  seg("type", v => { state.type = v; build(); });
  seg("evfilter", v => { state.evMode = v; build(); });
  seg("quality", v => { state.quality = v; build(); });
  ["dte-min", "dte-max", "delta-min", "delta-max", "max-price", "min-oi", "max-spread", "per-sym"].forEach(id => $("#" + id).addEventListener("input", () => { state.touched[id] = true; build(); maybeReloadRange(); }));
  let pt = null;
  ["plan-target", "plan-stop", "plan-hold"].forEach(id => $("#" + id).addEventListener("input", () => {
    const p = state.plan[state.side], v = parseFloat($("#" + id).value); if (!(v > 0)) return;
    if (id === "plan-target") p.target = v; else if (id === "plan-stop") p.stop = v; else p.hold = Math.round(v);
    planHint(); clearTimeout(pt); pt = setTimeout(() => { build(); if (state.sel) select(state.sel, true); }, 350);
  }));
  document.querySelectorAll("#tbl thead th").forEach(th => th.addEventListener("click", () => { const k = th.dataset.k; if (state.sortK === k) state.sortDir *= -1; else { state.sortK = k; state.sortDir = (k === "sym" || k === "type" || k === "grade") ? 1 : -1; } markSort(); build(); }));
  $("#refresh").addEventListener("click", async () => { if (state.mcp) { if (state.rt.size) rhRequote(true); else rhLoadAll([...new Set(CORE.concat(WATCH, state.extra))]); } else { setStatus("Refreshing…", "live"); await loadServer(); } });
  applyDefaults();
}
let rangeTimer = null;
function maybeReloadRange() {
  if (state.mode !== "rt" || !state.rtRange) return;
  clearTimeout(rangeTimer);
  rangeTimer = setTimeout(() => { const f = filters(); if (f.dteMin < state.rtRange.min - 0.5 || f.dteMax > state.rtRange.max + 0.5) { setStatus("Loading expirations for the new day range…", "live"); rhLoadAll([...state.rt.keys()]); } }, 1500);
}

/* ---------- start ---------- */
(async function start() {
  init(); renderLenses(); markSort();
  if (IN_CLAUDE) { loadTrack(); initJournal().catch(() => {}); await initClaude(); return; }
  await loadServer(); loadTrack(); loadEarnings();
  setInterval(() => { if (document.visibilityState === "visible" && state.mode === "server" && marketHours()) loadServer(); }, 5 * 60 * 1000);
  setInterval(() => { if (document.visibilityState === "visible" && state.mode === "server") { loadTrack(); loadEarnings(); } }, 30 * 60 * 1000);
})();
})();
