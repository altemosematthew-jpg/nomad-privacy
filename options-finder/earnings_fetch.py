#!/usr/bin/env python3
"""
Upcoming earnings dates for the Strike Finder watchlist, written to options-finder/earnings.json
in the engine's EARNINGS_SEED shape:

  {"asOf": "YYYY-MM-DD", "source": "...", "timingUnknown": [...],
   "d": {"SYM": ["YYYY-MM-DD", "am" | "pm", verified]}}

am = before the open, pm = after the close, verified = the source says the date is confirmed.
A date whose time of day the source does not give is written as "am" (so an expiry that day
counts as holding the report) and its symbol is listed in timingUnknown.

Free, keyless sources, tried in this order:
  1. Nasdaq per-symbol earnings date  api.nasdaq.com/api/analyst/SYM/earnings-date
     (date, confirmed vs. estimated, timing once confirmed; one request per stock)
  2. Yahoo Finance quote               one request for all of them (cookie + crumb, no key):
     fills the weeks after a report when Nasdaq has no date yet; a confirmed date beats an estimate
  3. Nasdaq earnings calendar          api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD
     (the time of day for dates still missing it; the whole window, one request per weekday, if 1 and 2 fail)
A stock no source has a date for (failed, or not set yet after a report) keeps its previous entry while that date is ahead.

  python3 options-finder/earnings_fetch.py             # write options-finder/earnings.json
  python3 options-finder/earnings_fetch.py --probe     # first print what each source returns
  python3 options-finder/earnings_fetch.py --out x.json

Standard library only.  Exits 1, leaving the old file alone, when no source answers.
"""
from __future__ import annotations

import gzip
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "earnings.json"
WATCHLIST = HERE / "watchlist.json"
DAYS = 100           # how far ahead to look
PAUSE = 0.6          # seconds between requests
NO_EARNINGS = set(("SPY QQQ IWM DIA SPX NDX RUT XSP VIX GLD SLV TLT HYG LQD EEM EFA FXI XLF XLE XLK XLV XLI XLY XLP "
                   "XLU XLB XLRE XBI SMH SOXX ARKK USO UNG UVXY VXX TQQQ SQQQ SOXL SOXS KRE IBIT").split())
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
NASDAQ = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
          "Accept-Encoding": "gzip, deflate", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
BROWSER = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate"}
SOURCE_NAMES = {"nasdaq": "Nasdaq earnings date", "yahoo": "Yahoo Finance", "calendar": "Nasdaq earnings calendar",
                "previous": "previous run"}


def log(*a):
    print(*a, flush=True)


def et_zone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:            # no tz database: EST is close enough for picking the date and am/pm
        return timezone(timedelta(hours=-5))


ET = et_zone()
_last = [0.0]


def get(url, headers, opener=None, tries=3, timeout=15):
    """GET with a pause before every request and retries with backoff; returns the (decompressed) body."""
    err = None
    for i in range(tries):
        wait = _last[0] + PAUSE - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers=headers)
            with (opener.open if opener else urllib.request.urlopen)(req, timeout=timeout) as r:
                body, enc = r.read(), (r.headers.get("Content-Encoding") or "").lower()
            _last[0] = time.time()
            if enc == "gzip":
                body = gzip.decompress(body)
            elif enc == "deflate":
                try:
                    body = zlib.decompress(body)
                except zlib.error:
                    body = zlib.decompress(body, -zlib.MAX_WBITS)
            return body
        except urllib.error.HTTPError as e:
            _last[0], err = time.time(), e
            if e.code in (400, 401, 403, 404):
                break            # will not change on a retry
        except Exception as e:   # noqa: BLE001  (timeouts, resets)
            _last[0], err = time.time(), e
        if i + 1 < tries:
            time.sleep(2 + 4 * i)
    raise err


def why(e):
    return f"{type(e).__name__}: {e}"[:160]


# ---------- 1. Nasdaq per-symbol earnings date ----------
def nasdaq_symbol(sym, tries=3):
    """(date | None when Nasdaq lists none, "am"|"pm"|None, confirmed, the text it was read from)."""
    raw = json.loads(get("https://api.nasdaq.com/api/analyst/%s/earnings-date" % urllib.parse.quote(sym.lower()), NASDAQ, tries=tries))
    data = (raw or {}).get("data") or {}
    text = " ".join(str(data.get(k) or "") for k in ("announcement", "reportText")).strip()
    d = None
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
    if m:
        d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    else:
        m = re.search(r"\b([A-Z][a-z]{2})[a-z]*\.? (\d{1,2}), (\d{4})\b", text)
        if m:
            try:
                d = datetime.strptime("%s %s %s" % m.groups(), "%b %d %Y").date()
            except ValueError:
                d = None
    if not d:
        return None, None, False, text
    low = text.lower()
    timing = ("am" if re.search(r"before (the )?(market|bell|open)|pre-?market", low)
              else "pm" if re.search(r"after (the )?(market|bell|close)|after-?hours|post-?market", low) else None)
    confirmed = "estimated" not in low and bool(re.search(r"\bexpected|\bconfirmed|\bscheduled", low))
    return d, timing, confirmed, text


# ---------- 2. Nasdaq earnings calendar ----------
def nasdaq_calendar(day, tries=3):
    """{SYM: "am"|"pm"|None} for one day of Nasdaq's earnings calendar."""
    raw = json.loads(get("https://api.nasdaq.com/api/calendar/earnings?date=" + day.isoformat(), NASDAQ, tries=tries))
    rows = ((raw or {}).get("data") or {}).get("rows") or []
    out = {}
    for r in rows:
        s = str(r.get("symbol") or "").upper().strip().replace("/", ".")
        t = str(r.get("time") or "").lower()
        out[s] = "am" if "pre" in t else "pm" if ("after" in t or "post" in t) else None
    return out


# ---------- 3. Yahoo Finance quote (needs a cookie and a crumb, no key) ----------
def yahoo(syms, tries=3):
    """{SYM: (date, "am"|"pm"|None, confirmed)} from one Yahoo quote request for all symbols."""
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        get("https://fc.yahoo.com/", BROWSER, op, tries=1)
    except Exception:            # a 404 is normal here: the cookie it sets is what matters
        pass
    crumb = get("https://query2.finance.yahoo.com/v1/test/getcrumb", BROWSER, op, tries=tries).decode("utf-8", "replace").strip()
    if not crumb or "<" in crumb or " " in crumb:
        raise RuntimeError("no crumb: %r" % crumb[:80])
    q = urllib.parse.urlencode({"symbols": ",".join(syms), "crumb": crumb,
                                "fields": "symbol,earningsTimestamp,earningsTimestampStart,earningsTimestampEnd,isEarningsDateEstimate,earningsCallTimestampStart"})
    raw = json.loads(get("https://query2.finance.yahoo.com/v7/finance/quote?" + q, BROWSER, op, tries=tries))
    out, now = {}, time.time()
    for r in ((raw.get("quoteResponse") or {}).get("result") or []):
        ts = [r.get(k) for k in ("earningsTimestamp", "earningsTimestampStart", "earningsCallTimestampStart")]
        ts = [t for t in ts if isinstance(t, (int, float)) and t > now - 86400]
        if not ts:
            out[str(r.get("symbol", "")).upper()] = None
            continue
        when = datetime.fromtimestamp(min(ts), ET)
        timing = None if (when.hour, when.minute) == (0, 0) else ("am" if when.hour < 12 else "pm")
        out[str(r.get("symbol", "")).upper()] = (when.date(), timing, r.get("isEarningsDateEstimate") is False)
    return out


def load_watchlist():
    try:
        wl = [str(s).upper().strip() for s in json.loads(WATCHLIST.read_text())]
    except Exception:
        wl = []
    return [s for s in dict.fromkeys(wl) if s and s not in NO_EARNINGS]


def probe(syms):
    """Print what each source returns for a couple of symbols (a handful of requests)."""
    pick = [s for s in ("NVDA", "MRVL", "AAPL") if s in syms][:2] or syms[:2]
    log("== probe:", pick)
    for s in pick:
        try:
            log("  nasdaq earnings-date %s ->" % s, nasdaq_symbol(s, tries=1))
        except Exception as e:
            log("  nasdaq earnings-date %s FAILED %s" % (s, why(e)))
    for ahead in (1, 85):
        day = datetime.now(ET).date() + timedelta(days=ahead)
        while day.weekday() > 4:
            day += timedelta(days=1)
        try:
            rows = nasdaq_calendar(day, tries=1)
            log("  nasdaq calendar %s -> %d rows, e.g. %s; watchlist: %s" % (day, len(rows), list(rows.items())[:4], {s: rows[s] for s in syms if s in rows}))
        except Exception as e:
            log("  nasdaq calendar %s FAILED %s" % (day, why(e)))
    try:
        log("  yahoo ->", yahoo(pick, tries=1))
    except Exception as e:
        log("  yahoo FAILED %s" % why(e))
    log("== end probe")


def main(argv):
    out_path = Path(argv[argv.index("--out") + 1]) if "--out" in argv else OUT
    today = datetime.now(ET).date()
    horizon = today + timedelta(days=DAYS)
    syms = load_watchlist()
    if "--probe" in argv:
        probe(syms)
    try:
        prev = json.loads(out_path.read_text()).get("d") or {}
    except Exception:
        prev = {}
    found = {}       # sym -> [date, timing|None, confirmed, source]
    answered = set()  # symbols some source gave a date for, in the window or not
    reached = []      # sources that answered at all

    def keep(s, d, timing, confirmed, src):
        answered.add(s)
        if d and today <= d <= horizon:
            found[s] = [d, timing, bool(confirmed), src]

    def show(r):
        return (r[0].isoformat() + " " + str(r[1]) + (" confirmed" if r[2] else " estimated")) if r else "no date"

    # 1. Nasdaq, one request per stock (it has no date for a while after a report)
    nq, fails = {}, 0
    for i, s in enumerate(syms):
        if i >= 2 and fails == i:
            log("nasdaq earnings-date: first %d requests failed, skipping the rest" % i)
            break
        try:
            r = nasdaq_symbol(s)
            nq[s] = r[:3] if r[0] else None
            reached.append("nasdaq")
            log("  %-5s nasdaq %s" % (s, show(nq[s]) if r[0] else "no date: " + (r[3][:110] or "(empty)")))
        except Exception as e:
            fails += 1
            log("  %-5s nasdaq earnings-date failed: %s" % (s, why(e)))
    # 2. Yahoo, one request for every stock: fills Nasdaq's gaps and may know a confirmed date Nasdaq still estimates
    yh = {}
    try:
        got = yahoo(syms)
        yh = {s: got[s] for s in syms if s in got}
        reached.append("yahoo")
        log("yahoo: " + ", ".join("%s %s" % (s, show(v)) for s, v in yh.items()))
    except Exception as e:
        log("yahoo failed: %s" % why(e))
    for s in syms:   # a confirmed date beats an estimate, then the earlier date (the safer guess), then Nasdaq
        if not (nq.get(s) or yh.get(s)):
            continue
        answered.add(s)
        cands = [(2 if r[2] else 1, pref, r, src) for r, pref, src in ((nq.get(s), 1, "nasdaq"), (yh.get(s), 0, "yahoo"))
                 if r and r[0] and today <= r[0] <= horizon]
        if not cands:
            continue
        cands.sort(key=lambda c: (-c[0], c[2][0], -c[1]))
        r, src = cands[0][2], cands[0][3]
        timing = r[1]
        for c in cands[1:]:
            if timing is None and c[2][0] == r[0] and c[2][1]:
                timing, src = c[2][1], src + "+" + c[3]
        keep(s, r[0], timing, r[2], src)

    # 3. Nasdaq calendar: the time of day for dates still missing it, or the whole window if most stocks still lack a date
    if len(answered) >= len(syms) / 2:
        days, full = sorted({v[0] for v in found.values() if v[1] is None}), False
    else:
        days, full = [today + timedelta(n) for n in range(DAYS + 1) if (today + timedelta(n)).weekday() < 5], True
    ok_days = fails = 0
    for i, day in enumerate(days):
        if i >= 2 and fails == i:
            log("nasdaq calendar: first %d requests failed, skipping the rest" % i)
            break
        try:
            rows = nasdaq_calendar(day)
            ok_days += 1
            reached.append("calendar")
        except Exception as e:
            fails += 1
            log("  calendar %s failed: %s" % (day, why(e)))
            continue
        for s in syms:
            if s not in rows:
                continue
            cur = found.get(s)
            if cur and cur[0] == day and cur[1] is None and rows[s]:
                cur[1] = rows[s]
                cur[3] = cur[3] if cur[3] == "calendar" else cur[3] + "+calendar"
            elif full and s not in found and s not in answered:
                keep(s, day, rows[s], False, "calendar")
    log("nasdaq calendar: %d of %d days read%s" % (ok_days, len(days), " (full window)" if full else ""))

    if not reached:
        log("No source answered; leaving %s as it was." % out_path)
        return 1
    for s in syms:   # no source has a date (failed, or not set yet after a report): keep the last one while it is ahead
        p = prev.get(s)
        if s not in answered and isinstance(p, list) and len(p) >= 3 and str(p[0]) >= today.isoformat():
            found[s] = [date.fromisoformat(p[0]), p[1], bool(p[2]), "previous"]
            log("  %-5s kept the previous entry %s" % (s, p))

    entries = sorted(found.items(), key=lambda kv: kv[0])
    used = {k for _, v in entries for k in v[3].split("+")}
    srcs = [name for k, name in SOURCE_NAMES.items() if k in used]
    unknown = [s for s, v in entries if v[1] is None]
    body = ",\n".join("  %s: %s" % (json.dumps(s), json.dumps([v[0].isoformat(), v[1] or "am", v[2]])) for s, v in entries)
    text = '{"asOf": %s, "source": %s, "timingUnknown": %s, "d": {\n%s\n}}\n' % (
        json.dumps(today.isoformat()), json.dumps(" + ".join(srcs) or "none"), json.dumps(unknown), body)
    json.loads(text)
    out_path.write_text(text)
    log("Wrote %s: %d of %d stocks with a date by %s (%s); timing unknown: %s"
        % (out_path, len(entries), len(syms), horizon, " + ".join(srcs), ", ".join(unknown) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
