"""Scene images. Chain: Cloudflare Workers AI (FLUX schnell, 10,000 free neurons/day) -> free Hugging Face ZeroGPU
Spaces running FLUX.1-schnell (config "image_spaces") -> local SD-Turbo on the runner's CPU (always available).
Test mode never calls Cloudflare: it reuses the last run's cached images or uses the local model.
Pollinations and the paid Hugging Face router were removed on purpose (always out of credit, 402)."""
import base64
import io
import json
import math
import os
import random
import re
import shutil
import time
from pathlib import Path

import requests
from PIL import Image

from common import CONFIG, ROOT, env, log

_STATE = {"cf_out": False, "spaces_out": False, "local_out": False, "cf_neurons": 0.0, "local_secs": 0.0,
          "clients": {}, "sd": None}
CF_URL = "https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/black-forest-labs/flux-1-schnell"
CF_CHECK_URL = "https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/baai/bge-small-en-v1.5"
CACHE_DIR = ROOT / "cache" / "last-images"   # saved/restored by daily.yml (actions/cache, "last-images-*")
QUOTA_RE = re.compile(r"\((\d+)s requested vs\. (-?\d+)s left\)")


def test_mode() -> bool:
    return os.environ.get("TEST_MODE", "").lower() in ("1", "true", "yes")


def _log_neurons(raw: bytes, headers) -> None:
    """Cloudflare bills FLUX schnell 4.8 neurons per 512x512 output tile + 9.6 per step (it has no size option)."""
    try:
        with Image.open(io.BytesIO(raw)) as im:
            tiles = math.ceil(im.width / 512) * math.ceil(im.height / 512)
    except Exception:  # noqa: BLE001
        tiles = 4
    steps = int(CONFIG.get("image_steps", 4))
    neurons = tiles * 4.8 + steps * 9.6
    _STATE["cf_neurons"] += neurons
    extra = {k: v for k, v in headers.items() if "neuron" in k.lower()}
    log(f"Cloudflare image: ~{neurons:.1f} neurons ({tiles} tiles x 4.8 + {steps} steps x 9.6), "
        f"~{_STATE['cf_neurons']:.0f} this run{f' {extra}' if extra else ''}")


def _cloudflare(prompt: str, seed: int) -> bytes:
    acct = env("CLOUDFLARE_ACCOUNT_ID")
    token = env("CLOUDFLARE_API_TOKEN")
    for wait in (5, 15, 30, 0):
        r = requests.post(CF_URL.format(acct=acct), timeout=120,
                          headers={"Authorization": f"Bearer {token}"},
                          json={"prompt": prompt[:2000], "steps": int(CONFIG.get("image_steps", 4))})
        if r.status_code == 200:
            break  # success: never scan the body, the base64 image can contain "4006" or anything else
        body = r.text[:300]
        try:
            errors = r.json().get("errors") or []
        except ValueError:
            errors = []
        codes = {e.get("code") for e in errors if isinstance(e, dict)}
        msgs = " ".join(str(e.get("message", "")) for e in errors if isinstance(e, dict)).lower()
        # Daily cap (error 4006, "daily free allocation of 10,000 neurons"): skip Cloudflare for the rest of the run.
        if 4006 in codes or "daily free allocation" in msgs or "neurons" in msgs:
            _STATE["cf_out"] = True
            raise RuntimeError(f"Cloudflare daily free limit used up (resets 00:00 UTC): {body}")
        # Plain 429 = short "slow down" limit: wait and retry, keep Cloudflare for the next images.
        if r.status_code != 429:
            break
        if not wait:
            raise RuntimeError(f"Cloudflare rate limited (short-term, will keep using it): {body}")
        try:
            wait = min(60, max(wait, int(float(r.headers.get("Retry-After", wait)))))
        except ValueError:
            pass
        log(f"Cloudflare rate limited, waiting {wait}s: {body}")
        time.sleep(wait)
    if r.status_code != 200:
        raise RuntimeError(f"Cloudflare HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    img_b64 = (data.get("result") or {}).get("image") or data.get("image")
    if not img_b64:
        raise RuntimeError(f"Cloudflare returned no image: {str(data)[:300]}")
    raw = base64.b64decode(img_b64)
    _log_neurons(raw, r.headers)
    return raw




def _space_endpoint(client):
    """The named endpoint that takes a prompt and returns an image (FLUX Spaces call it /infer)."""
    info = client.view_api(return_format="dict", print_info=False)
    best = None
    for name, ep in (info.get("named_endpoints") or {}).items():
        names = [p.get("parameter_name") or "" for p in ep.get("parameters", [])]
        returns = " ".join(str(r.get("component", "")) for r in ep.get("returns", [])).lower()
        if "prompt" in names and "image" in returns:
            score = 2 if name == "/infer" else 1
            if best is None or score > best[0]:
                best = (score, name, names)
    return (best[1], best[2]) if best else (None, None)


def _space_file(result):
    """Spaces return a path, a dict with 'path'/'url', or a tuple (image, seed): find the image file."""
    stack = [result]
    while stack:
        r = stack.pop(0)
        if isinstance(r, str) and os.path.exists(r):
            return r
        if isinstance(r, dict):
            stack.extend(v for k, v in r.items() if k in ("path", "image", "value", "name"))
        elif isinstance(r, (list, tuple)):
            stack.extend(r)
    return None


def _hf_space(prompt: str, seed: int, width: int | None = None, height: int | None = None,
              steps: int | None = None) -> bytes:
    """Free fallback: FLUX.1-schnell on Hugging Face ZeroGPU Spaces (shares the daily GPU minutes with ai_motion)."""
    if _STATE["spaces_out"]:
        raise RuntimeError("free GPU Spaces out of quota for this run")
    from gradio_client import Client
    import ai_motion
    size = CONFIG.get("space_image_size", [576, 1024])
    width, height = width or int(size[0]), height or int(size[1])
    steps = steps or int(CONFIG.get("image_steps", 4))
    token = os.environ.get("HF_TOKEN") or None
    errors = []
    for space in CONFIG.get("image_spaces", []):
        try:
            if space not in _STATE["clients"]:
                client = ai_motion._connect(Client, space, token)
                _STATE["clients"][space] = (client, *_space_endpoint(client))
            client, endpoint, names = _STATE["clients"][space]
            if not endpoint:
                errors.append(f"{space}: no prompt->image endpoint")
                continue
            kw = {"prompt": prompt[:1500]}
            for k, v in (("seed", seed % 2_147_483_647), ("randomize_seed", False), ("width", width),
                         ("height", height), ("num_inference_steps", steps), ("negative_prompt", NEGATIVE)):
                if k in names:
                    kw[k] = v
            path = _space_file(client.predict(api_name=endpoint, **kw))
            if not path:
                errors.append(f"{space}: no image returned")
                continue
            return Path(path).read_bytes()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            m = QUOTA_RE.search(msg)
            if m:
                log(f"ZeroGPU quota: {space} requested {m.group(1)}s, {m.group(2)}s left")
                if int(m.group(2)) <= 0:
                    _STATE["spaces_out"] = True
                    raise RuntimeError(f"free GPU minutes used up: {msg[:150]}") from e
            elif "runs limit" in msg.lower() or ("quota" in msg.lower() and "exceeded" in msg.lower()):
                _STATE["spaces_out"] = True
                raise RuntimeError(f"free GPU quota used up: {msg[:150]}") from e
            errors.append(f"{space}: {type(e).__name__}: {msg[:120]}")
    raise RuntimeError("; ".join(errors) or "no image_spaces configured")


def _local_sd(prompt: str, seed: int) -> bytes:
    """Last resort, always available: SD-Turbo on the runner's CPU (512x896, 1-2 steps, no guidance).
    Stability AI Community License (free commercial use under $1M/yr revenue; register once with Stability)."""
    import torch
    budget = float(CONFIG.get("local_image_budget_minutes", 12)) * 60
    if _STATE["local_secs"] >= budget:
        _STATE["local_out"] = True
        raise RuntimeError(f"local model time budget used up ({_STATE['local_secs']:.0f}s of {budget:.0f}s)")
    t0 = time.time()
    if _STATE["sd"] is None:
        from diffusers import AutoPipelineForText2Image
        model = CONFIG.get("local_image_model", "stabilityai/sd-turbo")
        log(f"Loading local image model {model} (CPU)...")
        pipe = AutoPipelineForText2Image.from_pretrained(model, torch_dtype=torch.float32, variant="fp16")
        pipe.set_progress_bar_config(disable=True)
        _STATE["sd"] = pipe
        log(f"Local image model loaded in {time.time() - t0:.0f}s")
    w, h = CONFIG.get("local_image_size", [512, 896])
    # No negative prompt: SD-Turbo runs without guidance (guidance_scale 0), where a negative prompt has no effect.
    image = _STATE["sd"](prompt=prompt, width=int(w), height=int(h), guidance_scale=0.0,
                         num_inference_steps=int(CONFIG.get("local_image_steps", 2)),
                         generator=torch.Generator("cpu").manual_seed(seed % 2_147_483_647)).images[0]
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "PNG")
    _STATE["local_secs"] += time.time() - t0
    return buf.getvalue()


def cloudflare_has_quota() -> bool | None:
    """Tiny embeddings call (a few neurons) to see if the daily allocation is used up. None = no token/unknown."""
    token = env("CLOUDFLARE_API_TOKEN", required=False)
    acct = env("CLOUDFLARE_ACCOUNT_ID", required=False)
    if not (token and acct):
        return None
    try:
        r = requests.post(CF_CHECK_URL.format(acct=acct), timeout=30, headers={"Authorization": f"Bearer {token}"},
                          json={"text": ["ok"]})
    except Exception as e:  # noqa: BLE001
        log(f"Cloudflare quota check failed ({e}); will just try it")
        return None
    if r.status_code == 200:
        return True
    try:
        errs = r.json().get("errors") or []
    except ValueError:
        errs = []
    text = " ".join(str(e.get("message", "")) for e in errs if isinstance(e, dict)).lower()
    if any(e.get("code") == 4006 for e in errs if isinstance(e, dict)) or "daily free allocation" in text:
        return False
    log(f"Cloudflare quota check: HTTP {r.status_code} {r.text[:150]}")
    return None


def preflight() -> str | None:
    """Before spending Gemini + voice time: make sure at least one image source works. Returns a problem or None."""
    if test_mode():
        log("TEST MODE: images come from the last run's cache or the local model (Cloudflare is never called)")
        return None
    cf = cloudflare_has_quota()
    if cf is not False:
        log(f"Cloudflare: {'has quota' if cf else 'status unknown, will try it'}")
        return None
    _STATE["cf_out"] = True
    log("Cloudflare daily limit is used up (resets 00:00 UTC = 8 PM New York); 2 shots per scene this run")
    try:
        _hf_space("a foggy forest at night, illustration", 1, width=256, height=256, steps=1)
        log("Free FLUX Spaces: working")
        return None
    except Exception as e:  # noqa: BLE001
        spaces_err = str(e)[:200]
        log(f"Free FLUX Spaces not usable: {spaces_err}")
    try:
        _local_sd("a foggy forest at night, illustration", 1)
        log("Local SD-Turbo: working (slow, CPU)")
        return None
    except Exception as e:  # noqa: BLE001
        return ("No image source available. Cloudflare daily limit used up (resets 8 PM New York); "
                f"free Spaces: {spaces_err}; local model: {str(e)[:200]}. Nothing was generated; "
                "inbox items stay queued.")


def save_cache(story: dict, images: list[list[Path]]) -> None:
    """Keep this run's images + story for test mode (daily.yml saves cache/last-images to the Actions cache)."""
    shutil.rmtree(CACHE_DIR, ignore_errors=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for shots in images:
        for p in shots:
            if p and p.exists():
                shutil.copy(p, CACHE_DIR / p.name)
    (CACHE_DIR / "story.json").write_text(json.dumps({"scenes": len(story.get("scenes", []))}))


def _cached_images(story: dict, outdir: Path) -> list[list[Path]] | None:
    """Test mode: reuse the last run's images if the new story has the same number of scenes."""
    meta = CACHE_DIR / "story.json"
    if not meta.exists():
        log("TEST MODE: no cached images yet")
        return None
    n = len(story["scenes"])
    if json.loads(meta.read_text()).get("scenes") != n:
        log(f"TEST MODE: cached images are for a different number of scenes, not {n}")
        return None
    per_scene = []
    for i in range(n):
        shots = []
        for s in ("a", "b", "c", "d"):
            src = CACHE_DIR / f"scene_{i:02d}{s}.png"
            if src.exists():
                shutil.copy(src, outdir / src.name)
                shots.append(outdir / src.name)
        if not shots:
            return None
        per_scene.append(shots)
    log(f"TEST MODE: reusing {sum(map(len, per_scene))} cached images from the last run (source: cache)")
    return per_scene


def _save_valid(raw: bytes, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(raw)
    with Image.open(tmp) as im:
        im = im.convert("RGB")
        if im.width < 256 or im.height < 256:
            raise RuntimeError("image too small")
        im.save(path, "PNG")
    tmp.unlink(missing_ok=True)


def _is_image(path: Path) -> bool:
    try:
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:  # noqa: BLE001
        return False


def _key(name: str) -> str:
    n = name.lower().strip()
    return n[4:] if n.startswith("the ") else n


SHORT_STYLE = "single full-frame dark cinematic illustration, painterly"
NEGATIVE = "comic page, multiple panels, panel grid, collage, split screen, text, letters, speech bubbles, watermark"
_PANEL_WORDS = re.compile(r"\b(graphic[- ]novel|comic(?:[- ]book)?s?|panels?)\b", re.IGNORECASE)


def _looks(story: dict, scene_i: int, shot: str) -> tuple[dict | None, list[dict]]:
    text = shot.lower()
    scene = story["scenes"][scene_i]
    loc_name = _key(scene.get("location") or "")
    loc = next((l for l in story.get("locations") or []
                if _key(l.get("name", "")) and (_key(l["name"]) == loc_name or _key(l["name"]) in text)), None)
    chars = [c for c in story.get("characters") or [] if _key(c.get("name", "")) and _key(c["name"]) in text]
    return loc, chars


def build_prompt(story: dict, scene_i: int, shot: str, style: str) -> str:
    """Cloudflare prompt: the shot FIRST, then the fixed character and location looks, then the art style,
    so every image of a story shares the same people, places and style (and the shot is never cut off)."""
    loc, chars = _looks(story, scene_i, shot)
    parts = [f"Shot: {shot}"] + [f"{c['name']}: {c['look']}" for c in chars]
    if loc:
        parts.append(f"Setting: {loc['look']}")
    parts.append(style)
    return ". ".join(p.strip().rstrip(".") for p in parts if p.strip())


def build_short_prompt(story: dict, scene_i: int, shot: str, max_words: int = 60) -> str:
    """Spaces / SD-Turbo prompt (SD-Turbo's text encoder stops at 77 tokens): shot first, then 1-2 short
    character/location cues, then a SHORT style tag. Never 'comic', 'graphic novel' or 'panels': those words
    make these models draw comic pages and panel grids."""
    loc, chars = _looks(story, scene_i, shot)
    cues = [" ".join(c["look"].split()[:8]) for c in chars[:1]]
    if loc:
        cues.append(" ".join(loc["look"].split()[:6]))
    shot_words = _PANEL_WORDS.sub("", shot).split()
    room = max_words - len(shot_words) - len(SHORT_STYLE.split())
    cue_words: list[str] = []
    for cue in cues[:2]:
        w = _PANEL_WORDS.sub("", cue).split()
        if room - len(cue_words) - len(w) >= 0:
            cue_words += w + [","]
    text = " ".join(shot_words[:max_words - len(SHORT_STYLE.split())])
    if cue_words:
        text += ", " + " ".join(cue_words).strip(" ,")
    return re.sub(r"\s+([,.])", r"\1", f"{text}, {SHORT_STYLE}").strip()


def _virtual_shot(src: Path, dest: Path, shot: str) -> None:
    """A second framing of an image from the same scene (75% crop, placed per shot letter)."""
    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        cw, ch = int(w * 0.75), int(h * 0.75)
        x = {"a": 0, "b": w - cw, "c": (w - cw) // 2, "d": 0}.get(shot, 0)
        y = {"a": 0, "b": h - ch, "c": (h - ch) // 2, "d": h - ch}.get(shot, 0)
        im.crop((x, y, x + cw, y + ch)).resize((w, h), Image.LANCZOS).save(dest, "PNG")


def check_image(path: Path, shot: str) -> bool | None:
    """Ask Gemini (vision, same free key) if the image is ONE scene showing the shot. None = check skipped."""
    if not CONFIG.get("image_check", True) or _STATE.get("check_off"):
        return None
    key = env("GEMINI_API_KEY", required=False)
    if not key:
        return None
    models = CONFIG.get("llm_models", [])
    model = CONFIG.get("image_check_model") or next((m for m in models if "lite" in m), models[0] if models else "")
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((512, 512))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
        question = (f'Is this a single scene, not a grid of panels or a collage, that shows: "{shot}"? '
                    "Answer YES or NO.")
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                          headers={"x-goog-api-key": key}, timeout=15, json={
                              "contents": [{"role": "user", "parts": [
                                  {"inline_data": {"mime_type": "image/jpeg",
                                                   "data": base64.b64encode(buf.getvalue()).decode()}},
                                  {"text": question}]}],
                              "generationConfig": {"temperature": 0, "maxOutputTokens": 5}})
    except Exception as e:  # noqa: BLE001
        log(f"Image check skipped ({str(e)[:80]})")
        return None
    if r.status_code == 429:
        _STATE["check_off"] = True  # rate-limited: keep the free quota for stories, stop checking this run
        log("Image check: Gemini rate-limited, skipping the checks for the rest of this run")
        return None
    if r.status_code != 200:
        log(f"Image check skipped (HTTP {r.status_code})")
        return None
    try:
        answer = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip().lower()
    except Exception:  # noqa: BLE001
        return None
    return answer.startswith("y")


def generate_images(story: dict, outdir: Path) -> list[list[Path]]:
    """Up to four images per scene, one per part of the narration. Returns [[a, b, c, d], ...]."""
    outdir.mkdir(parents=True, exist_ok=True)
    testing = test_mode()
    if testing:
        cached = _cached_images(story, outdir)
        if cached:
            return cached
    style = CONFIG["image_style"]
    base_seed = random.randint(1, 2_000_000_000)
    use_cf = bool(env("CLOUDFLARE_API_TOKEN", required=False)) and not testing

    jobs = []  # (scene index, shot letter, prompt)
    for i, scene in enumerate(story["scenes"]):
        jobs.append((i, "a", scene["image_prompt"]))
        extra_keys = (("image_prompt_2", "b"), ("image_prompt_3", "c"), ("image_prompt_4", "d"))
        for key, letter in extra_keys[: max(0, int(CONFIG.get("shots_per_scene", 4)) - 1)]:
            extra = scene.get(key) or ""
            if extra.strip():
                jobs.append((i, letter, extra))

    # Every scene's "a" shot first, then every "b", then the extra cuts ("c"/"d"): if a quota or the local time
    # budget runs out we lose cuts, never whole scenes.
    jobs.sort(key=lambda j: ("abcd".index(j[1]), j[0]))

    results: dict[tuple[int, str], Path | None] = {}
    sources: dict[str, int] = {}
    qa_failed: list[tuple[int, str]] = []
    told_two = False
    for n, (i, shot, raw_prompt) in enumerate(jobs):
        # Cloudflare out (or test mode): the fallbacks are slow/limited, so only 2 shots per scene from here on.
        if shot in ("c", "d") and (testing or _STATE["cf_out"] or not use_cf) \
                and not _is_image(outdir / f"scene_{i:02d}{shot}.png"):
            if not told_two:
                log("Cloudflare not available: 2 shots per scene for the rest of this run")
                told_two = True
            continue
        path = outdir / f"scene_{i:02d}{shot}.png"
        if _is_image(path):  # checkpoint from an earlier try of this same story: keep it
            sources["checkpoint"] = sources.get("checkpoint", 0) + 1
            results[(i, shot)] = path
            continue
        prompt = build_prompt(story, i, raw_prompt, style)            # Cloudflare: full prompt
        short_prompt = build_short_prompt(story, i, raw_prompt)        # Spaces / SD-Turbo: short, no "comic"
        ok, source = False, ""
        providers = (([_cloudflare] if use_cf and not _STATE["cf_out"] else [])
                     + ([] if testing or _STATE["spaces_out"] else [_hf_space])
                     + ([] if _STATE["local_out"] else [_local_sd]))
        if not providers:
            if not _STATE.get("told_none"):
                log("No image source left (Cloudflare/Spaces out, local time budget used): using what exists")
                _STATE["told_none"] = True
            results[(i, shot)] = None
            continue
        def draw(chain: list) -> int:
            """Try the sources in order; returns the index of the one that made the image, or -1."""
            for k, provider in enumerate(chain):
                p = prompt if provider is _cloudflare else short_prompt
                for attempt in range(2):
                    try:
                        _save_valid(provider(p, base_seed + n * 7 + attempt), path)
                        return k
                    except Exception as e:  # noqa: BLE001
                        log(f"Image {i}{shot} via {provider.__name__.lstrip('_')} failed: {str(e)[:150]}")
                        if (provider is _cloudflare and _STATE["cf_out"]) or provider is _local_sd \
                                or provider is _hf_space or any(x in str(e) for x in ("401", "403", "deprecated")):
                            break  # no point retrying this one (Spaces already tried every Space in the list)
            return -1

        k = draw(providers)
        if k >= 0:
            ok, source = True, providers[k].__name__.lstrip("_")
            # Fallback-image QA (never for Cloudflare): one yes/no vision question. "No" -> redraw once with the
            # NEXT source; still "no" -> replaced by a virtual shot from another good image of the scene at the end.
            verdict = None if providers[k] is _cloudflare else check_image(path, raw_prompt)
            if verdict is not None:
                log(f"Image {i}{shot} check: {'YES' if verdict else 'NO'}")
            if verdict is False:
                log(f"Image {i}{shot} ({source}) failed the check (panels/collage or wrong subject): redrawing")
                nxt = [p for p in providers[k + 1:] if not (p is _hf_space and _STATE["spaces_out"])
                       and not (p is _local_sd and _STATE["local_out"])]
                k2 = draw(nxt) if nxt else -1
                if k2 >= 0:
                    source = nxt[k2].__name__.lstrip("_")
                if k2 < 0 or check_image(path, raw_prompt) is False:
                    qa_failed.append((i, shot))
        sources[source or "FAILED"] = sources.get(source or "FAILED", 0) + 1
        log(f"Image {i}{shot}: {'ok (' + source + ')' if ok else 'FAILED'}")
        results[(i, shot)] = path if ok else None

    # Images that failed the check twice: use a virtual shot (crop of another good image of the same scene).
    for i, shot in qa_failed:
        sib = next((results[(i, s)] for s in ("a", "b", "c", "d")
                    if s != shot and results.get((i, s)) and (i, s) not in qa_failed), None)
        if sib:
            _virtual_shot(sib, outdir / f"scene_{i:02d}{shot}.png", shot)
            sources["virtual"] = sources.get("virtual", 0) + 1
            log(f"Image {i}{shot}: replaced by a virtual shot of {sib.name}")
        else:
            log(f"Image {i}{shot}: failed the check but no other image in the scene, keeping it")

    n_scenes = len(story["scenes"])
    empty = sum(1 for i in range(n_scenes) if not any(results.get((i, s)) for s in ("a", "b", "c", "d")))
    log("Image sources: " + ", ".join(f"{k} {v}" for k, v in sources.items())
        + (f"; local model total {_STATE['local_secs']:.0f}s" if _STATE["local_secs"] else "")
        + (f"; Cloudflare ~{_STATE['cf_neurons']:.0f} neurons" if _STATE["cf_neurons"] else ""))
    skipped = len(jobs) - len(results)
    failed = sum(p is None for p in results.values())
    if failed or skipped:
        log(f"Missing {failed + skipped} of {len(jobs)} images ({skipped} extra cuts skipped); "
            f"{empty} of {n_scenes} scenes have no image at all")
    if empty > max(1, n_scenes // 4):
        raise RuntimeError(f"{empty} of {n_scenes} scenes have no image; not rendering a broken video.")

    good = [p for p in results.values() if p]
    per_scene: list[list[Path]] = []
    for i in range(len(story["scenes"])):
        shots = [results.get((i, s)) for s in ("a", "b", "c", "d") if (i, s) in results]
        shots = [p for p in shots if p]
        if not shots:  # both failed: borrow the previous scene's last image
            shots = [per_scene[-1][-1] if per_scene else good[0]]
        per_scene.append(shots)
    return per_scene
