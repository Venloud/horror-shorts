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
    """Free backup: Hugging Face Inference Providers (FLUX.1 schnell, provider picked automatically). Needs HF_TOKEN."""
    token = env("HF_TOKEN", required=False)
    if not token:
        raise RuntimeError("no HF_TOKEN secret")
    import io
    from huggingface_hub import InferenceClient
    client = InferenceClient(provider="auto", api_key=token, timeout=180)
    image = client.text_to_image(prompt[:1500], model="black-forest-labs/FLUX.1-schnell",
                                 width=768, height=1344, num_inference_steps=4, seed=seed)
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def _pollinations(prompt: str, seed: int) -> bytes:
    """Backup: Pollinations (new gen.pollinations.ai API, free key from enter.pollinations.ai)."""
    key = env("POLLINATIONS_KEY", required=False)
    q = urllib.parse.quote(prompt[:1500])
    if key:
        url = f"https://gen.pollinations.ai/image/{q}?width=1080&height=1920&seed={seed}&model=flux&nologo=true"
        r = requests.get(url, timeout=180, headers={"Authorization": f"Bearer {key}"})
    else:  # old keyless endpoint, may be retired
        url = f"https://image.pollinations.ai/prompt/{q}?width=1080&height=1920&seed={seed}&nologo=true&model=flux"
        r = requests.get(url, timeout=180)
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
        raise RuntimeError(f"Pollinations HTTP {r.status_code}: {r.text[:150] if not r.headers.get('content-type','').startswith('image') else ''}")
    # crop the bottom 7% in case a logo is stamped there
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
                    if (provider is _cloudflare and _STATE["cf_out"]) or any(
                            k in str(e) for k in ("no HF_TOKEN", "410", "401", "403", "deprecated")):
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
