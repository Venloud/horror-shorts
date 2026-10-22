"""DARK EDITORIAL NOIR motion graphics for the explainer style (owner, Oct 21): midnight / charcoal / smoked taupe
grounds with muted paper grain, bold condensed type, selective hot-magenta highlights. Muted parchment only inside
small evidence / document / photo elements, never as a full-screen background.

Every template is drawn locally (0 Cloudflare neurons), takes the story's own words / verified numbers through
`fields`, and animates over its segment; word-synced reveals use the segment's narration word timings
(`ctx["words"]`: [{"word", "start"}] relative to the segment). Nothing is specific to one story.

render(template, fields, t, dur, ctx) -> RGBA 1080x1920 frame. Templates (TEMPLATES): true_story, title, evidence,
map_route, fact, filmstrip, quote, impact, connections, compare, missing, closing.
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
TEMPLATES = ("true_story", "title", "evidence", "map_route", "fact", "filmstrip", "quote", "impact", "connections",
             "compare", "missing", "closing")


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
    return ground(ctx.get("tone", "midnight"), ctx.get("seed", 1)).copy()


def _t_true_story(fields, t, dur, ctx):
    """TRUE STORY opener: slab slams in (overshoot, shake, flash), film edges and sweep lines, then wipes up."""
    acc = ctx["accent"]
    frame = ctx.get("bg") or _base(ctx)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    out = ease((t - (dur - 0.25)) / 0.25)
    for j in range(4):  # film perforations down both edges
        for y in range(0, H, 90):
            d.rounded_rectangle((18, y + 20, 48, y + 60), radius=6, fill=(0, 0, 0, 120))
            d.rounded_rectangle((W - 48, y + 20, W - 18, y + 60), radius=6, fill=(0, 0, 0, 120))
        break
    for j in range(3):
        g = ease((t - 0.06 * j) / 0.35)
        d.line((W * (1 - g), 700 + 210 * j, W, 700 + 210 * j), fill=acc + (150,), width=4)
    k = back(t / 0.22)
    f = font("cond", 190)
    label = "TRUE STORY"
    tw = int(d.textlength(label, font=f))
    slab = Image.new("RGBA", (tw + 120, 270), (0, 0, 0, 0))
    ds = ImageDraw.Draw(slab)
    ds.rectangle((0, 0, slab.width, slab.height), fill=acc + (255,))
    ds.text((60, -8), label, font=f, fill=(255, 255, 255))
    sc = max(0.05, 1.8 - 0.8 * min(1.12, k)) * min(1.0, 880 / slab.width)
    s2 = slab.resize((max(1, int(slab.width * sc)), max(1, int(slab.height * sc))), Image.BILINEAR)
    shake = 9 * math.sin(t * 95) * max(0.0, 1 - abs(t - 0.24) / 0.12) if 0.12 < t < 0.4 else 0
    if out < 1:
        s2.putalpha(s2.getchannel("A").point(lambda a: int(a * (1 - out))))
        paste(frame, s2, int(W / 2 - s2.width / 2 + shake), int(820 - s2.height / 2 - 900 * out))
    flash = max(0.0, 1 - abs(t - 0.2) / 0.1)
    if flash:
        frame.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, int(90 * flash))))
    d.text((W / 2, 1040 - 900 * out), fields.get("kicker") or "NIGHT FILES", font=font("mono", 32),
           fill=PARCHMENT + (int(255 * (1 - out)),), anchor="mm")
    frame.alpha_composite(ov)
    return frame


def _t_title(fields, t, dur, ctx):
    """Documentary title: tracked letters settle, magenta rule wipes, case-file kicker; slides up at the end."""
    acc = ctx["accent"]
    frame = ctx.get("bg") or _base(ctx)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    title = str(fields.get("text") or "").upper()
    f, lines = fit(title, "cond", 880, 3, 140)
    spacing = 30 * (1 - ease(t / 0.6))
    out = ease((t - (dur - 0.22)) / 0.22)
    y = 820 - len(lines) * f.size * 0.55 - 240 * out
    kicker(d, fields.get("kicker") or "NIGHT FILES · CASE FILE", 110, int(y - 70), t, acc)
    k = 0
    for line in lines:
        widths = [d.textlength(ch, font=f) for ch in line]
        total = sum(widths) + spacing * (len(line) - 1)
        x = (W - total) / 2
        for ch, w in zip(line, widths):
            a = ease((t - 0.02 * k) / 0.2) * (1 - out)
            if a > 0.01 and ch != " ":
                d.text((x, y), ch, font=f, fill=BONE + (int(255 * a),))
            x += w + spacing
            k += 1
        y += int(f.size * 1.08)
    g = ease((t - 0.35) / 0.4)
    d.rectangle((W / 2 - 260 * g, y + 24, W / 2 + 260 * g, y + 34), fill=acc + (int(255 * (1 - out)),))
    frame.alpha_composite(ov)
    return frame


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
    """One or two impact words, huge, with a hand-drawn magenta underline; slow push."""
    acc = ctx["accent"]
    frame = ctx.get("bg") or _base(ctx)
    words = str(fields.get("text") or "").upper()
    z = 1.0 + 0.03 * ease(t / max(dur, 0.1))
    f, lines = fit(words, "cond", int(880 / z), 3, int(230 * z), 90)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    lh = int(f.size * 1.02)
    y = 860 - len(lines) * lh // 2
    for k, line in enumerate(lines):
        at = spoken_at(line.split()[0], ctx, 0.08 * k)
        a = back((t - at) / 0.22)
        if a <= 0.02:
            continue
        lw = d.textlength(line, font=f)
        x = (W - lw) / 2
        d.text((x, y + int(30 * (1 - min(1, a)))), line, font=f, fill=BONE + (int(255 * min(1, a)),))
        if k == len(lines) - 1 or any(_same(w, fields.get("accent", "")) for w in line.split()):
            underline(d, x, x + lw, d.textbbox((x, y), line, font=f)[3] + 18, ease((t - at - 0.2) / 0.35), acc, 16)
        y += lh
    frame.alpha_composite(ov)
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
