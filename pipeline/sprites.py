"""The owner's host sprites (assets/character/host, cut from his sheets on Oct 21): the stick-figure host in a
black suit, white shirt and red tie. index.json lists every cut-out with its action / view / expression / prop.

draw(who, look, action, expression, view, facing, t, height) -> (RGBA, (foot_x, foot_y)) like stickman.draw:
- the best sprite for the action + view + expression (synonyms, then view, then expression; a big prop such as a
  door, train, stairs or bench only when the action needs it);
- walking / running / sneaking / stepping cycle through every frame of that action (4 / 8 / 3 frames a second);
- idle sprites breathe (tiny scale) so a held shot is never a frozen picture;
- a thin light rim keeps the black suit readable on dark painted places;
- other people (cast) are the same drawing recoloured (coat colour, tie dark) with a hat drawn on, crowds are grey
  silhouettes, so everyone stays in the owner's art style.
Without the library (or for an action it can't cover at all) the caller falls back to the code rig (stickman.py).
"""
import json
import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from common import ROOT

DIR = ROOT / "assets" / "character" / "host"
ACTION_ALIASES = {
    "observing": "looking", "turning": "standing", "presenting": "presenting", "reaching": "inspecting",
    "boarding": "walking",  # the train-door sprite reads as a pasted box; walking toward the train instead "seated": "seated", "holding": "holding", "waiting": "waiting", "scared": "scared",
    "reacting": "reacting", "leaving": "leaving", "sneaking": "sneaking", "thinking": "thinking",
}
CYCLE_FPS = {"walking": 4.0, "running": 8.0, "sneaking": 3.0, "stepping_up": 2.0}
SCENE_PROPS = {"stairs", "train_door", "door", "bench", "wall", "crate"}  # drawn into the sprite
PROP_FOR = {"stepping_up": {"stairs"}, "knocking": {"door"},
            "seated": {"bench", "crate", ""}, "leaning": {"wall"}}


@lru_cache(maxsize=1)
def library() -> list[dict]:
    try:
        idx = json.loads((DIR / "index.json").read_text())["sprites"]
    except (OSError, ValueError, KeyError):
        return []
    return [s for s in idx if (DIR / s["file"]).exists()]


def available() -> bool:
    return bool(library())


def actions() -> list[str]:
    return sorted({s["action"] for s in library()})


def expressions() -> list[str]:
    return sorted({s["expression"] for s in library()})


def _score(s: dict, action: str, view: str, expr: str) -> float:
    sc = 0.0
    if s["action"] == action:
        sc += 10
    elif action in ("standing", "observing", "looking") and s["action"] == "standing":
        sc += 6
    if s["view"] == view:
        sc += 4
    elif {s["view"], view} <= {"front", "three_quarter"}:
        sc += 2
    if s["expression"] == expr:
        sc += 2
    elif {s["expression"], expr} <= {"worried", "scared", "shocked"} or {s["expression"], expr} <= {
            "determined", "confident", "angry"} or {s["expression"], expr} <= {"curious", "confused", "neutral"}:
        sc += 1
    if s["prop"] in SCENE_PROPS and s["prop"] not in PROP_FOR.get(action, set()):
        sc -= 8  # a door / stairs / train drawn into the sprite only where the story has one
    return sc


def frames(action: str, view: str, expr: str) -> list[dict]:
    """The sprite(s) for this beat: all frames of a cycle action, else the single best match."""
    lib = library()
    if not lib:
        return []
    action = ACTION_ALIASES.get(action, action)
    if action in CYCLE_FPS:
        cyc = [s for s in lib if s["action"] == action and s["prop"] not in SCENE_PROPS - PROP_FOR.get(action, set())]
        if cyc:
            return sorted(cyc, key=lambda s: s["file"])
    best = max(lib, key=lambda s: (_score(s, action, view, expr), s["file"]))
    return [best]


@lru_cache(maxsize=160)
def _load(file: str, height: int, tint: tuple | None, hat: str, gray: bool) -> Image.Image:
    im = Image.open(DIR / file).convert("RGBA")
    if tint or gray:
        im = _recolor(im, tint, gray)
    w = max(1, round(im.width * height / im.height))
    im = im.resize((w, height), Image.LANCZOS).filter(ImageFilter.UnsharpMask(3, 120, 2))
    if hat and not gray:
        im = _hat(im, hat)
    if not gray:  # thin light rim: the black suit stays readable on dark painted places
        a = im.getchannel("A")
        rim = a.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(2))
        glow = Image.new("RGBA", im.size, (235, 235, 240, 0))
        glow.putalpha(rim.point(lambda v: int(v * 0.42)))
        glow.alpha_composite(im)
        im = glow
    return im


def _recolor(im: Image.Image, tint: tuple | None, gray: bool) -> Image.Image:
    a = np.asarray(im).astype(np.float32)
    rgb, al = a[..., :3], a[..., 3:]
    if gray:
        out = np.concatenate([np.full_like(rgb, 70), al * 0.55], axis=2)
        return Image.fromarray(out.astype("uint8"))
    lum = rgb.mean(axis=2, keepdims=True)
    red = (rgb[..., 0:1] > 140) & (rgb[..., 1:2] < 90) & (rgb[..., 2:3] < 90)
    dark = lum < 90
    t = np.array(tint, dtype=np.float32)[None, None, :]
    rgb = np.where(dark, t * (0.35 + lum / 90 * 0.65), rgb)  # suit -> their coat colour, keeping the shading
    rgb = np.where(red, np.array([40, 40, 46], dtype=np.float32)[None, None, :], rgb)  # the red tie is the host's
    return Image.fromarray(np.concatenate([np.clip(rgb, 0, 255), al], axis=2).astype("uint8"))


def _head_box(im: Image.Image) -> tuple[int, int, int] | None:
    """(centre x, top y, width) of the round white head: the first band of bright rows from the top."""
    a = np.asarray(im)
    top = a[: int(a.shape[0] * 0.4)]
    bright = (top[..., 3] > 200) & (top[..., :3].min(axis=2) > 200)
    rows = np.flatnonzero(bright.sum(axis=1) > 3)
    if not len(rows):
        return None
    y0 = rows[0]
    band = bright[y0:y0 + max(4, int(a.shape[0] * 0.08))]
    xs = np.flatnonzero(band.any(axis=0))
    return int((xs.min() + xs.max()) / 2), int(y0), int(xs.max() - xs.min())


def _hat(im: Image.Image, hat: str) -> Image.Image:
    hb = _head_box(im)
    if not hb:
        return im
    cx, y0, w = hb
    w = int(w * 1.15)
    pad = int(w * 0.9)
    out = Image.new("RGBA", (im.width, im.height + pad), (0, 0, 0, 0))
    out.alpha_composite(im, (0, pad))
    d = ImageDraw.Draw(out)
    y = y0 + pad
    col = (26, 26, 30, 255)
    if hat == "top":
        d.rectangle((cx - w * 0.33, y - w * 0.75, cx + w * 0.33, y + w * 0.08), fill=col)
    else:  # bowler / cap
        d.chord((cx - w * 0.4, y - w * 0.42, cx + w * 0.4, y + w * 0.38), 180, 360, fill=col)
    d.rounded_rectangle((cx - w * 0.55, y - 1, cx + w * 0.55, y + w * 0.07), radius=max(2, w // 20), fill=col)
    return out


def draw(who: str, look: dict, action: str, expression: str, view: str, facing: str, t: float,
         height: int) -> tuple | None:
    fr = frames(action, view, expression)
    if not fr:
        return None
    base = ACTION_ALIASES.get(action, action)
    k = int(t * CYCLE_FPS.get(base, 0)) % len(fr) if base in CYCLE_FPS else 0
    s = fr[k]
    host = who == "you"
    gray = who == "crowd"
    tint = None if host or gray else tuple(look.get("jacket") or (88, 74, 60))
    hat = "" if host or gray else (look.get("hat") or "")
    breath = 1.0 if base in CYCLE_FPS else 1.0 + 0.008 * math.sin(t * 2.6)
    im = _load(s["file"], int(height), tint, hat, gray)
    if abs(breath - 1.0) > 0.001:
        im = im.resize((im.width, max(1, int(im.height * breath))), Image.BILINEAR)
    flip = (facing == "left") != (s.get("facing", "right") == "left")
    if flip:
        im = ImageOps.mirror(im)
    return im, (im.width / 2, im.height)
