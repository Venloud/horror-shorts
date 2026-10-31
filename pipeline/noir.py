"""DARK EDITORIAL NOIR motion graphics for the explainer style (owner, Oct 21): midnight / charcoal / smoked taupe
grounds with muted paper grain, bold condensed type, selective hot-magenta highlights. Muted parchment only inside
small evidence / document / photo elements, never as a full-screen background.

Every template is drawn locally (0 Cloudflare neurons), takes the story's own words / verified numbers through
`fields`, and animates over its segment; word-synced reveals use the segment's narration word timings
(`ctx["words"]`: [{"word", "start"}] relative to the segment). Nothing is specific to one story.

render(template, fields, t, dur, ctx) -> RGBA 1080x1920 frame. Templates (TEMPLATES): evidence, map_route, fact,
filmstrip, quote, impact, connections, compare, missing, closing, photo_scan, clock_stop, shadow_reveal, choice,
phone. overlay(kind, fields, t, dur, ctx) -> a transparent layer drawn ON the shot on screen (OVERLAYS: the opening
title, the year reel, counters, stamps, redaction, polaroid, typewriter, kinetic phrases, film burn). ctx["bg"] (a darkened blur of the scene's own story image) replaces the
plain noir ground when given, so a graphic stays inside the story's world.
Safe area: x 70-960 (TikTok's right-hand buttons), y 200-1300 (captions sit at ~1430, the top bar ends ~140).
"""
import math
import random
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from common import CONFIG, ROOT

W, H = 1080, 1920
MIDNIGHT, CHARCOAL, TAUPE = (16, 20, 25), (37, 40, 45), (81, 75, 72)
PARCHMENT = (169, 158, 144)
BONE = (236, 230, 221)  # off-white type
FONT_DIR = ROOT / "assets" / "fonts" / "explainer"
SAFE_X0, SAFE_X1, SAFE_Y0, SAFE_Y1 = 70, 960, 200, 1300
TEMPLATES = ("evidence", "map_route", "fact", "filmstrip", "quote", "impact", "connections",
             "compare", "missing", "closing", "photo_scan", "clock_stop", "shadow_reveal", "choice", "phone")


def accent() -> tuple:
    h = str(CONFIG.get("explainer_accent", "#F01767")).lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------- type + easing

@lru_cache(maxsize=64)
def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        if kind == "mono":
            return ImageFont.truetype(str(FONT_DIR / "SpaceMono-Bold.ttf"), size)
        if kind in ("cond", "cond_med", "cond_light"):
            f = ImageFont.truetype(str(FONT_DIR / "Oswald-VF.ttf"), size)
            f.set_variation_by_name({"cond": "Bold", "cond_med": "Medium", "cond_light": "Light"}[kind])
            return f
        f = ImageFont.truetype(str(FONT_DIR / "Montserrat-VF.ttf"), size)
        f.set_variation_by_name({"black": "Black", "bold": "ExtraBold", "semi": "SemiBold"}.get(kind, "Black"))
        return f
    except Exception:  # noqa: BLE001
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def back(x: float) -> float:
    x = max(0.0, min(1.0, x))
    c = 1.7
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def wrap(text: str, f, width: int) -> list[str]:
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    lines, cur = [], []
    for w in str(text).split():
        if cur and d.textlength(" ".join(cur + [w]), font=f) > width:
            lines.append(" ".join(cur))
            cur = []
        cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


def fit(text: str, kind: str, width: int, max_lines: int, start: int, minimum: int = 40):
    """The biggest size (from start down) at which the text fits in width x max_lines (safe area)."""
    size = start
    while size > minimum:
        f = font(kind, size)
        lines = wrap(text, f, width)
        d = ImageDraw.Draw(Image.new("L", (1, 1)))
        if len(lines) <= max_lines and all(d.textlength(l, font=f) <= width for l in lines):
            return f, lines
        size -= 6
    f = font(kind, minimum)
    return f, wrap(text, f, width)[:max_lines]


def _same(a: str, b: str) -> bool:
    import re
    n = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())  # noqa: E731
    return bool(n(a)) and n(a) == n(b)


def spoken_at(word: str, ctx: dict, default: float) -> float:
    """Segment time at which the narration says this word (sync), else the default."""
    for w in ctx.get("words") or []:
        if _same(w["word"], word):
            return max(0.0, w["start"])
    return default


# ---------------------------------------------------------------- grounds + textures

@lru_cache(maxsize=8)
def _grain(seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    n = rng.normal(0, 1, (H // 2, W // 2)).astype(np.float32)
    n = (n - n.min()) / (n.max() - n.min())
    im = Image.fromarray((n * 255).astype("uint8")).resize((W, H), Image.BICUBIC)
    return im


@lru_cache(maxsize=12)
def ground(tone: str = "midnight", seed: int = 1) -> Image.Image:
    """Full-screen noir ground: a dark tone with muted paper grain, a soft top light and a vignette."""
    base = {"midnight": MIDNIGHT, "charcoal": CHARCOAL, "taupe": (62, 57, 55)}.get(tone, MIDNIGHT)
    arr = np.zeros((H, W, 3), np.float32) + np.array(base, np.float32)
    g = np.asarray(_grain(seed), np.float32) / 255.0
    arr += (g[..., None] - 0.5) * 14  # paper fibre
    y = np.linspace(0, 1, H)[:, None, None]
    x = np.linspace(-1, 1, W)[None, :, None]
    arr *= 1.08 - 0.25 * y  # light from above
    arr *= 1 - 0.35 * np.clip(np.sqrt(x ** 2 + ((y - 0.45) * 1.6) ** 2) - 0.55, 0, 1)  # vignette
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8")).convert("RGBA")


def tone_for(i: int) -> str:
    """Alternate midnight / charcoal / taupe so consecutive graphics differ without bright flashes."""
    return ("midnight", "charcoal", "midnight", "taupe")[i % 4]


@lru_cache(maxsize=6)
def paper(w: int, h: int, seed: int = 3) -> Image.Image:
    """A small muted-parchment sheet (evidence cards, documents, photo borders) with fibre and darker edges."""
    rng = np.random.default_rng(seed)
    arr = np.zeros((h, w, 3), np.float32) + np.array(PARCHMENT, np.float32)
    n = rng.normal(0, 1, (h // 3 + 1, w // 3 + 1)).astype(np.float32)
    n = np.asarray(Image.fromarray(((n - n.min()) / (np.ptp(n) or 1) * 255).astype("uint8")).resize((w, h)),
                   np.float32) / 255
    arr += (n[..., None] - 0.5) * 22
    yy, xx = np.mgrid[0:h, 0:w]
    edge = np.minimum(np.minimum(xx, w - 1 - xx), np.minimum(yy, h - 1 - yy)).astype(np.float32)
    arr *= (0.78 + 0.22 * np.clip(edge / 40, 0, 1))[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8")).convert("RGBA")


def paste(frame: Image.Image, im: Image.Image, x: int, y: int) -> None:
    l, t = max(0, -x), max(0, -y)
    r, b = min(im.width, W - x), min(im.height, H - y)
    if r > l and b > t:
        frame.alpha_composite(im.crop((l, t, r, b)), (max(0, x), max(0, y)))


def kicker(d: ImageDraw.ImageDraw, text: str, x: int, y: int, t: float, acc: tuple) -> None:
    """Small mono label with a magenta tick, slides in."""
    k = ease(t / 0.25)
    x = int(x - 40 * (1 - k))
    d.rectangle((x, y + 6, x + 18, y + 24), fill=acc + (int(255 * k),))
    d.text((x + 32, y), text.upper(), font=font("mono", 28), fill=PARCHMENT + (int(255 * k),))


def underline(d: ImageDraw.ImageDraw, x0: float, x1: float, y: float, g: float, acc: tuple, width: int = 12) -> None:
    """A hand-drawn magenta underline that wipes across (slight wobble)."""
    if g <= 0:
        return
    pts = []
    n = 24
    for i in range(n + 1):
        u = i / n
        if u > g:
            break
        pts.append((x0 + (x1 - x0) * u, y + 4 * math.sin(u * 7.0 + x0 * 0.01)))
    if len(pts) > 1:
        d.line(pts, fill=acc, width=width, joint="curve")


def dashed(d, p0, p1, g, acc, width=8, dash=26, gap=16):
    """A dashed magenta path from p0 toward p1, drawn up to fraction g."""
    (x0, y0), (x1, y1) = p0, p1
    L = math.hypot(x1 - x0, y1 - y0) or 1
    s = 0.0
    while s < L * g:
        e = min(s + dash, L * g)
        d.line((x0 + (x1 - x0) * s / L, y0 + (y1 - y0) * s / L, x0 + (x1 - x0) * e / L, y0 + (y1 - y0) * e / L),
               fill=acc, width=width)
        s += dash + gap


def headline(frame, text, x0, y0, width, t, acc, accent_word="", size=150, max_lines=3, kind="cond", color=BONE,
             stagger=0.06, ctx=None, center=False):
    """Bold condensed lines, word by word (synced to the narration when ctx words match); returns the bottom y."""
    f, lines = fit(text.upper(), kind, width, max_lines, size)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    lh = int(f.size * 1.08)
    y = y0
    k = 0
    for line in lines:
        words = line.split()
        widths = [d.textlength(w, font=f) for w in words]
        sp = d.textlength(" ", font=f)
        x = (W - (sum(widths) + sp * (len(words) - 1))) / 2 if center else x0
        for w, ww in zip(words, widths):
            at = spoken_at(w, ctx or {}, stagger * k) if ctx else stagger * k
            a = ease((t - at) / 0.18)
            if a > 0.01:
                dy = int(28 * (1 - a))
                col = acc if _same(w, accent_word) else color
                d.text((x, y + dy), w, font=f, fill=col + (int(255 * a),))
                if _same(w, accent_word):  # under the glyphs' real bottom edge (Oswald sits low in its box)
                    underline(d, x, x + ww, d.textbbox((x, y), w, font=f)[3] + 12, ease((t - at - 0.15) / 0.3),
                              acc, 10)
            x += ww + sp
            k += 1
        y += lh
    frame.alpha_composite(ov)
    return y


# ---------------------------------------------------------------- templates

def render(template: str, fields: dict, t: float, dur: float, ctx: dict) -> Image.Image:
    fn = globals().get(f"_t_{template}")
    if not fn:
        fn = _t_impact
    return fn(fields or {}, t, dur, ctx)


def _base(ctx: dict) -> Image.Image:
    if ctx.get("bg") is not None:
        return ctx["bg"].copy()
    return ground(ctx.get("tone", "midnight"), ctx.get("seed", 1)).copy()





def _t_evidence(fields, t, dur, ctx):
    """A parchment evidence card drops in, slightly tilted; the label types out; magenta ring circles the key word."""
    acc = ctx["accent"]
    frame = _base(ctx)
    cw, ch = 820, 600
    card = paper(cw, ch).copy()
    dc = ImageDraw.Draw(card, "RGBA")
    dc.text((48, 40), (fields.get("kicker") or "EXHIBIT A").upper(), font=font("mono", 30), fill=(70, 60, 52))
    dc.line((48, 90, cw - 48, 90), fill=(90, 80, 70), width=2)
    text = str(fields.get("text") or "")
    f, lines = fit(text.upper(), "cond", cw - 96, 3, 120)
    n = int(len(" ".join(lines)) * min(1.0, max(0.0, t - 0.3) / 0.6))
    y = 120
    ring = None
    for line in lines:
        s = line[:max(0, n)]
        n -= len(line) + 1
        dc.text((48, y), s, font=f, fill=(28, 24, 22))
        for w in line.split():
            if _same(w, fields.get("accent", "")) and ring is None:
                x0 = 48 + dc.textlength(line[:line.find(w)], font=f)
                ring = (x0 - 20, y - 6, x0 + dc.textlength(w, font=f) + 20, y + f.size * 1.15)
        y += int(f.size * 1.08)
    if fields.get("note"):
        dc.text((48, ch - 90), str(fields["note"]).upper()[:40], font=font("mono", 28), fill=(70, 60, 52))
    if ring:  # the annotation draws itself around the key word
        g = ease((t - 1.0) / 0.5)
        if g > 0:
            dc.arc(ring, -90, -90 + 360 * g, fill=acc + (255,), width=8)
    dc.rectangle((cw - 120, -10, cw - 90, 70), fill=(120, 120, 128))  # paper clip
    drop = back(t / 0.35)
    card = card.rotate(-3 + 2 * (1 - drop), expand=True, resample=Image.BICUBIC)
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    shadow.putalpha(card.getchannel("A").point(lambda a: int(a * 0.55)).filter(ImageFilter.GaussianBlur(14)))
    x, y0 = (W - card.width) // 2, int(380 - 380 * (1 - drop))
    paste(frame, shadow, x + 16, y0 + 24)
    paste(frame, card, x, y0)
    return frame


def _map_texture(seed: int) -> Image.Image:
    """A reusable dark chart: faint grid, contour lines and a coastline-like edge (schematic, not geography)."""
    frame = ground("midnight", seed).copy()
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for x in range(0, W, 90):
        d.line((x, 0, x, H), fill=TAUPE + (60,), width=1)
    for y in range(0, H, 90):
        d.line((0, y, W, y), fill=TAUPE + (60,), width=1)
    rng = random.Random(seed)
    for k in range(5):
        cx, cy, r = rng.randint(100, 980), rng.randint(300, 1200), rng.randint(140, 420)
        pts = [(cx + (r + 30 * math.sin(a * 5 + k)) * math.cos(a), cy + (r * 0.7 + 25 * math.cos(a * 3)) * math.sin(a))
               for a in np.linspace(0, 2 * math.pi, 60)]
        d.line(pts + [pts[0]], fill=TAUPE + (55,), width=2)
    coast = [(x, 300 + 220 * math.sin(x / 170 + seed) + 60 * math.sin(x / 47)) for x in range(-20, W + 40, 20)]
    d.line(coast, fill=PARCHMENT + (45,), width=3)
    frame.alpha_composite(ov)
    return frame


@lru_cache(maxsize=4)
def _map_cached(seed: int) -> Image.Image:
    return _map_texture(seed)


def _t_map_route(fields, t, dur, ctx):
    """Route between 2-4 places said in the narration: markers pop, a dashed magenta path draws, a dot travels."""
    acc = ctx["accent"]
    frame = _map_cached(ctx.get("seed", 1) % 4).copy()
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    stops = [str(s) for s in (fields.get("stops") or [])][:4] or ["A", "B"]
    n = len(stops)
    pts = [(170 + (780 - 170) * (k / max(1, n - 1)), 1060 - 520 * (k / max(1, n - 1)) + (90 if k % 2 else 0))
           for k in range(n)]
    kicker(d, fields.get("kicker") or "THE ROUTE", 110, 230, t, acc)
    seg_t = max(0.4, (dur - 0.8) / max(1, n - 1))
    for k in range(n - 1):
        g = ease((t - 0.4 - k * seg_t) / seg_t)
        dashed(d, pts[k], pts[k + 1], g, acc)
        if 0 < g < 1:
            x = pts[k][0] + (pts[k + 1][0] - pts[k][0]) * g
            y = pts[k][1] + (pts[k + 1][1] - pts[k][1]) * g
            d.ellipse((x - 14, y - 14, x + 14, y + 14), fill=BONE)
    for k, ((x, y), name) in enumerate(zip(pts, stops)):
        at = spoken_at(name.split()[0], ctx, 0.25 + k * seg_t)
        a = back((t - at) / 0.3)
        if a <= 0.02:
            continue
        r = 22 * a
        d.ellipse((x - r, y - r, x + r, y + r), fill=acc)
        pulse = (t - at) % 1.2
        if pulse < 0.8:
            pr = 22 + 60 * pulse
            d.ellipse((x - pr, y - pr, x + pr, y + pr), outline=acc + (int(200 * (1 - pulse / 0.8)),), width=4)
        f = font("cond", 64)
        lw = d.textlength(name.upper(), font=f)
        lx = min(max(SAFE_X0, x - lw / 2), SAFE_X1 - lw)
        d.rectangle((lx - 14, y + 40, lx + lw + 14, y + 124), fill=(10, 12, 16, int(220 * min(1, a))))
        d.text((lx, y + 44), name.upper(), font=f, fill=BONE)
    if fields.get("note"):
        d.text((110, 1260), str(fields["note"]).upper()[:36], font=font("mono", 30), fill=PARCHMENT)
    frame.alpha_composite(ov)
    return frame


def _t_fact(fields, t, dur, ctx):
    """A statistic: the number ticks up big (magenta), its label under a thin rule; optional caption."""
    acc = ctx["accent"]
    frame = _base(ctx)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    kicker(d, fields.get("kicker") or "THE NUMBERS", 110, 360, t, acc)
    to = float(fields.get("value") or 0)
    frm = float(fields.get("from") or 0)
    v = frm + (to - frm) * ease((t - 0.25) / max(0.6, min(1.6, dur - 0.6)))
    num = f"{int(round(v)):,}" if float(to).is_integer() else f"{v:.1f}"
    txt = f"{fields.get('prefix', '')}{num}{fields.get('suffix', '')}"
    f, _ = fit(txt, "cond", 860, 1, 360, 120)
    d.text((110, 430), txt, font=f, fill=acc)
    y = 430 + int(f.size * 1.18)
    g = ease((t - 0.5) / 0.4)
    d.rectangle((110, y, 110 + 760 * g, y + 4), fill=PARCHMENT)
    headline(frame, str(fields.get("label") or ""), 110, y + 30, 860, t - 0.6, acc, fields.get("accent", ""),
             size=96, max_lines=3, ctx=None)
    frame.alpha_composite(ov)
    return frame


def _t_filmstrip(fields, t, dur, ctx):
    """An archival filmstrip slides across with 3 frames from this video's own plates (sepia), then a caption."""
    acc = ctx["accent"]
    frame = _base(ctx)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    imgs = ctx.get("stills") or []
    strip_h, fw = 520, 420
    n = 4
    strip = Image.new("RGBA", (n * (fw + 40) + 80, strip_h), (12, 12, 14, 255))
    ds = ImageDraw.Draw(strip)
    for x in range(10, strip.width, 46):
        ds.rounded_rectangle((x, 16, x + 26, 44), radius=5, fill=(70, 66, 62))
        ds.rounded_rectangle((x, strip_h - 44, x + 26, strip_h - 16), radius=5, fill=(70, 66, 62))
    for k in range(n):
        x = 40 + k * (fw + 40)
        if imgs:
            im = ImageOps.fit(imgs[k % len(imgs)].convert("RGB"), (fw, strip_h - 120))
            im = ImageOps.colorize(ImageOps.grayscale(im), (25, 20, 16), (205, 190, 165))
            strip.paste(im, (x, 60))
        else:
            ds.rectangle((x, 60, x + fw, strip_h - 60), fill=(50, 46, 42))
    strip = strip.rotate(-4, expand=True, resample=Image.BICUBIC)
    off = int((W - strip.width) * ease(t / max(0.8, dur)) - 120)
    paste(frame, strip, off, 520)
    kicker(d, fields.get("kicker") or "ARCHIVE", 110, 360, t, acc)
    headline(frame, str(fields.get("text") or ""), 110, 1060, 860, t - 0.4, acc, fields.get("accent", ""), size=96,
             max_lines=2, ctx=ctx)
    frame.alpha_composite(ov)
    return frame


def _t_quote(fields, t, dur, ctx):
    """Kinetic quotation: big magenta marks, words land in sync with the narration, attribution line."""
    acc = ctx["accent"]
    frame = _base(ctx)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    a = ease(t / 0.3)
    d.text((90, 250), "“", font=font("cond", 320), fill=acc + (int(255 * a),))
    y = headline(frame, str(fields.get("text") or ""), 120, 520, 820, t - 0.15, acc, fields.get("accent", ""),
                 size=110, max_lines=5, kind="cond_med", ctx=ctx)
    if fields.get("by"):
        g = ease((t - 0.8) / 0.4)
        d.rectangle((120, y + 40, 120 + 60 * g, y + 46), fill=acc)
        d.text((200, y + 22), str(fields["by"]).upper()[:30], font=font("mono", 30), fill=PARCHMENT + (int(255 * g),))
    frame.alpha_composite(ov)
    return frame


def _t_impact(fields, t, dur, ctx):
    """One or two complete phrases of the narration ("CHOOSE RED" / "COVERED IN BLOOD"), huge, each revealed when it
    is spoken; ONLY the payoff word (fields["accent"]) is coloured and underlined, never every line. Slow push."""
    acc = ctx["accent"]
    frame = ctx.get("bg") or _base(ctx)
    beats = [str(b).upper() for b in (fields.get("lines") or []) if str(b).strip()] or \
        [str(fields.get("text") or "").upper()]
    accent = str(fields.get("accent") or "")
    z = 1.0 + 0.03 * ease(t / max(dur, 0.1))
    size = int((230 if len(beats) == 1 else 170) * z)
    blocks = []
    for k, beat in enumerate(beats):
        f, lines = fit(beat, "cond", int(860 / z), 2, size, 80)
        blocks.append((k, f, lines))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    gap = 70
    heights = [len(lines) * int(f.size * 1.02) for _, f, lines in blocks]
    y = 840 - (sum(heights) + gap * (len(blocks) - 1)) // 2
    for (k, f, lines), hgt in zip(blocks, heights):
        at = spoken_at(lines[0].split()[0], ctx, 0.5 * k) if lines else 0.5 * k
        a = back((t - at) / 0.22)
        lh = int(f.size * 1.02)
        if a > 0.02:
            for li, line in enumerate(lines):
                words = line.split()
                widths = [d.textlength(w, font=f) for w in words]
                sp = d.textlength(" ", font=f)
                x = (W - (sum(widths) + sp * (len(words) - 1))) / 2
                yy = y + li * lh + int(30 * (1 - min(1, a)))
                for w, ww in zip(words, widths):
                    hit = _same(w, accent)
                    d.text((x, yy), w, font=f, fill=(acc if hit else BONE) + (int(255 * min(1, a)),))
                    if hit:
                        underline(d, x, x + ww, d.textbbox((x, yy), w, font=f)[3] + 16,
                                  ease((t - at - 0.2) / 0.35), acc, 14)
                    x += ww + sp
        y += hgt + gap
    frame.alpha_composite(ov)
    return frame


COLOURS = {"RED": (205, 32, 48), "BLUE": (46, 96, 210), "YELLOW": (232, 192, 44), "GREEN": (44, 154, 86),
           "BLACK": (24, 24, 28), "WHITE": (238, 238, 238), "PURPLE": (124, 56, 168)}


def _t_choice(fields, t, dur, ctx):
    """A binary choice the narration offers: the approved P08 pose (both palms open, placement only) in a circular
    pool of light, one option above each open hand, each revealed when it is spoken. Without the pose (missing /
    changed file) the two options stand alone: never a substitute drawing."""
    frame = ctx.get("bg") or _base(ctx)
    left, right = str(fields.get("left") or "").upper(), str(fields.get("right") or "").upper()
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    cx, cy = W // 2, 900
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((cx - 430, cy - 430, cx + 430, cy + 430), fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    light = Image.new("RGBA", (W, H), (205, 196, 184, 0))
    light.putalpha(glow)
    frame.alpha_composite(light)
    hands = [(250, 610), (830, 610)]
    figure = None
    try:
        import sprites
        figure = sprites.pose("P08", 980)
        if isinstance(ctx.get("used_assets"), set):
            ctx["used_assets"].add("P08")
    except Exception:  # noqa: BLE001 (MissingAsset: options only, the build never substitutes art)
        figure = None
    if figure is not None:
        fx, fy = (W - figure.width) // 2, 1330 - figure.height
        rise = int(24 * (1 - ease(t / 0.3)))
        paste(frame, figure, fx, fy + rise)
        hands = [(fx + int(figure.width * 0.06), fy + int(figure.height * 0.27)),
                 (fx + int(figure.width * 0.94), fy + int(figure.height * 0.27))]
    for k, (opt, (hx, hy)) in enumerate(zip((left, right), hands)):
        if not opt:
            continue
        at = spoken_at(opt.split()[0], ctx, 0.25 + 0.45 * k)
        a = back((t - at) / 0.25)
        if a <= 0.02:
            continue
        f, lines = fit(opt, "cond", 360, 2, 120, 60)
        tw = max(d.textlength(l, font=f) for l in lines)
        lh = int(f.size * 1.02)
        col = COLOURS.get(opt)
        orb_y = hy - 34  # resting in the open palm
        if col:  # a glowing orb of that colour on the palm
            r = int(40 * min(1, a))
            d.ellipse((hx - r - 10, orb_y - r - 10, hx + r + 10, orb_y + r + 10), fill=col + (70,))
            d.ellipse((hx - r, orb_y - r, hx + r, orb_y + r), fill=col + (240,))
        bx = int(max(SAFE_X0 + tw / 2 + 10, min(SAFE_X1 - tw / 2 - 10, hx)))
        by = orb_y - (70 if col else 30) - len(lines) * lh  # the label floats above its hand, clear of the orb
        for li, line in enumerate(lines):
            lw = d.textlength(line, font=f)
            yy = by + li * lh + int(24 * (1 - min(1, a)))
            d.text((bx - lw / 2 + 4, yy + 5), line, font=f, fill=(0, 0, 0, int(170 * min(1, a))))
            d.text((bx - lw / 2, yy), line, font=f, fill=(col or BONE) + (int(255 * min(1, a)),))
    frame.alpha_composite(ov)
    return frame


def _t_phone(fields, t, dur, ctx):
    """A phone screen insert: the message the narration states (verbatim), typing dots, then the bubble pops in.
    No invented sender, number or time: an optional sender only when the narration names one."""
    frame = ctx.get("bg") or _base(ctx)
    k = back(t / 0.3)
    pw, ph = 560, 1000
    phone = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    dp = ImageDraw.Draw(phone)
    dp.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=70, fill=(12, 13, 16, 255), outline=(70, 72, 80, 255),
                         width=6)
    dp.rounded_rectangle((22, 22, pw - 23, ph - 23), radius=54, fill=(24, 27, 33, 255))
    dp.rounded_rectangle((pw // 2 - 70, 40, pw // 2 + 70, 66), radius=13, fill=(10, 10, 12, 255))
    who = str(fields.get("from") or "").upper()[:22]
    if who:
        fw = font("mono", 30)
        dp.text(((pw - dp.textlength(who, font=fw)) / 2, 110), who, font=fw, fill=PARCHMENT + (255,))
    dp.line((50, 170, pw - 50, 170), fill=(50, 54, 62, 255), width=2)
    text = str(fields.get("text") or "")
    f, lines = fit(text, "bold", pw - 170, 6, 48, 30)
    lh = int(f.size * 1.2)
    bh = len(lines) * lh + 50
    bw = int(max(dp.textlength(l, font=f) for l in lines) + 60) if lines else 200
    show = t >= 0.55
    if not show:  # typing dots before the message lands
        for j in range(3):
            on = int((t * 6 + j) % 3 == 0)
            dp.ellipse((70 + j * 34, 240, 92 + j * 34, 262), fill=(150, 150, 160, 160 + 95 * on))
    else:
        g = back((t - 0.55) / 0.2)
        x0, y0 = 50, 220
        bub = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        db = ImageDraw.Draw(bub)
        db.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=34, fill=(58, 62, 72, 255))
        for li, line in enumerate(lines):
            db.text((30, 25 + li * lh), line, font=f, fill=BONE + (255,))
        bub = bub.resize((max(1, int(bw * min(1.0, g))), max(1, int(bh * min(1.0, g)))))
        phone.alpha_composite(bub, (x0, y0))
    phone = phone.rotate(-2, expand=True, resample=Image.BICUBIC)
    shadow = Image.new("RGBA", phone.size, (0, 0, 0, 0))
    shadow.putalpha(phone.getchannel("A").point(lambda a: int(a * 0.6)).filter(ImageFilter.GaussianBlur(20)))
    x, y = (W - phone.width) // 2, int(300 + 140 * (1 - min(1.0, k)))
    paste(frame, shadow, x + 18, y + 26)
    paste(frame, phone, x, y)
    return frame


def _t_connections(fields, t, dur, ctx):
    """Investigation board: 3-4 pinned cards (the narration's names / clues), magenta strings draw between them."""
    acc = ctx["accent"]
    frame = ground("taupe", ctx.get("seed", 2)).copy()
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    nodes = [str(s) for s in (fields.get("nodes") or [])][:4] or ["?", "?"]
    pos = [(300, 420), (780, 560), (330, 960), (760, 1140)][:len(nodes)]
    kicker(d, fields.get("kicker") or "CONNECTIONS", 110, 230, t, acc)
    for k in range(len(nodes) - 1):
        g = ease((t - 0.5 - 0.35 * k) / 0.4)
        a, b = pos[k], pos[k + 1]
        if g > 0:
            d.line((a[0], a[1], a[0] + (b[0] - a[0]) * g, a[1] + (b[1] - a[1]) * g), fill=acc, width=6)
    if len(nodes) > 2:
        g = ease((t - 0.5 - 0.35 * (len(nodes) - 1)) / 0.4)
        a, b = pos[0], pos[-1]
        if g > 0:
            dashed(d, a, b, g, acc, width=4)
    for k, ((x, y), name) in enumerate(zip(pos, nodes)):
        at = spoken_at(name.split()[0], ctx, 0.15 + 0.3 * k)
        a = back((t - at) / 0.25)
        if a <= 0.02:
            continue
        f, lines = fit(name.upper(), "cond", 330, 2, 64, 40)
        cw = int(max(d.textlength(l, font=f) for l in lines) + 60)
        chh = int(len(lines) * f.size * 1.1 + 50)
        card = paper(cw, chh, 5 + k).copy()
        dc = ImageDraw.Draw(card)
        yy = 22
        for l in lines:
            dc.text((30, yy), l, font=f, fill=(28, 24, 22))
            yy += int(f.size * 1.1)
        card = card.rotate((-4, 3, -2, 5)[k], expand=True, resample=Image.BICUBIC)
        sc = min(1.0, a)
        card = card.resize((max(1, int(card.width * sc)), max(1, int(card.height * sc))))
        cx = min(max(SAFE_X0, x - card.width // 2), SAFE_X1 - card.width)
        paste(frame, card, cx, y - card.height // 2)
        d.ellipse((x - 12, y - card.height // 2 - 6, x + 12, y - card.height // 2 + 18), fill=acc)  # pin
    frame.alpha_composite(ov)
    return frame


def _t_compare(fields, t, dur, ctx):
    """Side-by-side theories: two columns reveal their points; a magenta '?' settles between them."""
    acc = ctx["accent"]
    frame = _base(ctx)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    kicker(d, fields.get("kicker") or "TWO THEORIES", 110, 260, t, acc)
    cols = [fields.get("left") or {}, fields.get("right") or {}]
    for c, col in enumerate(cols):
        x0 = 90 + c * 470
        a = ease((t - 0.2 - 0.3 * c) / 0.3)
        d.rectangle((x0, 340, x0 + 430, 1240), fill=(255, 255, 255, int(10 * a)), outline=TAUPE + (int(255 * a),),
                    width=2)
        f, lines = fit(str(col.get("title") or f"THEORY {c + 1}").upper(), "cond", 380, 2, 80, 44)
        y = 370
        for l in lines:
            d.text((x0 + 26, y), l, font=f, fill=(acc if c else BONE) + (int(255 * a),))
            y += int(f.size * 1.08)
        d.rectangle((x0 + 26, y + 10, x0 + 26 + 120 * a, y + 16), fill=acc)
        y += 50
        for k, item in enumerate((col.get("items") or [])[:4]):
            g = ease((t - 0.7 - 0.25 * k - 0.15 * c) / 0.3)
            if g <= 0:
                continue
            fi, li = fit(str(item).upper(), "cond_med", 360, 3, 52, 34)
            d.text((x0 + 26, y + 6), "—", font=fi, fill=acc + (int(255 * g),))
            for l in li:
                d.text((x0 + 70, y), l, font=fi, fill=BONE + (int(255 * g),))
                y += int(fi.size * 1.12)
            y += 18
    g = back((t - 1.2) / 0.35)
    if g > 0.02:
        f = font("cond", int(170 * min(1.0, g)))
        d.text((W / 2, 1180), "?", font=f, fill=acc, anchor="mm")
    frame.alpha_composite(ov)
    return frame


def _t_missing(fields, t, dur, ctx):
    """Disappearance: the person's figure dissolves into scanlines and a dashed outline stays; a stamp lands."""
    acc = ctx["accent"]
    frame = ctx.get("bg") or _base(ctx)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    fig = ctx.get("figure")
    fade = ease((t - 0.5) / max(0.6, dur - 1.0))
    if fig is not None:
        x, y = W // 2 - fig.width // 2, 1300 - fig.height
        # Thick readable rim at phone scale; the old 1-pixel FIND_EDGES disappeared on dark grounds.
        alpha = fig.getchannel("A")
        from PIL import ImageChops
        outline = ImageChops.subtract(alpha.filter(ImageFilter.MaxFilter(19)),
                                       alpha.filter(ImageFilter.MinFilter(9)))
        outline = outline.point(lambda v: 255 if v > 24 else 0)
        dash = Image.new("RGBA", fig.size, acc + (0,))
        dash.putalpha(outline.point(lambda v: int(v * (0.78 + 0.22 * fade))))
        halo = dash.filter(ImageFilter.GaussianBlur(12))
        halo.putalpha(halo.getchannel("A").point(lambda v: int(v * 0.52)))
        paste(frame, halo, x, y)
        body = fig.copy()
        arr = np.asarray(body).copy()
        rows = np.arange(arr.shape[0])
        keep = ((rows // 6) % 2 == 0) | (np.random.default_rng(int(t * 30)).random(arr.shape[0]) > fade)
        arr[~keep, :, 3] = 0
        arr[..., 3] = (arr[..., 3] * (1 - fade)).astype("uint8")
        body = Image.fromarray(arr)
        shift = int(18 * math.sin(t * 40) * fade)
        paste(frame, body, x + shift, y)
        paste(frame, dash, x, y)
    word = str(fields.get("word") or "").upper()
    if word:
        g = back((t - max(0.6, dur * 0.45)) / 0.3)
        if g > 0.02:
            f = font("cond", 150)
            tw = d.textlength(word, font=f)
            stamp = Image.new("RGBA", (int(tw + 80), 210), (0, 0, 0, 0))
            dst = ImageDraw.Draw(stamp)
            dst.rectangle((4, 4, stamp.width - 5, stamp.height - 5), outline=acc + (255,), width=10)
            dst.text((40, 8), word, font=f, fill=acc + (255,))
            stamp = stamp.rotate(-8, expand=True, resample=Image.BICUBIC)
            sc = (2.0 - min(1.0, g)) * min(1.0, 860 / stamp.width)
            stamp = stamp.resize((max(1, int(stamp.width * sc)), max(1, int(stamp.height * sc))))
            paste(frame, stamp, W // 2 - stamp.width // 2, 520 - stamp.height // 2)
    if fields.get("last_seen"):
        a = ease((t - 0.3) / 0.3)
        d.rectangle((90, 300, 98, 380), fill=acc + (int(255 * a),))
        d.text((118, 296), "LAST SEEN", font=font("mono", 28), fill=PARCHMENT + (int(255 * a),))
        d.text((118, 330), str(fields["last_seen"]).upper()[:28], font=font("cond", 54), fill=BONE + (int(255 * a),))
    frame.alpha_composite(ov)
    return frame


def _t_closing(fields, t, dur, ctx):
    """Closing mystery card: the question in big condensed type, a magenta '?' watermark, the case-file stamp."""
    acc = ctx["accent"]
    frame = _base(ctx)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    g = ease(t / 0.6)
    d.text((W - 30, 1020), "?", font=font("cond", 760), fill=acc + (int(26 * g),), anchor="rm")
    kicker(d, fields.get("kicker") or "YOUR CALL", 110, 420, t, acc)
    headline(frame, str(fields.get("text") or ""), 110, 500, 860, t - 0.1, acc, fields.get("accent", ""), size=124,
             max_lines=5, ctx=ctx)
    frame.alpha_composite(ov)
    return frame


# ------------------------------------------------------------- reusable cinematic tools
# These effects were created specifically for Night Files. Conceptual references:
# Bouriko's free Remotion graphics; OpenMontage's visual QA and cinematic camera direction.
# No third-party AGPL source code, paid models, assets, or new dependencies are used.

def cinematic_camera(frame: Image.Image, motion: str, t: float, dur: float) -> Image.Image:
    """Opt-in editorial camera motion, applied BEFORE captions, never distorts original PNGs.

    Motion operates on a composed frame. It intentionally moves only 2-7% so that
    the approved character's eyes and crimson rim stay crisp and inside frame.
    """
    if motion not in ("subtle_push", "subtle_pan", "parallax_light"):
        return frame
    progress = ease(t / max(0.2, dur))
    factor = 1.0 + (0.065 if motion == "subtle_push" else 0.035) * progress
    crop_w, crop_h = W / factor, H / factor
    center_x = W / 2 + ((progress - 0.5) * 0.045 * W if motion == "subtle_pan" else 0)
    center_y = H * 0.48 - (progress * 0.015 * H if motion == "subtle_push" else 0)
    left = max(0.0, min(W - crop_w, center_x - crop_w / 2))
    top = max(0.0, min(H - crop_h, center_y - crop_h / 2))
    result = frame.transform((W, H), Image.Transform.EXTENT,
                             (left, top, left + crop_w, top + crop_h),
                             resample=Image.Resampling.BICUBIC)
    if motion == "parallax_light":
        # Very faint, mobile-safe light sweep, not a replacement background.
        light = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(light)
        travel = int((0.15 + progress * 0.7) * W)
        ld.polygon([(travel - 180, 0), (travel + 35, 0),
                    (travel + 340, H), (travel + 120, H)],
                   fill=(220, 229, 238, 12))
        result.alpha_composite(light)
    return result


def _draw_shadow_person(draw: ImageDraw.ImageDraw, cx: int, baseline: int,
                        size: float, fill: tuple) -> None:
    """Abstract SHADOW symbol only. This is never represented as archival evidence."""
    r = int(56 * size)
    head = int(baseline - 270 * size)
    # Light rim is required for legibility on the dark editorial stage.
    rim = (180, 188, 196, int(fill[3] * 0.75))
    draw.ellipse((cx-r, head-r, cx+r, head+r),
                 fill=fill, outline=rim, width=max(3,int(5*size)))
    draw.rounded_rectangle((cx-int(80*size), head+int(64*size),
                            cx+int(80*size), baseline),
                           radius=int(35*size), fill=fill, outline=rim,
                           width=max(3,int(5*size)))


def _focus_ring_points(target: tuple, seed: int = 0, padding: float = 22.0) -> list[tuple[int, int]]:
    """Loose, hand-drawn circle that STILL contains the target's full bounding box.

    The target coordinates come from the actual object geometry, never a fixed
    screen location. The sqrt(2) factor contains even a rectangular target's
    corners; the generous padding safely absorbs the small hand-drawn wobble.
    """
    x0, y0, x1, y1 = target
    if not (x1 > x0 and y1 > y0):
        raise ValueError("Attention ring requires a non-empty target bounds")
    cx, cy = (x0+x1)/2.0, (y0+y1)/2.0
    rx = math.sqrt(2) * ((x1-x0)/2.0 + padding)
    ry = math.sqrt(2) * ((y1-y0)/2.0 + padding)
    points = []
    for i in range(96):
        angle = i * 2 * math.pi / 96
        wobble = 1 + 0.014 * math.sin(3*angle + seed) + 0.007 * math.cos(5*angle + 2*seed)
        points.append((round(cx + rx*wobble*math.cos(angle)),
                       round(cy + ry*wobble*math.sin(angle))))
    return points


def draw_attention_ring(draw: ImageDraw.ImageDraw, bounds: tuple, color: tuple,
                        *, seed: int = 0, padding: float = 18, width: int = 5) -> None:
    """Generic focus annotation for ANY evidence/prop/figure with known screen bounds.

    Imperfect outline is intentional. Geometric containment of the target is not
    optional. Supply actual rendered object bounds, never a guessed label position.
    """
    points = _focus_ring_points(bounds, seed=seed, padding=padding)
    draw.line(points + [points[0]], fill=color, width=width, joint="curve")


def _resolve_clock_time(fields: dict) -> str:
    """Resolve a clock value from arbitrary storyboard fields, never from a named story.

    Explicit `time` wins. Otherwise infer well-defined labels (MIDNIGHT / NOON)
    or a literal spoken HH:MM; an unspecified event is deliberately unlabelled.
    """
    import re
    explicit = str(fields.get("time") or "").strip()
    if explicit:
        return explicit[:16]
    words = " ".join(str(fields.get(k) or "") for k in ("text", "kicker", "label")).upper()
    if re.search(r"\bMIDNIGHT\b", words):
        return "12:00 AM"
    if re.search(r"\bNOON\b", words):
        return "12:00 PM"
    match = re.search(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[AP]M)?\b", words)
    return match.group(0).strip() if match else ""


def _clock_angles(time_label: str) -> tuple[float, float]:
    """Hands (radians) for an explicitly specified clock time; default is illustrative 10:10."""
    value = str(time_label or "").strip().upper()
    if value in ("MIDNIGHT", "00:00", "12:00 AM", "12:00AM"):
        hours, minutes = 0, 0
    else:
        import re
        match = re.fullmatch(r"(\d{1,2}):(\d{2})(?:\s*(AM|PM))?", value)
        if not match:
            hours, minutes = 10, 10  # visually illustrative when narration did not specify a time
        else:
            hours, minutes = int(match.group(1)), int(match.group(2))
            if not (0 <= hours <= 23 and 0 <= minutes < 60):
                hours, minutes = 10, 10
            elif match.group(3) == "PM":
                hours = (hours % 12) + 12
            elif match.group(3) == "AM":
                hours = hours % 12
    return (math.radians(-90 + 30*(hours%12) + 0.5*minutes),
            math.radians(-90 + 6*minutes))


def _t_photo_scan(fields, t, dur, ctx):
    """Reusable illustrated photo inspection: reveal, scan beam, evidence focus."""
    acc = ctx["accent"]
    frame = _base(ctx)
    d = ImageDraw.Draw(frame, "RGBA")
    kicker(d, str(fields.get("kicker") or "IMAGE INSPECTION"), 108, 218, t, acc)
    # 2D editorial specimen, NOT a faked 'historical photo'. Optional silhouettes.
    x0, y0, x1, y1 = 126, 346, 948, 1225
    slide = int(55 * (1 - back(t/0.42)))
    x0, x1, y0, y1 = x0 + slide, x1 + slide, y0 + slide, y1 + slide
    d.rounded_rectangle((x0, y0, x1, y1), radius=18,
                        fill=(31, 34, 40, 255), outline=BONE+(215,), width=5)
    d.rectangle((x0+35, y0+45, x1-35, y1-182),
                fill=(16, 20, 25, 255), outline=(119, 120, 120, 255), width=2)
    # Pinpointing in an abstract 2D image, rather than claiming an archival photo.
    for i in range(8):
        yy = y0 + 82 + i * 65
        d.line((x0+40, yy, x1-39, yy), fill=(154, 160, 158, 20), width=2)
    count = max(1, min(3, int(fields.get("count") or 1)))
    for k in range(count):
        appear = 0.15 + 0.46*k/max(1, count-1)
        a = ease((t/max(0.1,dur)-appear)/0.22)
        if a < 0.01:
            continue
        cx = round((x0+x1)/2 + (k-(count-1)/2)*211)
        baseline = y1-275
        size = 0.85
        _draw_shadow_person(d, cx, baseline, size,
                            (10, 11, 15, int(160*a)))
        # Calculate from that precise figure's silhouette bounds. The imperfect
        # oval encloses the ENTIRE subject, not empty space near the subject.
        target = (cx-80*size, baseline-(270+56)*size,
                  cx+80*size, baseline)
        draw_attention_ring(d, target, acc+(int(120*a),),
                            seed=k+1, padding=15)
    # Light passes over subject, held evidence remains in focus after it passes.
    g = ease((t-0.35)/max(0.3, dur-0.9))
    beam = int(x0 + 45 + (x1-x0-90)*g)
    d.line((beam, y0+50, beam, y1-184), fill=acc+(205,), width=7)
    d.rectangle((x0+47, y1-146, x1-47, y1-141), fill=acc+(120,))
    d.text((x0+47,y1-127), "ILLUSTRATIVE RECONSTRUCTION",
           font=font("mono", 25), fill=PARCHMENT+(255,))
    txt = str(fields.get("text") or "").upper()[:58]
    headline(frame, txt, 116, 1290, 830, t-0.18, acc,
             fields.get("accent",""), size=89, max_lines=2)
    return frame


def _t_clock_stop(fields, t, dur, ctx):
    """Animated illustrated clock hand physically slows then freezes."""
    acc = ctx["accent"]
    frame = _base(ctx)
    d = ImageDraw.Draw(frame, "RGBA")
    kicker(d, str(fields.get("kicker") or "TIME"), 110, 240, t, acc)
    cx, cy, radius = 540, 822, 280
    d.ellipse((cx-radius-22, cy-radius-22, cx+radius+22, cy+radius+22),
              outline=acc+(100,), width=5)
    d.ellipse((cx-radius, cy-radius, cx+radius, cy+radius),
              fill=(23, 28, 34, 255), outline=BONE+(230,), width=12)
    for n in range(60):
        rad = math.radians(n*6-90)
        long = n % 5 == 0
        inner = radius-(42 if long else 24)
        outer = radius-11
        a = (cx+inner*math.cos(rad), cy+inner*math.sin(rad))
        b = (cx+outer*math.cos(rad), cy+outer*math.sin(rad))
        d.line((*a,*b),fill=(229, 228, 221, 230 if long else 100),width=6 if long else 2)
    # The hour and minute hands show the precise narration-grounded time
    # throughout. At MIDNIGHT they BOTH point straight up at 12, not 10:10.
    time_label = _resolve_clock_time(fields)
    hour_angle, minute_angle = _clock_angles(time_label)
    d.line((cx,cy,cx+148*math.cos(hour_angle),cy+148*math.sin(hour_angle)),
           fill=BONE+(255,),width=16)
    d.line((cx,cy,cx+207*math.cos(minute_angle),cy+207*math.sin(minute_angle)),
           fill=PARCHMENT+(255,),width=9)
    # Only the second hand moves, decelerating and FREEZING exactly at 12.
    freeze = min(1.0, max(0.0, t/max(0.25, min(1.3, dur*.55))))
    angle = math.radians(-90 - 305*(1.0-ease(freeze)))
    d.line((cx-35*math.cos(angle),cy-35*math.sin(angle),
            cx+235*math.cos(angle),cy+235*math.sin(angle)),
           fill=acc+(255,),width=7)
    d.ellipse((cx-19,cy-19,cx+19,cy+19),fill=acc+(255,))
    a2 = ease((t-min(1.3,dur*.55))/0.25)
    if a2:
        d.rounded_rectangle((232,1175,848,1275),radius=20,fill=(18, 22, 27, int(220*a2)),
                            outline=acc+(int(180*a2),),width=3)
        label = str(fields.get("text") or "CLOCK STOPPED").upper()[:27]
        f,_ = fit(label,"cond",575,1,74,42)
        d.text((540,1193),label,font=f,fill=BONE+(int(255*a2),),anchor="mt")
    if time_label:
        d.text((540,1325),time_label[:12],font=font("mono",42),
               fill=acc+(255,),anchor="mm")
    return frame


def _t_shadow_reveal(fields, t, dur, ctx):
    """Reveal N shadow silhouettes individually; diagram, never a fabricated historical shot."""
    acc = ctx["accent"]
    frame = _base(ctx)
    d = ImageDraw.Draw(frame, "RGBA")
    count = max(1,min(4,int(fields.get("count") or 1)))
    kicker(d,str(fields.get("kicker") or "VISUAL BREAKDOWN"),110,290,t,acc)
    d.line((180,1160,900,1160),fill=PARCHMENT+(110,),width=5)
    spacing = 700/(count+1)
    for k in range(count):
        a = ease((t-0.22-(dur-0.85)*k/max(1,count))/.3)
        if a<=.01:
            continue
        cx=int(180+(k+1)*spacing)
        size = 0.95 if count<=2 else 0.72
        baseline = 1153
        _draw_shadow_person(d,cx,baseline,size,(10,11,16,int(240*a)))
        target = (cx-80*size, baseline-(270+56)*size,
                  cx+80*size, baseline)
        draw_attention_ring(d, target, acc+(int(128*a),),
                            seed=k+11, padding=17)
        d.text((cx,1235),f"{k+1:02d}",font=font("mono",44),
               fill=acc+(int(255*a),),anchor="mm")
    d.text((110,1320),"SCHEMATIC, NOT ARCHIVAL FOOTAGE",font=font("mono",25),
           fill=PARCHMENT+(220,))
    headline(frame,str(fields.get("text") or "").upper()[:75],
             110,390,860,t-.12,acc,fields.get("accent",""),
             size=108,max_lines=3)
    return frame


# ================================================================ motion overlays (owner, Oct 31)
# Reusable kinetic overlays drawn ON TOP of the shot that is on screen (a story picture), never a full-screen card:
# the explainer's planner (explainer.plan_effects) picks one by MEANING from the narration's own words and times it
# to the spoken word. overlay(kind, fields, t, dur, ctx) -> a transparent RGBA layer; t is local to the effect.
# All of them stay in the safe area (x 70-960, y 230-1090): captions sit at 1120-1290 (above the platforms' own
# caption UI), TikTok's buttons on the right.
# Entries ease out (small overshoot on UI-like elements), exits ease in; no linear keyframes.

OVERLAYS = ("title", "year_reel", "year_line", "globe_pin", "ocean_crossing", "night_mode", "battery_low",
            "signal_lost", "temperature_drop", "sticky_note", "hit_profile", "counter", "stamp", "redaction", "polaroid", "typewriter", "phrase", "film_burn")
REEL_TRAVEL = 1.25  # seconds the year reel spins before it lands on the spoken word
REEL_ROW = 150      # px between two years on the reel
TYPE_CPS = 18.0     # typewriter characters per second
STAMPS = ("MISSING", "VANISHED", "DISAPPEARED", "UNSOLVED", "CLASSIFIED", "CASE CLOSED")


def ease_in(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x ** 3


def title_seconds(text: str) -> float:
    """How long the opening title stays readable (owner): min(6 s, 1.5 s + 0.35 s per word), never under 3.5 s."""
    n = len(str(text or "").split())
    return round(max(3.5, min(6.0, 1.5 + 0.35 * n)), 3)


def reel_values(target: int, kind: str = "year", span: int = 8) -> list[int]:
    """The years (or days) the reel passes, ending on the target: 1890 -> 1898 for a year, never past day 1."""
    lo = 1 if kind == "day" else 1000
    start = max(lo, target - span)
    return list(range(start, target + 1))


def reel_position(t: float, n: int, land: float = REEL_TRAVEL) -> float:
    """Reel index (0 = first value, n-1 = target) at local time t: ease-out from t=0, exactly n-1 at t=land."""
    if n <= 1 or t >= land:
        return float(max(0, n - 1))
    return (n - 1) * ease(t / land)


def reel_ticks(n: int, land: float = REEL_TRAVEL) -> list[float]:
    """Local times at which the reel passes each value after the first (inverse of the ease-out): one tick per year;
    the last one is the landing (t == land)."""
    out = []
    for k in range(1, n):
        p = k / (n - 1)
        out.append(round(land * (1 - (1 - p) ** (1 / 3)), 4))
    return out


def type_times(text: str, start: float = 0.0, cps: float = TYPE_CPS) -> list[float]:
    """Local time each visible character of a typewriter reveal appears (spaces are silent)."""
    out, k = [], 0
    for ch in str(text):
        if ch.strip():
            out.append(round(start + k / cps, 4))
        k += 1
    return out


def overlay(kind: str, fields: dict, t: float, dur: float, ctx: dict) -> Image.Image:
    fn = globals().get(f"_o_{kind}")
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if fn and 0 <= t <= dur:
        fn(layer, fields or {}, t, dur, ctx or {})
    return layer


def _fade_out(t: float, dur: float, length: float = 0.32) -> float:
    return 1 - ease_in((t - (dur - length)) / length)


def _band(layer: Image.Image, y0: int, y1: int, alpha: float) -> None:
    """A soft dark band behind overlay type, so it reads over any picture (feathered top and bottom)."""
    if alpha <= 0:
        return
    h = y1 - y0
    col = np.linspace(0, 1, h)
    a = np.minimum(1, np.minimum(col, 1 - col) * 5) * 175 * alpha
    band = Image.new("RGBA", (W, h), (8, 10, 14, 0))
    band.putalpha(Image.fromarray(np.repeat(a[:, None], W, 1).astype("uint8")))
    layer.alpha_composite(band, (0, max(0, y0)))


def _o_title(layer, fields, t, dur, ctx):
    """The opening title over the first story picture, kept simple (owner): a small accent kicker (TRUE STORY on
    true stories) and the title in Oswald, rising in line by line with an ease-out, easing up and out at the end.
    No band, rule or per-letter tricks."""
    acc = ctx.get("accent") or accent()
    text = str(fields.get("text") or "").upper()
    if not text:
        return
    out = _fade_out(t, dur, 0.4)
    f, lines = fit(text, "cond", 860, 3, 120, 64)
    lh = int(f.size * 1.06)
    y = int(520 - len(lines) * lh / 2 - 20 * ease_in((t - (dur - 0.4)) / 0.4))
    d = ImageDraw.Draw(layer)
    kick = str(fields.get("kicker") or "").upper()
    if kick:
        k = ease(t / 0.35) * out
        d.text((W / 2, y - 50), kick, font=font("mono", 32), fill=acc + (int(255 * k),), anchor="mm")
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ds = ImageDraw.Draw(shadow)
    for n, line in enumerate(lines):
        p = ease((t - 0.12 * n) / 0.45) * out
        if p > 0.01:
            yy = y + n * lh + int(30 * (1 - p))
            ds.text((W / 2, yy + 6), line, font=f, fill=(0, 0, 0, int(170 * p)), anchor="ma")
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(10)))
    for n, line in enumerate(lines):  # crisp type above its soft shadow
        p = ease((t - 0.12 * n) / 0.45) * out
        if p > 0.01:
            d.text((W / 2, y + n * lh + int(30 * (1 - p))), line, font=f, fill=BONE + (int(255 * p),), anchor="ma")


def _o_year_reel(layer, fields, t, dur, ctx):
    """Slot-machine reel: the years (or days) scroll up toward the target, ease out and LAND on the spoken word
    (fields land = local time). The landed value: accent red, heavier weight, a small punch; the spoken full date
    types out under it. Passing values are lighter and dimmer; nothing else is claimed about them."""
    vals = [str(v) for v in fields.get("values") or []]
    if not vals:
        return
    land = float(fields.get("land", REEL_TRAVEL))
    red = (232, 36, 52)
    intro = ease(t / 0.22)
    out = _fade_out(t, dur, 0.3)
    alpha = intro * out
    cy = 760
    _band(layer, cy - 290, cy + 300, alpha)
    d = ImageDraw.Draw(layer)
    kick = str(fields.get("kicker") or "").upper()[:26]
    if kick:
        d.text((W / 2, cy - 238), kick, font=font("mono", 30), fill=PARCHMENT + (int(230 * alpha),), anchor="mm")
    pos = reel_position(t, len(vals), land)
    landed = t >= land
    # timeline rails on both sides of the window (the "lane" the reel runs in)
    for x0, x1 in ((110, 300), (780, 970)):
        d.line((x0, cy, x1, cy), fill=(225, 220, 212, int(120 * alpha)), width=4)
    if landed:
        g = ease((t - land) / 0.25)
        d.line((110, cy, 110 + 190 * g, cy), fill=red + (int(255 * alpha),), width=8)
        d.line((970 - 190 * g, cy, 970, cy), fill=red + (int(255 * alpha),), width=8)
    reel = Image.new("RGBA", (W, 3 * REEL_ROW + 40), (0, 0, 0, 0))
    rd = ImageDraw.Draw(reel)
    mid = reel.height / 2
    base = int(math.floor(pos))
    for k in range(base - 2, base + 3):
        if not 0 <= k < len(vals):
            continue
        off = (k - pos) * REEL_ROW
        if abs(off) > REEL_ROW * 1.6:
            continue
        target = k == len(vals) - 1 and landed
        if target:
            continue  # drawn below with its punch
        near = max(0.0, 1 - abs(off) / (REEL_ROW * 1.5))
        f = font("cond_light" if abs(off) > REEL_ROW * 0.5 else "cond_med", 118)
        rd.text((W / 2, mid + off), vals[k], font=f, fill=BONE + (int(235 * near * alpha),), anchor="mm")
    layer.alpha_composite(reel, (0, int(cy - mid)))
    if landed:
        p = (t - land) / 0.28
        sc = 1.0 + 0.16 * math.sin(math.pi * min(1.0, max(0.0, p))) * (1 - min(1.0, max(0.0, p)) * 0.4)
        f = font("cond", int(150 * sc))
        d.text((W / 2, cy), vals[-1], font=f, fill=red + (int(255 * out),), anchor="mm")
    label = str(fields.get("label") or "").upper()[:28]
    if label and landed:
        times = type_times(label, land + 0.18)
        shown = sum(1 for tt in times if tt <= t)
        txt, vis = "", 0
        for ch in label:
            if ch.strip():
                if vis >= shown:
                    break
                vis += 1
            txt += ch
        f = font("mono", 54)
        x0 = W / 2 - d.textlength(label, font=f) / 2
        d.text((x0, cy + 150), txt, font=f, fill=BONE + (int(240 * out),))
        if shown < len(times) or int(t * 3) % 2 == 0:
            cx = x0 + d.textlength(txt, font=f) + 6
            d.rectangle((cx, cy + 158, cx + 26, cy + 206), fill=red + (int(200 * out),))


def line_bumps(n_between: int) -> int:
    """Small bumps along a timeline line: one per year in between, at most 12 (a century is not 99 bumps)."""
    return max(0, min(12, int(n_between)))


def line_ticks(bumps: int, land: float = REEL_TRAVEL) -> list[float]:
    """Local times the moving dot passes each bump (the line draws with an ease-out and reaches the end at land)."""
    out = []
    for k in range(1, bumps + 1):
        p = k / (bumps + 1)
        out.append(round(land * (1 - (1 - p) ** (1 / 3)), 4))
    return out


def _o_year_line(layer, fields, t, dur, ctx):
    """Every date after the first: a timeline line moves from the previous date to the new one (left to right, or
    right to left when the story goes back in time), small bumps pop up along it as the dot passes, and it stops on
    the new date exactly on the spoken word (fields land): new date in accent red, heavier, a small punch; the full
    date types out under it. The bumps are scale marks, never extra events."""
    a_lab, b_lab = str(fields.get("from") or ""), str(fields.get("to") or "")
    if not b_lab:
        return
    land = float(fields.get("land", REEL_TRAVEL))
    back_in_time = bool(fields.get("backwards"))
    red = (232, 36, 52)
    alpha = ease(t / 0.22) * _fade_out(t, dur, 0.3)
    cy = 760
    _band(layer, cy - 220, cy + 260, alpha)
    d = ImageDraw.Draw(layer)
    kick = str(fields.get("kicker") or "").upper()[:26]
    if kick:
        d.text((W / 2, cy - 160), kick, font=font("mono", 30), fill=PARCHMENT + (int(230 * alpha),), anchor="mm")
    x_from, x_to = (900, 180) if back_in_time else (180, 900)
    g = ease(t / land) if t < land else 1.0
    head = x_from + (x_to - x_from) * g
    d.line((min(x_from, x_to), cy, max(x_from, x_to), cy), fill=(225, 220, 212, int(70 * alpha)), width=4)
    d.line((min(x_from, head), cy, max(x_from, head), cy), fill=red + (int(250 * alpha),), width=8)
    n = line_bumps(int(fields.get("bumps") or 0))
    for k in range(1, n + 1):
        bx = x_from + (x_to - x_from) * k / (n + 1)
        passed = (bx - x_from) / ((x_to - x_from) or 1) <= g
        if passed:
            since = t - line_ticks(n, land)[k - 1]
            hgt = 10 + 12 * math.exp(-max(0.0, since) * 9) * max(0.0, math.cos(since * 22)) if since >= 0 else 10
            d.line((bx, cy - hgt, bx, cy), fill=red + (int(230 * alpha),), width=5)
        else:
            d.line((bx, cy - 8, bx, cy), fill=(225, 220, 212, int(120 * alpha)), width=4)
    d.ellipse((x_from - 12, cy - 12, x_from + 12, cy + 12), fill=BONE + (int(230 * alpha),))
    d.text((x_from, cy + 62), a_lab, font=font("cond_med", 64), fill=BONE + (int(190 * alpha),), anchor="mm")
    if t < land:
        d.ellipse((head - 16, cy - 16, head + 16, cy + 16), fill=red + (int(255 * alpha),))
    else:
        p = (t - land) / 0.28
        sc = 1.0 + 0.18 * math.sin(math.pi * min(1.0, max(0.0, p)))
        d.ellipse((x_to - 18, cy - 18, x_to + 18, cy + 18), fill=red + (int(255 * alpha),))
        d.text((x_to, cy + 80), b_lab, font=font("cond", int(104 * sc)), fill=red + (int(255 * alpha),),
               anchor="mm")
    label = str(fields.get("label") or "").upper()[:28]
    if label and t >= land:
        times = type_times(label, land + 0.18)
        shown = sum(1 for tt in times if tt <= t)
        txt, vis = "", 0
        for ch in label:
            if ch.strip():
                if vis >= shown:
                    break
                vis += 1
            txt += ch
        f = font("mono", 46)
        d.text((W / 2 - d.textlength(label, font=f) / 2, cy + 170), txt, font=f, fill=BONE + (int(240 * alpha),))


@lru_cache(maxsize=16)
def profile_icon(h: int, color: tuple = (240, 238, 232)) -> Image.Image:
    """A plain side-view head-and-shoulders silhouette (drawn, not an asset): head, nose, neck, shoulders."""
    s = 4  # supersample
    w, hh = int(h * 0.82) * s, h * s
    im = Image.new("RGBA", (w, hh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = color + (255,)
    r = hh * 0.22
    cx, cy = w * 0.5, hh * 0.3
    d.ellipse((cx - r, cy - r, cx + r, cy + r * 1.08), fill=c)                       # head
    d.polygon([(cx + r * 0.85, cy - r * 0.05), (cx + r * 1.22, cy + r * 0.32), (cx + r * 0.8, cy + r * 0.42)],
              fill=c)                                                                 # nose
    d.rectangle((cx - r * 0.42, cy + r * 0.7, cx + r * 0.38, cy + r * 1.45), fill=c)  # neck
    d.pieslice((cx - r * 2.0, cy + r * 1.2, cx + r * 1.9, cy + r * 4.4), 180, 360, fill=c)  # shoulders
    d.rectangle((cx - r * 2.0, cy + r * 2.78, cx + r * 1.9, hh), fill=c)
    return im.resize((w // s, hh // s), Image.LANCZOS)


def _bullet_icon(h: int) -> Image.Image:
    im = Image.new("RGBA", (h // 3 + 4, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w = h // 3
    d.rounded_rectangle((2, h * 0.38, w + 2, h - 2), radius=3, fill=(196, 160, 72, 255))   # brass case
    d.rectangle((2, h - h * 0.1, w + 2, h - 2), fill=(150, 120, 52, 255))
    d.pieslice((2, 0, w + 2, h * 0.76), 180, 360, fill=(176, 104, 64, 255))             # copper tip
    d.rectangle((2, h * 0.37, w + 2, h * 0.42), fill=(176, 104, 64, 255))
    return im


def _burst(d, x, y, r, a):
    pts = []
    for k in range(16):
        ang = k * math.pi / 8
        rr = r if k % 2 == 0 else r * 0.45
        pts.append((x + rr * math.cos(ang), y + rr * math.sin(ang)))
    d.polygon(pts, fill=(255, 196, 70, int(255 * a)))
    d.ellipse((x - r * 0.35, y - r * 0.35, x + r * 0.35, y + r * 0.35), fill=(255, 255, 235, int(255 * a)))


def _o_counter(layer, fields, t, dur, ctx):
    """A count the narration says, showing WHAT is counted: people = white profile silhouettes filling in as the
    number rolls up, bullets = bullet icons, shots = small bursts, anything else = the number and its noun. It
    lands on the spoken number (red, small punch). Many icons: each icon stands for a stated share ("EACH = 10")."""
    try:
        value = int(fields.get("value"))
    except (TypeError, ValueError):
        return
    land = float(fields.get("land", 1.0))
    kind = fields.get("kind") or "plain"
    out = _fade_out(t, dur, 0.3)
    alpha = ease(t / 0.2) * out
    g = ease(t / land) if t < land else 1.0
    cur = int(round(value * g))
    d = ImageDraw.Draw(layer)
    if kind in ("people", "bullets", "shots"):
        per = 1 if value <= 60 else int(math.ceil(value / 50.0))
        n_icons = int(math.ceil(value / per))
        shown = int(math.ceil(cur / per)) if cur else 0
        cols = min(10, max(3, int(math.ceil(math.sqrt(n_icons * 1.6)))))
        rows = int(math.ceil(n_icons / cols))
        cell = int(min(820 / cols, 480 / max(1, rows)))
        x0 = 540 - cols * cell / 2
        y0 = 600 - rows * cell / 2
        _band(layer, int(y0 - 170), int(y0 + rows * cell + 230), alpha)
        icon = profile_icon(int(cell * 0.86)) if kind == "people" else _bullet_icon(int(cell * 0.86)) \
            if kind == "bullets" else None
        for k in range(n_icons):
            cx = x0 + (k % cols) * cell + cell / 2
            cy = y0 + (k // cols) * cell + cell / 2
            if k >= shown:
                if kind != "shots":
                    ghost = icon.copy()
                    ghost.putalpha(ghost.getchannel("A").point(lambda v: int(v * 0.16 * alpha)))
                    layer.alpha_composite(ghost, (int(cx - ghost.width / 2), int(cy - ghost.height / 2)))
                continue
            since = t - land * (1 - (1 - (k + 1) / n_icons) ** (1 / 3)) if n_icons else 0
            pop = back(since / 0.18) if since < 0.18 else 1.0
            if kind == "shots":
                _burst(d, cx, cy, cell * 0.36 * max(0.2, pop), alpha * (0.55 + 0.45 * math.exp(-max(0, since) * 4)))
                continue
            im = icon if pop >= 0.99 else icon.resize((max(1, int(icon.width * pop)), max(1, int(icon.height * pop))))
            im = im.copy()
            im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
            layer.alpha_composite(im, (int(cx - im.width / 2), int(cy - im.height / 2)))
        ny = int(y0 + rows * cell + 90)
        if per > 1:
            d.text((540, int(y0 - 120)), f"EACH = {per}", font=font("mono", 30), fill=PARCHMENT + (int(220 * alpha),),
                   anchor="mm")
    else:
        ny = 760
        _band(layer, ny - 220, ny + 230, alpha)
    punch = 1 + 0.1 * math.sin(math.pi * min(1, max(0, (t - land) / 0.25))) if t >= land else 1.0
    col = (232, 36, 52) if t >= land else BONE
    txt = str(fields.get("prefix") or "") + f"{cur:,}"
    unit = str(fields.get("unit") or "").upper()[:24]
    if kind == "plain":
        d.text((W / 2, ny), txt, font=font("cond", int(170 * punch)), fill=col + (int(255 * alpha),), anchor="mm")
        if unit:
            d.text((W / 2, ny + 130), unit, font=font("mono", 44), fill=PARCHMENT + (int(235 * alpha),), anchor="mm")
    else:
        f1, f2 = font("cond", int(110 * punch)), font("cond_med", 64)
        w1 = d.textlength(txt, font=f1)
        w2 = d.textlength(" " + unit, font=f2)
        x = W / 2 - (w1 + w2) / 2
        d.text((x, ny), txt, font=f1, fill=col + (int(255 * alpha),), anchor="lm")
        d.text((x + w1, ny + 8), " " + unit, font=f2, fill=BONE + (int(235 * alpha),), anchor="lm")


def _o_hit_profile(layer, fields, t, dur, ctx):
    """'Shot twice': one white profile silhouette; each hit puts a small red bullet hole on it with a tiny white
    flash that stays on the profile only. No blood, no wound detail."""
    hits = max(1, min(8, int(fields.get("hits") or 1)))
    alpha = ease(t / 0.2) * _fade_out(t, dur, 0.3)
    icon = profile_icon(560)
    x0, y0 = int(540 - icon.width / 2), 330
    _band(layer, y0 - 60, y0 + icon.height + 60, alpha)
    body = icon.copy()
    body.putalpha(body.getchannel("A").point(lambda v: int(v * alpha)))
    layer.alpha_composite(body, (x0, y0))
    spots = [(0.50, 0.74), (0.36, 0.82), (0.62, 0.86), (0.44, 0.92), (0.30, 0.94), (0.68, 0.76), (0.56, 0.95),
             (0.40, 0.72)][:hits]  # chest / torso, spread so every hit reads
    first = 0.25
    gap = max(0.18, min(0.45, (dur - 1.0) / hits))
    d = ImageDraw.Draw(layer)
    for k, (u, v) in enumerate(spots):
        at = first + k * gap
        if t < at:
            continue
        x, y = x0 + icon.width * u, y0 + icon.height * v
        q = t - at
        if q < 0.1:  # the flash, masked to the silhouette
            fl = Image.new("RGBA", icon.size, (255, 255, 255, 0))
            ImageDraw.Draw(fl).ellipse((x - x0 - 90, y - y0 - 90, x - x0 + 90, y - y0 + 90),
                                       fill=(255, 255, 255, int(220 * (1 - q / 0.1))))
            fl.putalpha(Image.fromarray(np.minimum(np.asarray(fl.getchannel("A")), np.asarray(icon.getchannel("A")))))
            layer.alpha_composite(fl, (x0, y0))
        r = 13 * (back(q / 0.12) if q < 0.12 else 1.0)
        d.ellipse((x - r - 5, y - r - 5, x + r + 5, y + r + 5), fill=(120, 10, 18, int(230 * alpha)))
        d.ellipse((x - r, y - r, x + r, y + r), fill=(214, 28, 40, int(255 * alpha)))


def hit_times(hits: int, dur: float) -> list[float]:
    gap = max(0.18, min(0.45, (dur - 1.0) / max(1, hits)))
    return [0.25 + k * gap for k in range(max(1, min(8, hits)))]


def counter_ticks(land: float, n: int = 10) -> list[float]:
    """Roll-up tick times (local): n evenly spaced VALUE steps on the ease-out curve, the last on the landing."""
    return [round(land * (1 - (1 - k / n) ** (1 / 3)), 4) for k in range(1, n + 1)]


def _o_stamp(layer, fields, t, dur, ctx):
    """Rubber stamp slam: drops from 2x scale onto the picture at fields land (thud + a short shake, added by the
    explainer), a slight rotation, rough red ink; holds, then fades."""
    text = str(fields.get("text") or "").upper()
    if text not in STAMPS:
        return
    land = float(fields.get("land", 0.18))
    if t < land - 0.16:
        return
    p = (t - (land - 0.16)) / 0.16
    sc = 2.1 - 1.1 * ease(p) if t < land else 1.0 - 0.04 * math.sin(math.pi * min(1, (t - land) / 0.2))
    a = min(1.0, max(0.0, p)) * _fade_out(t, dur, 0.3)
    red = (214, 34, 46)
    f = font("cond", 128)
    d0 = ImageDraw.Draw(Image.new("L", (1, 1)))
    tw = int(d0.textlength(text, font=f))
    st = Image.new("RGBA", (tw + 110, 230), (0, 0, 0, 0))
    ds = ImageDraw.Draw(st)
    ds.rounded_rectangle((8, 8, st.width - 8, st.height - 8), radius=18, outline=red + (255,), width=12)
    ds.text((st.width / 2, st.height / 2 + 4), text, font=f, fill=red + (255,), anchor="mm")
    rng = np.random.default_rng(len(text))
    ink = (rng.random((st.height // 4 + 1, st.width // 4 + 1)) > 0.18).astype("uint8") * 255
    mask = Image.fromarray(ink).resize(st.size, Image.NEAREST)
    st.putalpha(Image.fromarray(np.minimum(np.asarray(st.getchannel("A")), np.asarray(mask))).point(
        lambda v: int(v * 0.92 * a)))
    st = st.rotate(-8, resample=Image.BICUBIC, expand=True)
    if abs(sc - 1) > 0.003:
        st = st.resize((max(1, int(st.width * sc)), max(1, int(st.height * sc))), Image.BILINEAR)
    paste(layer, st, int(W / 2 - st.width / 2), int(820 - st.height / 2))


def _o_redaction(layer, fields, t, dur, ctx):
    """A redaction bar over a word on a document strip; the bar pulls away to reveal it on the spoken word."""
    word = str(fields.get("text") or "").upper()[:26]
    if not word:
        return
    land = float(fields.get("land", 0.6))
    alpha = ease(t / 0.22) * _fade_out(t, dur, 0.3)
    f, lines = fit(word, "cond", 760, 1, 120, 60)
    d = ImageDraw.Draw(layer)
    tw = d.textlength(lines[0], font=f)
    x0, cy = W / 2 - tw / 2, 860
    sheet = paper(int(tw + 140), 220, 5).copy()
    sheet.putalpha(int(235 * alpha))
    paste(layer, sheet, int(x0 - 70), cy - 110)
    kick = str(fields.get("kicker") or "").upper()[:24]
    if kick:
        d.text((x0 - 50, cy - 98), kick, font=font("mono", 26), fill=(40, 34, 30, int(230 * alpha)))
    d.text((W / 2, cy + 18), lines[0], font=f, fill=(24, 22, 22, int(255 * alpha)), anchor="mm")
    g = ease_in((t - land) / 0.3) if t >= land else 0.0
    x_start = x0 - 16 + (tw + 32) * g
    if g < 1:
        d.rectangle((x_start, cy - 52, x0 + tw + 16, cy + 74), fill=(6, 6, 8, int(255 * alpha)))


def _o_polaroid(layer, fields, t, dur, ctx):
    """A polaroid of the scene's own picture drops in with a small tilt and bounce; flash at the shutter."""
    src = fields.get("image")
    if not src:
        return
    land = float(fields.get("land", 0.45))
    cache = ctx.setdefault("_polaroid", {})
    if src not in cache:
        try:
            im = Image.open(src).convert("RGB")
        except OSError:
            cache[src] = None
            return
        ph = ImageOps.fit(im, (560, 560), Image.LANCZOS)
        card = Image.new("RGBA", (620, 740), (238, 234, 226, 255))
        card.paste(ph, (30, 30))
        cap = str(fields.get("caption") or "").upper()[:22]
        if cap:
            ImageDraw.Draw(card).text((310, 660), cap, font=font("mono", 34), fill=(40, 36, 34, 255), anchor="mm")
        cache[src] = card
    card = cache[src]
    if card is None:
        return
    p = t / land
    y = 330 - 760 * (1 - back(p)) if t < land else 330
    rot = 9 - 13 * ease(p)
    a = _fade_out(t, dur, 0.3)
    c = card.copy()
    c.putalpha(int(255 * a))
    shadow = Image.new("RGBA", (c.width + 60, c.height + 60), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle((30, 40, c.width + 30, c.height + 40), fill=(0, 0, 0, int(140 * a)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    shadow.alpha_composite(c, (30, 30))
    r = shadow.rotate(rot, resample=Image.BICUBIC, expand=True)
    paste(layer, r, int(W / 2 - r.width / 2), int(y))
    flash = max(0.0, 1 - abs(t - land) / 0.09)
    if flash:
        layer.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, int(70 * flash))))


def _o_typewriter(layer, fields, t, dur, ctx):
    """Typed text (a quote, a note, a message the narration states) on a dark strip, one character at a time;
    the explainer adds one quiet typing click per character from type_times()."""
    text = str(fields.get("text") or "")[:90]
    if not text:
        return
    alpha = ease(t / 0.2) * _fade_out(t, dur, 0.3)
    times = type_times(text, float(fields.get("start", 0.15)))
    shown = sum(1 for tt in times if tt <= t)
    f = font("mono", 48)
    lines = wrap(text, f, 820)[:3]
    _band(layer, 840 - 40, 840 + len(lines) * 66 + 60, alpha)
    d = ImageDraw.Draw(layer)
    kick = str(fields.get("kicker") or "").upper()[:24]
    if kick:
        d.text((120, 805), kick, font=font("mono", 26), fill=PARCHMENT + (int(220 * alpha),))
    vis = 0
    y = 850
    cur = (120, 850)
    for line in lines:
        txt = ""
        for ch in line:
            if ch.strip():
                if vis >= shown:
                    break
                vis += 1
            txt += ch
        d.text((120, y), txt, font=f, fill=BONE + (int(245 * alpha),))
        cur = (120 + d.textlength(txt, font=f) + 6, y)
        if len(txt) < len(line):
            break
        vis += 0
        y += 66
    if int(t * 3) % 2 == 0 or shown < len(times):
        d.rectangle((cur[0], cur[1] + 8, cur[0] + 24, cur[1] + 56), fill=(232, 36, 52, int(220 * alpha)))


def _o_phrase(layer, fields, t, dur, ctx):
    """Kinetic key phrase on the picture: mode pop (word pop + scale), stagger (letter stagger), highlight (a red
    swipe behind the accent word), strike (a red line strikes through it), underline / circle (drawn on the accent
    word) or glitch (a brief RGB-split flicker). fields land = when the accent move happens (the spoken word)."""
    acc = (232, 36, 52)
    text = str(fields.get("text") or "").upper()[:48]
    if not text:
        return
    mode = fields.get("mode") or "pop"
    land = float(fields.get("land", 0.3))
    alpha = ease(t / 0.2) * _fade_out(t, dur, 0.3)
    f, lines = fit(text, "cond", 840, 2, 112, 60)
    lh = int(f.size * 1.08)
    y0 = 640
    _band(layer, y0 - 90, y0 + len(lines) * lh + 90, alpha)
    d = ImageDraw.Draw(layer)
    target = str(fields.get("accent") or "").upper()
    k = 0
    y = y0
    for line in lines:
        words = line.split()
        widths = [d.textlength(w, font=f) for w in words]
        sp = d.textlength(" ", font=f)
        x = (W - (sum(widths) + sp * (len(words) - 1))) / 2
        for w, ww in zip(words, widths):
            hit = _same(w, target)
            bb = (x - 10, y + 6, x + ww + 10, y + lh - 2)
            if hit and mode == "highlight":
                g = ease((t - land) / 0.3)
                if g > 0:
                    d.rectangle((bb[0], bb[1] + 10, bb[0] + (bb[2] - bb[0]) * g, bb[3] - 8), fill=acc + (int(230 * alpha),))
            if mode == "stagger":
                cx = x
                for j, ch in enumerate(w):
                    a = ease((t - 0.03 * (k * 4 + j)) / 0.22) * alpha
                    d.text((cx, y + 24 * (1 - a)), ch, font=f, fill=BONE + (int(255 * a),))
                    cx += d.textlength(ch, font=f)
            else:
                p = (t - 0.07 * k) / 0.32
                a = ease(p) * alpha
                sc = 1.0 + (0.18 * (1 - back(p)) if mode == "pop" else 0)
                col = acc if hit and mode in ("pop", "underline", "circle", "strike") else BONE
                if hit and mode == "highlight":
                    col = (255, 255, 255)
                fs = font("cond", max(20, int(f.size * sc)))
                d.text((x + ww / 2, y + lh / 2), w, font=fs, fill=col + (int(255 * a),), anchor="mm")
            if hit and mode == "strike" and t >= land:
                g = ease((t - land) / 0.28)
                d.line((bb[0], (bb[1] + bb[3]) / 2, bb[0] + (bb[2] - bb[0]) * g, (bb[1] + bb[3]) / 2),
                       fill=acc + (int(255 * alpha),), width=12)
            if hit and mode == "underline":
                underline(d, bb[0], bb[2], bb[3] + 4, ease((t - land) / 0.35), acc + (int(255 * alpha),), 10)
            if hit and mode == "circle" and t >= land:
                g = ease((t - land) / 0.45)
                pts = _focus_ring_points(((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2, (bb[2] - bb[0]) / 2 + 26,
                                          (bb[3] - bb[1]) / 2 + 24), seed=len(w))
                n = max(2, int(len(pts) * g))
                d.line(pts[:n], fill=acc + (int(255 * alpha),), width=8, joint="curve")
            x += ww + sp
            k += 1
        y += lh
    if mode == "glitch":
        q = (t - land) / 0.35
        if 0 <= q <= 1 and int(t * 30) % 3 != 1:
            arr = np.asarray(layer).copy()
            shift = int(14 * (1 - q))
            arr[..., 0] = np.roll(arr[..., 0], shift, axis=1)
            arr[..., 2] = np.roll(arr[..., 2], -shift, axis=1)
            band_y = int(y0 + (len(lines) * lh) * ((t * 7) % 1))
            arr[band_y:band_y + 18] = np.roll(arr[band_y:band_y + 18], 30, axis=1)
            layer.paste(Image.fromarray(arr))


def _o_film_burn(layer, fields, t, dur, ctx):
    """A short warm film burn over a narrated time jump: amber blooms flare from an edge and fade (<= 0.6 s)."""
    p = t / max(0.05, dur)
    a = math.sin(math.pi * min(1, max(0, p)))
    if a <= 0.01:
        return
    yy, xx = np.mgrid[0:H // 8, 0:W // 8].astype(np.float32)
    cx, cy = W / 8 * (0.15 + 0.5 * p), H / 8 * 0.25
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / (W / 8)
    glow = np.clip(1.2 - r * 1.6, 0, 1) ** 2 * a
    rgb = np.zeros((H // 8, W // 8, 4), np.float32)
    rgb[..., 0], rgb[..., 1], rgb[..., 2] = 255, 150 + 90 * glow, 60 + 120 * glow ** 2
    rgb[..., 3] = glow * 210
    layer.alpha_composite(Image.fromarray(rgb.astype("uint8")).resize((W, H), Image.BICUBIC))


# ---------------------------------------------------------------- Hollywood context graphics (owner, Oct 31)
# Drawn over the picture on screen like every overlay (no extra image quota). Picked by pipeline/hollywood.py from
# the narration line by line; nothing here knows a story.
GEO_DIR = ROOT / "assets" / "geo"
PANEL = (80, 250, 1000, 1080)  # map panel: inside the safe area, above the captions
OCEAN, LAND, LAND_HI = (14, 24, 36), (58, 62, 66), (92, 84, 80)


@lru_cache(maxsize=1)
def geo_countries() -> list:
    import json
    p = GEO_DIR / "countries.json"
    out = json.loads(p.read_text()) if p.is_file() else []
    for c in out:
        c["_np"] = [np.radians(np.array(r, dtype=np.float32)) for r in c["rings"]]
        lons = [x for r in c["rings"] for x, _ in r]
        lats = [y for r in c["rings"] for _, y in r]
        c["_box"] = (min(lons), min(lats), max(lons), max(lats)) if lons else (0, 0, 0, 0)
    return out


@lru_cache(maxsize=8)
def geo_admin1(iso2: str) -> list:
    """The states / provinces of one country (radians rings), for faint borders when the map zooms in."""
    import json
    p = GEO_DIR / "admin1.json"
    if not p.is_file():
        return []
    return [{"name": a["name"], "_np": [np.radians(np.array(r, dtype=np.float32)) for r in a["rings"]]}
            for a in json.loads(p.read_text()) if a["iso2"] == iso2]


@lru_cache(maxsize=64)
def _flag(iso2: str):
    p = GEO_DIR / "flags" / f"{str(iso2).upper()}.png"
    return Image.open(p).convert("RGBA") if p.is_file() else None


def _ortho(ring_rad, lon0, lat0, r, cx, cy):
    """Orthographic projection of a (n, 2) radians ring; returns (points, visible mask)."""
    lon, lat = ring_rad[:, 0], ring_rad[:, 1]
    dl = lon - lon0
    cosc = math.sin(lat0) * np.sin(lat) + math.cos(lat0) * np.cos(lat) * np.cos(dl)
    x = cx + r * np.cos(lat) * np.sin(dl)
    y = cy - r * (math.cos(lat0) * np.sin(lat) - math.sin(lat0) * np.cos(lat) * np.cos(dl))
    return np.stack([x, y], 1), cosc > 0


def _extent_deg(rings) -> float:
    lons = [x for r in rings for x, _ in r]
    lats = [y for r in rings for _, y in r]
    if not lons:
        return 5.0
    return max(1.5, max(lons) - min(lons), (max(lats) - min(lats)) * 1.3)


def _o_globe_pin(layer, fields, t, dur, ctx):
    """A place the narration names: the globe spins and eases to it, zooms in, a pin with the country's flag drops
    on the spoken word (fields land). Deeper only when the narration is deeper: a named state / province is zoomed
    to and outlined in red; a named city gets the pin at the city. Labels are only the words said."""
    try:
        lon, lat = float(fields["lon"]), float(fields["lat"])
    except (KeyError, TypeError, ValueError):
        return
    land = float(fields.get("land", 1.6))
    alpha = ease(t / 0.25) * _fade_out(t, dur, 0.3)
    x0, y0, x1, y1 = PANEL
    pw, ph = x1 - x0, y1 - y0
    cx, cy = pw / 2, ph / 2
    spin_end, zoom_end = land * 0.55, land * 0.92
    s = ease(t / spin_end)
    lon0 = math.radians(lon + 150 * (1 - s))
    lat0 = math.radians(lat * s)
    r_globe = 360.0
    region = fields.get("region_rings") or []
    country = next((c for c in geo_countries() if c["iso2"] == fields.get("iso2")), None)
    ext = _extent_deg(region) if region else (_extent_deg(country["rings"]) if country else 12.0)
    r_target = max(r_globe, min(60000.0, 0.62 * pw / math.radians(ext)))
    z = ease((t - spin_end) / max(0.05, zoom_end - spin_end))
    r = r_globe * (r_target / r_globe) ** z  # zoom feels even: geometric
    panel = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(panel)
    d.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=28, fill=(8, 11, 16, 215))
    if r < 1.2 * max(pw, ph):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=OCEAN + (255,), outline=(70, 90, 110, 255), width=3)
    else:
        d.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=28, fill=OCEAN + (255,))
    view = math.degrees(min(math.pi, (max(pw, ph) / r))) + 5
    for c in geo_countries():
        bx = c["_box"]
        if r > 2 * r_globe and not (bx[0] - view < lon < bx[2] + view and bx[1] - view < lat < bx[3] + view):
            continue
        hi = c["iso2"] == fields.get("iso2") and z > 0.3 and not region
        for ring in c["_np"]:
            pts, vis = _ortho(ring, lon0, lat0, r, cx, cy)
            if vis.sum() < 3:
                continue
            pts = pts[vis]
            d.polygon([tuple(p) for p in pts], fill=(LAND_HI if hi else LAND) + (255,),
                      outline=(30, 34, 38, 255))
    if region and z > 0.2:  # the country's other states / provinces as faint borders, the named one filled
        for a in geo_admin1(fields.get("iso2") or ""):
            same = a["name"] == fields.get("region_name")
            for ring in a["_np"]:
                pts, vis = _ortho(ring, lon0, lat0, r, cx, cy)
                if vis.sum() >= 3:
                    d.polygon([tuple(q) for q in pts[vis]], fill=(LAND_HI + (255,)) if same else None,
                              outline=(96, 100, 106, int(255 * min(1.0, z * 1.5))))
    if region and z > 0.5:
        g = ease((z - 0.5) / 0.5)
        for ring in region:
            pts, vis = _ortho(np.radians(np.array(ring, dtype=np.float32)), lon0, lat0, r, cx, cy)
            if vis.sum() >= 3:
                d.line([tuple(p) for p in pts[vis]] + [tuple(pts[vis][0])], fill=(232, 36, 52, int(255 * g)), width=6)
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw - 1, ph - 1), radius=28, fill=255)
    panel.putalpha(Image.fromarray((np.asarray(mask, np.float32) * np.asarray(panel.getchannel("A"), np.float32)
                                    / 255 * alpha).astype("uint8")))
    layer.alpha_composite(panel, (x0, y0))
    d = ImageDraw.Draw(layer)
    if t >= land - 0.25:
        p = (t - (land - 0.25)) / 0.25
        drop = int(-120 * (1 - back(p))) if p < 1 else 0
        px, py = x0 + cx, y0 + cy + drop
        red = (232, 36, 52, int(255 * alpha))
        d.ellipse((px - 26, py - 92, px + 26, py - 40), fill=red)
        d.polygon([(px - 22, py - 58), (px + 22, py - 58), (px, py)], fill=red)
        d.ellipse((px - 10, py - 76, px + 10, py - 56), fill=(255, 255, 255, int(255 * alpha)))
        flag = _flag(fields.get("iso2") or "")
        label = str(fields.get("label") or "").upper()[:26]
        f = font("cond", 58)
        tw = int(d.textlength(label, font=f)) if label else 0
        fw = 0
        card_w = tw + 60 + (90 if flag else 0)
        bx0 = int(max(SAFE_X0, min(SAFE_X1 - card_w, px - card_w / 2)))
        by0 = int(py + 24)
        ca = ease((t - land) / 0.25) * alpha
        if ca > 0.02:
            d.rounded_rectangle((bx0, by0, bx0 + card_w, by0 + 84), radius=14, fill=(240, 236, 228, int(240 * ca)))
            if flag:
                fl = flag.resize((72, max(1, int(flag.height * 72 / flag.width))), Image.LANCZOS)
                fl.putalpha(fl.getchannel("A").point(lambda v: int(v * ca)))
                layer.alpha_composite(fl, (bx0 + 20, by0 + 42 - fl.height // 2))
                fw = 90
            d.text((bx0 + 30 + fw, by0 + 42), label, font=f, fill=(20, 20, 22, int(255 * ca)), anchor="lm")


OCEAN_ENDS = {  # coast-to-coast endpoints used only when the narration names the water and no two places
    "atlantic": ((-72.0, 40.5), (-6.0, 50.0)), "pacific": ((-122.4, 37.8), (139.7, 35.7)),
    "indian": ((39.7, -4.0), (100.5, 13.7)), "english channel": ((1.6, 50.7), (1.85, 51.1)),
    "mediterranean": ((-5.4, 36.1), (32.3, 31.2)), "arctic": ((-150.0, 71.0), (25.0, 70.0)),
}


def _o_ocean_crossing(layer, fields, t, dur, ctx):
    """Something crosses a named ocean: a flat map of that water, a dashed arc draws from coast to coast and a small
    plane / ship icon travels it (ease in-out), the water's name as the label."""
    a, b = fields.get("from"), fields.get("to")
    if not (a and b):
        return
    (lon_a, lat_a), (lon_b, lat_b) = a, b
    if lon_b - lon_a > 180:
        lon_b -= 360
    elif lon_a - lon_b > 180:
        lon_b += 360
    alpha = ease(t / 0.25) * _fade_out(t, dur, 0.3)
    x0, y0, x1, y1 = PANEL
    pw, ph = x1 - x0, y1 - y0
    pad = 18.0
    lo0, lo1 = min(lon_a, lon_b) - pad, max(lon_a, lon_b) + pad
    span = lo1 - lo0
    mid_lat = (lat_a + lat_b) / 2
    la0, la1 = mid_lat - span * ph / pw / 2, mid_lat + span * ph / pw / 2
    sx = lambda lo: (lo - lo0) / span * pw  # noqa: E731
    sy = lambda la: (la1 - la) / (la1 - la0) * ph  # noqa: E731
    panel = Image.new("RGBA", (pw, ph), OCEAN + (235,))
    d = ImageDraw.Draw(panel)
    for c in geo_countries():
        bx = c["_box"]
        for shift in (0, -360, 360):
            if bx[2] + shift < lo0 or bx[0] + shift > lo1 or bx[3] < la0 or bx[1] > la1:
                continue
            for ring in c["rings"]:
                d.polygon([(sx(x + shift), sy(y)) for x, y in ring], fill=LAND + (255,), outline=(30, 34, 38, 255))
    pa, pb = (sx(lon_a), sy(lat_a)), (sx(lon_b), sy(lat_b))
    bulge = -0.18 * math.hypot(pb[0] - pa[0], pb[1] - pa[1])
    def arc(u):
        mx, my = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2 + bulge
        return ((1 - u) ** 2 * pa[0] + 2 * (1 - u) * u * mx + u * u * pb[0],
                (1 - u) ** 2 * pa[1] + 2 * (1 - u) * u * my + u * u * pb[1])
    travel = float(fields.get("travel", max(0.8, dur - 0.9)))
    g = (lambda x: 3 * x * x - 2 * x ** 3)(max(0.0, min(1.0, (t - 0.3) / travel)))
    red = (232, 36, 52, 255)
    steps = 40
    for k in range(int(steps * g)):
        if k % 2 == 0:
            d.line([arc(k / steps), arc((k + 1) / steps)], fill=red, width=7)
    for p in (pa, pb):
        d.ellipse((p[0] - 11, p[1] - 11, p[0] + 11, p[1] + 11), fill=BONE + (255,))
    hx, hy = arc(g)
    tx, ty = arc(min(1.0, g + 0.01))
    ang = math.atan2(ty - hy, tx - hx)
    shape = [(34, 0), (-20, -24), (-10, 0), (-20, 24)] if fields.get("vehicle") != "ship" else \
        [(30, 0), (14, -14), (-26, -14), (-26, 14), (14, 14)]
    pts = [(hx + x * math.cos(ang) - y * math.sin(ang), hy + x * math.sin(ang) + y * math.cos(ang)) for x, y in shape]
    d.polygon(pts, fill=(255, 255, 255, 255))
    label = str(fields.get("label") or "").upper()[:26]
    if label:
        d.text((pw / 2, ph - 70), label, font=font("cond", 60), fill=BONE + (255,), anchor="mm")
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw - 1, ph - 1), radius=28, fill=int(255 * alpha))
    panel.putalpha(Image.fromarray(np.minimum(np.asarray(mask), np.asarray(panel.getchannel("A")))))
    layer.alpha_composite(panel, (x0, y0))


def _phone_panel(layer, alpha, title):
    """A phone-style control panel (rounded, frosted dark) centered in the safe area; returns its box."""
    bx = (300, 380, 780, 1010)
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle(bx, radius=56, fill=(22, 24, 30, int(225 * alpha)), outline=(90, 96, 106, int(200 * alpha)),
                        width=3)
    d.text(((bx[0] + bx[2]) / 2, bx[1] + 60), title, font=font("mono", 30), fill=BONE + (int(230 * alpha),),
           anchor="mm")
    return bx


def _o_night_mode(layer, fields, t, dur, ctx):
    """It gets dark: a phone brightness slider slides down, the night-mode moon switches on and the whole picture
    dims with it (eases in, settles)."""
    alpha = ease(t / 0.25) * _fade_out(t, dur, 0.35)
    g = ease((t - 0.3) / max(0.4, dur * 0.55))
    dim = Image.new("RGBA", (W, H), (0, 0, 10, int(125 * g * _fade_out(t, dur, 0.35))))
    layer.alpha_composite(dim)
    bx = _phone_panel(layer, alpha, str(fields.get("label") or "NIGHT MODE").upper()[:18])
    d = ImageDraw.Draw(layer)
    sx0, sy0, sx1, sy1 = bx[0] + 150, bx[1] + 130, bx[2] - 150, bx[3] - 60
    d.rounded_rectangle((sx0, sy0, sx1, sy1), radius=40, fill=(60, 64, 72, int(255 * alpha)))
    level = 0.9 - 0.78 * g
    top = sy1 - (sy1 - sy0) * level
    d.rounded_rectangle((sx0, top, sx1, sy1), radius=40, fill=(236, 230, 221, int(255 * alpha)))
    mx, my = (sx0 + sx1) / 2, sy1 - 70
    sun = 1 - g
    if sun > 0.05:
        d.ellipse((mx - 22, my - 22, mx + 22, my + 22), fill=(250, 196, 60, int(255 * alpha * sun)))
    if g > 0.05:
        d.ellipse((mx - 26, my - 26, mx + 26, my + 26), fill=(120, 140, 220, int(255 * alpha * g)))
        d.ellipse((mx - 10, my - 34, mx + 34, my + 10), fill=(60, 64, 72, int(255 * alpha * g)))


def _o_battery_low(layer, fields, t, dur, ctx):
    """A phone battery drains to empty and blinks red."""
    alpha = ease(t / 0.25) * _fade_out(t, dur, 0.3)
    bx = _phone_panel(layer, alpha, str(fields.get("label") or "BATTERY").upper()[:18])
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = bx[0] + 90, bx[1] + 240, bx[2] - 110, bx[1] + 420
    d.rounded_rectangle((x0, y0, x1, y1), radius=22, outline=BONE + (int(255 * alpha),), width=8)
    d.rounded_rectangle((x1 + 4, (y0 + y1) / 2 - 30, x1 + 26, (y0 + y1) / 2 + 30), radius=6,
                        fill=BONE + (int(255 * alpha),))
    lvl = max(0.04, 0.8 - 0.76 * ease((t - 0.2) / max(0.5, dur * 0.6)))
    red = lvl < 0.2
    on = not red or int(t * 4) % 2 == 0
    if on:
        col = (232, 36, 52) if red else (90, 200, 120)
        d.rounded_rectangle((x0 + 14, y0 + 14, x0 + 14 + (x1 - x0 - 28) * lvl, y1 - 14), radius=12,
                            fill=col + (int(255 * alpha),))
    d.text(((bx[0] + bx[2]) / 2, y1 + 90), f"{int(lvl * 100)}%", font=font("cond", 90),
           fill=((232, 36, 52) if red else BONE) + (int(255 * alpha),), anchor="mm")


def _o_signal_lost(layer, fields, t, dur, ctx):
    """Signal bars drop one by one to none, then NO SIGNAL."""
    alpha = ease(t / 0.25) * _fade_out(t, dur, 0.3)
    bx = _phone_panel(layer, alpha, str(fields.get("label") or "SIGNAL").upper()[:18])
    d = ImageDraw.Draw(layer)
    g = ease((t - 0.2) / max(0.5, dur * 0.55))
    bars = 4 - int(round(4 * g))
    base = bx[1] + 470
    for k in range(4):
        x = bx[0] + 120 + k * 70
        h = 60 + k * 50
        on = k < bars
        d.rounded_rectangle((x, base - h, x + 46, base), radius=8,
                            fill=(BONE if on else (70, 74, 82)) + (int(255 * alpha),))
    if bars == 0:
        d.text(((bx[0] + bx[2]) / 2, base + 110), "NO SIGNAL", font=font("cond", 72),
               fill=(232, 36, 52, int(255 * alpha)), anchor="mm")


def _o_temperature_drop(layer, fields, t, dur, ctx):
    """A thermometer's level falls and frost creeps in at the frame edges."""
    alpha = ease(t / 0.25) * _fade_out(t, dur, 0.3)
    g = ease((t - 0.2) / max(0.5, dur * 0.6))
    frost = Image.new("RGBA", (W // 8, H // 8), (0, 0, 0, 0))
    yy, xx = np.mgrid[0:H // 8, 0:W // 8].astype(np.float32)
    edge = np.minimum(np.minimum(xx, W // 8 - xx), np.minimum(yy, H // 8 - yy)) / 30
    a = np.clip(1 - edge, 0, 1) ** 3 * 90 * g * alpha
    frost = Image.fromarray(np.dstack([np.full_like(a, 200), np.full_like(a, 225), np.full_like(a, 255), a])
                            .astype("uint8")).resize((W, H), Image.BICUBIC)
    layer.alpha_composite(frost)
    d = ImageDraw.Draw(layer)
    cx, top, bot = 540, 380, 900
    d.rounded_rectangle((cx - 34, top, cx + 34, bot), radius=34, fill=(30, 34, 40, int(230 * alpha)),
                        outline=BONE + (int(255 * alpha),), width=6)
    d.ellipse((cx - 64, bot - 30, cx + 64, bot + 98), fill=(30, 34, 40, int(230 * alpha)),
              outline=BONE + (int(255 * alpha),), width=6)
    lvl = 0.85 - 0.7 * g
    col = (int(232 - 160 * g), int(36 + 120 * g), int(52 + 190 * g))
    d.ellipse((cx - 46, bot - 12, cx + 46, bot + 80), fill=col + (int(255 * alpha),))
    d.rectangle((cx - 16, bot - (bot - top - 30) * lvl, cx + 16, bot), fill=col + (int(255 * alpha),))
    label = str(fields.get("label") or "").upper()[:20]
    if label:
        d.text((cx, bot + 160), label, font=font("cond", 66), fill=BONE + (int(255 * alpha),), anchor="mm")


def _o_sticky_note(layer, fields, t, dur, ctx):
    """A small detail worth remembering: a yellow sticky note slaps on at a slight tilt with the detail written on
    it (the narration's own words). Used for small details only; bigger beats get bigger graphics."""
    text = str(fields.get("text") or "")[:60]
    if not text:
        return
    land = float(fields.get("land", 0.25))
    p = t / land
    a = _fade_out(t, dur, 0.3) * (ease(p) if t < land else 1.0)
    note = Image.new("RGBA", (440, 400), (0, 0, 0, 0))
    dn = ImageDraw.Draw(note)
    dn.rectangle((10, 10, 430, 390), fill=(0, 0, 0, 70))
    dn.rectangle((0, 0, 420, 380), fill=(246, 214, 92, 255))
    dn.rectangle((0, 0, 420, 46), fill=(232, 196, 70, 255))
    f, lines = fit(text.upper(), "cond_med", 360, 4, 64, 34)
    y = 80
    for ln in lines:
        dn.text((30, y), ln, font=f, fill=(40, 34, 30, 255))
        y += int(f.size * 1.12)
    sc = 1.25 - 0.25 * back(p) if t < land else 1.0
    note = note.rotate(-6 + 3 * (1 - min(1, p)), resample=Image.BICUBIC, expand=True)
    if abs(sc - 1) > 0.003:
        note = note.resize((max(1, int(note.width * sc)), max(1, int(note.height * sc))), Image.BILINEAR)
    note.putalpha(note.getchannel("A").point(lambda v: int(v * a)))
    paste(layer, note, int(W - 120 - note.width), 420)
