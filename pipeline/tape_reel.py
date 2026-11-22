"""Ten on the Tape as a Reel.

Usage:
  python3 pipeline/tape_reel.py specs/D-tape.json out/D/finance            # reel.mp4, cover.jpg, _preview.jpg
  python3 pipeline/tape_reel.py specs/D-tape.json out/D/finance --preview  # cover + preview sheet only (fast)

It reads the same spec as tape.py (the output of mkspec.py), so the prices, the % moves and the checks are identical.
The number of stocks in the spec picks the format:

  3, 4 or 5 stocks  SHORT format (the default from 21 Nov 2026), 26-34 seconds:
                    scene 1 (2.4 s)  the single biggest move as a giant number, on screen from the first frame,
                                     with its ticker, the reason ("reel_hook") and the other tickers as chips
                    one scene per stock (5.6-6.8 s)  ticker badge, counting % move, one-line reason ("headline"),
                                     the 2-month candlestick chart drawing itself in a gold frame, then two facts
                                     computed from the spec (volume vs normal, distance from the 52-week high)
                    last scene (3.6 s)  the question card
  10 stocks         CLASSIC format, 36 seconds: a scoreboard of all ten, 3 seconds a stock, the question card.

Optional extra keys in the spec:
  "reel_hook":  short format: the reason for the biggest move, two short lines of capitals, [..] = highlighted phrase,
                e.g. "REUTERS: SEC IS EXAMINING\\n[ITS ACCOUNTING]". Say who reported it.
                classic format: the day's story, e.g. "CHIPS GOT HIT.\\nNVIDIA [REPORTS TONIGHT]"
  "reel_sub":   one plain sentence under the hook
  "reel_outro": "WHICH ONE ARE\\nYOU [WATCHING]?"
Each stock shows its "headline" (keep it under about 28 characters); the longer "body" belongs in the caption.
The short format also needs avg_volume_30d, high_52w and low_52w for each stock (mkspec.py passes them through).

Look: the carousel's navy and gold, a scrolling ticker tape, a big counting % move, a candlestick chart that
draws itself, sound on every cut and every number, film grain and a vignette (finish.py).
Instagram's own buttons sit on the right edge and its caption at the bottom, so charts stop at x 930 and
everything readable stays above y 1520.
"""
import sys, os, json, math, subprocess
from PIL import Image, ImageDraw
from kit import font, fit_font, wrap, money, pct_text, save_jpg, parse_date
from finish import Finish
import tape
from reel import make_music, loudnorm, segs, ease, ease_io, ramp, clamp

RW, RH, FPS = 1080, 1920, 30
BG_TOP, BG_BOT = (17, 26, 45), (8, 12, 21)
GOLD, GOLD_DIM = (214, 178, 100), (112, 96, 62)
IVORY, SOFT, DIM = (244, 239, 230), (201, 206, 216), (120, 132, 154)
GRID = (30, 40, 58)
GREEN, RED, BLUE = (46, 204, 143), (240, 98, 108), (126, 178, 245)
INK = (14, 20, 33)
MX = 60
SHOW = 44
CHART = (MX, 950, 930, 1415)  # x0, y0, x1, y1 - clear of Instagram's right-hand buttons
COUNTS = (3, 4, 5, 10)
WORDS = {3: "three", 4: "four", 5: "five", 10: "ten"}


def timing(n):
    """Seconds for (first scene, each stock, last scene)."""
    if n == 10:
        return 2.8, 3.0, 3.4  # classic: 36.2 s
    return 2.4, {3: 6.8, 4: 6.2, 5: 5.6}[n], 3.6  # short: 26.4 / 30.8 / 34.0 s


def rgba(c, a=1.0):
    return (c[0], c[1], c[2], int(255 * clamp(a)))


_bg = None


def background():
    global _bg
    if _bg is None:
        im = Image.new("RGB", (RW, RH), BG_BOT)
        d = ImageDraw.Draw(im)
        for y in range(RH):
            f = min(1, y / (RH - 1) * 1.25)
            d.line([0, y, RW, y], fill=tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * f) for i in range(3)))
        _bg = im
    return _bg.copy()


def move(s, spec):
    return tape.pct(s["close"], s["prev_close"])


# ---------------- pieces ----------------
def big_headline(d, text, y, a_t, maxw=RW - 2 * MX, size=124, min_size=78, hl=RED):
    """Two lines of condensed capitals; [..] gets a highlight box that wipes in."""
    lines = text.split("\n")
    plain = ["".join(tx for tx, _ in segs(ln)) for ln in lines]
    while size > min_size and max(d.textlength(p, font=font("Barlow-ExtraBold", size)) for p in plain) > maxw:
        size -= 2
    if max(d.textlength(p, font=font("Barlow-ExtraBold", size)) for p in plain) > maxw:
        raise SystemExit(f"headline too long for the frame: {text!r}")
    fnt = font("Barlow-ExtraBold", size)
    lh = int(size * 0.98)
    for i, line in enumerate(lines):
        a = ease(ramp(a_t, 0.0 + i * 0.12, 0.26))
        if a > 0:
            yy = y + (1 - a) * 24
            x = MX
            for txt, st in segs(line):
                w = d.textlength(txt, font=fnt)
                if st == "h":
                    g = ease(ramp(a_t, 0.34 + i * 0.12, 0.28))
                    if g > 0:
                        d.rectangle([x - 12, yy + size * 0.13, x - 12 + (w + 24) * g, yy + size * 1.03], fill=rgba(hl, a))
                    d.text((x, yy), txt, font=fnt, fill=rgba(INK if hl == GOLD and g > 0.5 else IVORY, a))
                else:
                    d.text((x, yy), txt, font=fnt, fill=rgba(IVORY, a))
                x += w
        y += lh
    return y


def spaced(d, x, y, txt, fnt, fill, spacing=3, anchor="lm"):
    for ch in txt:
        d.text((x, y), ch, font=fnt, fill=fill, anchor=anchor)
        x += d.textlength(ch, font=fnt) + spacing
    return x


def spaced_w(d, txt, fnt, spacing=3):
    return sum(d.textlength(ch, font=fnt) + spacing for ch in txt) - spacing


def week(spec):
    """True for the Sunday and Monday editions, where the % move covers several sessions (move_bars > 1)."""
    return spec.get("move_bars", 1) > 1


def header(d, spec):
    f = font("Mono-SemiBold", 23)
    txt = f"WEEK TO {spec['session_short'].upper()}" if week(spec) else f"{spec['session_short'].upper()} CLOSE"
    spaced(d, MX, 166, f"TEN ON THE TAPE · {txt}", f, rgba(GOLD, 0.95), spacing=3)


def ticker_tape(d, spec, T, current=None):
    """A strip of all the tickers scrolling right to left, the one on screen boxed in gold."""
    y0, y1 = 205, 263
    d.rectangle([0, y0, RW, y1], fill=(7, 11, 19, 235))
    d.line([0, y0, RW, y0], fill=rgba(GOLD_DIM), width=2)
    d.line([0, y1, RW, y1], fill=rgba(GOLD_DIM), width=2)
    f = font("Mono-SemiBold", 28)
    items = []
    for i, s in enumerate(spec["stocks"]):
        p = move(s, spec)
        items.append((i, "$" + s["sym"], pct_text(p), GREEN if p >= 0 else RED))
    widths = [d.textlength(sym + " ", font=f) + d.textlength(mv, font=f) + 64 for _, sym, mv, _ in items]
    total = sum(widths)
    off = -(T * 120.0) % total
    x = off - total
    yc = (y0 + y1) / 2
    while x < RW:
        for (i, sym, mv, col), w in zip(items, widths):
            if x + w > 0 and x < RW:
                if i == current:
                    d.rounded_rectangle([x - 14, y0 + 8, x + w - 50, y1 - 8], radius=6, fill=rgba(GOLD, 0.95))
                    d.text((x, yc), sym, font=f, fill=INK, anchor="lm")
                    d.text((x + d.textlength(sym + " ", font=f), yc), mv, font=f, fill=INK, anchor="lm")
                else:
                    d.text((x, yc), sym, font=f, fill=rgba(IVORY, 0.92), anchor="lm")
                    d.text((x + d.textlength(sym + " ", font=f), yc), mv, font=f, fill=rgba(col), anchor="lm")
            x += w


def fine_print(d, txt, y=1490, a=1.0):
    f = fit_font(d, txt.upper(), "Mono-Medium", 20, RW - 2 * MX - 60, min_size=14)
    spaced(d, MX, y, txt.upper(), f, rgba(SOFT, 0.85 * a), spacing=2)


def facts(s, spec):
    """Two facts for the stock scene, computed from the spec (the same sums as the carousel's stat row).
    They cover the same sessions as the % move: one day in the daily edition, the whole week in the week edition
    (average daily volume over those sessions; a 52-week low or high touched on any of them)."""
    span = s["bars"][-spec.get("move_bars", 1):]
    out = [f"{sum(b[5] for b in span) / len(span) / s['avg_volume_30d']:.1f}× normal volume"]
    if min(b[3] for b in span) <= s["low_52w"] * 1.0005:
        out.append("hit a 52-week low")
    elif max(b[2] for b in span) >= s["high_52w"] * 0.9995:
        out.append("hit a 52-week high")
    elif s["close"] >= s["high_52w"] * 0.995:
        out.append(f"{pct_text(tape.pct(s['close'], s['low_52w']), 0)} from 52-week low")
    else:
        out.append(f"{pct_text(tape.pct(s['close'], s['high_52w']), 0)} from 52-week high")
    return out


def chip(d, x, yc, txt, a, dy=0.0):
    """Small boxed mono fact; returns its width."""
    f = font("Mono-SemiBold", 22)
    txt = txt.upper()
    w = spaced_w(d, txt, f, 2) + 62
    if a > 0:
        d.rounded_rectangle([x, yc - 22 + dy, x + w, yc + 22 + dy], radius=7, fill=rgba((20, 30, 50), 0.95 * a), outline=rgba(GOLD_DIM, a), width=2)
        d.rectangle([x + 16, yc - 7 + dy, x + 30, yc + 7 + dy], fill=rgba(GOLD, a))
        spaced(d, x + 44, yc + dy, txt, f, rgba(IVORY, a), spacing=2)
    return w


def chart(d, s, spec, t, box=CHART):
    """Candles draw themselves left to right; then the session candle(s) get a gold box and price tags appear."""
    x0, y0, x1, y1 = box
    bars = s["bars"]
    closes = [b[4] for b in bars]
    view = bars[-SHOW:]
    off = len(bars) - SHOW
    first = next(i for i, b in enumerate(bars) if b[0] >= s.get("break_date", "0000"))
    drawn = [(k, b) for k, b in enumerate(view) if off + k >= first]
    hi2 = max(b[2] for _, b in drawn)
    lo2 = min(b[3] for _, b in drawn)
    ma = [(k, sum(closes[off + k - 19:off + k + 1]) / 20) for k in range(SHOW) if off + k >= first + 19]
    lo_all, hi_all = min([lo2] + [v for _, v in ma]), max([hi2] + [v for _, v in ma])
    pad = (hi_all - lo_all) * 0.08 or 0.5
    top, bot = hi_all + pad, lo_all - pad
    ref = hi2
    lab = lambda v: tape.price_label(v, ref)
    lw = int(max(d.textlength(lab(v), font=font("Mono-Medium", 22)) for v in (hi_all, lo_all))) + 16
    px0, px1 = x0 + lw, x1 - 120
    py0, py1 = y0 + 10, y1 - 44
    Y = lambda v: py1 - (py1 - py0) * (v - bot) / (top - bot)
    step = (px1 - px0) / SHOW
    X = lambda k: px0 + step * (k + 0.5)
    a0 = ease(ramp(t, 0.05, 0.25))
    for q in range(4):
        v = lo_all + (hi_all - lo_all) * (q + 0.5) / 4
        d.line([px0, Y(v), px1, Y(v)], fill=rgba(GRID, a0), width=2)
        d.text((x0, Y(v)), lab(v), font=font("Mono-Medium", 22), fill=rgba(DIM, a0), anchor="lm")
    last_m = view[0][0][:7]
    for k, b in enumerate(view):
        if b[0][:7] != last_m:
            last_m = b[0][:7]
            d.text((X(k), py1 + 26), parse_date(b[0]).strftime("%b").upper(), font=font("Mono-Medium", 22), fill=rgba(DIM, a0), anchor="mm")
    g = ease_io(ramp(t, 0.15, 1.0))
    shown = int(math.ceil(g * SHOW))
    pts = [(X(k), Y(v)) for k, v in ma if k < shown]
    if len(pts) > 1:
        d.line(pts, fill=rgba(BLUE, 0.9), width=4, joint="curve")
    bw = max(4, int(step * 0.58))
    for k, b in drawn:
        if k >= shown:
            break
        o, h, l, c = b[1], b[2], b[3], b[4]
        col = GREEN if c >= o else RED
        x = X(k)
        d.line([x, Y(h), x, Y(l)], fill=rgba(col), width=3)
        ya, yb = sorted((Y(o), Y(c)))
        d.rectangle([x - bw / 2, ya, x + bw / 2, max(yb, ya + 3)], fill=rgba(col))
    ga = ease(ramp(t, 1.2, 0.3))
    if ga > 0:
        mb = spec.get("move_bars", 1)
        hl = view[-mb:]
        xa, xb = X(SHOW - mb), X(SHOW - 1)
        pulse = 0.75 + 0.25 * math.sin((t - 1.2) * 6.0)
        d.rounded_rectangle([xa - bw / 2 - 10, Y(max(c[2] for c in hl)) - 12, xb + bw / 2 + 10, Y(min(c[3] for c in hl)) + 12],
                            radius=8, outline=rgba(GOLD, ga * pulse), width=4)
        for v, col in ((hi2, GREEN), (lo2, RED)):
            xx = px0
            while xx < px1:
                d.line([xx, Y(v), min(xx + 12, px1), Y(v)], fill=rgba(col, 0.75 * ga), width=2)
                xx += 20
        items = [[Y(s["close"]), lab(s["close"]), GOLD]]
        for v, col in ((hi2, GREEN), (lo2, RED)):
            if lab(v) != lab(s["close"]):
                items.append([Y(v), lab(v), col])
        items.sort(key=lambda it: it[0])
        for _ in range(6):
            for p, q in zip(items, items[1:]):
                if q[0] - p[0] < 46:
                    mid = (p[0] + q[0]) / 2
                    p[0], q[0] = mid - 23, mid + 23
        f = font("Barlow-Bold", 30)
        for yy, txt, col in items:
            w = d.textlength(txt, font=f) + 24
            tx = x1 - w
            d.rounded_rectangle([tx, yy - 20, tx + w, yy + 20], radius=6, fill=rgba(col, ga))
            d.text((tx + w / 2, yy), txt, font=f, fill=rgba(INK, ga), anchor="mm")


# ---------------- scenes ----------------
def lead(spec):
    """Index of the single biggest move (by size, up or down)."""
    st = spec["stocks"]
    return max(range(len(st)), key=lambda i: abs(move(st[i], spec)))


def hook(spec, t, cover=False):
    """Short format, scene 1: the biggest move as a giant number with its ticker and the reason.
    The ticker, the number and the reason are readable in the very first frame; the rest arrives around them."""
    im = background()
    d = ImageDraw.Draw(im, "RGBA")
    header(d, spec)
    st = spec["stocks"]
    k = lead(spec)
    s = st[k]
    ticker_tape(d, spec, t, current=k)
    at = 99 if cover else t
    p = move(s, spec)
    col = GREEN if p >= 0 else RED
    day = spec.get("move_label", spec["session_day"])
    fb = font("Barlow-Bold", 84)
    sym = "$" + s["sym"]
    tw = d.textlength(sym, font=fb)
    d.rounded_rectangle([MX, 320, MX + tw + 48, 428], radius=14, fill=rgba(GOLD))
    d.text((MX + 24, 374), sym, font=fb, fill=INK, anchor="lm")
    nx = MX + tw + 48 + 26
    d.text((nx, 352), s["name"], font=fit_font(d, s["name"], "Inter-Medium", 46, RW - MX - nx, min_size=28), fill=rgba(IVORY), anchor="lm")
    d.text((nx, 404), f"{day} · closed {money(s['close'])}", font=font("Inter-Regular", 32), fill=rgba(SOFT), anchor="lm")
    txt = pct_text(p)
    size = 380
    while size > 200 and d.textlength(txt, font=font("Barlow-ExtraBold", int(size * 1.07))) > RW - 2 * MX + 16:
        size -= 4
    z = 1 + 0.07 * (1 - ease(ramp(at, 0.0, 0.28)))  # lands with a small punch instead of fading in
    d.text((MX - 8, 620), txt, font=font("Barlow-ExtraBold", int(size * z)), fill=rgba(col), anchor="lm")
    y = 620 + int(size * 0.44)
    reason = spec.get("reel_hook") or s["headline"].upper()
    y = big_headline(d, reason, y, at + 0.30, size=104, min_size=64, hl=RED if p < 0 else GOLD)
    if spec.get("reel_sub"):
        a = ease(ramp(at, 0.15, 0.3))
        fs = font("Inter-Regular", 38)
        for ln in wrap(d, spec["reel_sub"], fs, RW - 2 * MX):
            d.text((MX, y + 16), ln, font=fs, fill=rgba(SOFT, a))
            y += 52
    rest = [i for i in range(len(st)) if i != k]
    rows = math.ceil(len(rest) / 2)
    gy = y + 76
    if gy + rows * 116 > 1474:
        raise SystemExit("hook: the reason and sub are too tall for the first scene; shorten them")
    f = font("Barlow-Bold", 56)
    colw = (940 - MX - 30) / 2  # stays left of Instagram's like / comment / share buttons
    for j, i in enumerate(rest):
        a = ease(ramp(at, 0.55 + j * 0.13, 0.22))
        if a <= 0:
            continue
        x = MX + (j % 2) * (colw + 30)
        yy = gy + (j // 2) * 116 + (1 - a) * 18
        d.rounded_rectangle([x, yy, x + colw, yy + 96], radius=12, fill=rgba((20, 30, 50), 0.92 * a), outline=rgba(GOLD_DIM, a), width=2)
        q = move(st[i], spec)
        d.text((x + 24, yy + 48), "$" + st[i]["sym"], font=f, fill=rgba(IVORY, a), anchor="lm")
        d.text((x + colw - 24, yy + 48), pct_text(q), font=f, fill=rgba(GREEN if q >= 0 else RED, a), anchor="rm")
    if not cover:
        fine_print(d, f"{spec['session_day']} {spec['session_short'].split(' ', 1)[1]} closing prices · Robinhood", 1490, ease(ramp(t, 0.4, 0.4)))
    return im


def intro(spec, t, cover=False):
    """Classic format, scene 1: the day's hook over a scoreboard of all ten moves."""
    im = background()
    d = ImageDraw.Draw(im, "RGBA")
    header(d, spec)
    ticker_tape(d, spec, t)
    day = spec.get("move_label", spec["session_day"])
    hook_txt = spec.get("reel_hook", f"10 STOCKS THAT\nMOVED [{day.upper()}]")
    at = 99 if cover else t
    ix = spec.get("indices") or []
    down = bool(ix) and ix[0]["close"] < ix[0]["prev_close"]
    y = big_headline(d, hook_txt, 330, at, hl=RED if down else GOLD)
    sub = spec.get("reel_sub", "Ten stocks with big news, one chart each.")
    a = ease(ramp(at, 0.5, 0.35))
    fs = font("Inter-Regular", 40)
    for ln in wrap(d, sub, fs, RW - 2 * MX):
        d.text((MX, y + 18), ln, font=fs, fill=rgba(SOFT, a))
        y += 54
    gy = max(y + 70, 760)
    f = font("Barlow-Bold", 60)
    colw = (940 - MX - 36) / 2  # stays left of Instagram's like / comment / share buttons
    for i, s in enumerate(spec["stocks"]):
        r, c = i % 5, i // 5
        a = ease(ramp(at, 0.45 + i * 0.07, 0.22))
        if a <= 0:
            continue
        x = MX + c * (colw + 36)
        yy = gy + r * 124 + (1 - a) * 20
        d.rounded_rectangle([x, yy, x + colw, yy + 100], radius=12, fill=rgba((20, 30, 50), 0.92 * a), outline=rgba(GOLD_DIM, a), width=2)
        p = move(s, spec)
        d.text((x + 24, yy + 50), "$" + s["sym"], font=f, fill=rgba(IVORY, a), anchor="lm")
        d.text((x + colw - 24, yy + 50), pct_text(p), font=f, fill=rgba(GREEN if p >= 0 else RED, a), anchor="rm")
    if gy + 5 * 124 > 1500:
        raise SystemExit("intro: the hook and sub are too tall; shorten them")
    if not cover:
        fine_print(d, f"{spec['session_day']} {spec['session_short'].split(' ', 1)[1]} closing prices · Robinhood", 1490, ease(ramp(t, 0.6, 0.4)))
    return im


def stock(spec, k, t):
    s = spec["stocks"][k]
    n = len(spec["stocks"])
    short = n != 10
    t_in, seg, _ = timing(n)
    im = background()
    d = ImageDraw.Draw(im, "RGBA")
    header(d, spec)
    ticker_tape(d, spec, t_in + k * seg + t, current=k)
    e = ease(ramp(t, 0.0, 0.22))
    dx = (1 - e) * 90
    layer = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    L = ImageDraw.Draw(layer)
    f = font("Mono-SemiBold", 26)
    L.text((MX, 318), f"{k + 1:>2}/{n}" if n == 10 else f"{k + 1}/{n}", font=f, fill=rgba(GOLD), anchor="lm")
    for j in range(n):
        cx = MX + (110 if n == 10 else 84) + j * 22
        L.ellipse([cx - 6, 312, cx + 6, 324], fill=rgba(GOLD if j <= k else GOLD_DIM, 1.0 if j <= k else 0.6))
    fb = font("Barlow-Bold", 62)
    sym = "$" + s["sym"]
    tw = L.textlength(sym, font=fb)
    L.rounded_rectangle([MX, 368, MX + tw + 40, 448], radius=12, fill=rgba(GOLD))
    L.text((MX + 20, 408), sym, font=fb, fill=INK, anchor="lm")
    nx = MX + tw + 40 + 24
    L.text((nx, 408), s["name"], font=fit_font(L, s["name"], "Inter-Medium", 40, RW - MX - nx, min_size=26), fill=rgba(IVORY), anchor="lm")
    p = move(s, spec)
    col = GREEN if p >= 0 else RED
    g = ease(ramp(t, 0.12, 0.5))
    L.text((MX - 6, 590), pct_text(p * g), font=font("Barlow-ExtraBold", 230), fill=rgba(col), anchor="lm")
    day = spec.get("move_label", spec["session_day"])
    L.text((MX, 725), f"{day} · closed {money(s['close'])}", font=font("Inter-Regular", 38), fill=rgba(SOFT), anchor="lm")
    fh = font("Barlow-Bold", 80)
    lines = wrap(L, s["headline"], fh, RW - 2 * MX)
    if len(lines) > 2:
        raise SystemExit(f"{s['sym']}: headline needs {len(lines)} lines: {s['headline']!r}")
    ha = ease(ramp(t, 0.35, 0.3))
    for i, ln in enumerate(lines):
        L.text((MX, 820 + i * 78 + (1 - ha) * 16), ln, font=fh, fill=rgba(IVORY, ha), anchor="lm")
    if short:  # chart in a thin gold frame, with room for the two facts under it
        box = (CHART[0] + 16, CHART[1] + (76 if len(lines) == 2 else 16), CHART[2] - 14, 1392)
        fa = ease(ramp(t, 0.05, 0.25))
        L.rounded_rectangle([CHART[0], box[1] - 16, CHART[2], box[3] + 8], radius=14, fill=rgba((11, 16, 28), 0.55 * fa), outline=rgba(GOLD_DIM, fa), width=2)
        chart(L, s, spec, t, box)
        x = MX
        for i, txt in enumerate(facts(s, spec)):
            a = ease(ramp(t, 2.5 + i * 0.5, 0.25))
            x += chip(L, x, 1437, txt, a, dy=(1 - a) * 10) + 14
            if x > 932:
                raise SystemExit(f"{s['sym']}: the two facts under the chart are too wide")
    else:
        box = CHART if len(lines) == 1 else (CHART[0], CHART[1] + 60, CHART[2], CHART[3])
        chart(L, s, spec, t, box)
    fine_print(L, f"Sources: {s['sources']}", 1490, ease(ramp(t, 0.5, 0.3)))
    if e < 1:  # slide and fade the card in; the header and tape stay put
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * (0.3 + 0.7 * e))))
    im.paste(layer, (int(dx), 0), layer)
    return im


def outro(spec, t, cover=False):
    n = len(spec["stocks"])
    t_in, seg, _ = timing(n)
    im = background()
    d = ImageDraw.Draw(im, "RGBA")
    header(d, spec)
    ticker_tape(d, spec, t_in + n * seg + t)
    q = spec.get("reel_outro", "WHICH ONE ARE\nYOU [WATCHING]?")
    y = big_headline(d, q, 360, t, hl=GOLD)
    a = ease(ramp(t, 0.45, 0.35))
    d.text((MX, y + 40), f"Comment the ticker. All {WORDS[n]} are in the caption.", font=font("Inter-Regular", 40), fill=rgba(SOFT, a))
    if spec.get("indices"):
        a2 = ease(ramp(t, 0.8, 0.35))
        yy = y + 170
        when = spec.get("move_label", spec["session_day"]) if week(spec) else spec["session_day"]  # the spec's indices cover the same span
        d.text((MX, yy), f"THE WHOLE MARKET, {when.upper()}", font=font("Mono-SemiBold", 24), fill=rgba(GOLD, a2), anchor="lm")
        yy += 60
        for ix in spec["indices"]:
            p = (ix["close"] / ix["prev_close"] - 1) * 100
            d.text((MX, yy), ix["name"], font=font("Barlow-Bold", 64), fill=rgba(IVORY, a2), anchor="lm")
            d.text((RW - MX - 60, yy), pct_text(p), font=font("Barlow-Bold", 64), fill=rgba(GREEN if p >= 0 else RED, a2), anchor="rm")
            yy += 84
    a3 = ease(ramp(t, 1.2, 0.4))
    d.text((RW / 2, 1300), "@thegildedticker", font=font("Barlow-Bold", 66), fill=rgba(GOLD, a3), anchor="mm")
    d.text((RW / 2, 1372), "Follow for tomorrow's tape", font=font("Inter-Medium", 38), fill=rgba(IVORY, a3), anchor="mm")
    fine_print(d, f"{spec['session_short']} closing prices · not investment advice", 1490, a3)
    return im


# ---------------- build ----------------
def build(spec_path, out_dir, preview=False):
    spec = json.load(open(spec_path))
    tape.validate(spec, counts=COUNTS)
    os.makedirs(out_dir, exist_ok=True)
    n = len(spec["stocks"])
    short = n != 10
    t_in, seg, t_out = timing(n)
    total = t_in + n * seg + t_out
    nframes = int(round(total * FPS))
    print(f"finance reel ({'short' if short else 'classic'} format, {n} stocks): {total:.1f} s, {nframes} frames")
    if short:
        for s in spec["stocks"]:
            for key in ("avg_volume_30d", "high_52w", "low_52w"):
                if not s.get(key):
                    raise SystemExit(f"{s['sym']}: the short format needs {key} (get_equity_fundamentals)")
        b = spec["stocks"][lead(spec)]
        print(f"scene 1: ${b['sym']} {pct_text(move(b, spec))} | {spec.get('reel_hook', b['headline'])!r}")
    fin = Finish(RW, RH, seed=7)
    first = hook if short else intro

    def frame(i):
        T = i / FPS
        if T < t_in:
            im = first(spec, T)
        elif T < t_in + n * seg:
            k = int((T - t_in) // seg)
            im = stock(spec, k, T - t_in - k * seg)
        else:
            im = outro(spec, T - t_in - n * seg)
        return fin.apply(im, i)

    for k in range(n):  # fail fast on text that does not fit
        stock(spec, k, seg - 0.2)
    save_jpg(fin.apply(first(spec, t_in - 0.1, cover=True), 0, handle=False), f"{out_dir}/cover.jpg", quality=92)
    if short:
        save_jpg(frame(0), f"{out_dir}/_first.jpg", quality=90)  # what a viewer sees before anything has moved
        ts = [0.0, 0.5, t_in - 0.1] + [t_in + k * seg + x for k in range(n) for x in (0.6, 2.0, seg - 0.2)] + [t_in + n * seg + 0.8, total - 0.1]
    else:
        ts = [0.5, 2.6] + [t_in + k * seg + x for k in range(n) for x in (0.6, 2.4)] + [t_in + n * seg + 0.8, total - 0.1]
    thumbs = [frame(int(t * FPS)).resize((RW // 4, RH // 4), Image.LANCZOS) for t in ts]
    cols = 6
    sheet = Image.new("RGB", (cols * RW // 4, math.ceil(len(thumbs) / cols) * RH // 4), (0, 0, 0))
    for i, th in enumerate(thumbs):
        sheet.paste(th, ((i % cols) * RW // 4, (i // cols) * RH // 4))
    sheet.save(f"{out_dir}/_preview.jpg", quality=88)
    if preview:
        return
    raw, wav = f"{out_dir}/_music_raw.wav", f"{out_dir}/_music.wav"
    if short:
        sfx = [(0.0, "impact", 0.9), (0.34, "tick", 0.5)] + [(0.55 + j * 0.13, "pop", 0.3) for j in range(n - 1)]
    else:
        sfx = [(0.0, "impact", 0.8)] + [(0.45 + i * 0.07, "tick", 0.25) for i in range(0, 10, 3)]
    for k in range(n):
        t0 = t_in + k * seg
        sfx += [(t0 - 0.22, "whoosh", 0.65), (t0 + 0.6, "tick", 0.6), (t0 + 1.2, "pop", 0.35)]
        if short:
            sfx += [(t0 + 2.5, "tick", 0.4), (t0 + 3.0, "tick", 0.4)]
    sfx += [(t_in + n * seg - 0.22, "whoosh", 0.7), (t_in + n * seg, "impact", 0.6)]
    make_music(raw, total, [], seed=f"tape-{spec['session_date']}", sfx=sfx, booms=False)
    li = loudnorm(raw, wav)
    print(f"music: {li:.1f} LUFS -> -14 LUFS")
    mp4 = f"{out_dir}/reel.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RW}x{RH}", "-r", str(FPS), "-i", "-",
           "-i", wav, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-g", str(FPS * 2), "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-shortest", "-movflags", "+faststart",
           "-use_editlist", "0", mp4]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(nframes):
        pr.stdin.write(frame(i).convert("RGB").tobytes())
    pr.stdin.close()
    if pr.wait() != 0:
        raise SystemExit("ffmpeg failed")
    print("wrote", mp4, os.path.getsize(mp4) // 1024, "KB")


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], preview="--preview" in sys.argv)
