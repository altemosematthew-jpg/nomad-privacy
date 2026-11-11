"""The Gilded Ticker - small shared helpers for the slide and Reel renderers."""
from PIL import Image, ImageFont
import math, os, datetime as _dt
from decimal import Decimal, ROUND_HALF_UP

HERE = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(HERE, "fonts") + os.sep
_cache = {}


def font(name, size):
    """name: Atkinson-Regular/Bold, AtkinsonNext-SemiBold, Barlow-Bold/ExtraBold, Inter-Regular/Medium, Mono-Medium/SemiBold"""
    k = (name, size)
    if k not in _cache:
        _cache[k] = ImageFont.truetype(F + name + ".ttf", size)
    return _cache[k]


def wrap(draw, text, fnt, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=fnt) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_font(draw, text, name, size, maxw, min_size=20):
    """Largest font size <= size at which text fits in maxw on one line."""
    while size > min_size and draw.textlength(text, font=font(name, size)) > maxw:
        size -= 2
    return font(name, size)


def pct_text(p, digits=1):
    """+8.3% / −5.5% with a real minus sign."""
    return ("+" if p >= 0 else "−") + f"{abs(p):.{digits}f}%"


def money(v, digits=2):
    """$12.51 with round-half-up (official closes can carry half cents)."""
    q = Decimal(str(v)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return "$" + f"{q:,.{digits}f}"


def save_jpg(im, path, quality=93):
    """Instagram's publishing API takes JPEG. 4:4:4 chroma keeps thin coloured text crisp."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    im.convert("RGB").save(path, "JPEG", quality=quality, subsampling=0, optimize=True)
    return path


def contact_sheet(paths, out, cols=2, scale=0.5):
    """Tile slides into one preview image for visual QA (look at it with the Read tool)."""
    ims = [Image.open(p).convert("RGB") for p in paths]
    w, h = ims[0].size
    rows = math.ceil(len(ims) / cols)
    sheet = Image.new("RGB", (w * cols, h * rows), (0, 0, 0))
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % cols) * w, (i // cols) * h))
    sheet = sheet.resize((int(w * cols * scale), int(h * rows * scale)))
    sheet.save(out, quality=85)
    return out


def parse_date(s):
    return _dt.datetime.strptime(s, "%Y-%m-%d")
