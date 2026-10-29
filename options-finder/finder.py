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
  GET /api/health            {"ok": true, ...}

No API keys.  Data is delayed and for information only; nothing here places
orders.  Standard library only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", os.environ.get("FINDER_PORT", "8765")))
HOST = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
CBOE = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
DEFAULT_WATCHLIST = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
                     "AMD", "NFLX", "AVGO", "COIN", "PLTR", "SOFI", "F", "BAC", "INTC", "HOOD"]
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


def fetch_cboe(sym: str) -> dict:
    req = urllib.request.Request(CBOE.format(sym=urllib.parse.quote(sym)),
                                 headers={"User-Agent": "Mozilla/5.0 (options-finder; personal use)",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


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
               "source": "Cboe delayed quotes (15 min)", "live": True}
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

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
            elif u.path == "/api/scan":
                self._json(scan())
            else:
                self._json({"error": "not found"}, 404)
        except urllib.error.HTTPError as e:
            self._json({"error": f"upstream HTTP {e.code}"}, 502)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"[:200]}, 500)


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Options Finder: http://{HOST}:{PORT}  (Ctrl-C to stop)", flush=True)
    # warm the scan in the background so the first page load is fast
    threading.Thread(target=lambda: (time.sleep(1), scan()), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
