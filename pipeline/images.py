"""Generates one image per scene. Cloudflare Workers AI (Flux schnell) first, Pollinations as free fallback."""
import base64
import random
import shutil
import urllib.parse
from pathlib import Path

import requests
from PIL import Image

from common import CONFIG, env, log

_STATE = {"cf_out": False}
HF_URL = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
CF_URL = "https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/black-forest-labs/flux-1-schnell"


def _cloudflare(prompt: str, seed: int) -> bytes:
    acct = env("CLOUDFLARE_ACCOUNT_ID")
    token = env("CLOUDFLARE_API_TOKEN")
    r = requests.post(CF_URL.format(acct=acct), timeout=120,
                      headers={"Authorization": f"Bearer {token}"},
                      json={"prompt": prompt[:2000], "steps": int(CONFIG.get("image_steps", 4))})
    if r.status_code == 429 or "daily free allocation" in r.text:
        _STATE["cf_out"] = True
        raise RuntimeError("Cloudflare daily free limit used up (resets 00:00 UTC)")
    if r.status_code != 200:
        raise RuntimeError(f"Cloudflare HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    img_b64 = (data.get("result") or {}).get("image") or data.get("image")
    if not img_b64:
        raise RuntimeError(f"Cloudflare returned no image: {str(data)[:300]}")
    return base64.b64decode(img_b64)


def _huggingface(prompt: str, seed: int) -> bytes:
    """Free backup: Hugging Face Inference (FLUX.1 schnell), needs HF_TOKEN."""
    token = env("HF_TOKEN", required=False)
    if not token:
        raise RuntimeError("no HF_TOKEN secret")
    r = requests.post(HF_URL, timeout=180, headers={"Authorization": f"Bearer {token}", "Accept": "image/png"},
                      json={"inputs": prompt[:1500],
                            "parameters": {"width": 768, "height": 1344, "num_inference_steps": 4, "seed": seed}})
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
        raise RuntimeError(f"Hugging Face HTTP {r.status_code}: {r.text[:200]}")
    return r.content


def _pollinations(prompt: str, seed: int) -> bytes:
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:1500])
           + f"?width=1080&height=1920&seed={seed}&nologo=true&model=flux")
    r = requests.get(url, timeout=180)
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
        raise RuntimeError(f"Pollinations HTTP {r.status_code}")
    # Pollinations stamps a small logo in the bottom corner: crop the bottom 7% off.
    import io
    with Image.open(io.BytesIO(r.content)) as im:
        im = im.convert("RGB")
        im = im.crop((0, 0, im.width, int(im.height * 0.93)))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()


def _save_valid(raw: bytes, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(raw)
    with Image.open(tmp) as im:
        im = im.convert("RGB")
        if im.width < 256 or im.height < 256:
            raise RuntimeError("image too small")
        im.save(path, "PNG")
    tmp.unlink(missing_ok=True)


def generate_images(story: dict, outdir: Path) -> list[list[Path]]:
    """Two images per scene (shot A = first half, shot B = second half). Returns [[a, b], ...]."""
    outdir.mkdir(parents=True, exist_ok=True)
    style = CONFIG["image_style"]
    base_seed = random.randint(1, 2_000_000_000)
    use_cf = bool(env("CLOUDFLARE_API_TOKEN", required=False))

    jobs = []  # (scene index, shot letter, prompt)
    for i, scene in enumerate(story["scenes"]):
        jobs.append((i, "a", scene["image_prompt"]))
        second = scene.get("image_prompt_2") or ""
        if second.strip():
            jobs.append((i, "b", second))

    results: dict[tuple[int, str], Path | None] = {}
    for n, (i, shot, raw_prompt) in enumerate(jobs):
        prompt = f"{raw_prompt}. {style}"
        path = outdir / f"scene_{i:02d}{shot}.png"
        ok = False
        providers = ([_cloudflare] if use_cf and not _STATE["cf_out"] else []) + [_huggingface, _pollinations]
        for provider in providers:
            for attempt in range(2):
                try:
                    _save_valid(provider(prompt, base_seed + n * 7 + attempt), path)
                    ok = True
                    break
                except Exception as e:  # noqa: BLE001
                    log(f"Image {i}{shot} via {provider.__name__} failed: {str(e)[:150]}")
                    if (provider is _cloudflare and _STATE["cf_out"]) or "no HF_TOKEN" in str(e):
                        break  # no point retrying this provider
            if ok:
                break
        log(f"Image {i}{shot}: {'ok' if ok else 'FAILED'}")
        results[(i, shot)] = path if ok else None

    failed = sum(p is None for p in results.values())
    if failed > max(2, len(jobs) // 4):
        raise RuntimeError(f"{failed} of {len(jobs)} images failed; not rendering a broken video.")

    good = [p for p in results.values() if p]
    per_scene: list[list[Path]] = []
    for i in range(len(story["scenes"])):
        shots = [results.get((i, s)) for s in ("a", "b") if (i, s) in results]
        shots = [p for p in shots if p]
        if not shots:  # both failed: borrow the previous scene's last image
            shots = [per_scene[-1][-1] if per_scene else good[0]]
        per_scene.append(shots)
    return per_scene
