"""Finishing touches shared by both Reels: film grain, a soft vignette, a small handle bug, and sound effects.

Perfectly clean vector frames and a music bed that ignores the edit are what make a video read as machine-made.
A little texture on the picture and sounds that land on the cuts, pins and numbers make it read as an edited show.

  fin = Finish(1080, 1920)            # once per video
  frame = fin.apply(frame, i)         # every frame (i = frame number, picks the grain plate)
  L, R = add_sfx(L, R, sr, [(t, "whoosh"), (t, "tick"), (t, "pop"), (t, "impact")])
"""
import numpy as np
from PIL import Image, ImageDraw
from kit import font


class Finish:
    def __init__(self, w, h, grain=3.5, vignette=0.24, seed=11, plates=1, handle="@THEGILDEDTICKER", handle_xy=None):
        rng = np.random.default_rng(seed)
        ys = (np.arange(h) - h / 2) / (h / 2)
        xs = (np.arange(w) - w / 2) / (w / 2)
        r2 = 0.8 * ys[:, None] ** 2 + xs[None, :] ** 2
        self.vig = (1.0 - vignette * np.clip(r2 - 0.30, 0, None) / 1.5).astype(np.float32)[..., None]
        self.plates = []
        for _ in range(plates):  # grain drawn at half size and scaled up; one still plate keeps files small (moving grain made them 8x bigger)
            n = rng.standard_normal((h // 2 + 1, w // 2 + 1)).astype(np.float32) * grain
            self.plates.append(np.repeat(np.repeat(n, 2, axis=0), 2, axis=1)[:h, :w][..., None])
        self.w, self.h = w, h
        self.handle = handle
        self.handle_xy = handle_xy or (w - 60, 173)

    def apply(self, im, i, handle=True):
        if handle and self.handle:
            im = im.copy()
            d = ImageDraw.Draw(im, "RGBA")
            d.text(self.handle_xy, self.handle, font=font("Mono-Medium", 21), fill=(214, 178, 100, 150), anchor="rm")
        a = np.asarray(im, dtype=np.float32)
        a = a * self.vig + self.plates[i % len(self.plates)]
        return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


# ---------------- sound effects ----------------
def _whoosh(sr, rng, dur=0.42):
    n = int(dur * sr)
    t = np.arange(n) / sr
    noise = rng.standard_normal(n)
    out = np.zeros(n)
    y = 0.0
    for k in range(n):  # one-pole low-pass whose cutoff sweeps up then down: air moving past
        c = 0.02 + 0.30 * np.sin(np.pi * k / n) ** 2
        y += c * (noise[k] - y)
        out[k] = y
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
    return 0.55 * out * env


def _tick(sr, rng):
    n = int(0.05 * sr)
    t = np.arange(n) / sr
    return 0.22 * np.exp(-t * 90) * np.sin(2 * np.pi * 2600 * t) + 0.25 * np.exp(-t * 60) * np.sin(2 * np.pi * 180 * t)


def _pop(sr, rng):
    n = int(0.09 * sr)
    t = np.arange(n) / sr
    f = 1100 * np.exp(-t * 14) + 520
    return 0.20 * np.exp(-t * 38) * np.sin(2 * np.pi * np.cumsum(f) / sr)


def _impact(sr, rng):
    n = int(0.9 * sr)
    t = np.arange(n) / sr
    return 0.55 * np.exp(-t * 5.0) * np.sin(2 * np.pi * (38 * t + 60 * (1 - np.exp(-t * 10)) / 10)) + 0.08 * rng.standard_normal(n) * np.exp(-t * 25)


SFX = {"whoosh": _whoosh, "tick": _tick, "pop": _pop, "impact": _impact}


def add_sfx(L, R, sr, events, seed=5):
    """events: [(seconds, kind) or (seconds, kind, gain)]. Mixed in place, slightly off-centre so they sit beside the music."""
    rng = np.random.default_rng(seed)
    n = len(L)
    for ev in events:
        t0, kind = ev[0], ev[1]
        g = ev[2] if len(ev) > 2 else 1.0
        s = SFX[kind](sr, rng) * g
        i0 = int(max(0.0, t0) * sr)
        m = min(len(s), n - i0)
        if m <= 0:
            continue
        L[i0:i0 + m] += s[:m] * 1.0
        R[i0:i0 + m] += s[:m] * 0.85
    return L, R
