"""Map-explainer Reel engine, in the style already running on @thegildedticker
("Russia's oil, hit from two sides", "Xi is coming to Washington"): a full-screen dark map that slowly
pushes in, a small date tag, a big condensed headline with one highlighted phrase, a plain subhead,
pins / routes / pulses on the map, a data panel, and a one-word question at the end.

Usage:
  python3 pipeline/reel.py specs/D-reel.json out/D/reel            # full render (video, cover, preview)
  python3 pipeline/reel.py specs/D-reel.json out/D/reel --preview  # cover + preview sheet + layout check only
Outputs: reel.mp4 (1080x1920, 30 fps, H.264 + AAC 48 kHz, -14 LUFS, faststart), cover.jpg, _preview.jpg.
Every run prints a LAYOUT CHECK: text cut off at the screen edge, text in Instagram's caption zone, and
boxes that overlap. Fix every "!!" line before publishing. --strict makes them fatal.

Storyboard: {"title", "seed", "cover_scene": 0, "cover_t": 4.0, "scenes": [ ... ]}
Every scene: dur (seconds) plus any of
  tag, tag_tone ("red"|"amber")             small mono label, top left
  headline "LINE ONE\\nLINE [TWO]"           [..] = highlighted box; hl ("red"|"amber") picks its colour
  sub                                        one or two plain sentences under the headline
  map {bbox [w,s,e,n], bbox_to (optional slow push-in), tint {"SAU": "gold", "IRN": "red"}}
  focus [x0,y0,x1,y1]                        where on screen the bbox sits (default 70,640,1010,1470).
                                             Put it between the text and any panel so the map shows.
  cam "out"                                  fast start to the push-in (good for the hook scene)
  cam_span [t0, t1]                          hold on bbox until t0, move to bbox_to by t1, then hold
                                             (a pull-back reveal: start close on one place, end wide)
  names  [{lon, lat, text}]                  faint country / sea names
  pins   [{lon, lat, text, tone, t, dx, dy, anchor}]
  routes [{points [[lon,lat],...], tone, t0, dur, dash, flow, arc, width}]
  pulses [{lon, lat, tone, t}]               repeating rings (an attack, a hotspot)
  rings  [{lon, lat, r, tone, t, text, text_dy}]  dashed circle around an area; text_dy < 0 puts the label above
  callout {x, y | lon, lat, dx, dy, text, tone, t}  small boxed mono note
  panel  {y, title, t, and ONE of: bars [...], chart {...}, list [...], stat {...}}
  chain  {y, lines [{text, t}]}              centred condensed lines; {red} <amber> ^green^
  src    "SOURCES: ..."                      small mono line near the bottom (y 1500)
  end    {handle, note}                      end card extras
Times are seconds from the start of the scene. Keep important things above y=1560: Instagram's own
buttons and caption cover the bottom of a Reel. Map coordinates are [longitude, latitude].
The music is synthesized from the seed, so every Reel gets its own original track (no licensing).
"""
import sys, json, os, math, subprocess, wave, hashlib, re
import numpy as np
from PIL import Image, ImageDraw
from kit import font, fit_font, save_jpg, HERE

RW, RH, FPS = 1080, 1920, 30
OCEAN = (10, 15, 26)
LAND = (29, 37, 53)
BORDER = (50, 61, 83)
TINT = {"red": (84, 36, 40), "gold": (92, 76, 36), "blue": (34, 54, 90), "grey": (44, 54, 74)}
WHITE = (247, 246, 242)
GREY = (200, 205, 214)
DIM = (104, 116, 138)
REDC = (232, 82, 58)
AMBER = (242, 166, 59)
GREENC = (46, 204, 143)
GOLD = (214, 178, 100)
PANEL = (12, 18, 30)
PANEL_LINE = (62, 74, 98)
TONE = {"red": REDC, "amber": AMBER, "green": GREENC, "gold": GOLD, "white": WHITE, "grey": (150, 160, 178)}
MX = 60
EDGE = 22          # nothing readable closer than this to the left/right edge
SAFE_BOTTOM = 1560  # Instagram's caption and buttons start below this
FOCUS = (70, 640, 1010, 1470)
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def ease(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_io(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def ramp(t, t0, dur):
    return (1.0 if t >= t0 else 0.0) if dur <= 0 else clamp((t - t0) / dur)


def rgba(c, a=1.0):
    return (c[0], c[1], c[2], int(255 * clamp(a)))


# ---------------- map ----------------
_geo = None


def geo():
    global _geo
    if _geo is None:
        _geo = json.load(open(os.path.join(HERE, "geo", "countries50.json")))
    return _geo


def window(bbox, focus=FOCUS):
    """Frame window (centre lon/lat, px per degree of latitude, cos factor) that puts bbox inside focus."""
    w, s, e, n = bbox
    k = math.cos(math.radians((s + n) / 2))
    fx0, fy0, fx1, fy1 = focus
    sc = min((fx1 - fx0) / ((e - w) * k), (fy1 - fy0) / (n - s))
    clon = (w + e) / 2 - ((fx0 + fx1) / 2 - RW / 2) / (k * sc)
    clat = (s + n) / 2 + ((fy0 + fy1) / 2 - RH / 2) / sc
    return clon, clat, sc, k


class MapCam:
    def __init__(self, m, focus=FOCUS):
        a = window(m["bbox"], focus)
        b = window(m.get("bbox_to", m["bbox"]), focus)
        self.a, self.b = a, b
        self.k = (a[3] + b[3]) / 2
        # base map scale: sharp at the tightest view, but never taller than ~4200 px
        self.s = min(max(a[2], b[2]), 4200 * min(a[2], b[2]) / RH)
        ext = []
        for clon, clat, sc, _ in (a, b):
            hw, hh = RW / 2 / (self.k * sc), RH / 2 / sc
            ext.append((clon - hw, clat - hh, clon + hw, clat + hh))
        self.w0 = min(x[0] for x in ext) - 0.5
        self.s0 = min(x[1] for x in ext) - 0.5
        self.e0 = max(x[2] for x in ext) + 0.5
        self.n0 = max(x[3] for x in ext) + 0.5
        size = (int((self.e0 - self.w0) * self.k * self.s), int((self.n0 - self.s0) * self.s))
        im = Image.new("RGB", size, OCEAN)
        d = ImageDraw.Draw(im)
        for lon in range(int(self.w0 // 10) * 10, int(self.e0) + 10, 10):
            d.line([self.bx(lon, self.s0), self.bx(lon, self.n0)], fill=(16, 22, 36), width=2)
        for lat in range(int(self.s0 // 10) * 10, int(self.n0) + 10, 10):
            d.line([self.bx(self.w0, lat), self.bx(self.e0, lat)], fill=(16, 22, 36), width=2)
        tint = m.get("tint", {})
        for c in geo():
            fill = TINT.get(tint.get(c["iso"]), LAND)
            for ring in c["rings"]:
                lons = [p[0] for p in ring]
                lats = [p[1] for p in ring]
                if max(lons) < self.w0 or min(lons) > self.e0 or max(lats) < self.s0 or min(lats) > self.n0:
                    continue
                pts = [self.bx(lo, la) for lo, la in ring]
                d.polygon(pts, fill=fill)
                d.line(pts + [pts[0]], fill=BORDER, width=2)
        self.base = im

    def bx(self, lon, lat):
        return ((lon - self.w0) * self.k * self.s, (self.n0 - lat) * self.s)

    def at(self, p):
        """Camera at progress p (0..1): returns (frame image, function lon/lat -> frame xy)."""
        clon = self.a[0] + (self.b[0] - self.a[0]) * p
        clat = self.a[1] + (self.b[1] - self.a[1]) * p
        sc = self.a[2] * (self.b[2] / self.a[2]) ** p
        cx, cy = self.bx(clon, clat)
        f = self.s / sc
        cw, ch = RW * f, RH * f
        box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        frame = self.base.resize((RW, RH), Image.BICUBIC, box=box)

        def xy(lon, lat):
            x, y = self.bx(lon, lat)
            return ((x - box[0]) / f, (y - box[1]) / f)
        return frame, xy


def smooth(pts, n=12):
    if len(pts) < 3:
        return pts
    P = [pts[0]] + pts + [pts[-1]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for j in range(n):
            u = j / n
            out.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * u + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * u * u
                                    + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * u ** 3) for k in (0, 1)))
    out.append(pts[-1])
    return out


def arc(p, q, bulge=0.22, n=40):
    """Curve from p to q that bows upward on screen by bulge x its length."""
    cx, cy = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2 - math.dist(p, q) * bulge
    return [((1 - u) ** 2 * p[0] + 2 * (1 - u) * u * cx + u * u * q[0], (1 - u) ** 2 * p[1] + 2 * (1 - u) * u * cy + u * u * q[1])
            for u in [i / n for i in range(n + 1)]]


def partial(pts, frac):
    seg = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total = sum(seg)
    need, out, acc = total * clamp(frac), [pts[0]], 0.0
    for i, L in enumerate(seg):
        if acc + L <= need:
            out.append(pts[i + 1])
            acc += L
        else:
            f = (need - acc) / L if L else 0
            out.append((pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f))
            break
    return out, total


def point_at(pts, dist):
    for i in range(len(pts) - 1):
        L = math.dist(pts[i], pts[i + 1])
        if dist <= L:
            f = dist / L if L else 0
            return (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f)
        dist -= L
    return pts[-1]


def dash_line(d, pts, fill, width, dash=22, gap=16):
    total = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    pos = 0.0
    while pos < total:
        a, b = point_at(pts, pos), point_at(pts, min(total, pos + dash))
        d.line([a, b], fill=fill, width=width)
        pos += dash + gap


_glow = {}


def glow(radius, col):
    key = (radius, col)
    if key not in _glow:
        yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
        r = np.sqrt(xx * xx + yy * yy) / radius
        a = np.clip(1 - r, 0, 1) ** 2.2 * 190
        arr = np.zeros((2 * radius + 1, 2 * radius + 1, 4), dtype=np.uint8)
        arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3] = col[0], col[1], col[2], a.astype(np.uint8)
        _glow[key] = Image.fromarray(arr, "RGBA")
    return _glow[key]


# ---------------- text ----------------
def spaced_width(d, text, fnt, spacing):
    return sum(d.textlength(ch, font=fnt) for ch in text) + spacing * (len(text) - 1)


def spaced(d, x, y, text, fnt, fill, spacing=4, anchor="l"):
    total = spaced_width(d, text, fnt, spacing)
    if anchor == "m":
        x -= total / 2
    for ch in text:
        d.text((x, y), ch, font=fnt, fill=fill, anchor="lm")
        x += d.textlength(ch, font=fnt) + spacing
    return total


def segs(line):
    """Split 'OIL IS [DOWN 20%]' / 'OIL {DOWN}' into (text, style) runs."""
    out, cur, style = [], "", "n"
    closing = {"]": "h", "}": "r", ">": "a", "^": "g"}
    for ch in line:
        if ch in "[{<" or (ch == "^" and style != "g"):
            if cur:
                out.append((cur, style))
            cur, style = "", {"[": "h", "{": "r", "<": "a", "^": "g"}[ch]
        elif ch in closing and style == closing[ch]:
            if cur:
                out.append((cur, style))
            cur, style = "", "n"
        else:
            cur += ch
    if cur:
        out.append((cur, style))
    return out


def wrap(d, text, fnt, maxw):
    lines = []
    for part in text.split("\n"):
        cur = ""
        for w in part.split():
            tt = (cur + " " + w).strip()
            if d.textlength(tt, font=fnt) <= maxw:
                cur = tt
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


# ---------------- scene ----------------
SCRIM = None


def scrim():
    global SCRIM
    if SCRIM is None:
        arr = np.zeros((RH, RW, 4), dtype=np.uint8)
        arr[..., 0], arr[..., 1], arr[..., 2] = OCEAN
        ys = np.arange(RH)
        top = np.clip(1 - (ys - 380) / 420, 0, 1) * 0.93
        bot = np.clip((ys - 1560) / 360, 0, 1) * 0.72
        arr[..., 3] = (np.maximum(top, bot) * 255).astype(np.uint8)[:, None]
        SCRIM = Image.fromarray(arr, "RGBA")
    return SCRIM


class Scene:
    def __init__(self, sc):
        self.sc = sc
        self.dur = float(sc["dur"])
        self.cam = MapCam(sc["map"], tuple(sc.get("focus", FOCUS)))
        self.boxes = None

    # layout bookkeeping for the checker
    def reg(self, kind, box, label="", a=1.0):
        if self.boxes is not None:
            self.boxes.append((kind, tuple(float(v) for v in box), label, a))

    def headline(self, d, t, y):
        sc = self.sc
        hl = TONE[sc.get("hl", "red")]
        size = sc.get("headline_size", 118)
        plain = ["".join(tx for tx, _ in segs(ln)) for ln in sc["headline"].split("\n")]
        while size > 70 and max(d.textlength(ln, font=font("Barlow-ExtraBold", size)) for ln in plain) > RW - 2 * MX - 14:
            size -= 2
        fnt = font("Barlow-ExtraBold", size)
        lh = int(size * 0.98)
        for i, line in enumerate(sc["headline"].split("\n")):
            a = ease(ramp(t, 0.05 + i * 0.13, 0.28))
            w_all = d.textlength(plain[i], font=fnt)
            self.reg("headline", (MX - 12, y + size * 0.13, MX + w_all + 12, y + size * 1.03), plain[i])
            if a <= 0:
                y += lh
                continue
            yy = y + (1 - a) * 26
            x = MX
            for txt, st in segs(line):
                w = d.textlength(txt, font=fnt)
                if st == "h":
                    g = ease(ramp(t, 0.42 + i * 0.13, 0.3))
                    if g > 0:
                        d.rectangle([x - 12, yy + size * 0.13, x - 12 + (w + 24) * g, yy + size * 1.03], fill=rgba(hl, a))
                    dark = sc.get("hl", "red") == "amber" and g > 0.5
                    d.text((x, yy), txt, font=fnt, fill=rgba((16, 20, 30) if dark else WHITE, a))
                else:
                    d.text((x, yy), txt, font=fnt, fill=rgba({"r": REDC, "a": AMBER, "g": GREENC}.get(st, WHITE), a))
                x += w
            y += lh
        return y

    def label(self, d, x, y, text, fnt, a, anchor="lm", kind="pin", stroke=5, fill=WHITE, line_h=None):
        """Multi-line label that never runs off the side of the frame."""
        lines = text.split("\n")
        line_h = line_h or int(fnt.size * 1.25)
        w = max(d.textlength(ln, font=fnt) for ln in lines)
        if anchor[0] == "l":
            x0 = x
        elif anchor[0] == "r":
            x0 = x - w
        else:
            x0 = x - w / 2
        x0 = clamp(x0, EDGE, RW - EDGE - w)
        if a > 0:
            for i, ln in enumerate(lines):
                d.text((x0, y + i * line_h), ln, font=fnt, fill=rgba(fill, a), anchor="l" + anchor[1],
                       stroke_width=stroke, stroke_fill=rgba(OCEAN, a))
        asc = fnt.size * 0.62
        self.reg(kind, (x0, y - asc, x0 + w, y + (len(lines) - 1) * line_h + asc), lines[0], a)

    def panel(self, d, t):
        sc = self.sc
        p = sc["panel"]
        x0, x1 = MX, RW - MX
        head = 44 + (50 if p.get("title") else 0)
        rows, notes, nf = None, None, None
        if "list" in p:
            rows = []
            for it in p["list"]:
                fnt = font("Inter-Medium", it.get("size", 44))
                lh = int(it.get("size", 44) * 1.28)
                lines = wrap(d, it["text"], fnt, x1 - x0 - 34 - 34 - 46)
                rows.append((it, fnt, lh, lines, (46 if it.get("kicker") else 0) + len(lines) * lh + 36))
            h = head + sum(r[4] for r in rows) + 4
        elif "stat" in p:
            s = p["stat"]
            nf = font("Inter-Medium", s.get("notes_size", 36))
            notes = [wrap(d, n_, nf, x1 - x0 - 68 - 46) for n_ in s.get("notes", [])]
            h = head + int(s.get("size", 200) * 0.95) + (30 + sum(len(n_) * 46 + 22 for n_ in notes) if notes else 0) + 24
        elif "bars" in p:
            h = head + 118 * len(p["bars"]) + (60 if p.get("note") else 0) + 10
        else:
            h = p.get("h", 420)
        a = ease(ramp(t, p.get("t", 0.8), 0.35))
        self.reg("panel", (x0, p["y"], x1, p["y"] + h), p.get("title", "panel"), a)
        if a <= 0:
            return
        y0 = p["y"] + (1 - a) * 24
        d.rounded_rectangle([x0, y0, x1, y0 + h], radius=18, fill=rgba(PANEL, 0.90 * a), outline=rgba(PANEL_LINE, a), width=2)
        tt = t - p.get("t", 0.8)
        y = y0 + 44
        if p.get("title"):
            spaced(d, x0 + 34, y, p["title"].upper(), font("Mono-SemiBold", 22), rgba(GREY, a), spacing=2)
            y += 50
        if "bars" in p:
            maxw = x1 - x0 - 68 - 250
            for i, b in enumerate(p["bars"]):
                g = ease_io(ramp(tt, 0.25 + i * 0.35, 0.7))
                spaced(d, x0 + 34, y + 4, b["label"].upper(), font("Mono-Medium", 22), rgba(GREY, a), spacing=2)
                col = TONE[b.get("tone", "grey")]
                bw = max(6, maxw * b["frac"] * g)
                d.rectangle([x0 + 34, y + 30, x0 + 34 + bw, y + 78], fill=rgba(col, a))
                d.text((x0 + 34 + bw + 20, y + 54), b["value"], font=font("Barlow-Bold", 56),
                       fill=rgba(WHITE if b.get("tone", "grey") == "grey" else col, a * g), anchor="lm")
                y += 118
            if p.get("note"):
                fnt = font("Mono-SemiBold", 22)
                txt = p["note"].upper()
                w = spaced_width(d, txt, fnt, 2) + 28
                g = ease(ramp(tt, 1.4, 0.3))
                d.rounded_rectangle([x0 + 34, y, x0 + 34 + w, y + 42], radius=6, fill=rgba(TONE[p.get("note_tone", "red")], a * g))
                spaced(d, x0 + 48, y + 21, txt, fnt, rgba((16, 20, 30), a * g), spacing=2)
        elif "chart" in p:
            c = p["chart"]
            vals = [float(v) for _, v in c["series"]]
            dates = [ds for ds, _ in c["series"]]
            cx0, cx1, cy0, cy1 = x0 + 112, x1 - 60, y + 64, y0 + h - 76
            lo, hi = min(vals), max(vals)
            pad = (hi - lo) * 0.12 or 1
            lo, hi = lo - pad, hi + pad
            n = len(vals)
            X = lambda i: cx0 + (cx1 - cx0) * i / (n - 1)
            Y = lambda v: cy1 - (cy1 - cy0) * (v - lo) / (hi - lo)
            for k in range(4):
                v = lo + (hi - lo) * (k + 0.5) / 4
                d.line([cx0, Y(v), cx1, Y(v)], fill=rgba((34, 44, 62), a), width=2)
                d.text((cx0 - 16, Y(v)), f"${v:,.0f}", font=font("Mono-Medium", 24), fill=rgba(DIM, a), anchor="rm")
            last_m = dates[0][:7]
            d.text((X(0), cy1 + 34), MONTHS[int(dates[0][5:7]) - 1], font=font("Mono-Medium", 24), fill=rgba(DIM, a), anchor="lm")
            for i, ds in enumerate(dates):
                if ds[:7] != last_m:
                    last_m = ds[:7]
                    d.text((X(i), cy1 + 34), MONTHS[int(ds[5:7]) - 1], font=font("Mono-Medium", 24), fill=rgba(DIM, a), anchor="mm")
            g = ease_io(ramp(tt, c.get("t0", 0.4), c.get("dur", 2.6)))
            col = TONE[c.get("tone", "red")]
            if g > 0:
                f = g * (n - 1)
                k = int(f)
                pts = [(X(i), Y(vals[i])) for i in range(k + 1)]
                if k < n - 1:
                    fr = f - k
                    pts.append((X(k) + (X(k + 1) - X(k)) * fr, Y(vals[k] + (vals[k + 1] - vals[k]) * fr)))
                if len(pts) > 1:
                    d.polygon(pts + [(pts[-1][0], cy1), (pts[0][0], cy1)], fill=rgba(col, 0.16 * a))
                    d.line(pts, fill=rgba(col, a), width=8, joint="curve")
                ex, ey = pts[-1]
                d.ellipse([ex - 13, ey - 13, ex + 13, ey + 13], fill=rgba(col, a), outline=rgba(PANEL, a), width=4)
            for mk in c.get("marks", []):  # boxed price + date, appears when the line gets there
                i = dates.index(mk["date"])
                if g * (n - 1) >= i - 0.01:
                    fnt = font("Barlow-Bold", 46)
                    tw = d.textlength(mk["text"], font=fnt)
                    bx = clamp(X(i) + mk.get("dx", 0), x0 + 30 + tw / 2 + 14, x1 - 30 - tw / 2 - 14)
                    by = Y(vals[i]) + mk.get("dy", -56)
                    d.rounded_rectangle([bx - tw / 2 - 14, by - 31, bx + tw / 2 + 14, by + 29], radius=7, fill=rgba(TONE[mk.get("tone", "white")], a))
                    d.text((bx, by - 2), mk["text"], font=fnt, fill=rgba((16, 20, 30), a), anchor="mm")
        elif "list" in p:
            for i, (it, fnt, lh, lines, ih) in enumerate(rows):
                g = ease(ramp(t, it.get("t", p.get("t", 0.8) + 0.3 + i * 1.6), 0.35))
                if g > 0:
                    xx = x0 + 34 + (1 - g) * 40
                    col = TONE[it.get("tone", "amber")]
                    d.rectangle([xx, y + 6, xx + 20, y + 26], fill=rgba(col, a * g))
                    yy = y - 10
                    if it.get("kicker"):
                        spaced(d, xx + 46, y + 16, it["kicker"].upper(), font("Mono-SemiBold", 24), rgba(col, a * g), spacing=3)
                        yy = y + 40
                    for ln in lines:
                        d.text((xx + 46, yy), ln, font=fnt, fill=rgba(WHITE, a * g))
                        yy += lh
                y += ih
        elif "stat" in p:
            s = p["stat"]
            g = ease(ramp(tt, 0.3, 0.9))
            col = TONE[s.get("tone", "amber")]
            size = s.get("size", 200)
            full = s["text"] if "value" not in s else f"{s.get('prefix', '')}{s['value']:,.{s.get('decimals', 0)}f}{s.get('suffix', '')}"
            txt = s["text"] if "value" not in s else f"{s.get('prefix', '')}{s['value'] * g:,.{s.get('decimals', 0)}f}{s.get('suffix', '')}"
            fnt = font("Barlow-ExtraBold", size)
            d.text((x0 + 30, y + size * 0.42), txt, font=fnt, fill=rgba(col, a), anchor="lm")
            tw = d.textlength(full, font=fnt)
            lf = font("Inter-Medium", 40)
            lines = wrap(d, s["label"], lf, x1 - x0 - 34 - tw - 70)
            yy = y + size * 0.42 - len(lines) * 26
            for ln in lines:
                d.text((x0 + 30 + tw + 36, yy), ln, font=lf, fill=rgba(WHITE, a * ease(ramp(tt, 0.5, 0.4))))
                yy += 52
            y += int(size * 0.95)
            if notes:
                d.line([x0 + 34, y, x1 - 34, y], fill=rgba(PANEL_LINE, a), width=2)
                y += 30
                for j, nl in enumerate(notes):
                    g2 = ease(ramp(tt, s.get("notes_t", 2.2) + j * s.get("notes_gap", 1.4), 0.35))
                    if g2 > 0:
                        d.rectangle([x0 + 34, y + 12, x0 + 54, y + 32], fill=rgba(col, a * g2))
                        for k2, ln in enumerate(nl):
                            d.text((x0 + 80, y + k2 * 46), ln, font=nf, fill=rgba(WHITE, a * g2))
                    y += len(nl) * 46 + 22

    def render(self, t, top=150, cover=False):
        sc = self.sc
        span = sc.get("cam_span")
        if span:
            p = ease_io(ramp(t, span[0], span[1] - span[0]))
        elif sc.get("cam") == "out":
            p = ease(t / self.dur)
        else:
            p = ease_io(t / self.dur)
        frame, xy = self.cam.at(p)
        ui = scrim().copy()
        d = ImageDraw.Draw(ui)
        for nm in sc.get("names", []):
            x, y = xy(nm["lon"], nm["lat"])
            fnt = font("Mono-Medium", nm.get("size", 22))
            txt = nm["text"].upper()
            w = spaced_width(d, txt, fnt, 6)
            x = clamp(x, EDGE + w / 2, RW - EDGE - w / 2)
            a = 0.85 * clamp((y - nm.get("min_y", 470)) / 70) * clamp((1520 - y) / 70)
            if a > 0.02:
                spaced(d, x, y, txt, fnt, rgba(DIM, a), spacing=6, anchor="m")
            self.reg("name", (x - w / 2, y - 12, x + w / 2, y + 12), txt, a)
        for rg in sc.get("rings", []):
            a = ease(ramp(t, rg.get("t", 0), 0.4))
            x, y = xy(rg["lon"], rg["lat"])
            r = rg.get("r", 70)
            if a > 0:
                col = TONE[rg.get("tone", "red")]
                n = 26
                for i in range(n):
                    if i % 2 == 0:
                        a0 = 360 / n * i + t * 16
                        d.arc([x - r, y - r, x + r, y + r], a0, a0 + 360 / n * 0.95, fill=rgba(col, a), width=6)
            if rg.get("text"):
                fnt = font("Mono-SemiBold", 24)
                txt = rg["text"].upper()
                w = spaced_width(d, txt, fnt, 3)
                ty = y + (rg["text_dy"] if "text_dy" in rg else r + 34)
                cx = clamp(x, EDGE + w / 2, RW - EDGE - w / 2)
                if a > 0:
                    spaced(d, cx, ty, txt, fnt, rgba(WHITE, a), spacing=3, anchor="m")
                self.reg("ring", (cx - w / 2, ty - 14, cx + w / 2, ty + 14), txt, a)
        for r in sc.get("routes", []):
            g = ease_io(ramp(t, r.get("t0", 0), r.get("dur", 1.5)))
            if g <= 0:
                continue
            pts = [xy(lo, la) for lo, la in r["points"]]
            pts = arc(pts[0], pts[-1], r["arc"]) if r.get("arc") else smooth(pts)
            col = TONE[r.get("tone", "gold")]
            part, total = partial(pts, g)
            if len(part) > 1:
                if r.get("dash"):
                    dash_line(d, part, rgba(col, 0.95), r.get("width", 6))
                else:
                    d.line(part, fill=rgba(col, 0.28), width=r.get("width", 9) + 12, joint="curve")
                    d.line(part, fill=rgba(col), width=r.get("width", 9), joint="curve")
                hx, hy = part[-1]
                if g < 1:
                    d.ellipse([hx - 9, hy - 9, hx + 9, hy + 9], fill=rgba(WHITE))
            if r.get("flow") and g >= 1:
                n = r.get("flow_n", 7)
                for i in range(n):
                    dist = (t * r.get("flow_speed", 140) + i * total / n) % total
                    px, py = point_at(pts, total - dist if r.get("flow_dir", 1) < 0 else dist)
                    d.ellipse([px - 7, py - 7, px + 7, py + 7], fill=rgba(WHITE))
        for pz in sc.get("pulses", []):
            tt = t - pz.get("t", 0)
            if tt < 0:
                continue
            x, y = xy(pz["lon"], pz["lat"])
            col = TONE[pz.get("tone", "red")]
            gl = glow(pz.get("glow", 120), col)
            ui.alpha_composite(gl, (int(x - gl.size[0] / 2), int(y - gl.size[1] / 2)))
            d = ImageDraw.Draw(ui)
            for k in range(3):
                ph = ((tt * 0.85) + k / 3) % 1.0
                rr = 16 + 100 * ph
                d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=rgba(col, (1 - ph) * 0.9), width=5)
            r0 = 14 * ease(ramp(tt, 0, 0.25))
            d.ellipse([x - r0, y - r0, x + r0, y + r0], fill=rgba(col), outline=rgba(WHITE), width=3)
        for pn in sc.get("pins", []):
            a = ease(ramp(t, pn.get("t", 0), 0.3))
            x, y = xy(pn["lon"], pn["lat"])
            if a > 0:
                col = TONE[pn.get("tone", "gold")]
                if pn.get("glow", True):
                    gl = glow(46, col)
                    ui.alpha_composite(gl, (int(x - gl.size[0] / 2), int(y - gl.size[1] / 2)))
                    d = ImageDraw.Draw(ui)
                d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=rgba(col, a), outline=rgba(WHITE, a), width=3)
            if pn.get("text"):
                fnt = font("Mono-SemiBold", pn.get("size", 24))
                self.label(d, x + pn.get("dx", 18), y + pn.get("dy", 0), pn["text"].upper(), fnt, a, anchor=pn.get("anchor", "lm"))
        co = None if cover else sc.get("callout")
        if co:
            a = ease(ramp(t, co.get("t", 1.0), 0.3))
            fnt = font("Mono-SemiBold", 23)
            lines = co["text"].upper().split("\n")
            w = max(d.textlength(ln, font=fnt) for ln in lines) + 40
            h = 30 * len(lines) + 28
            if "lon" in co:
                cx, cy = xy(co["lon"], co["lat"])
                cx, cy = cx + co.get("dx", 0), cy + co.get("dy", 70)
            else:
                cx, cy = co["x"], co["y"]
            cx = clamp(cx, MX, RW - MX - w)
            self.reg("callout", (cx, cy, cx + w, cy + h), lines[0], a)
            if a > 0:
                col = TONE[co.get("tone", "red")]
                d.rounded_rectangle([cx, cy, cx + w, cy + h], radius=8, fill=rgba(PANEL, 0.92 * a), outline=rgba(col, a), width=2)
                for i, ln in enumerate(lines):
                    d.text((cx + 20, cy + 14 + i * 30), ln, font=fnt, fill=rgba(WHITE, a))
        # --- top text block ---
        y = top
        if sc.get("tag"):
            a = ease(ramp(t, 0, 0.25))
            fnt = font("Mono-SemiBold", 24)
            txt = sc["tag"].upper()
            w = spaced_width(d, txt, fnt, 3) + 32
            d.rounded_rectangle([MX, y, MX + w, y + 46], radius=5, fill=rgba(TONE[sc.get("tag_tone", "red")], a))
            spaced(d, MX + 16, y + 23, txt, fnt, rgba((16, 20, 30), a), spacing=3)
            self.reg("tag", (MX, y, MX + w, y + 46), txt)
            y += 46 + 20
        if sc.get("headline"):
            y = self.headline(d, t, y) + 22
        if sc.get("sub") and not (cover and sc.get("cover_hide_sub")):
            a = ease(ramp(t, 0.55, 0.4))
            size = sc.get("sub_size", 39)
            fnt = font("Inter-Regular", size)
            for ln in wrap(d, sc["sub"], fnt, RW - 2 * MX - 30):
                d.text((MX, y), ln, font=fnt, fill=rgba(GREY, a))
                self.reg("sub", (MX, y + size * 0.15, MX + d.textlength(ln, font=fnt), y + size * 1.15), ln)
                y += int(size * 1.36)
        if sc.get("panel"):
            self.panel(d, t)
        ch = sc.get("chain")
        if ch:
            yy = ch["y"]
            fnt = font("Barlow-Bold", ch.get("size", 72))
            for ln in ch["lines"]:
                a = ease(ramp(t, ln.get("t", 0), 0.3))
                runs = segs(ln["text"])
                total = sum(d.textlength(tx, font=fnt) for tx, _ in runs)
                x = (RW - total) / 2
                self.reg("chain", (x, yy - fnt.size * 0.5, x + total, yy + fnt.size * 0.5), ln["text"])
                if a > 0:
                    for tx, st in runs:
                        d.text((x, yy + (1 - a) * 18), tx, font=fnt, fill=rgba({"r": REDC, "a": AMBER, "g": GREENC, "h": AMBER}.get(st, WHITE), a),
                               anchor="lm", stroke_width=6, stroke_fill=rgba(OCEAN, a))
                        x += d.textlength(tx, font=fnt)
                yy += int(ch.get("size", 72) * 1.22)
        en = sc.get("end")
        if en:
            a = ease(ramp(t, en.get("t", 1.6), 0.4))
            ey = en.get("y", 1330)
            f1, f2 = font("Barlow-Bold", 64), font("Inter-Medium", 36)
            handle, note = en.get("handle", "@thegildedticker"), en.get("note", "Follow for the next chapter")
            w1, w2 = d.textlength(handle, font=f1), d.textlength(note, font=f2)
            self.reg("end", (RW / 2 - w1 / 2, ey - 36, RW / 2 + w1 / 2, ey + 36), handle)
            self.reg("end", (RW / 2 - w2 / 2, ey + 50, RW / 2 + w2 / 2, ey + 90), note)
            if a > 0:
                d.text((RW / 2, ey), handle, font=f1, fill=rgba(GOLD, a), anchor="mm", stroke_width=6, stroke_fill=rgba(OCEAN, a))
                d.text((RW / 2, ey + 70), note, font=f2, fill=rgba(WHITE, a), anchor="mm", stroke_width=5, stroke_fill=rgba(OCEAN, a))
        if sc.get("src") and not cover:
            a = ease(ramp(t, 0.6, 0.4))
            txt = sc["src"].upper()
            fnt = fit_font(d, txt + " " * 6, "Mono-Medium", 20, RW - 2 * MX - 2 * len(txt), min_size=14)
            w = spaced_width(d, txt, fnt, 2)
            spaced(d, MX, 1500, txt, fnt, rgba(GREY, 0.9 * a), spacing=2)
            self.reg("src", (MX, 1500 - 12, MX + w, 1500 + 12), txt)
        out = frame.convert("RGBA")
        out.alpha_composite(ui)
        return out.convert("RGB")


# ---------------- layout check ----------------
IMPORTANT = {"tag", "headline", "sub", "panel", "callout", "pin", "ring", "chain", "end", "src"}
BLOCKS = {"tag", "headline", "sub", "panel", "callout", "chain", "end", "src"}


def overlap(a, b, m=3):
    return min(a[2], b[2]) - max(a[0], b[0]) > m and min(a[3], b[3]) - max(a[1], b[1]) > m


def layout_issues(boxes, label):
    issues = []
    boxes = [b for b in boxes if b[3] >= 0.3]  # only what is clearly visible at that moment
    for kind, b, txt, _ in boxes:
        if kind in IMPORTANT and (b[0] < EDGE - 4 or b[2] > RW - EDGE + 4):
            issues.append(f"{label}: {kind} '{txt[:40]}' is cut off at the side ({b[0]:.0f}..{b[2]:.0f})")
        if kind in IMPORTANT and b[3] > SAFE_BOTTOM:
            issues.append(f"{label}: {kind} '{txt[:40]}' sits in Instagram's caption zone (bottom {b[3]:.0f} > {SAFE_BOTTOM})")
        if kind in IMPORTANT and b[1] < 120:
            issues.append(f"{label}: {kind} '{txt[:40]}' is too close to the top (y {b[1]:.0f})")
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (k1, b1, t1, _), (k2, b2, t2, _) = boxes[i], boxes[j]
            if not overlap(b1, b2):
                continue
            pair = {k1, k2}
            if k1 == k2 and k1 in ("headline", "sub"):
                continue
            if pair <= BLOCKS and k1 != k2:
                issues.append(f"{label}: {k1} '{t1[:30]}' overlaps {k2} '{t2[:30]}'")
            elif "pin" in pair and (pair - {"pin"}) & (BLOCKS | {"ring"}):
                issues.append(f"{label}: pin label overlaps {k1 if k2 == 'pin' else k2} ('{t1[:24]}' / '{t2[:24]}')")
            elif k1 == k2 == "pin":
                issues.append(f"{label}: two pin labels overlap ('{t1[:24]}' / '{t2[:24]}')")
            elif "ring" in pair and (pair - {"ring"}) & BLOCKS:
                issues.append(f"{label}: ring label overlaps {k1 if k2 == 'ring' else k2} ('{t1[:24]}' / '{t2[:24]}')")
            elif "name" in pair and (pair - {"name"}) & (BLOCKS | {"pin", "ring"}):
                issues.append(f"{label}: map name '{t1 if k1 == 'name' else t2}' is hidden behind {k2 if k1 == 'name' else k1} '{(t2 if k1 == 'name' else t1)[:24]}'")
    return issues


def check_layout(scene, label, t=None, top=150, cover=False, step=0.5):
    """Render the scene every `step` seconds (or once at t) and list layout problems, each once, with when it starts."""
    times = [t] if t is not None else [x * step for x in range(1, int(scene.dur / step) + 1)] + [scene.dur - 0.05]
    found = {}
    for tt in times:
        scene.boxes = []
        scene.render(min(tt, scene.dur - 0.05), top=top, cover=cover)
        for msg in layout_issues(scene.boxes, label):
            found.setdefault(msg, tt)
        scene.boxes = None
    return [f"{msg} (from {tt:.1f} s)" if t is None else msg for msg, tt in found.items()]


# ---------------- music ----------------
def make_music(path, dur, hits, seed="gt", sr=44100):
    rng = np.random.default_rng(int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16))
    n = int(dur * sr)
    tt = np.arange(n) / sr
    bpm = int(rng.choice([88, 92, 96, 100]))
    beat = 60 / bpm
    root = float(rng.choice([43.65, 46.25, 49.0, 55.0]))  # F1, F#1, G1, A1
    progs = [[0, -4, -2, -5], [0, 3, -2, -4], [0, -2, -4, -2], [0, 5, 3, -2]]
    prog = progs[int(rng.integers(len(progs)))]
    L, R = np.zeros(n), np.zeros(n)
    bar = beat * 4
    for b in range(int(dur / bar) + 1):
        f0 = root * 2 ** (prog[b % 4] / 12)
        i0, i1 = int(b * bar * sr), min(n, int((b + 1) * bar * sr))
        if i0 >= n:
            break
        seg = tt[i0:i1] - b * bar
        env = np.minimum(1, seg / 0.6) * np.minimum(1, (bar - seg) / 0.5)
        for ratio in (2, 2 * 2 ** (3 / 12), 2 * 2 ** (7 / 12), 4):  # minor-chord pad, detuned left / right
            for h, amp in ((1, 1.0), (2, 0.28), (3, 0.12)):
                L[i0:i1] += 0.030 * amp * env * np.sin(2 * np.pi * f0 * ratio * h * 1.002 * seg)
                R[i0:i1] += 0.030 * amp * env * np.sin(2 * np.pi * f0 * ratio * h * 0.998 * seg + 0.6)
        for k in range(4):
            j0 = int((b * bar + k * beat) * sr)
            j1 = min(n, j0 + int(beat * sr))
            if j0 >= n:
                break
            s = np.arange(j1 - j0) / sr
            bass = 0.22 * np.exp(-s * 3.2) * np.sin(2 * np.pi * f0 * s + 0.6 * np.sin(2 * np.pi * f0 * 2 * s))
            L[j0:j1] += bass
            R[j0:j1] += bass
            if k in (0, 2):
                kl = min(j1 - j0, int(0.22 * sr))
                ks = np.arange(kl) / sr
                kick = 0.30 * np.exp(-ks * 16) * np.sin(2 * np.pi * (48 * ks + 70 * (1 - np.exp(-ks * 28)) / 28))
                L[j0:j0 + kl] += kick
                R[j0:j0 + kl] += kick
            for e in (0, 0.5):
                h0 = int((b * bar + (k + e) * beat) * sr)
                hl = int(0.045 * sr)
                if h0 + hl < n:
                    nz = np.diff(rng.standard_normal(hl) * np.exp(-np.arange(hl) / sr * 90), prepend=0)
                    g = 0.035 if e == 0 else 0.022
                    L[h0:h0 + hl] += g * nz
                    R[h0:h0 + hl] += g * nz * 0.8
    for ht in hits:  # riser into every scene change, then a low impact
        i0 = int(ht * sr)
        r0 = max(0, i0 - int(0.7 * sr))
        m = i0 - r0
        if m > 0:
            sw = np.cumsum(rng.standard_normal(m)) / 40
            sw -= sw.mean()
            rise = 0.05 * (np.arange(m) / m) ** 3 * np.diff(sw, prepend=0) * 30
            L[r0:i0] += rise
            R[r0:i0] += rise
        il = min(n - i0, int(1.1 * sr))
        if il > 0:
            s = np.arange(il) / sr
            boom = 0.5 * np.exp(-s * 4.5) * np.sin(2 * np.pi * (34 * s + 55 * (1 - np.exp(-s * 9)) / 9)) + 0.10 * rng.standard_normal(il) * np.exp(-s * 22)
            L[i0:i0 + il] += boom
            R[i0:i0 + il] += boom
    fade = np.minimum(1, tt / 0.25) * np.minimum(1, (dur - tt) / 1.4)
    st = np.tanh(np.stack([L, R], axis=1) * fade[:, None] * 1.6) / np.tanh(1.6)
    st = st / np.abs(st).max() * 0.80
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((st * 32767).astype("<i2").tobytes())
    return path


def loudnorm(src, dst, target=-14.0, tp=-1.5, lra=11.0):
    """Two-pass EBU R128 normalisation so every Reel plays at the same loudness (Instagram targets about -14 LUFS)."""
    f = f"loudnorm=I={target}:TP={tp}:LRA={lra}"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", src, "-af", f + ":print_format=json", "-f", "null", "-"], capture_output=True, text=True)
    m = json.loads(re.findall(r"\{[^{}]*\}", r.stderr)[-1])
    f2 = (f + f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
          f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-af", f2, "-ar", "48000", dst], check=True)
    return float(m["input_i"])


# ---------------- render ----------------
def build(spec_path, out_dir, preview=False, strict=False):
    sb = json.load(open(spec_path))
    os.makedirs(out_dir, exist_ok=True)
    scenes = [Scene(s) for s in sb["scenes"]]
    starts, acc = [], 0.0
    for s in scenes:
        starts.append(acc)
        acc += s.dur
    total = acc
    nframes = int(round(total * FPS))
    print(f"{len(scenes)} scenes, {total:.1f} s, {nframes} frames")
    if not 45 <= total <= 62:
        print(f"!! total length {total:.1f} s is outside 45-62 s")

    ci = sb.get("cover_scene", 0)
    cover_top = sb.get("cover_top", 340)
    issues = []
    for i, s in enumerate(scenes):
        issues += check_layout(s, f"scene {i + 1} ({s.sc.get('tag', '')})")
    issues += check_layout(scenes[ci], "cover", t=min(scenes[ci].dur - 0.05, sb.get("cover_t", 4.0)), top=cover_top, cover=True)
    print("LAYOUT CHECK: " + ("ok" if not issues else f"{len(issues)} problem(s)"))
    for x in issues:
        print("  !! " + x)
    if strict and issues:
        raise SystemExit("layout problems (see above)")

    def frame(i):
        T = i / FPS
        k = max(j for j in range(len(scenes)) if starts[j] <= T + 1e-9)
        im = scenes[k].render(T - starts[k])
        fi = (T - starts[k]) * FPS
        if k > 0 and fi < 3:  # 3-frame dip to dark on each cut
            im = Image.blend(Image.new("RGB", (RW, RH), OCEAN), im, (fi + 1) / 4)
        return im

    # the profile grid crops covers to the middle of the frame, so the cover's text block starts lower
    save_jpg(scenes[ci].render(min(scenes[ci].dur - 0.05, sb.get("cover_t", 4.0)), top=cover_top, cover=True), f"{out_dir}/cover.jpg", quality=92)
    ts = []
    for s0, s in zip(starts, scenes):
        ts += [s0 + 0.5, s0 + s.dur * 0.55, s0 + s.dur - 0.1]
    thumbs = [frame(int(t * FPS)).resize((RW // 4, RH // 4), Image.LANCZOS) for t in ts]
    cols = 6
    sheet = Image.new("RGB", (cols * RW // 4, math.ceil(len(thumbs) / cols) * RH // 4), (0, 0, 0))
    for i, th in enumerate(thumbs):
        sheet.paste(th, ((i % cols) * RW // 4, (i // cols) * RH // 4))
    sheet.save(f"{out_dir}/_preview.jpg", quality=88)
    if preview:
        return issues
    raw = f"{out_dir}/_music_raw.wav"
    wav = f"{out_dir}/_music.wav"
    make_music(raw, total, starts[1:] + sb.get("extra_hits", []), seed=str(sb.get("seed", sb.get("title", "gt"))))
    li = loudnorm(raw, wav)
    print(f"music: {li:.1f} LUFS -> -14 LUFS")
    mp4 = f"{out_dir}/reel.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RW}x{RH}", "-r", str(FPS), "-i", "-",
           "-i", wav, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-g", str(FPS * 2), "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-shortest", "-movflags", "+faststart",
           "-use_editlist", "0", mp4]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(nframes):
        p.stdin.write(frame(i).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise SystemExit("ffmpeg failed")
    print("wrote", mp4, os.path.getsize(mp4) // 1024, "KB")
    return issues


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], preview="--preview" in sys.argv, strict="--strict" in sys.argv)
