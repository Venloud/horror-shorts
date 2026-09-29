"""Free motion effects that make still pictures feel alive:
- 2.5D depth parallax: a small free depth model (Depth Anything V2 Small, runs on CPU) estimates what is near
  and far, and the camera drifts so the foreground moves more than the background.
- Drifting fog and floating dust overlays.
- Light flicker on scenes that mention lights; a short camera shake on the twist.
Everything falls back to the plain Ken Burns zoom if anything is missing or fails.
"""
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from common import CONFIG, log

W, H, FPS = 1080, 1920, 30
_DEPTH = {"pipe": None, "failed": False}


def enabled(name: str) -> bool:
    return bool(CONFIG.get("effects", {}).get(name, True))


# ---------- depth parallax ----------

def depth_map(img: Path) -> np.ndarray | None:
    """0..1 map where 1 = nearest. None if the depth model can't run here."""
    if _DEPTH["failed"] or not enabled("parallax"):
        return None
    try:
        if _DEPTH["pipe"] is None:
            from transformers import pipeline
            _DEPTH["pipe"] = pipeline("depth-estimation",
                                      model=CONFIG.get("depth_model", "depth-anything/Depth-Anything-V2-Small-hf"),
                                      device=-1)
            log("Depth model loaded (3D parallax on)")
        out = _DEPTH["pipe"](Image.open(img).convert("RGB"))
        d = np.asarray(out["depth"], dtype=np.float32)
        d = (d - d.min()) / max(1e-6, float(d.max() - d.min()))
        return d
    except Exception as e:  # noqa: BLE001
        _DEPTH["failed"] = True
        log(f"3D parallax off for this run ({str(e)[:150]}); using normal zooms")
        return None


PARALLAX_MOVES = ("dolly_in", "dolly_out", "drift_left", "drift_right", "rise")


def parallax_clip(img: Path, depth: np.ndarray, seconds: float, move: str, out: Path) -> Path:
    """Render one shot with depth-based camera motion straight into an mp4."""
    import cv2
    frames = max(2, int(round(seconds * FPS)))
    margin = 1.16
    sw, sh = int(W * margin), int(H * margin)
    src = Image.open(img).convert("RGB")
    scale = max(sw / src.width, sh / src.height)
    src = src.resize((int(src.width * scale) + 1, int(src.height * scale) + 1), Image.LANCZOS)
    left, top = (src.width - sw) // 2, (src.height - sh) // 2
    src = np.asarray(src.crop((left, top, left + sw, top + sh)))[:, :, ::-1].copy()  # RGB -> BGR

    d = Image.fromarray((depth * 255).astype(np.uint8)).resize((sw, sh), Image.BILINEAR)
    d = np.asarray(d.filter(ImageFilter.GaussianBlur(9)), dtype=np.float32) / 255.0
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    # depth at each output pixel (static approximation is fine for small moves)
    d_out = cv2.remap(d, xs + (sw - W) / 2, ys + (sh - H) / 2, cv2.INTER_LINEAR)
    dc = d_out - 0.5

    amp = W * 0.028          # how far near objects slide (px)
    zamp = 0.07              # dolly zoom amount
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
         "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    try:
        for f in range(frames):
            p = f / max(1, frames - 1)
            p = p * p * (3 - 2 * p)  # ease in/out
            zoom, cx, cy = 1.0, 0.0, 0.0
            if move == "dolly_in":
                zoom = 1.0 + zamp * p
            elif move == "dolly_out":
                zoom = 1.0 + zamp * (1 - p)
            elif move == "drift_left":
                cx, zoom = amp * (p - 0.5) * 2, 1.03
            elif move == "drift_right":
                cx, zoom = -amp * (p - 0.5) * 2, 1.03
            else:  # rise
                cy, zoom = amp * (p - 0.5) * 2, 1.03
            # near pixels (dc > 0) zoom and slide more than far ones -> 3D feel
            zl = zoom * (1 + (zoom - 1) * 0.9 * dc * 2)
            mx = sw / 2 + (xs - W / 2) / zl - cx * (0.35 + d_out)
            my = sh / 2 + (ys - H / 2) / zl - cy * (0.35 + d_out)
            frame = cv2.remap(src, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError("parallax encode failed")
    return out


# ---------- overlays ----------

def make_textures(workdir: Path) -> dict:
    """Seamless fog (scrolls sideways) and dust (drifts up) textures, made fresh with numpy."""
    rng = np.random.default_rng()
    tex = {}
    if enabled("fog"):
        small = rng.random((24, 20)).astype(np.float32)
        small = np.concatenate([small, small], axis=1)  # repeat -> seamless when scrolled by W
        fog = Image.fromarray((small * 255).astype(np.uint8)).resize((W * 2, H), Image.BICUBIC)
        fog = fog.filter(ImageFilter.GaussianBlur(60))
        a = np.asarray(fog, dtype=np.float32) / 255.0
        a = np.clip((a - 0.35) * 1.6, 0, 1) * float(CONFIG.get("effects", {}).get("fog_strength", 0.22))
        rgba = np.zeros((H, W * 2, 4), np.uint8)
        rgba[..., :3] = 215
        rgba[..., 3] = (a * 255).astype(np.uint8)
        tex["fog"] = workdir / "fog.png"
        Image.fromarray(rgba, "RGBA").save(tex["fog"])
    if enabled("dust"):
        rgba = np.zeros((H, W, 4), np.uint8)
        for _ in range(170):
            x, y = int(rng.integers(0, W)), int(rng.integers(0, H))
            r = int(rng.integers(1, 4))
            alpha = int(rng.integers(60, 170))
            y0, y1, x0, x1 = max(0, y - r), min(H, y + r + 1), max(0, x - r), min(W, x + r + 1)
            rgba[y0:y1, x0:x1, :3] = 235
            rgba[y0:y1, x0:x1, 3] = np.maximum(rgba[y0:y1, x0:x1, 3], alpha)
        dust = Image.fromarray(rgba, "RGBA").filter(ImageFilter.GaussianBlur(1.2))
        tall = Image.new("RGBA", (W, H * 2))
        tall.paste(dust, (0, 0)); tall.paste(dust, (0, H))  # seamless vertical loop
        tex["dust"] = workdir / "dust.png"
        tall.save(tex["dust"])
    return tex


LIGHT_WORDS = ("light", "lamp", "bulb", "flicker", "candle", "tv", "television", "screen", "flashlight", "neon", "lantern")


def flicker_expr(story: dict, starts: list[float], total: float) -> str | None:
    """eq brightness expression that flickers during scenes that mention lights."""
    if not enabled("flicker"):
        return None
    spans = []
    for i, sc in enumerate(story.get("scenes", [])):
        text = sc.get("narration", "").lower()
        if i < len(starts) and any(w in text.split() or w in text for w in LIGHT_WORDS):
            end = starts[i + 1] if i + 1 < len(starts) else total
            spans.append(f"between(t,{starts[i]:.2f},{end:.2f})")
    if not spans:
        return None
    on = "+".join(spans)
    return f"-0.09*gt({on},0)*(gt(sin(t*31),0.72)+0.6*gt(sin(t*11+2),0.86))"


def shake_expr(story: dict, starts: list[float], extra: list[float] | None = None) -> tuple[str, str] | None:
    """Camera shake on the twist (+ `extra` moments, e.g. the hook's end in fast mode)."""
    if not enabled("shake"):
        return None
    tw = int(story.get("twist_scene", -1))
    times = ([starts[tw]] if 0 < tw < len(starts) else []) + list(extra or [])
    if not times:
        return None
    on = "+".join(f"between(t,{a:.2f},{a + 0.45:.2f})" for a in times)
    on = f"gt({on},0)"
    return (f"(iw-ow)/2+if({on},16*sin(t*71),0)", f"(ih-oh)/2+if({on},12*cos(t*89),0)")
