"""Ten on the Tape - the candlestick carousel already running on @thegildedticker (first posted 18 Sept 2026).

Usage:  python3 pipeline/tape.py specs/2026-11-11-tape.json out/2026-11-11/tape

Ten slides, one stock each (Instagram's publishing API allows at most 10 per carousel). Slide 1 carries
the "Ten on the Tape" title box. Every slide: gold ticker badge, company, % move, a written headline,
three lines of plain-English body, a 2-month candlestick chart with the 20-day average and the
2-month high / low, then three stats (close, volume vs normal, distance from the 52-week high).

Spec keys:
  post_label "Wednesday 11 November" (the day it is posted), session_date "2026-11-10", session_day "Tuesday", session_short "Tuesday 10 Nov"
  stocks: exactly 10, in editorial order (best-known story first). Each:
     sym, name, headline (<= ~28 characters), body (<= 3 lines), sources ("CNBC, Robinhood"),
     close (official close), prev_close, bars [[YYYY-MM-DD, open, high, low, close, volume], ...] ending on
     session_date (send ~65 trading days so the 20-day average covers the whole chart),
     avg_volume_30d, high_52w, low_52w
Optional, for the Sunday and Monday editions (see RUNBOOK.md):
  title_sub  "10 biggest movers of the week"   (default "10 stocks with big news")
  move_label "This week"                       (default: session_day)
  move_bars  5                                 (the % move is close vs the close this many bars back; default 1)
The % move, volume multiple and 52-week distance are computed here, never typed by hand.
"""
import sys, json, os, math
from PIL import Image, ImageDraw
from kit import font, wrap, fit_font, money, pct_text, save_jpg, contact_sheet, parse_date

W, H = 1080, 1350
BG_TOP, BG_BOT = (17, 26, 45), (9, 13, 22)
GOLD = (214, 178, 100)
GOLD_DIM = (112, 96, 62)
IVORY = (244, 239, 230)
SOFT = (201, 206, 216)
GRID = (30, 40, 58)
GREEN = (46, 204, 143)
RED = (240, 98, 108)
BLUE = (126, 178, 245)
INK = (14, 20, 33)
MX = 72
SHOW = 44  # trading days on the chart (about two months)


def background():
    im = Image.new("RGB", (W, H), BG_BOT)
    d = ImageDraw.Draw(im)
    for y in range(H):
        f = min(1, y / (H - 1) * 1.35)
        d.line([0, y, W, y], fill=tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * f) for i in range(3)))
    d.rectangle([30, 28, W - 31, H - 29], outline=GOLD_DIM, width=2)
    return im


_bg = None


def canvas():
    global _bg
    if _bg is None:
        _bg = background()
    im = _bg.copy()
    return im, ImageDraw.Draw(im)


def pct(close, prev):
    return (close / prev - 1) * 100


def validate(spec):
    errs = []
    st = spec["stocks"]
    if len(st) != 10:
        errs.append(f"need exactly 10 stocks, got {len(st)}")
    if len({s["sym"] for s in st}) != len(st):
        errs.append("duplicate ticker")
    for s in st:
        b = s["bars"]
        if b[-1][0] != spec["session_date"]:
            errs.append(f"{s['sym']}: bars end {b[-1][0]}, not {spec['session_date']}")
        if abs(b[-1][4] - s["close"]) > 0.011:
            errs.append(f"{s['sym']}: last bar close {b[-1][4]} != official close {s['close']}")
        mb = spec.get("move_bars", 1)
        if abs(b[-1 - mb][4] - s["prev_close"]) > 0.011:
            errs.append(f"{s['sym']}: close {mb} bar(s) back is {b[-1 - mb][4]}, not prev_close {s['prev_close']}")
        if len(b) < SHOW + 20:
            errs.append(f"{s['sym']}: {len(b)} bars; need {SHOW + 20} for the 20-day average")
        for row in b:
            if not (row[3] <= min(row[1], row[4]) + 1e-6 and row[2] >= max(row[1], row[4]) - 1e-6):
                errs.append(f"{s['sym']}: bad OHLC on {row[0]}: {row}")
                break
        if b[-1][5] <= 0:
            errs.append(f"{s['sym']}: no volume on the session day (interpolated bar?)")
        if abs(pct(s["close"], s["prev_close"])) > 80:
            errs.append(f"{s['sym']}: move over 80% - check for a split or bad data")
    if errs:
        raise SystemExit("SPEC ERRORS:\n  " + "\n  ".join(errs))


def price_label(v, ref):
    """Axis/tag price text: cents when the chart tops out below $50, whole dollars above (like the posts already up)."""
    return f"${v:,.2f}" if ref < 50 else f"${v:,.0f}"


def dashed(d, x0, x1, y, col, dash=14, gap=9, width=2):
    x = x0
    while x < x1:
        d.line([x, y, min(x + dash, x1), y], fill=col, width=width)
        x += dash + gap


def tag(d, x0, y, text, fill, w=120, h=42):
    d.rounded_rectangle([x0, y - h // 2, x0 + w, y + h // 2], radius=7, fill=fill)
    d.text((x0 + w / 2, y), text, font=font("Atkinson-Bold", 25), fill=INK, anchor="mm")


def chart(im, d, s, spec, x0, y0, x1, y1):
    """Candles in [x0..x1-150], y labels left, tags right."""
    bars = s["bars"]
    closes = [b[4] for b in bars]
    view = bars[-SHOW:]
    off = len(bars) - SHOW
    hi2 = max(b[2] for b in view)
    lo2 = min(b[3] for b in view)
    ma_vals = [sum(closes[off + i - 19:off + i + 1]) / 20 for i in range(SHOW) if off + i >= 19]
    ref = hi2
    lo_all, hi_all = min([lo2] + ma_vals), max([hi2] + ma_vals)  # keep the 20-day average inside the chart too
    pad = (hi_all - lo_all) * 0.07 or 0.5
    top, bot = hi_all + pad, lo_all - pad
    lab_w = int(max(d.textlength(price_label(v, ref), font=font("Atkinson-Bold", 22)) for v in (hi_all, lo_all))) + 18
    px0, px1 = x0 + lab_w, x1 - 148
    py0, py1 = y0 + 14, y1 - 46
    Y = lambda v: py1 - (py1 - py0) * (v - bot) / (top - bot)
    step = (px1 - px0) / SHOW
    X = lambda i: px0 + step * (i + 0.5)
    for k in range(4):  # grid + y labels
        v = lo_all + (hi_all - lo_all) * (k + 0.5) / 4
        d.line([px0, Y(v), px1, Y(v)], fill=GRID, width=2)
        d.text((x0, Y(v)), price_label(v, ref), font=font("Atkinson-Bold", 22), fill=SOFT, anchor="lm")
    last_m = view[0][0][:7]
    for i, b in enumerate(view):  # month labels
        if b[0][:7] != last_m:
            last_m = b[0][:7]
            d.text((X(i), py1 + 28), parse_date(b[0]).strftime("%b"), font=font("Atkinson-Bold", 23), fill=SOFT, anchor="mm")
    dashed(d, px0, px1 + 12, Y(hi2), GREEN)
    dashed(d, px0, px1 + 12, Y(lo2), RED)
    ma = []
    for i in range(SHOW):  # 20-day average
        j = off + i
        if j >= 19:
            ma.append((X(i), Y(sum(closes[j - 19:j + 1]) / 20)))
    if len(ma) > 1:
        d.line(ma, fill=BLUE, width=4, joint="curve")
    bw = max(4, int(step * 0.56))
    for i, b in enumerate(view):  # candles
        o, h, l, c = b[1], b[2], b[3], b[4]
        col = GREEN if c >= o else RED
        x = X(i)
        d.line([x, Y(h), x, Y(l)], fill=col, width=3)
        ya, yb = sorted((Y(o), Y(c)))
        if yb - ya < 3:
            yb = ya + 3
        d.rectangle([x - bw / 2, ya, x + bw / 2, yb], fill=col)
    b = view[-1]  # highlight the session's candle
    x = X(SHOW - 1)
    d.rounded_rectangle([x - bw / 2 - 9, Y(b[2]) - 10, x + bw / 2 + 9, Y(b[3]) + 10], radius=8, outline=GOLD, width=3)
    tx = x1 - 120  # right-hand tags, nudged apart so they never overlap
    close_txt = price_label(s["close"], ref)
    items = [[Y(s["close"]), close_txt, GOLD]]
    for v, col in ((hi2, GREEN), (lo2, RED)):
        if price_label(v, ref) != close_txt:  # a close at the 2-month high/low gets one gold tag, not two
            items.append([Y(v), price_label(v, ref), col])
    items.sort(key=lambda t: t[0])
    for _ in range(6):
        for a, b2 in zip(items, items[1:]):
            if b2[0] - a[0] < 48:
                mid = (a[0] + b2[0]) / 2
                a[0], b2[0] = mid - 24, mid + 24
    for yy, txt, col in items:
        tag(d, tx, int(yy), txt, col)


def legend(d, y, day):
    f = font("Atkinson-Bold", 22)
    x = MX
    d.rounded_rectangle([x, y - 11, x + 20, y + 11], radius=4, outline=GOLD, width=3)
    x += 30
    d.text((x, y), day, font=f, fill=SOFT, anchor="lm")
    x += d.textlength(day, font=f) + 30
    d.line([x, y, x + 34, y], fill=BLUE, width=4)
    x += 44
    d.text((x, y), "20-day average", font=f, fill=SOFT, anchor="lm")
    x += d.textlength("20-day average", font=f) + 30
    for label, col in (("2-month high", GREEN), ("2-month low", RED)):
        dashed(d, x, x + 34, y, col, dash=9, gap=6, width=3)
        x += 44
        d.text((x, y), label, font=f, fill=SOFT, anchor="lm")
        x += d.textlength(label, font=f) + 30


def slide(spec, s, n, out):
    im, d = canvas()
    p = pct(s["close"], s["prev_close"])
    col = GREEN if p >= 0 else RED
    day = spec["session_day"]
    first = n == 1
    d.text((MX, 86), "The Gilded Ticker" if first else "Ten on the Tape", font=font("Atkinson-Bold", 27), fill=GOLD, anchor="lm")
    d.text((W - MX, 86), f"{n} / 10", font=font("Atkinson-Bold", 27), fill=GOLD, anchor="rm")
    y = 128
    if first:
        d.rounded_rectangle([MX, y, W - MX, y + 150], radius=14, fill=(24, 33, 52), outline=GOLD_DIM, width=2)
        d.text((MX + 30, y + 54), "Ten on the Tape", font=font("Atkinson-Bold", 60), fill=IVORY, anchor="lm")
        d.text((MX + 32, y + 112), f"10 stocks with big news · {spec['post_label']}", font=font("Atkinson-Bold", 28), fill=GOLD, anchor="lm")
        y += 150 + 46
    else:
        y += 20
    fb = font("Atkinson-Bold", 40)  # ticker badge, name, move
    tw = d.textlength("$" + s["sym"], font=fb)
    d.rounded_rectangle([MX, y, MX + tw + 40, y + 74], radius=12, fill=GOLD)
    d.text((MX + 20, y + 37), "$" + s["sym"], font=fb, fill=INK, anchor="lm")
    nx = MX + tw + 40 + 22
    fp = font("Atkinson-Bold", 76)
    pw = d.textlength(pct_text(p), font=fp)
    d.text((nx, y + 37), s["name"], font=fit_font(d, s["name"], "AtkinsonNext-SemiBold", 31, W - MX - pw - 30 - nx, min_size=22), fill=IVORY, anchor="lm")
    d.text((W - MX, y + 30), pct_text(p), font=fp, fill=col, anchor="rm")
    d.text((W - MX, y + 92), f"{day} · closed {money(s['close'])}", font=font("AtkinsonNext-SemiBold", 24), fill=IVORY, anchor="rm")
    y += 74 + 62
    fh = fit_font(d, s["headline"], "Atkinson-Bold", 56, W - 2 * MX, min_size=42)  # headline + body
    if d.textlength(s["headline"], font=fh) > W - 2 * MX:
        raise SystemExit(f"{s['sym']}: headline too long: {s['headline']!r}")
    d.text((MX, y + 24), s["headline"], font=fh, fill=IVORY, anchor="lm")
    y += 72
    fbody = font("Atkinson-Regular", 31)
    lines = wrap(d, s["body"], fbody, W - 2 * MX)
    if len(lines) > 3:
        raise SystemExit(f"{s['sym']}: body needs {len(lines)} lines, max 3: {s['body']!r}")
    for ln in lines:
        d.text((MX, y + 16), ln, font=fbody, fill=IVORY, anchor="lm")
        y += 43
    y += (3 - len(lines)) * 14 + 30
    stats_y = 1160  # chart fills what is left above the legend and stats
    chart(im, d, s, spec, MX, y, W - MX, stats_y - 92)
    legend(d, stats_y - 62, day)
    d.line([MX, stats_y - 22, W - MX, stats_y - 22], fill=GOLD_DIM, width=2)
    vol_x = s["bars"][-1][5] / s["avg_volume_30d"]
    if s["close"] >= s["high_52w"] * 0.995:
        third = (pct_text(pct(s["close"], s["low_52w"]), 0), "from 52-week low")
    else:
        third = (pct_text(pct(s["close"], s["high_52w"]), 0), "from 52-week high")
    stats = [(money(s["close"]), f"{day} close"), (f"{vol_x:.1f}×", "normal trading volume"), third]
    colw = (W - 2 * MX) / 3
    for i, (val, lab) in enumerate(stats):
        x = MX + i * colw + (0 if i == 0 else 26)
        if i:
            d.line([MX + i * colw, stats_y, MX + i * colw, stats_y + 104], fill=GOLD_DIM, width=2)
        d.text((x, stats_y + 30), val, font=font("Atkinson-Bold", 46), fill=GOLD, anchor="lm")
        d.text((x, stats_y + 82), lab, font=font("Atkinson-Regular", 25), fill=IVORY, anchor="lm")
    fine = f"Prices at {spec['session_short']} close. Sources: {s['sources']}. Not investment advice."
    d.text((MX, 1292), fine, font=fit_font(d, fine, "Atkinson-Regular", 20, W - 2 * MX, min_size=16), fill=SOFT, anchor="lm")
    return save_jpg(im, out)


def build(spec_path, out_dir):
    spec = json.load(open(spec_path))
    validate(spec)
    os.makedirs(out_dir, exist_ok=True)
    paths = [slide(spec, s, i + 1, f"{out_dir}/{i + 1:02d}.jpg") for i, s in enumerate(spec["stocks"])]
    contact_sheet(paths[:6], f"{out_dir}/_sheet_a.jpg", cols=3, scale=0.5)
    contact_sheet(paths[6:], f"{out_dir}/_sheet_b.jpg", cols=2, scale=0.5)
    for s in spec["stocks"]:
        vx = s["bars"][-1][5] / s["avg_volume_30d"]
        print(f"{s['sym']:6s} close {money(s['close']):>10s}  prev {money(s['prev_close']):>10s}  {pct_text(pct(s['close'], s['prev_close']), 2):>8s}"
              f"  vol {vx:.1f}x  vs 52w high {pct(s['close'], s['high_52w']):+.1f}%")
    return paths


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
