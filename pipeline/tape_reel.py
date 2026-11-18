"""Ten on the Tape as a Reel: the session's ten big movers in about 36 seconds.

Usage:
  python3 pipeline/tape_reel.py specs/D-tape.json out/D/finance            # reel.mp4, cover.jpg, _preview.jpg
  python3 pipeline/tape_reel.py specs/D-tape.json out/D/finance --preview  # cover + preview sheet only (fast)

It reads the same spec as tape.py (the output of mkspec.py), so the prices, the % moves and the checks are identical.
Optional extra keys in the spec:
  "reel_hook":  "CHIPS GOT HIT.\\nNVIDIA [REPORTS TONIGHT]"  two short lines of capitals, [..] = highlighted phrase
                (default "10 STOCKS THAT\\nMOVED [MONDAY]")
  "reel_sub":   one plain sentence under the hook, e.g. "Ten stocks with big news, one chart each."
  "reel_outro": "WHICH ONE ARE\\nYOU [WATCHING]?"
Each stock shows its "headline" (keep it under about 28 characters); the longer "body" belongs in the caption.

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
INTRO, SEG, OUTRO = 2.8, 3.0, 3.4
CHART = (MX, 950, 930, 1415)  # x0, y0, x1, y1 - clear of Instagram's right-hand buttons


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


def header(d, spec):
    f = font("Mono-SemiBold", 23)
    spaced(d, MX, 166, f"TEN ON THE TAPE · {spec['session_short'].upper()} CLOSE", f, rgba(GOLD, 0.95), spacing=3)


def ticker_tape(d, spec, T, current=None):
    """A strip of all ten tickers scrolling right to left, the one on screen boxed in gold."""
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
def intro(spec, t, cover=False):
    im = background()
    d = ImageDraw.Draw(im, "RGBA")
    header(d, spec)
    ticker_tape(d, spec, t)
    day = spec.get("move_label", spec["session_day"])
    hook = spec.get("reel_hook", f"10 STOCKS THAT\nMOVED [{day.upper()}]")
    at = 99 if cover else t
    ix = spec.get("indices") or []
    down = bool(ix) and ix[0]["close"] < ix[0]["prev_close"]
    y = big_headline(d, hook, 330, at, hl=RED if down else GOLD)
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
    im = background()
    d = ImageDraw.Draw(im, "RGBA")
    header(d, spec)
    ticker_tape(d, spec, INTRO + k * SEG + t, current=k)
    e = ease(ramp(t, 0.0, 0.22))
    dx = (1 - e) * 90
    layer = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    L = ImageDraw.Draw(layer)
    f = font("Mono-SemiBold", 26)
    L.text((MX, 318), f"{k + 1:>2}/10", font=f, fill=rgba(GOLD), anchor="lm")
    for j in range(10):
        cx = MX + 110 + j * 22
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
    box = CHART if len(lines) == 1 else (CHART[0], CHART[1] + 60, CHART[2], CHART[3])
    chart(L, s, spec, t, box)
    fine_print(L, f"Sources: {s['sources']}", 1490, ease(ramp(t, 0.5, 0.3)))
    if e < 1:  # slide and fade the card in; the header and tape stay put
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * (0.3 + 0.7 * e))))
    im.paste(layer, (int(dx), 0), layer)
    return im


def outro(spec, t, cover=False):
    im = background()
    d = ImageDraw.Draw(im, "RGBA")
    header(d, spec)
    ticker_tape(d, spec, INTRO + 10 * SEG + t)
    q = spec.get("reel_outro", "WHICH ONE ARE\nYOU [WATCHING]?")
    y = big_headline(d, q, 360, t, hl=GOLD)
    a = ease(ramp(t, 0.45, 0.35))
    d.text((MX, y + 40), "Comment the ticker. All ten are in the caption.", font=font("Inter-Regular", 40), fill=rgba(SOFT, a))
    if spec.get("indices"):
        a2 = ease(ramp(t, 0.8, 0.35))
        yy = y + 170
        d.text((MX, yy), f"THE WHOLE MARKET, {spec['session_day'].upper()}", font=font("Mono-SemiBold", 24), fill=rgba(GOLD, a2), anchor="lm")
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
    tape.validate(spec)
    os.makedirs(out_dir, exist_ok=True)
    total = INTRO + 10 * SEG + OUTRO
    nframes = int(round(total * FPS))
    print(f"finance reel: {total:.1f} s, {nframes} frames")
    fin = Finish(RW, RH, seed=7)

    def frame(i):
        T = i / FPS
        if T < INTRO:
            im = intro(spec, T)
        elif T < INTRO + 10 * SEG:
            k = int((T - INTRO) // SEG)
            im = stock(spec, k, T - INTRO - k * SEG)
        else:
            im = outro(spec, T - INTRO - 10 * SEG)
        return fin.apply(im, i)

    for k in range(10):  # fail fast on text that does not fit
        stock(spec, k, 2.5)
    save_jpg(fin.apply(intro(spec, 2.7, cover=True), 0, handle=False), f"{out_dir}/cover.jpg", quality=92)
    ts = [0.5, 2.6] + [INTRO + k * SEG + x for k in range(10) for x in (0.6, 2.4)] + [INTRO + 10 * SEG + 0.8, total - 0.1]
    thumbs = [frame(int(t * FPS)).resize((RW // 4, RH // 4), Image.LANCZOS) for t in ts]
    cols = 6
    sheet = Image.new("RGB", (cols * RW // 4, math.ceil(len(thumbs) / cols) * RH // 4), (0, 0, 0))
    for i, th in enumerate(thumbs):
        sheet.paste(th, ((i % cols) * RW // 4, (i // cols) * RH // 4))
    sheet.save(f"{out_dir}/_preview.jpg", quality=88)
    if preview:
        return
    raw, wav = f"{out_dir}/_music_raw.wav", f"{out_dir}/_music.wav"
    sfx = [(0.0, "impact", 0.8)] + [(0.45 + i * 0.07, "tick", 0.25) for i in range(0, 10, 3)]
    for k in range(10):
        t0 = INTRO + k * SEG
        sfx += [(t0 - 0.22, "whoosh", 0.65), (t0 + 0.6, "tick", 0.6), (t0 + 1.2, "pop", 0.35)]
    sfx += [(INTRO + 10 * SEG - 0.22, "whoosh", 0.7), (INTRO + 10 * SEG, "impact", 0.6)]
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
