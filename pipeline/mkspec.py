"""Build a Ten on the Tape spec from your story notes plus raw Robinhood price history.

Usage:
  python3 pipeline/mkspec.py work/stories.json specs/2026-11-12-tape.json /tmp/claude-tool-results/.../get_equity_historicals-*.txt [more.txt ...]

The history files are the raw JSON that mcp get_equity_historicals returned (interval "day", ~95 calendar
days back so each stock has 65+ trading days). Large results are saved by the harness under
/tmp/claude-tool-results/ - pass those paths here instead of retyping numbers.

stories.json:
{
  "publish_date": "2026-11-12", "post_label": "Thursday 12 November",
  "session_date": "2026-11-11", "session_day": "Wednesday", "session_short": "Wednesday 11 Nov",
  (optional) "title_sub", "move_label", "move_bars",
  "stocks": [ { "sym", "name", "headline", "body", "sources",
                "close":   official close from get_equity_quotes -> close.price (close.date must equal session_date),
                "avg_volume_30d", "high_52w", "low_52w":  from get_equity_fundamentals,
                "session": [open, high, low, volume]   ONLY if the daily bar for session_date is missing or
                           interpolated: take these from get_equity_fundamentals (bounds "regular") and check
                           that its market_date equals session_date } x 10 ],
  "indices": [...optional...], "data_notes": {...}, "story_sources": {...}
}
"""
import sys, json


def load_hist(paths):
    out = {}
    for p in paths:
        raw = json.load(open(p))
        res = raw.get("data", raw).get("results", [])
        for r in res:
            rows = [[b["begins_at"][:10], float(b["open_price"]), float(b["high_price"]), float(b["low_price"]), float(b["close_price"]), int(b["volume"])]
                    for b in r["bars"] if not b.get("interpolated") and int(b["volume"]) > 0]
            if rows:
                have = {x[0] for x in out.get(r["symbol"], [])}
                out[r["symbol"]] = sorted(out.get(r["symbol"], []) + [x for x in rows if x[0] not in have])
    return out


def main(stories_path, out_path, hist_paths):
    st = json.load(open(stories_path))
    hist = load_hist(hist_paths)
    S = st["session_date"]
    mb = st.get("move_bars", 1)
    problems = []
    for s in st["stocks"]:
        sym = s["sym"]
        if sym not in hist:
            problems.append(f"{sym}: no price history in the files given")
            continue
        bars = [b for b in hist[sym] if b[0] < S]
        today = [b for b in hist[sym] if b[0] == S]
        if today:
            o, h, l, v = today[0][1], today[0][2], today[0][3], today[0][5]
        elif "session" in s:
            o, h, l, v = s["session"]
        else:
            problems.append(f"{sym}: no real daily bar for {S} and no 'session' override (use get_equity_fundamentals, or drop the stock)")
            continue
        c = float(s["close"])
        bars.append([S, o, max(h, c, o), min(l, c, o), c, int(v)])
        if len(bars) < 64:
            problems.append(f"{sym}: only {len(bars)} trading days of history; ask for ~95 calendar days")
            continue
        s["bars"] = bars[-70:]
        s["prev_close"] = bars[-1 - mb][4]
        s.pop("session", None)
    if problems:
        raise SystemExit("CANNOT BUILD SPEC:\n  " + "\n  ".join(problems))
    json.dump(st, open(out_path, "w"), ensure_ascii=False)
    for s in st["stocks"]:
        print(f"{s['sym']:6s} {len(s['bars'])} bars  prev {s['prev_close']:.2f} -> close {s['close']:.2f}  {(s['close'] / s['prev_close'] - 1) * 100:+.2f}%")
    print("wrote", out_path)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
