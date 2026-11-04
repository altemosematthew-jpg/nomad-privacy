/* ENGINE-START
 * Strike Finder engine: the analytics shared by the page and by the daily track-record job (track.js).
 * Pure functions only: no DOM, no network, no clock except the `now` passed in.
 */
var Engine = (function () {
  "use strict";
  var R = 0.04;          // risk-free rate
  var W_IV = 0.6;        // forecast variance weight on implied vol; the rest on realized vol (earnings gaps removed)
  var FILL = 0.5;        // limit-order fills assumed halfway between the mid and the natural price, both in and out
  var YEAR_MS = 365 * 864e5;

  /* Known earnings dates (ET), refreshed live from Robinhood in the Claude version. Past dates are ignored. */
  var EARNINGS_SEED = { asOf: "2026-11-04", d: {
    UBER: ["2026-11-04", "am", true], ARM: ["2026-11-04", "pm", true], DIS: ["2026-11-17", "am", true], NVDA: ["2026-11-17", "pm", true],
    MRVL: ["2026-12-01", "pm", false], AVGO: ["2026-12-09", "pm", true], MU: ["2026-12-23", "pm", false] } };

  var NO_EARNINGS = {}; "SPY QQQ IWM DIA SPX NDX RUT XSP VIX GLD SLV TLT HYG LQD EEM EFA FXI XLF XLE XLK XLV XLI XLY XLP XLU XLB XLRE XBI SMH SOXX ARKK USO UNG UVXY VXX TQQQ SQQQ SOXL SOXS KRE IBIT".split(" ").forEach(function (s) { NO_EARNINGS[s] = 1; });

  /* ---------- math ---------- */
  function ncdf(x) {
    var t = 1 / (1 + 0.2316419 * Math.abs(x));
    var d = 0.3989422804014327 * Math.exp(-x * x / 2);
    var p = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
    return x > 0 ? 1 - p : p;
  }
  function bs(S, K, T, sig, isC) {
    if (!(S > 0) || !(K > 0)) return 0;
    if (!(T > 1e-6)) return Math.max(0, isC ? S - K : K - S);
    if (!(sig > 1e-4)) { var dk = K * Math.exp(-R * T); return Math.max(0, isC ? S - dk : dk - S); }
    var sq = sig * Math.sqrt(T), d1 = (Math.log(S / K) + (R + 0.5 * sig * sig) * T) / sq, d2 = d1 - sq, df = Math.exp(-R * T);
    return isC ? S * ncdf(d1) - K * df * ncdf(d2) : K * df * ncdf(-d2) - S * ncdf(-d1);
  }
  /* Black-Scholes implied vol from a price (bisection on [1%, 500%]); null when the price is at or below intrinsic. */
  function impliedVol(price, S, K, T, isC) {
    if (!(price > 0 && S > 0 && K > 0 && T > 0)) return null;
    var intr = Math.max(0, isC ? S - K * Math.exp(-R * T) : K * Math.exp(-R * T) - S);
    if (price <= intr + 1e-4 || price >= (isC ? S : K)) return null;
    var lo = 0.01, hi = 5;
    if (bs(S, K, T, lo, isC) > price || bs(S, K, T, hi, isC) < price) return null;
    for (var i = 0; i < 40; i++) { var mid = (lo + hi) / 2; if (bs(S, K, T, mid, isC) > price) hi = mid; else lo = mid; if (hi - lo < 1e-5) break; }
    return (lo + hi) / 2;
  }
  /* Probability the stock finishes above (or below) a level, lognormal with vol sig. */
  function probBeyond(S, level, T, sig, above) {
    if (!(S > 0 && T > 0 && sig > 0)) return null;
    if (!(level > 0)) return above ? 1 : 0;
    var d = (Math.log(S / level) + (R - sig * sig / 2) * T) / (sig * Math.sqrt(T));
    return above ? ncdf(d) : ncdf(-d);
  }
  function mean(a) { var s = 0; for (var i = 0; i < a.length; i++) s += a[i]; return a.length ? s / a.length : NaN; }
  function median(a) { var b = a.slice().sort(function (x, y) { return x - y; }); var n = b.length; return n ? (n % 2 ? b[(n - 1) / 2] : (b[n / 2 - 1] + b[n / 2]) / 2) : NaN; }
  function stdev(a) { if (a.length < 2) return null; var m = mean(a), s = 0; for (var i = 0; i < a.length; i++) s += (a[i] - m) * (a[i] - m); return Math.sqrt(s / (a.length - 1)); }
  function hash(s) { var h = 2166136261; s = String(s); for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function rng(seed) { var a = seed >>> 0; return function () { a = (a + 0x6D2B79F5) | 0; var t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  function normals(rand, n) {
    var z = new Float64Array(n);
    for (var i = 0; i < n; i += 2) { var u = rand(); if (u < 1e-12) u = 1e-12; var v = rand(), r = Math.sqrt(-2 * Math.log(u)); z[i] = r * Math.cos(2 * Math.PI * v); if (i + 1 < n) z[i + 1] = r * Math.sin(2 * Math.PI * v); }
    return z;
  }

  /* ---------- dates ---------- */
  function parseOCC(occ) {
    var m = /^([A-Z0-9.\-^]{1,10})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/.exec(occ); if (!m) return null;
    return { root: m[1], exp: etTime(2000 + +m[2], +m[3], +m[4], 16, 0), type: m[5], strike: +m[6] / 1000 };
  }
  /* Epoch ms for a wall-clock time in New York (handles daylight saving). */
  function etTime(y, mo, d, hh, mm) {
    var mar = new Date(Date.UTC(y, 2, 1)).getUTCDay(), secondSun = 1 + ((7 - mar) % 7) + 7;   // DST starts the second Sunday of March
    var nov = new Date(Date.UTC(y, 10, 1)).getUTCDay(), firstSun = 1 + ((7 - nov) % 7);       // and ends the first Sunday of November
    var dst = (mo > 3 && mo < 11) || (mo === 3 && d >= secondSun) || (mo === 11 && d < firstSun);
    return Date.UTC(y, mo - 1, d, hh + (dst ? 4 : 5), mm);
  }
  function earnMap(seed, now) {
    var out = {}; var d = (seed || EARNINGS_SEED).d;
    for (var s in d) { var e = d[s], p = e[0].split("-"); var t = etTime(+p[0], +p[1], +p[2], e[1] === "am" ? 9 : 16, e[1] === "am" ? 0 : 5);
      if (t > now) out[s] = { t: t, date: e[0], timing: e[1], verified: !!e[2], src: "calendar" }; }
    return out;
  }

  /* ---------- price history ---------- */
  function histStats(closes) {
    var c = []; for (var i = 0; i < closes.length; i++) { var x = +closes[i]; if (x > 0) c.push(x); }
    if (c.length < 25) return null;
    var r = []; for (i = 1; i < c.length; i++) r.push(Math.log(c[i] / c[i - 1]));
    var last = c[c.length - 1];
    function sma(n) { return c.length >= n ? mean(c.slice(-n)) : null; }
    function hv(n) { return r.length >= n ? stdev(r.slice(-n)) * Math.sqrt(252) : null; }
    function hvx(n) { // realized vol with jump days (earnings gaps) removed: |r - median| > 4 robust sigmas
      if (r.length < n) return null; var a = r.slice(-n), med = median(a), mad = median(a.map(function (x) { return Math.abs(x - med); })) * 1.4826;
      var cut = 4 * Math.max(mad, 0.002), b = a.filter(function (x) { return Math.abs(x - med) <= cut; });
      return stdev(b.length >= Math.ceil(n * 0.8) ? b : a) * Math.sqrt(252);
    }
    function ret(n) { return c.length > n ? last / c[c.length - 1 - n] - 1 : null; }
    var y = c.slice(-252);
    return { last: last, sma20: sma(20), sma50: sma(50), sma200: sma(200), hv20: hv(20), hv60: hv(60), hv20x: hvx(20), hv60x: hvx(60),
      ret1m: ret(21), ret3m: ret(63), hi52: Math.max.apply(null, y), lo52: Math.min.apply(null, y), n: c.length };
  }
  function realizedVol(h) {
    if (!h) return null;
    var a = h.hv20x != null ? h.hv20x : h.hv20, b = h.hv60x != null ? h.hv60x : h.hv60;
    if (a > 0 && b > 0) return Math.sqrt((a * a + b * b) / 2);
    return a > 0 ? a : b > 0 ? b : null;
  }
  function trendOf(px, h) { if (!h || !h.sma20 || !h.sma50) return 0; return px > h.sma20 && h.sma20 > h.sma50 ? 1 : px < h.sma20 && h.sma20 < h.sma50 ? -1 : 0; }

  /* ---------- term structure and scheduled events ---------- */
  function termStructure(S, now) {
    var rows = [];
    for (var i = 0; i < S.o.length; i++) { var o = S.o[i], p = parseOCC(o[0]); if (p) rows.push({ exp: p.exp, iv: +o[5], delta: +o[8] }); }
    return termFrom(rows, now);
  }
  /* ATM implied vol per expiry: delta-weighted average of the 0.3–0.7 delta contracts. */
  function termFrom(rows, now) {
    var by = {}, i;
    for (i = 0; i < rows.length; i++) {
      var r = rows[i], iv = +r.iv, ad = Math.abs(+r.delta); if (!(iv > 0.01 && iv < 5) || ad < 0.3 || ad > 0.7) continue;
      var w = 1 - Math.abs(ad - 0.5) / 0.2; if (w <= 0) continue;
      var g = by[r.exp] || (by[r.exp] = { exp: r.exp, s: 0, sw: 0 }); g.s += w * iv; g.sw += w;
    }
    var pts = [];
    for (var k in by) { var gg = by[k], T = (gg.exp - now) / YEAR_MS; if (gg.sw > 0 && T >= 1.5 / 365) pts.push({ exp: gg.exp, T: T, iv: gg.s / gg.sw }); }
    pts.sort(function (a, b) { return a.T - b.T; });
    return pts;
  }
  function atmIVAt(pts, T) {
    if (!pts || !pts.length) return null;
    if (T <= pts[0].T) return pts[0].iv;
    var n = pts.length; if (T >= pts[n - 1].T) return pts[n - 1].iv;
    for (var i = 1; i < n; i++) if (T <= pts[i].T) {
      var a = pts[i - 1], b = pts[i], va = a.iv * a.iv * a.T, vb = b.iv * b.iv * b.T;
      return Math.sqrt(Math.max(va + (vb - va) * (T - a.T) / (b.T - a.T), 1e-8) / T);
    }
    return pts[n - 1].iv;
  }
  /* Forward variance between consecutive expiries. A spike that stands out from its neighbouring intervals is a scheduled jump
     (earnings); its excess variance is the market's implied move. Expiries under 5 days out are noisy, so a spike there must be huge. */
  function detectEvent(pts, earn, now) {
    var fw = [], prev = 0, i;
    for (i = 0; i < pts.length; i++) {
      var v = Math.max(pts[i].iv * pts[i].iv * pts[i].T, prev), t0 = i ? pts[i - 1].T : 0;
      fw.push({ t0: t0, t1: pts[i].T, e0: i ? pts[i - 1].exp : now, e1: pts[i].exp, f: (v - prev) / Math.max(pts[i].T - t0, 1e-6) }); prev = v;
    }
    var SHORT = 5 / 365, usable = fw.filter(function (x) { return x.t1 >= SHORT; });
    var base = usable.length >= 3 ? median(usable.map(function (x) { return x.f; })) : fw.length ? median(fw.map(function (x) { return x.f; })) : 0;
    function excess(x) { return Math.max(0, (x.f - base) * (x.t1 - x.t0)); }
    if (earn && earn.t > now) {
      var tE = (earn.t - now) / YEAR_MS, hit = null;
      for (i = 0; i < fw.length; i++) if (tE > fw[i].t0 - 1e-9 && tE <= fw[i].t1) { hit = fw[i]; break; }
      var mv = hit ? Math.sqrt(excess(hit)) : null;
      return { src: "calendar", tEvent: tE, at: earn.t, date: earn.date, timing: earn.timing, verified: earn.verified, move: mv && mv >= 0.005 ? mv : null };
    }
    var best = null;
    for (i = 0; i < fw.length; i++) {
      var x = fw[i], ex = excess(x), ok;
      if (x.t1 < SHORT) ok = x.f > 2 * base && ex >= 0.0016;
      else {
        var L = i > 0 ? fw[i - 1].f : base, Rn = i + 1 < fw.length ? fw[i + 1].f : null;
        var ref = Math.max(base, Rn != null ? (L + Rn) / 2 : L);
        ok = x.f > 1.25 * ref && ex >= 0.0009;
      }
      if (ok && (!best || ex > best.ex)) best = { x: x, ex: ex };
    }
    if (!best) return null;
    return { src: "iv", tEvent: (best.x.t0 + best.x.t1) / 2, tFrom: best.x.t0, tTo: best.x.t1, from: best.x.e0, to: best.x.e1, move: Math.sqrt(best.ex) };
  }
  function spans(ev, T) { if (!ev) return false; return ev.src === "calendar" ? T > ev.tEvent : T >= ev.tTo - 0.5 / 365; }

  /* ---------- per-symbol analysis ---------- */
  /* S: {s, px, iv30, ivchg, chg, o:[[occ,bid,ask,bidSize,askSize,iv,oi,vol,delta,gamma,theta,vega,theo,last,copL,copS,instId]], hist, h, rt} */
  /* The stock price the option quotes themselves imply (put-call parity on near-the-money pairs). When the stock quote and the
     option quotes are out of sync (a delayed feed, a gap after earnings), pricing off the stock quote invents edges that aren't there. */
  function paritySpot(S, now) {
    var px = +S.px, by = {}, i, o, p, out = [];
    for (i = 0; i < S.o.length; i++) {
      o = S.o[i]; p = parseOCC(o[0]); if (!p || !(+o[1] > 0) || !(+o[2] > 0)) continue;
      var T = (p.exp - now) / YEAR_MS; if (T < 5 / 365 || T > 70 / 365 || Math.abs(p.strike / px - 1) > 0.12) continue;
      var k = p.exp + "|" + p.strike, g = by[k] || (by[k] = { T: T, K: p.strike }); g[p.type] = (+o[1] + +o[2]) / 2;
      if (g.C != null && g.P != null) { out.push(g.C - g.P + g.K * Math.exp(-R * g.T)); g.C = g.P = null; }
    }
    if (out.length < 3) return null;
    return median(out);
  }
  function analyzeSymbol(S, ctx) {
    var px0 = +S.px; if (!(px0 > 0) || !S.o) return null;
    // Always price off the spot the option quotes imply (put-call parity), so call and put IVs at a strike agree;
    // flag it when it's far from the stock quote.
    var now = ctx.now, ps = paritySpot(S, now), px = ps || px0, mismatch = ps && Math.abs(ps / px0 - 1) > 0.025 ? { quoted: px0, implied: ps } : null;
    var pts = termStructure(S, now), earn = ctx.earn ? ctx.earn[S.s] : null;
    var h = S.hist || null, hv = realizedVol(h);
    var A = { sym: S.s, px: px, pxQuoted: px0, mismatch: mismatch, dropped: 0, pts: pts, ev: null, hist: h, hv: hv, trend: trendOf(px, h), iv30: null,
      ivchg: S.ivchg != null ? +S.ivchg : null, chg: S.chg != null ? +S.chg : null, rt: !!S.rt, stab: S.h || null, legs: [] };
    for (var i = 0; i < S.o.length; i++) {
      var o = S.o[i], p = parseOCC(o[0]); if (!p) continue;
      var bid = +o[1] || 0, ask = +o[2] || 0; if (!(ask > 0)) continue;
      var T = (p.exp - now) / YEAR_MS; if (T <= 0.5 / 365) continue;
      var ivSrc = +o[5] > 0.01 ? +o[5] : null, mid = bid > 0 ? (bid + ask) / 2 : ask;
      var ivMid = bid > 0 ? impliedVol(mid, px, p.strike, T, p.type === "C") : null;   // the contract's own quote, priced consistently
      if (ivMid && ivSrc && Math.abs(ivMid / ivSrc - 1) > 0.6) { A.dropped++; continue; }   // quote and IV disagree badly: a data problem, not an edge
      var iv = ivMid || ivSrc || atmIVAt(pts, T) || 0.3;
      A.legs.push({ ivSrc: ivSrc, sym: S.s, S: px, occ: o[0], type: p.type, isC: p.type === "C", exp: p.exp, T: T, dte: T * 365, K: p.strike, bid: bid, ask: ask,
        mid: bid > 0 ? (bid + ask) / 2 : ask, bs: +o[3] || 0, as: +o[4] || 0, iv: iv, oi: +o[6] || 0, vol: +o[7] || 0, delta: +o[8] || 0,
        gamma: +o[9] || 0, theta: +o[10] || 0, vega: +o[11] || 0, theo: +o[12] || 0, last: +o[13] || 0,
        copL: o[14] > 0 ? +o[14] : null, copS: o[15] > 0 ? +o[15] : null, instId: o[16] || null });
    }
    // term structure, 30-day IV and events on the same basis as the legs (their own mid-implied vols)
    var ptsMid = termFrom(A.legs, now); if (ptsMid.length >= 2) A.pts = ptsMid;
    A.iv30 = atmIVAt(A.pts, 30 / 365) || (S.iv30 ? S.iv30 / 100 : null);
    A.ev = NO_EARNINGS[S.s] && !earn ? null : detectEvent(A.pts, earn, now);   // funds have no earnings: term-structure bumps there aren't events
    return A;
  }

  /* ---------- structures: one option, or a two-leg vertical, as the combo you'd buy ---------- */
  function makeSingle(L, A, side) {
    return finish({ kind: "single", id: L.occ, sym: L.sym, S: L.S, type: L.type, isC: L.isC, exp: L.exp, T: L.T, dte: L.dte, K: L.K, K2: null,
      bid: L.bid, ask: L.ask, mid: L.mid, bs: L.bs, as: L.as, iv: L.iv, delta: L.delta, gamma: L.gamma, theta: L.theta, vega: L.vega,
      oi: L.oi, vol: L.vol, oiMin: L.oi, volMin: L.vol, theo: L.theo, last: L.last, copL: L.copL, copS: L.copS, anchorDelta: Math.abs(L.delta),
      raw: [L], legs: [{ K: L.K, isC: L.isC, q: 1, iv: L.iv }] }, A, side);
  }
  function makeSpread(A, a, b, side) {
    var width = Math.abs(b.K - a.K), bid = Math.max(0, a.bid - b.ask), ask = a.ask - b.bid, mid = Math.min(ask, Math.max(bid, a.mid - b.mid));
    var st = { kind: "spread", id: a.occ + "/" + b.occ, sym: a.sym, S: a.S, type: a.type, isC: a.isC, exp: a.exp, T: a.T, dte: a.dte, K: a.K, K2: b.K,
      width: width, bid: bid, ask: ask, mid: mid, bs: Math.min(a.bs, b.as), as: Math.min(a.as, b.bs), iv: (a.iv + b.iv) / 2,
      delta: a.delta - b.delta, gamma: a.gamma - b.gamma, theta: a.theta - b.theta, vega: a.vega - b.vega,
      oi: Math.min(a.oi, b.oi), vol: Math.min(a.vol, b.vol), oiMin: Math.min(a.oi, b.oi), volMin: Math.min(a.vol, b.vol),
      theo: a.theo > 0 && b.theo > 0 ? a.theo - b.theo : 0, last: 0, copL: null, copS: null, anchorDelta: Math.abs(a.delta),
      raw: [a, b], legs: [{ K: a.K, isC: a.isC, q: 1, iv: a.iv }, { K: b.K, isC: b.isC, q: -1, iv: b.iv }] };
    finish(st, A, side);
    var pr = st.price;
    if (side === "buy") { st.maxGain = width - pr; st.maxLoss = pr; st.rr = (width - pr) / pr; }
    else { st.maxGain = pr; st.maxLoss = width - pr; st.creditPct = pr / width; st.rr = pr / (width - pr); }
    return st;
  }
  /* For each anchor leg inside the delta range, pair the further-out strike that gives a standard shape:
     debit spreads near 1:1 reward to risk, credit spreads collecting about a third of the width. */
  function verticals(A, side, f) {
    var out = [], groups = {}, i, j;
    for (i = 0; i < A.legs.length; i++) { var L = A.legs[i], k = L.type + "|" + L.exp; (groups[k] || (groups[k] = [])).push(L); }
    for (var key in groups) {
      var g = groups[key].sort(function (x, y) { return x.K - y.K; });
      for (i = 0; i < g.length; i++) {
        var a = g[i], ad = Math.abs(a.delta); if (ad < f.dMin || ad > f.dMax || !(a.bid > 0)) continue;
        var best = null;
        for (j = 1; j <= 8; j++) {
          var b = a.isC ? g[i + j] : g[i - j]; if (!b) break;
          var width = Math.abs(b.K - a.K); if (width / A.px > 0.15) break;
          if (!(b.bid > 0)) continue;
          var bid = a.bid - b.ask, ask = a.ask - b.bid; if (!(ask > 0) || ask >= width) continue;
          var d;
          if (side === "buy") { var rr = (width - ask) / ask; if (rr < 0.5 || rr > 4) continue; d = Math.abs(Math.log(rr)); }
          else { if (!(bid > 0)) continue; var cp = bid / width; if (cp < 0.12 || cp > 0.65) continue; d = Math.abs(cp - 0.33); }
          if (!best || d < best.d) best = { b: b, d: d };
        }
        if (best) out.push(makeSpread(A, a, best.b, side));
      }
    }
    return out;
  }
  /* Volatility model. Forecast diffusive vol blends implied (60%) with realized ex-jumps (40%); every strike is scaled by the same
     factor k, so the model never claims to know the skew is mispriced. A scheduled event keeps the market's implied jump, capped at
     85% of a leg's implied variance so the forecast never sits above the market for no reason. */
  var EV_CAP = 0.85;
  function volModel(st) {
    var T = st.T, m = st.m || 0, atm = st.atm || st.iv;
    var evTot = Math.min(m * m, EV_CAP * atm * atm * T);         // the event's variance (total over the life), capped
    var atmDiff2 = atm * atm - evTot / T;
    var fd = st.hv > 0 ? Math.sqrt(W_IV * atmDiff2 + (1 - W_IV) * st.hv * st.hv) : Math.sqrt(atmDiff2);
    var k = fd / Math.sqrt(atmDiff2), i, L;
    for (i = 0; i < st.legs.length; i++) {
      L = st.legs[i]; L.ev2 = Math.min(evTot / T, EV_CAP * L.iv * L.iv); L.diff2 = L.iv * L.iv - L.ev2; L.evTot = L.ev2 * T;
      L.sigF = Math.sqrt(k * k * L.diff2 + L.ev2);
    }
    st.k = k; st.atmDiff = Math.sqrt(atmDiff2);
    // Simulation: each leg follows its own price path driven by the same market shocks, at its own forecast diffusive vol and with
    // its own share of the event jump, and is repriced at its own market IV. Every leg (and so every spread) is then priced by the
    // simulation exactly as the forecast prices it: skew can't leak in as fake profit or loss, and a fairly priced trade averages zero.
    var wsum = 0, vsum = 0, mmax = 0, sq = Math.sqrt(T);
    for (i = 0; i < st.legs.length; i++) {
      L = st.legs[i]; L.sigP = k * Math.sqrt(L.diff2); L.mJ = Math.sqrt(L.evTot); if (L.mJ > mmax) mmax = L.mJ;
      var s0 = Math.sqrt(L.diff2), d1 = (Math.log(st.S / L.K) + (R + s0 * s0 / 2) * T) / (s0 * sq), vg = Math.exp(-d1 * d1 / 2);
      wsum += vg; vsum += vg * L.sigP;
    }
    st.sigPath = wsum > 0 ? vsum / wsum : st.legs[0].sigP;   // for display: vega-weighted forecast vol of the structure
    st.mPath = mmax;
    return st;
  }
  function valueAt(legs, S, T, key) { var v = 0; for (var i = 0; i < legs.length; i++) { var L = legs[i]; v += L.q * bs(S, L.K, T, key ? L[key] : L.iv, L.isC); } return v; }
  function intrinsic(legs, S) { var v = 0; for (var i = 0; i < legs.length; i++) { var L = legs[i]; v += L.q * Math.max(0, L.isC ? S - L.K : L.K - S); } return v; }
  function finish(st, A, side) {
    var buy = side === "buy";
    st.side = side;
    st.mid = st.bid > 0 ? Math.min(st.ask, Math.max(st.bid, st.mid)) : st.ask;
    st.spreadPct = st.mid > 0 ? (st.ask - Math.max(0, st.bid)) / st.mid : 9;
    st.evt = spans(A.ev, st.T) ? A.ev : null;
    st.m = st.evt && st.evt.move ? st.evt.move : 0;
    st.tEv = st.evt ? st.evt.tEvent : null;
    st.atm = atmIVAt(A.pts, st.T) || st.iv;
    st.hv = A.hv;
    volModel(st);
    st.hs = Math.max(0, (st.ask - Math.max(0, st.bid)) / 2);
    st.price = buy ? Math.min(st.ask, st.mid + FILL * (st.ask - st.mid)) : Math.max(0, st.mid - FILL * (st.mid - Math.max(0, st.bid)));
    st.fair = valueAt(st.legs, st.S, st.T, "sigF");
    st.ev = buy ? st.fair - st.price : st.price - st.fair;
    if (st.kind === "single") st.risk = buy ? st.price : (st.isC ? null : st.K - st.price);
    else st.risk = buy ? st.price : st.width - st.price;
    st.evBase = buy || st.kind === "single" ? st.price : st.risk;   // premium paid, premium received, or a credit spread's max loss
    st.evPct = st.evBase > 0 ? st.ev / st.evBase : null;
    st.be = st.isC ? st.K + st.price : st.K - st.price;
    st.moveBE = (st.be - st.S) / st.S;
    var pMkt = probBeyond(st.S, st.be, st.T, st.iv, buy ? st.isC : !st.isC);
    st.pop = st.kind === "single" ? (buy ? (st.copL != null ? st.copL : pMkt) : (st.copS != null ? st.copS : pMkt)) : pMkt;
    st.thetaPct = st.mid > 0 ? Math.max(0, -st.theta) / st.mid : 0;   // daily decay of the combo's value (0 when it gains with time)
    st.lever = st.mid > 0 ? Math.abs(st.delta) * st.S / st.mid : 0;
    st.flow = st.oi > 0 ? st.vol / st.oi : (st.vol > 0 ? 5 : 0);
    st.theoEdge = st.theo > 0 && st.price > 0 ? (buy ? (st.theo - st.price) / st.price : (st.price - st.theo) / st.theo) : null;
    st.ivRel = A.iv30 ? st.iv / A.iv30 - 1 : 0;
    st.ivTrend = A.ivchg != null ? -A.ivchg / 100 : 0;
    st.trend = A.trend; st.trendFit = (st.isC ? 1 : -1) * (buy ? 1 : -1) * A.trend;
    st.cost = buy ? st.price * 100 : (st.kind === "spread" ? (st.width - st.price) * 100 : null);
    st.expMove = st.S * st.iv * Math.sqrt(st.T);
    st.rt = A.rt; st.hist = A.hist; st.iv30 = A.iv30;
    st.mismatch = !!A.mismatch;
    st.srcGap = 0; for (var gi = 0; gi < st.legs.length; gi++) { var Lg = st.legs[gi]; if (Lg.ivSrc && Lg.iv) st.srcGap = Math.max(st.srcGap, Math.abs(Lg.iv / Lg.ivSrc - 1)); }
    return st;
  }

  /* ---------- the trade plan, simulated ---------- */
  /* Daily closes on a forecast-vol price path (plus the event jump, when there is one), each leg repriced at its own market IV
     (rising into the event, crushed after it). Exits pay the half spread. Levels are per share:
     buy → exit value = value − half spread, win at ≥ targetLevel, stop at ≤ stopLevel;
     sell → buy-back cost = value + half spread, win at ≤ targetLevel, stop at ≥ stopLevel. */
  function simulateLevels(st, side, entry, targetLevel, stopLevel, horizonDays, nPaths, seed, opts) {
    var muX = opts && opts.drift ? opts.drift : 0;   // extra drift per year (scenario analysis); 0 = the risk-neutral path
    var T0 = st.T; if (!(entry > 0) || !(T0 > 0)) return null;
    var hs = FILL * Math.max(0, (st.ask - Math.max(0, st.bid)) / 2);
    var horizon = Math.max(1, Math.min(horizonDays, T0 * 365)), expires = horizon >= T0 * 365 - 1e-9;
    // monitor once per trading day, on the options' calendar clock: total path variance = vol^2 x calendar time, as in the IVs
    var steps = Math.max(1, Math.round(horizon * 5 / 7)), dt = horizon / steps / 365, sdt = Math.sqrt(dt);
    var legs = st.legs, nL = legs.length, buy = side === "buy", i;
    var tEv = (st.mPath > 0 && st.tEv > 0 && st.tEv < T0) ? st.tEv : null;
    var drift = new Float64Array(nL), vol = new Float64Array(nL), jump = new Float64Array(nL), lnS = new Float64Array(nL), ln0 = Math.log(st.S);
    for (i = 0; i < nL; i++) { var Lg = legs[i]; drift[i] = (R + muX - 0.5 * Lg.sigP * Lg.sigP) * dt; vol[i] = Lg.sigP * sdt; jump[i] = Lg.mJ || 0; }
    var half = Math.ceil(nPaths / 2), stride = steps + 1, zs = normals(rng(hash(seed || st.id || "x")), half * stride);
    var nT = 0, nS = 0, nX = 0, nW = 0, sum = 0, sumW = 0, sumL = 0, nL2 = 0, pls = [], dsum = 0;
    for (var p = 0; p < half; p++) for (var anti = 0; anti < 2; anti++) {
      var sgn = anti ? -1 : 1, pl = 0, kind = "x", evDone = tEv == null, day = horizon;
      for (i = 0; i < nL; i++) lnS[i] = ln0;
      for (var k = 1; k <= steps; k++) {
        var z = sgn * zs[p * stride + k - 1], t = k * dt;
        for (i = 0; i < nL; i++) lnS[i] += drift[i] + vol[i] * z;
        if (!evDone && t >= tEv) { var ze = sgn * zs[p * stride + steps]; for (i = 0; i < nL; i++) lnS[i] += -0.5 * jump[i] * jump[i] + jump[i] * ze; evDone = true; }
        var Tr = T0 - t, v = 0;
        for (i = 0; i < nL; i++) {
          var L = legs[i], Si = Math.exp(lnS[i]);
          v += L.q * (Tr <= 1e-6 ? Math.max(0, L.isC ? Si - L.K : L.K - Si) : bs(Si, L.K, Tr, Math.sqrt(L.diff2 + (evDone ? 0 : L.evTot / Tr)), L.isC));
        }
        // no clamp to [0, width] here: each leg rides its own path, and clamping their sum would cut one tail and bias fair spreads
        var last = k === steps, atExp = last && expires, x, disc = Math.exp(-R * t);   // P/L in today's dollars: a fairly priced trade averages zero
        if (buy) {
          x = Math.max(0, atExp ? v : v - hs);
          if (x >= targetLevel) { pl = x * disc - entry; kind = "t"; } else if (x <= stopLevel) { pl = x * disc - entry; kind = "s"; } else if (last) pl = x * disc - entry; else continue;
        } else {
          x = Math.max(0, atExp ? v : v + hs);
          if (x <= targetLevel) { pl = entry - x * disc; kind = "t"; } else if (x >= stopLevel) { pl = entry - x * disc; kind = "s"; } else if (last) pl = entry - x * disc; else continue;
        }
        day = t * 365; break;
      }
      if (kind === "t") nT++; else if (kind === "s") nS++; else nX++;
      if (pl > 0) { nW++; sumW += pl; } else { nL2++; sumL += pl; }
      sum += pl; dsum += day; pls.push(pl);
    }
    var n = half * 2; pls.sort(function (a, b) { return a - b; });
    var plHi = st.width ? (buy ? st.width - entry : entry) : Infinity, plLo = st.width ? (buy ? -entry : entry - st.width) : -Infinity;   // shown percentiles stay inside the spread's max gain/loss
    function q(f) { return Math.min(plHi, Math.max(plLo, pls[Math.min(n - 1, Math.max(0, Math.floor(f * n)))])); }
    return { n: n, days: horizon, avgDays: dsum / n, pTarget: nT / n, pStop: nS / n, pTime: nX / n, pWin: nW / n, ev: sum / n,
      avgWin: nW ? sumW / nW : 0, avgLoss: nL2 ? sumL / nL2 : 0, p10: q(0.1), p50: q(0.5), p90: q(0.9), entry: entry };
  }
  /* Exit levels per share for a plan (fractions), shared by the simulation and the order ticket. */
  function planLevels(st, plan) {
    var buy = st.side === "buy", entry = st.price; if (!(entry > 0)) return null;
    var tgt = buy ? entry * (1 + plan.target) : entry * (1 - plan.target);
    var stp = buy ? (plan.stop >= 1 ? -1 : entry * (1 - plan.stop)) : (plan.stop >= 20 ? Infinity : entry * (1 + plan.stop));   // 100% (buy) / 2000% (sell) = no stop
    if (buy && st.kind === "spread") tgt = Math.min(tgt, Math.max(entry * 1.05, (st.width - FILL * st.hs) * 0.95));   // a vertical tops out at its width
    return { entry: entry, target: tgt, stop: stp, hold: Math.min(plan.hold, st.dte) };
  }
  function simulate(st, plan, nPaths, seed, opts) {
    var lv = planLevels(st, plan); if (!lv) return null;
    return simulateLevels(st, st.side, lv.entry, lv.target, lv.stop, plan.hold, nPaths, seed, opts);
  }

  /* ---------- profit odds: the plan's win rate under several worlds, not just the forecast ----------
     The forecast is one guess about volatility. These odds re-run the plan with the market's own vol (no forecast edge),
     with vol a fifth calmer and a fifth wilder, with the stock drifting a quarter of a sigma against the trade over the hold,
     and with a bigger earnings jump when there is one, and blend them with the probability of profit at expiry.
     The result is a probability (a weighted average of probabilities), with a sampling band and a confidence score that
     says how far to trust it, from the data behind it. */
  var ODDS_W = { base: 0.30, market: 0.25, calm: 0.10, wild: 0.10, against: 0.10, expiry: 0.15 };
  function withVol(st, f, kind) {   // a copy of the structure with each leg's path vol scaled (kind "market": forecast = implied)
    var legs = st.legs.map(function (L) { var c = {}; for (var k in L) c[k] = L[k]; c.sigP = kind === "market" ? Math.sqrt(Math.max(0, L.diff2)) : L.sigP * f; return c; });
    var c = {}; for (var k in st) c[k] = st[k]; c.legs = legs; return c;
  }
  function withJump(st, f) {
    var legs = st.legs.map(function (L) { var c = {}; for (var k in L) c[k] = L[k]; c.mJ = Math.min((L.mJ || 0) * f, Math.sqrt(EV_CAP * L.iv * L.iv * st.T)); return c; });
    var c = {}; for (var k in st) c[k] = st[k]; c.legs = legs; c.mPath = Math.max.apply(null, legs.map(function (L) { return L.mJ || 0; })); return c;
  }
  function profitOdds(st, plan, nPaths, seed, base) {
    base = base && base.n === nPaths ? base : simulate(st, plan, nPaths, seed); if (!base) return null;
    var hold = Math.min(plan.hold, st.dte || plan.hold), Th = Math.max(1, hold) / 365;
    var dir = (st.isC ? 1 : -1) * (st.side === "buy" ? 1 : -1);   // +1: the trade wants the stock up
    var against = -dir * 0.25 * (st.sigPath || st.iv) / Math.sqrt(Th);
    var sc = {
      base: base,
      market: simulate(withVol(st, 1, "market"), plan, nPaths, seed),
      calm: simulate(withVol(st, 0.8), plan, nPaths, seed),
      wild: simulate(withVol(st, 1.2), plan, nPaths, seed),
      against: simulate(st, plan, nPaths, seed, { drift: against })
    };
    if (st.mPath > 0 && st.tEv > 0) sc.bigJump = simulate(withJump(st, 1.5), plan, nPaths, seed);
    var p = 0, w = 0, lo = 1, hi = 0, list = [], k;
    for (k in ODDS_W) {
      var v = k === "expiry" ? st.pop : (sc[k] ? sc[k].pWin : null); if (v == null || isNaN(v)) continue;
      p += ODDS_W[k] * v; w += ODDS_W[k]; if (k !== "expiry") { lo = Math.min(lo, v); hi = Math.max(hi, v); }
      list.push({ id: k, p: v, ev: sc[k] ? sc[k].ev : null });
    }
    if (sc.bigJump) { list.push({ id: "bigJump", p: sc.bigJump.pWin, ev: sc.bigJump.ev }); lo = Math.min(lo, sc.bigJump.pWin); hi = Math.max(hi, sc.bigJump.pWin); }
    if (!w) return null;
    p /= w;
    var se = Math.sqrt(Math.max(p * (1 - p), 1e-6) / Math.max(1, base.n / 2));   // antithetic pairs: about half the paths are independent draws
    // confidence in the number, from the data behind it (0-100)
    var conf = 100, why = [];
    if (st.spreadPct > 0.04) { var d1 = Math.round(30 * Math.min(1, st.spreadPct / 0.15)); conf -= d1; why.push("wide market (" + Math.round(st.spreadPct * 100) + "% spread)"); }
    if (st.oiMin < 500) { conf -= 15; why.push("thin open interest"); }
    if (st.mismatch) { conf -= 20; why.push("stock quote out of sync with the options"); }
    if (st.srcGap > 0.10) { conf -= 15; why.push("our IV disagrees with the source's by " + Math.round(st.srcGap * 100) + "%"); }
    if (!st.hist) { conf -= 10; why.push("no price history for the forecast"); }
    if (st.evt && st.evt.src === "iv") { conf -= 10; why.push("event date inferred from option prices"); }
    else if (st.evt && st.evt.verified === false) { conf -= 5; why.push("earnings date not yet confirmed"); }
    if (st.dte < 10) { conf -= 10; why.push("very little time: one day's move decides it"); }
    if (hi - lo > 0.15) { conf -= 15; why.push("the worlds disagree by " + Math.round((hi - lo) * 100) + " points"); }
    if (base.n < 1000) { conf -= 5; why.push("quick estimate (" + base.n + " paths; open the details for more)"); }
    conf = Math.max(0, Math.min(100, conf));
    // sizing math from the base plan: payoff ratio and the Kelly fraction (of the money at risk per trade)
    var b = base.avgWin > 0 && base.avgLoss < 0 ? base.avgWin / -base.avgLoss : null;
    var kelly = b ? p - (1 - p) / b : null;
    return { p: p, se: se, lo: lo, hi: hi, scenarios: list, conf: conf, why: why, b: b, kelly: kelly, n: base.n,
      planEv: st.evBase > 0 ? base.ev / st.evBase : null };
  }

  /* ---------- grades: absolute checks ---------- */
  var CHECKS = {
    liquid: ["liquid, tight market", "thin or wide market"],
    priced: ["expected value no worse than about −5% after costs", "expected value clearly negative after costs"],
    odds: ["the plan wins often enough", "the plan loses too often"],
    time: ["the right amount of time for the plan", "too little (or too much) time"],
    decay: ["decay under control", "decay too fast"],
    noEvent: ["no earnings inside the window", "earnings inside the window"],
    trend: ["trend with you, or flat", "fighting the trend"],
    payoff: ["reward worth the risk", "reward too small for the risk"]
  };
  var ODDS = { singleBuy: 0.42, spreadBuy: 0.40, sell: 0.60 };
  function grade(st) {
    var buy = st.side === "buy", sp = st.kind === "spread", c = {}, pw = st.plan ? st.plan.pWin : null;
    c.liquid = sp ? (st.oiMin >= 300 && st.volMin >= 10 && (st.spreadPct <= 0.15 || (st.ask - st.bid) <= 0.10))
                  : (st.oi >= 500 && st.vol >= 25 && (st.spreadPct <= 0.08 || (st.ask - st.bid) <= 0.05));
    c.priced = (st.evPct == null || st.evPct >= -0.05) && (sp || st.theoEdge == null || st.theoEdge >= -0.03);
    c.odds = buy ? (pw != null ? pw >= (sp ? ODDS.spreadBuy : ODDS.singleBuy) : st.pop >= 0.35) : (pw != null ? pw >= ODDS.sell : st.pop >= 0.65);
    c.time = buy ? (st.dte >= 21 && st.dte <= 120) : (st.dte >= 14 && st.dte <= 60);
    c.decay = !buy || st.thetaPct <= (sp ? 0.01 : 0.012);
    c.noEvent = !st.evt;
    c.trend = st.trendFit !== -1;
    if (sp) c.payoff = buy ? st.rr >= 0.8 : st.creditPct >= 0.2;
    var fails = []; for (var k in c) if (!c[k]) fails.push(k);
    return { g: fails.length === 0 ? "A" : fails.length === 1 ? "B" : fails.length === 2 ? "C" : "–", fails: fails, checks: c };
  }

  /* ---------- filters and ranking ---------- */
  function prefilter(st, f) {
    if (f.types !== "both" && st.type !== f.types) return false;
    if (st.dte < f.dteMin || st.dte > f.dteMax) return false;
    if (st.anchorDelta < f.dMin || st.anchorDelta > f.dMax) return false;
    if (st.oiMin < f.minOI) return false;
    if (st.spreadPct > f.maxSpread) return false;
    if (st.cost != null && st.cost > f.maxPrice) return false;
    if (f.evMode === "avoid" && st.evt) return false;
    if (f.evMode === "only" && !st.evt) return false;
    if (st.side === "sell" ? !(st.bid > 0) : !(st.ask > 0)) return false;
    return true;
  }
  var LENSES = [
    { id: "durable", name: "Good & durable", desc: "Built to still look good next week: expected value at or above break-even after costs, a plan that wins often enough, enough time that one quiet week doesn't kill it, with the trend, in a market you can get out of. Weights: expected value 20%, plan's expected result 10%, plan win rate 20%, liquidity 15%, spread 10%, low decay 10%, trend fit 10%, consistency across scans 5%.",
      w: { ev: .20, planEv: .10, win: .20, liq: .15, spread: .10, theta: .10, trendFit: .10, stab: .05 } },
    { id: "odds", name: "Most likely to profit", desc: "The plan's chance of ending in profit across several worlds, not just our forecast: the market's own volatility (no forecast edge), calmer and wilder volatility, the stock drifting against the trade, a bigger earnings jump, and the odds at expiry, blended into one probability. Kept honest by the expected result, because a 75% win rate with losses three times the wins still loses money. Weights: profit odds 45%, worst world 15%, plan's expected result 15%, expected value 10%, confidence 5%, liquidity 5%, spread 5%.",
      w: { odds: .45, oddsLow: .15, planEv: .15, ev: .10, conf: .05, liq: .05, spread: .05 } },
    { id: "win", name: "Highest win rate", desc: "How often the trade plan (take profit, stop, time limit) ends in profit, simulated on price paths, kept honest by expected value. High win rates come with average losses bigger than average wins: check the expected result in the details. Weights: plan win rate 45%, plan's expected result 20%, expected value 10%, liquidity 15%, spread 10%.",
      w: { win: .45, planEv: .20, ev: .10, liq: .15, spread: .10 } },
    { id: "value", name: "Best priced", desc: "The most expected value per dollar at risk: priced below what the volatility forecast says it's worth, after paying the spread. Weights: expected value 45%, vs the source's fair value 20%, spread 15%, liquidity 15%, low decay 5%.",
      w: { ev: .45, theoEdge: .20, spread: .15, liq: .15, theta: .05 } },
    { id: "liquid", name: "Tightest & most liquid", desc: "Best execution: narrowest spreads and the deepest open interest and volume. Weights: spread 45%, liquidity 45%, expected value 10%.",
      w: { spread: .45, liq: .45, ev: .10 } },
    { id: "cheapvol", name: "Cheap volatility", desc: "Strikes whose implied volatility is low versus the symbol's 30-day IV and whose IV is falling. Weights: IV vs 30d 45%, IV trend 15%, spread 20%, liquidity 20%.",
      w: { ivRel: .45, ivTrend: .15, spread: .20, liq: .20 } },
    { id: "lever", name: "Most leverage", desc: "Most stock exposure per dollar of premium. These are the lottery tickets; theta eats them, so decay is penalised. Weights: leverage 50%, theta burn 20%, spread 15%, liquidity 15%.",
      w: { lever: .50, theta: .20, spread: .15, liq: .15 } },
    { id: "flow", name: "Unusual activity", desc: "Where money is moving today: volume far above open interest. Weights: volume/OI 55%, volume 25%, spread 20%.",
      w: { flow: .55, volRank: .25, spread: .20 } }
  ];
  function pctRank(arr, key, higherBetter) {
    var vals = arr.map(key).map(function (v) { return v == null || isNaN(v) ? NaN : v; });
    var sorted = vals.filter(function (v) { return !isNaN(v); }).sort(function (a, b) { return a - b; }), n = sorted.length;
    return vals.map(function (v) {
      if (isNaN(v) || !n) return 0.5;
      var lo = 0, hi = n, m; while (lo < hi) { m = (lo + hi) >> 1; if (sorted[m] < v) lo = m + 1; else hi = m; }
      var a = lo; hi = n; while (lo < hi) { m = (lo + hi) >> 1; if (sorted[m] <= v) lo = m + 1; else hi = m; }
      var p = n > 1 ? ((a + lo - 1) / 2) / (n - 1) : 0.5; p = Math.min(1, Math.max(0, p)); return higherBetter ? p : 1 - p;   // ties share the middle rank
    });
  }
  function scoreRows(rows, lensId) {
    var L = LENSES.filter(function (l) { return l.id === lensId; })[0] || LENSES[0];
    var sell = rows.length && rows[0].side === "sell";
    var comps = {
      ev: pctRank(rows, function (r) { return r.evPct; }, true),
      win: pctRank(rows, function (r) { return r.plan ? r.plan.pWin : null; }, true),
      odds: pctRank(rows, function (r) { return r.odds ? r.odds.p : null; }, true),
      oddsLow: pctRank(rows, function (r) { return r.odds ? r.odds.lo : null; }, true),
      conf: pctRank(rows, function (r) { return r.odds ? r.odds.conf : null; }, true),
      planEv: pctRank(rows, function (r) { return r.plan && r.evBase > 0 ? r.plan.ev / r.evBase : null; }, true),
      theoEdge: pctRank(rows, function (r) { return r.theoEdge; }, true),
      spread: pctRank(rows, function (r) { return r.spreadPct; }, false),
      liq: pctRank(rows, function (r) { return Math.log(1 + r.oiMin) + 0.6 * Math.log(1 + r.volMin) + 0.2 * Math.log(1 + r.bs + r.as); }, true),
      theta: pctRank(rows, function (r) { return r.thetaPct; }, sell),
      ivRel: pctRank(rows, function (r) { return r.ivRel; }, sell),
      ivTrend: pctRank(rows, function (r) { return r.ivTrend; }, !sell),
      pop: pctRank(rows, function (r) { return r.pop; }, true),
      lever: pctRank(rows, function (r) { return r.lever; }, true),
      flow: pctRank(rows, function (r) { return r.flow; }, true),
      volRank: pctRank(rows, function (r) { return r.vol; }, true),
      trendFit: pctRank(rows, function (r) { return r.trendFit; }, true),
      stab: pctRank(rows, function (r) { return r.stabPos; }, true)
    };
    rows.forEach(function (r, i) {
      var s = 0, ws = 0, parts = {};
      for (var k in L.w) { s += L.w[k] * comps[k][i]; ws += L.w[k]; parts[k] = comps[k][i]; }
      r.score = ws ? s / ws : 0; r.parts = parts;
    });
    return rows;
  }
  var STRUCT_DEFAULTS = {
    "single|buy": { dMin: 0.20, dMax: 0.70, maxSpread: 10 }, "single|sell": { dMin: 0.15, dMax: 0.45, maxSpread: 10 },
    "spread|buy": { dMin: 0.35, dMax: 0.75, maxSpread: 20 }, "spread|sell": { dMin: 0.15, dMax: 0.40, maxSpread: 25 }
  };
  var PLAN_DEFAULTS = { buy: { target: 50, stop: 50, hold: 21 }, sell: { target: 50, stop: 200, hold: 21 } };

  return { R: R, W_IV: W_IV, FILL: FILL, NO_EARNINGS: NO_EARNINGS, YEAR_MS: YEAR_MS, EARNINGS_SEED: EARNINGS_SEED, ncdf: ncdf, bs: bs, probBeyond: probBeyond, median: median, hash: hash,
    parseOCC: parseOCC, etTime: etTime, earnMap: earnMap, histStats: histStats, realizedVol: realizedVol, trendOf: trendOf,
    paritySpot: paritySpot, termStructure: termStructure, termFrom: termFrom, atmIVAt: atmIVAt, detectEvent: detectEvent, spans: spans, analyzeSymbol: analyzeSymbol,
    makeSingle: makeSingle, makeSpread: makeSpread, verticals: verticals, volModel: volModel, valueAt: valueAt, intrinsic: intrinsic,
    impliedVol: impliedVol, finish: finish, simulateLevels: simulateLevels, simulate: simulate, profitOdds: profitOdds, ODDS_W: ODDS_W, planLevels: planLevels, grade: grade, CHECKS: CHECKS, ODDS: ODDS, prefilter: prefilter,
    LENSES: LENSES, pctRank: pctRank, scoreRows: scoreRows, STRUCT_DEFAULTS: STRUCT_DEFAULTS, PLAN_DEFAULTS: PLAN_DEFAULTS };
})();
if (typeof module !== "undefined" && module.exports) module.exports = Engine;
/* ENGINE-END */
