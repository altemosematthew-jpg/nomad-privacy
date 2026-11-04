#!/usr/bin/env python3
"""
Options Finder — local data server for the Mac mini.

Serves the finder UI at http://127.0.0.1:8765 and proxies Cboe's free delayed
option-chain feed (15-minute delayed, bid/ask/sizes/IV/greeks/OI/volume/theo)
so the page can scan live data without CORS or CSP problems.

  python3 ~/options_finder/finder.py            # run in the foreground
  (launchd keeps it running; see README.md)

Endpoints
  GET /                      the UI (index.html next to this file)
  GET /api/chain?symbol=SPY  one symbol's full compact chain (cached 60 s)
  GET /api/scan              every watchlist symbol, compact (cached 120 s)
  GET /api/watchlist         the configured watchlist
  GET /api/hist?symbol=SPY   price-history stats (cached 6 h)
  GET /api/track             the daily track record (from GitHub, cached 10 min)
  GET /api/health            {"ok": true, ...}

No API keys.  Data is delayed and for information only; nothing here places
orders.  Standard library only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", os.environ.get("FINDER_PORT", "8765")))
HOST = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
CBOE = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
CBOE_HIST = "https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/{sym}.json"
# The Mac mini copy pings the public server so Render's free tier stays awake (set to "" to disable).
KEEPALIVE_URL = os.environ.get("KEEPALIVE_URL", "" if os.environ.get("PORT") else "https://strike-finder.onrender.com/api/health")
DEFAULT_WATCHLIST = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
                     "AMD", "NFLX", "AVGO", "COIN", "PLTR", "SOFI", "F", "BAC", "INTC", "HOOD",
                     "MRVL", "MU", "UBER", "ARM"]
WATCHLIST_FILE = HERE / "watchlist.json"
DATA_DIR = HERE / "data"
SYM_RE = re.compile(r"^[A-Z][A-Z0-9.\-^]{0,9}$")
OCC_RE = re.compile(r"^([A-Z0-9.\-^]{1,10})(\d{6})([CP])(\d{8})$")

_cache = {}            # symbol -> (ts, compact dict)
_cache_lock = threading.Lock()
CHAIN_TTL = 60
SCAN_TTL = 120


def watchlist():
    try:
        wl = json.loads(WATCHLIST_FILE.read_text())
        wl = [s.upper() for s in wl if isinstance(s, str) and SYM_RE.match(s.upper())]
        if wl:
            return wl[:60]
    except Exception:
        pass
    return DEFAULT_WATCHLIST


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (options-finder; personal use)",
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_cboe(sym: str) -> dict:
    return fetch_json(CBOE.format(sym=urllib.parse.quote(sym)))


# ---------- price history: trend and realized volatility per symbol (cached 6 h) ----------
_hist_cache = {}
HIST_TTL = 6 * 3600


def hist_stats(closes):
    """Trend/vol stats from daily closes (oldest first): moving averages, realized vol, returns, 52-week range."""
    c = [float(x) for x in closes if x and float(x) > 0]
    if len(c) < 25:
        return None

    def sma(n):
        return sum(c[-n:]) / n if len(c) >= n else None

    def hv(n):
        if len(c) < n + 1:
            return None
        rets = [math.log(c[i] / c[i - 1]) for i in range(len(c) - n, len(c))]
        m = sum(rets) / n
        var = sum((r - m) ** 2 for r in rets) / (n - 1)
        return math.sqrt(var * 252)

    def ret(n):
        return c[-1] / c[-1 - n] - 1 if len(c) > n else None

    def hvx(n):
        # realized vol with jump days (earnings gaps) removed: |r - median| > 4 robust sigmas (same rule as the page's engine)
        if len(c) < n + 1:
            return None
        a = [math.log(c[i] / c[i - 1]) for i in range(len(c) - n, len(c))]
        s = sorted(a)
        med = (s[(n - 1) // 2] + s[n // 2]) / 2
        d = sorted(abs(x - med) for x in a)
        mad = (d[(n - 1) // 2] + d[n // 2]) / 2 * 1.4826
        cut = 4 * max(mad, 0.002)
        b = [x for x in a if abs(x - med) <= cut]
        use = b if len(b) >= math.ceil(n * 0.8) else a
        m = sum(use) / len(use)
        return math.sqrt(sum((x - m) ** 2 for x in use) / (len(use) - 1) * 252)

    y = c[-252:]
    return {"last": c[-1], "sma20": sma(20), "sma50": sma(50), "sma200": sma(200), "hv20": hv(20), "hv60": hv(60), "hv20x": hvx(20), "hv60x": hvx(60),
            "ret1m": ret(21), "ret3m": ret(63), "hi52": max(y), "lo52": min(y), "n": len(c), "src": "cboe"}


def hist(sym: str):
    with _cache_lock:
        hit = _hist_cache.get(sym)
        if hit and time.time() - hit[0] < HIST_TTL:
            return hit[1]
    out = None
    try:
        raw = fetch_json(CBOE_HIST.format(sym=urllib.parse.quote(sym)))
        rows = raw.get("data") or raw.get("prices") or []
        closes = [r.get("close") for r in rows if isinstance(r, dict)]
        out = hist_stats(closes)
    except Exception:
        out = None
    with _cache_lock:
        _hist_cache[sym] = (time.time(), out)
    return out


# ---------- track record: the ledger the daily GitHub Action keeps (cached 10 min) ----------
TRACK_URL = os.environ.get("TRACK_URL", "https://raw.githubusercontent.com/altemosematthew-jpg/nomad-privacy/main/options-finder/track/ledger.json")
_track = {"ts": 0.0, "data": None}


def track():
    if _track["data"] is not None and time.time() - _track["ts"] < 600:
        return _track["data"]
    data = None
    try:
        data = fetch_json(TRACK_URL + "?t=%d" % int(time.time() // 600))
    except Exception:
        local = HERE / "track" / "ledger.json"
        try:
            data = json.loads(local.read_text())
        except Exception:
            data = _track["data"] or {"version": 1, "picks": [], "updated": None}
    _track.update(ts=time.time(), data=data)
    return data


# ---------- consistency: how each contract's edge has held up across scans while this server is awake ----------
_stab = {}             # occ -> deque of (ts, buyer edge, seller edge, spread%)
_stab_lock = threading.Lock()
STAB_KEEP = 36


def stab_update(results):
    now = time.time()
    with _stab_lock:
        for S in results:
            for o in S["o"]:
                occ, bid, ask, theo = o[0], o[1], o[2], o[12]
                mid = (bid + ask) / 2 or ask
                tb = (theo - ask) / ask if theo > 0 and ask > 0 else None
                ts_ = (bid - theo) / theo if theo > 0 else None
                sp = (ask - bid) / mid if mid > 0 else None
                d = _stab.get(occ)
                if d is None:
                    d = _stab[occ] = deque(maxlen=STAB_KEEP)
                if not d or now - d[-1][0] >= 100:
                    d.append((now, tb, ts_, sp))
        if len(_stab) > 60000:   # forget contracts not seen for a day
            for occ in [k for k, d in _stab.items() if now - d[-1][0] > 86400]:
                del _stab[occ]


def stab_for(S):
    """{occ: [n, mean buyer edge, share of scans with buyer edge > 0, mean seller edge, share > 0, mean spread]} for contracts seen twice or more."""
    out = {}
    with _stab_lock:
        for o in S["o"]:
            d = _stab.get(o[0])
            if not d or len(d) < 2:
                continue
            tb = [x[1] for x in d if x[1] is not None]
            ts_ = [x[2] for x in d if x[2] is not None]
            sp = [x[3] for x in d if x[3] is not None]
            mean = lambda a: round(sum(a) / len(a), 4) if a else None
            pos = lambda a: round(sum(1 for v in a if v > 0) / len(a), 3) if a else None
            out[o[0]] = [len(d), mean(tb), pos(tb), mean(ts_), pos(ts_), mean(sp)]
    return out


def compact(sym: str, raw: dict) -> dict:
    """Trim the Cboe payload to what the UI needs.  Keeps 1-120 DTE contracts that
    have a market (bid or ask) and some open interest or volume."""
    d = raw.get("data") or {}
    px = d.get("current_price") or d.get("close") or 0
    now = time.time()
    out = []
    for o in d.get("options") or []:
        m = OCC_RE.match(o.get("option", ""))
        if not m:
            continue
        yymmdd = m.group(2)
        try:
            exp_ts = time.mktime(time.strptime(yymmdd + " 16:00", "%y%m%d %H:%M"))
        except ValueError:
            continue
        dte = (exp_ts - now) / 86400.0
        if dte < 0.2 or dte > 120:
            continue
        bid, ask = float(o.get("bid") or 0), float(o.get("ask") or 0)
        oi, vol = int(o.get("open_interest") or 0), int(o.get("volume") or 0)
        if ask <= 0 or (oi < 25 and vol < 10):
            continue
        delta = float(o.get("delta") or 0)
        if abs(delta) < 0.01 or abs(delta) > 0.99:
            continue
        out.append([
            m.group(0), bid, ask, int(o.get("bid_size") or 0), int(o.get("ask_size") or 0),
            float(o.get("iv") or 0), oi, vol, delta, float(o.get("gamma") or 0),
            float(o.get("theta") or 0), float(o.get("vega") or 0), float(o.get("theo") or 0),
            float(o.get("last_trade_price") or 0),
        ])
    return {
        "s": sym, "px": px, "iv30": d.get("iv30"), "ivchg": d.get("iv30_change_percent"),
        "chg": d.get("price_change_percent"), "ts": raw.get("timestamp"), "fetched": int(now),
        "n_raw": len(d.get("options") or []), "o": out,
    }


def chain(sym: str) -> dict:
    with _cache_lock:
        hit = _cache.get(sym)
        if hit and time.time() - hit[0] < CHAIN_TTL:
            return hit[1]
    data = compact(sym, fetch_cboe(sym))
    stab_update([data])
    data = {"hist": hist(sym), "h": stab_for(data), **data}   # small fields first; "o" (the big list) last
    with _cache_lock:
        _cache[sym] = (time.time(), data)
    return data


_scan_cache = {"ts": 0.0, "data": None}
_scan_lock = threading.Lock()


def scan() -> dict:
    with _scan_lock:
        if _scan_cache["data"] and time.time() - _scan_cache["ts"] < SCAN_TTL:
            return _scan_cache["data"]
        wl = watchlist()
        results, errors = [], {}

        def one(s):
            try:
                return s, chain(s), None
            except Exception as e:      # noqa: BLE001
                return s, None, f"{type(e).__name__}: {e}"[:120]

        with ThreadPoolExecutor(max_workers=6) as ex:
            for s, data, err in ex.map(one, wl):
                if data:
                    results.append(data)
                else:
                    errors[s] = err
        out = {"generated": int(time.time()), "watchlist": wl, "symbols": results, "errors": errors,
               "source": "Cboe delayed quotes (15 min)", "live": True, "stab_scans": max([len(d) for d in list(_stab.values())[:2000]] or [0])}
        _scan_cache.update(ts=time.time(), data=out)
        try:
            DATA_DIR.mkdir(exist_ok=True)
            (DATA_DIR / "latest.json").write_text(json.dumps(out))
        except OSError:
            pass
        return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):   # quiet
        if "/api/" in (args[0] if args else ""):
            return
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self):
        # The published claude.ai page (and any copy of index.html) reads this server cross-origin.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                body = (HERE / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif u.path == "/api/health":
                self._json({"ok": True, "port": PORT, "watchlist": watchlist(), "cached": sorted(_cache)})
            elif u.path == "/api/watchlist":
                self._json({"watchlist": watchlist()})
            elif u.path == "/api/chain":
                sym = (q.get("symbol") or [""])[0].upper().strip()
                if not SYM_RE.match(sym):
                    return self._json({"error": "bad symbol"}, 400)
                self._json(chain(sym))
            elif u.path == "/api/hist":
                sym = (q.get("symbol") or [""])[0].upper().strip()
                if not SYM_RE.match(sym):
                    return self._json({"error": "bad symbol"}, 400)
                self._json({"symbol": sym, "hist": hist(sym)})
            elif u.path == "/api/scan":
                self._json(scan())
            elif u.path == "/api/track":
                self._json(track())
            else:
                self._json({"error": "not found"}, 404)
        except urllib.error.HTTPError as e:
            self._json({"error": f"upstream HTTP {e.code}"}, 502)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"[:200]}, 500)


def market_hours() -> bool:
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return True
    t = now.hour * 60 + now.minute
    return now.weekday() < 5 and 9 * 60 + 25 <= t <= 16 * 60 + 20


def background():
    """Keep scanning every 5 minutes in market hours so the consistency stats build up, and keep the public server awake from the Mac."""
    time.sleep(1)
    last_scan = 0.0
    last_ping = 0.0
    while True:
        try:
            if time.time() - last_scan >= 300 and (market_hours() or last_scan == 0):
                scan()
                last_scan = time.time()
            if KEEPALIVE_URL and time.time() - last_ping >= 600:
                try:
                    urllib.request.urlopen(KEEPALIVE_URL, timeout=90).read()
                except Exception:
                    pass
                last_ping = time.time()
        except Exception:
            pass
        time.sleep(20)


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Options Finder: http://{HOST}:{PORT}  (Ctrl-C to stop)", flush=True)
    threading.Thread(target=background, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
