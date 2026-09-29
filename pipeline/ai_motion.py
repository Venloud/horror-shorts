"""Real AI animation for the hook shot, using free Hugging Face ZeroGPU Spaces (Wan, LTX...).

Nothing is hard-wired to one Space: the Space list lives in config.json ("ai_motion" -> "spaces"), and for each
Space the code reads its live API, finds the endpoint that takes an image + a prompt, fills in what it can
recognise (image, prompt, size, length) and leaves every other setting at the Space's own default.
Any failure (queue, quota, Space paused, API changed, timeout) just moves on to the next Space, and if all of
them fail the shot uses the free 3D parallax instead. The video is never blocked by this step.
"""
import json
import os
import re
import shutil
import time
from pathlib import Path

from common import CONFIG, log, media_duration

VIDEO_EXT = (".mp4", ".webm", ".mov", ".mkv", ".gif")
QUOTA_RE = re.compile(r"\((\d+)s requested vs\. (-?\d+)s left\)")


def _settings() -> dict:
    s = {"enabled": True, "max_shots": 1, "seconds": 2, "timeout": 240, "total_budget": 420,
         "spaces": ["multimodalart/wan2-1-fast", "DeepRat/LTX-Video-ZeroGPU-Optimized", "Lightricks/ltx-video-distilled"]}
    s.update(CONFIG.get("ai_motion", {}))
    return s


def _find_endpoint(info: dict):
    """Pick the named endpoint that takes an image and a text prompt."""
    best = None
    for name, ep in (info.get("named_endpoints") or {}).items():
        params = ep.get("parameters", [])
        img = [p for p in params if "image" in (p.get("component", "") + p.get("parameter_name", "")).lower()
               and "video" not in p.get("parameter_name", "").lower()]
        txt = [p for p in params if "prompt" in p.get("parameter_name", "").lower()
               and "negative" not in p.get("parameter_name", "").lower()]
        if not img or not txt:
            continue
        score = 0
        low = name.lower()
        score += 3 if "video" in low or "generate" in low else 0
        score += 2 if "i2v" in low or "image" in low else 0
        score -= 5 if "t2v" in low or "text" in low else 0
        if best is None or score > best[0]:
            best = (score, name, params)
    return (best[1], best[2]) if best else (None, None)


def _fill(params: list, image: Path, prompt: str, seconds: float) -> dict:
    """Fill the parameters we recognise; everything else keeps the Space's own default."""
    from gradio_client import handle_file
    kw, image_done = {}, False
    for p in params:
        name = p.get("parameter_name") or ""
        low = name.lower()
        comp = (p.get("component") or "").lower()
        if not name:
            continue
        if not image_done and ("image" in comp or "image" in low) and "video" not in low:
            kw[name] = handle_file(str(image))
            image_done = True
        elif "negative" in low:
            kw[name] = "blurry, distorted face, deformed hands, extra limbs, text, watermark, fast chaotic motion, low quality"
        elif "prompt" in low:
            kw[name] = prompt
        elif low == "height":
            kw[name] = 832
        elif low == "width":
            kw[name] = 480
        elif "duration" in low or low in ("seconds", "length_seconds"):
            kw[name] = seconds
    return kw


def _video_path(result) -> str | None:
    """Spaces return a path, a dict like {"video": path}, or a tuple; find the video file in it."""
    stack = [result]
    while stack:
        r = stack.pop()
        if isinstance(r, str) and r.lower().endswith(VIDEO_EXT) and os.path.exists(r):
            return r
        if isinstance(r, dict):
            stack.extend(r.values())
        elif isinstance(r, (list, tuple)):
            stack.extend(r)
    return None


def _connect(Client, space: str, token):
    """gradio_client renamed its login argument over time (hf_token -> token); try both, then no login."""
    for kw in ({"token": token}, {"hf_token": token}, {}):
        if kw and not token:
            continue
        try:
            return Client(space, verbose=False, **kw)
        except TypeError:
            continue
    return Client(space)


def animate(image: Path, shot_prompt: str, out: Path) -> Path | None:
    """Try each Space in turn. Returns the animated clip, or None to use the free 3D effect."""
    s = _settings()
    token = os.environ.get("HF_TOKEN") or None
    if not s["enabled"]:
        return None
    try:
        from gradio_client import Client
    except Exception as e:  # noqa: BLE001
        log(f"AI animation off (gradio_client not installed: {e})")
        return None
    prompt = (f"{shot_prompt}. Subtle cinematic motion: slow camera push-in, fog drifting, small natural "
              f"movements, eerie atmosphere, consistent illustrated art style, no sudden changes. Preserve the exact "
              f"composition, character identity, clothing, location and object positions. Do not add or remove "
              f"people or objects. Do not morph faces.")
    start = time.time()
    for space in s["spaces"]:
        if time.time() - start > s["total_budget"]:
            log("AI animation: time budget used up, using the free 3D effect")
            break
        try:
            client = _connect(Client, space, token)
            info = client.view_api(return_format="dict", print_info=False)
            endpoint, params = _find_endpoint(info)
            if not endpoint:
                log(f"AI animation: {space} has no image+prompt endpoint, skipping")
                continue
            kwargs = _fill(params, image, prompt, float(s["seconds"]))
            log(f"AI animation: trying {space} {endpoint} ({', '.join(kwargs)})")
            job = client.submit(api_name=endpoint, **kwargs)
            try:
                result = job.result(timeout=s["timeout"])
            except Exception:
                try:
                    job.cancel()  # don't leave a queued job eating GPU quota
                except Exception:  # noqa: BLE001
                    pass
                raise
            path = _video_path(result)
            if not path:
                log(f"AI animation: {space} returned no video ({json.dumps(str(result))[:120]})")
                continue
            shutil.copy(path, out)
            if media_duration(out) < 0.8:
                log(f"AI animation: {space} clip too short, skipping")
                continue
            log(f"AI animation: got a {media_duration(out):.1f}s clip from {space}")
            return out
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            log(f"AI animation: {space} failed ({type(e).__name__}: {msg[:160]})")
            # The GPU quota is shared by every Space. "Xs requested vs. Ys left" only means THIS Space asks for
            # too much: a cheaper Space may still fit. Stop only on the hard runs limit or when nothing is left.
            m = QUOTA_RE.search(msg)
            if m:
                requested, left = int(m.group(1)), int(m.group(2))
                log(f"AI animation: ZeroGPU quota: {space} requested {requested}s, {left}s left")
                if left <= 0:
                    log("AI animation: no free GPU time left today, using the free 3D effect")
                    break
            elif "runs limit" in msg.lower():
                log("AI animation: ZeroGPU runs limit reached for today, using the free 3D effect")
                break
    return None
