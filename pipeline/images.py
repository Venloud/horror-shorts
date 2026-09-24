"""Generates one image per scene. Cloudflare Workers AI (Flux schnell) first, Pollinations as free fallback."""
import base64
import random
import shutil
import urllib.parse
from pathlib import Path

import requests
from PIL import Image

from common import CONFIG, env, log

CF_URL = "https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/black-forest-labs/flux-1-schnell"


def _cloudflare(prompt: str, seed: int) -> bytes:
    acct = env("CLOUDFLARE_ACCOUNT_ID")
    token = env("CLOUDFLARE_API_TOKEN")
    r = requests.post(CF_URL.format(acct=acct), timeout=120,
                      headers={"Authorization": f"Bearer {token}"},
                      json={"prompt": prompt[:2000], "steps": 8})
    if r.status_code != 200:
        raise RuntimeError(f"Cloudflare HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    img_b64 = (data.get("result") or {}).get("image") or data.get("image")
    if not img_b64:
        raise RuntimeError(f"Cloudflare returned no image: {str(data)[:300]}")
    return base64.b64decode(img_b64)


def _pollinations(prompt: str, seed: int) -> bytes:
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:1500])
           + f"?width=1080&height=1920&seed={seed}&nologo=true&model=flux")
    r = requests.get(url, timeout=180)
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
        raise RuntimeError(f"Pollinations HTTP {r.status_code}")
    return r.content


def _save_valid(raw: bytes, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(raw)
    with Image.open(tmp) as im:
        im = im.convert("RGB")
        if im.width < 256 or im.height < 256:
            raise RuntimeError("image too small")
        im.save(path, "PNG")
    tmp.unlink(missing_ok=True)


def generate_images(story: dict, outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    style = CONFIG["image_style"]
    base_seed = random.randint(1, 2_000_000_000)
    use_cf = bool(env("CLOUDFLARE_API_TOKEN", required=False))
    paths: list[Path | None] = []

    for i, scene in enumerate(story["scenes"]):
        prompt = f"{scene['image_prompt']}. {style}"
        path = outdir / f"scene_{i:02d}.png"
        ok = False
        providers = ([_cloudflare] if use_cf else []) + [_pollinations]
        for provider in providers:
            for attempt in range(2):
                try:
                    _save_valid(provider(prompt, base_seed + i * 7 + attempt), path)
                    ok = True
                    break
                except Exception as e:  # noqa: BLE001
                    log(f"Image {i} via {provider.__name__} failed: {e}")
            if ok:
                break
        log(f"Image {i}: {'ok' if ok else 'FAILED'}")
        paths.append(path if ok else None)

    failed = sum(p is None for p in paths)
    if failed > max(1, len(paths) // 4):
        raise RuntimeError(f"{failed} of {len(paths)} images failed; not rendering a broken video.")
    # Fill any gaps with the nearest good neighbour so timing stays intact.
    good = [p for p in paths if p]
    for i, p in enumerate(paths):
        if p is None:
            src = next((paths[j] for j in list(range(i - 1, -1, -1)) + list(range(i + 1, len(paths))) if paths[j]), good[0])
            dst = outdir / f"scene_{i:02d}.png"
            shutil.copy(src, dst)
            paths[i] = dst
    return paths  # type: ignore[return-value]
