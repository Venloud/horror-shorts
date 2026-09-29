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
    if extra:  # the per-image line in generate_images shows the estimate; log Cloudflare's own figure if it sends one
        log(f"Cloudflare neuron headers: {extra}")


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
        n = test_cloudflare_images()
        log(f"TEST MODE: {n} real Cloudflare image(s), then the local model" if n else
            "TEST MODE: images come from the last run's cache or the local model (Cloudflare is never called)")
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
    _STATE["spaces_out"] = True
    # Local SD-Turbo alone is a gap filler (local_image_max per video), never enough for a whole video: wait for
    # the quota instead of spending Gemini + voice + 12 minutes of CPU on a weak video. The buffer covers the gap.
    try:
        _quota_stop(f"Cloudflare daily limit used up and the free Spaces are out ({spaces_err[:120]}). "
                    "No story was written; inbox items stay queued.")
    except ImageQuotaWait as e:
        return str(e)
    return None


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
            raise RuntimeError(f"image too small ({im.width}x{im.height})")
        if im.width > im.height * 1.1:  # the video is vertical: a landscape image is the wrong format
            raise RuntimeError(f"wrong dimensions ({im.width}x{im.height}, landscape)")
        im.save(path, "PNG")
    tmp.unlink(missing_ok=True)


def _is_image(path: Path) -> bool:
    try:
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:  # noqa: BLE001
        return False


_CAMERA = re.compile(r"\b(extreme close-up|close-up|close up|medium shot|medium close-up|wide shot|wide establishing "
                     r"shot|establishing shot|long shot|full shot|over-the-shoulder|low angle|high angle|eye-level|"
                     r"bird's-eye view|top-down|profile shot|two-shot|point-of-view|pov)\b", re.IGNORECASE)


PROMPT_KEYS = {"a": "image_prompt", "b": "image_prompt_2", "c": "image_prompt_3", "d": "image_prompt_4"}
LOC_KEYS = {"a": "image_location", "b": "image_location_2", "c": "image_location_3", "d": "image_location_4"}
_LABELS = re.compile(r"\b(CHARACTERS?|SETTING|SHOT|CAMERA|STYLE|LOCATION)\s*:\s*", re.IGNORECASE)
_OUTDOOR = re.compile(r"\b(forest|woods|trees?|river\w*|lake\w*|creek|stream|shore|beach|sea|ocean|mountains?|hills?|"
                      r"hillside|field|meadow|road|highway|street|alley|sky|outside|outdoors?|exterior|parking lot|"
                      r"bridge|cliff|swamp|desert|clearing|trail|path|garden|yard|cemetery|graveyard|tarmac|runway|"
                      r"rooftop|roof|porch|snow\w*|dock|pier|waterfall|cave)\b", re.IGNORECASE)
# Words that put a SHOT indoors (a building's name alone, e.g. "the cabin at night, snow on the roof", does not).
_INSIDE = re.compile(r"\b(inside|interior|indoors|room|kitchen|bedroom|hallway|corridor|basement|attic|office|"
                     r"bathroom|lobby|fireplace|bed|couch|sofa|desk|aisle|seats?|closet|ceiling|walls?|cockpit)\b",
                     re.IGNORECASE)
_INDOOR = re.compile(r"\b(cabin|room|kitchen|bedroom|hallway|corridor|basement|attic|interior|inside|indoors|office|"
                     r"bathroom|lobby|cell|walls?|ceiling|fireplace|bed|couch|sofa|desk|cockpit|aisle|seats?|"
                     r"staircase|closet|gallery|hall)\b", re.IGNORECASE)
_OBJECTS = re.compile(r"\b(note|letter|envelope|briefcase|suitcase|bag|money|cash|bills?|banknotes?|coins?|photo\w*|"
                      r"picture|key|keys|phone|map|ticket|parachute|jewel\w*|crown|necklace|ring|diary|journal|book|"
                      r"newspaper|file|folder|documents?|badge|knife|bottle|cup|mug|watch|clock|footprints?|shoe|"
                      r"glove|tape|camera|recorder|radio|lantern|candle|lock|box|chest|painting|password|screen|"
                      r"monitor|tie|clip|receipt|map|skull|doll|mirror)\b", re.IGNORECASE)
_DETAIL = re.compile(r"\b(extreme close-up|close-up|close up|macro|detail shot|insert shot|top-down)\b", re.IGNORECASE)


def _key(name: str) -> str:
    n = name.lower().strip()
    return n[4:] if n.startswith("the ") else n


SHORT_STYLE = "single full-frame dark cinematic illustration, painterly"
NEGATIVE = "comic page, multiple panels, panel grid, collage, split screen, text, letters, speech bubbles, watermark"
# Style words that make models draw page layouts. Only these phrases: a literal "panel" (an elevator's button panel,
# a control panel) is part of the shot and must never be cut out of it.
_PANEL_WORDS = re.compile(r"\b(graphic[- ]novels?|comic(?:[- ]book)?s?(?:[- ]panels?)?|multiple panels|panel grids?|"
                          r"storyboards?|page layouts?)\b", re.IGNORECASE)
# Things the image models render as garbled fake text. Never ask for readable words: show the object blank.
_QUOTED = re.compile(r"[\"“”]([^\"“”]{1,60})[\"“”]")
_TEXTY = re.compile(r"\b(signs?|signboard|neon|lettering|headlines?|newspapers?|documents?|letters?|notes?|screens?|"
                    r"monitors?|laptops?|phones?|posters?|title cards?|labels?|clipboards?|reports?|receipts?|"
                    r"forms?|files?|folders?|books?|diary|journal|maps?|plaques?|billboards?|menus?)\b", re.IGNORECASE)


def _no_text(shot: str) -> str:
    """Remove requests for readable text: quoted words, "sign reading ...", "neon sign" -> glowing neon tubes."""
    shot = re.sub(r"\b(reading|saying|that says|that reads|labeled|labelled|titled|with the words?)\s+" + _QUOTED.pattern,
                  "", shot, flags=re.IGNORECASE)
    shot = _QUOTED.sub("", shot)
    shot = re.sub(r"\b(retro |glowing |old |flickering )?neon (sign|lettering|letters)s?\b", "glowing neon tubes",
                  shot, flags=re.IGNORECASE)
    return re.sub(r"\s+([,.;])", r"\1", re.sub(r"\s{2,}", " ", shot)).strip()


def _letter(scene: dict, shot: str) -> str:
    return next((l for l, k in PROMPT_KEYS.items() if (scene.get(k) or "").strip() == shot.strip()), "a")


def _is_interior(look: str) -> bool:
    return bool(_INDOOR.search(look)) and not _OUTDOOR.search(look)


def _is_exterior_shot(shot: str) -> bool:
    return bool(_OUTDOOR.search(shot)) and not _INSIDE.search(shot)


def _shot_location(story: dict, scene_i: int, letter: str, shot: str) -> dict | None:
    """The location of THIS shot (scene plan field image_location[_N]; "none" = no setting). Older plans without
    it: a location named in the shot, else the scene's. An exterior shot never gets an interior block."""
    scene = story["scenes"][scene_i]
    locs = [l for l in story.get("locations") or [] if _key(l.get("name", "")) and l.get("look")]
    field = LOC_KEYS.get(letter, "image_location")
    if field in scene:
        name = _key(scene.get(field) or "")
        if not name or name in ("none", "n/a", "no location", "-"):
            return None
        loc = next((l for l in locs if _key(l["name"]) == name), None) \
            or next((l for l in locs if _key(l["name"]) in name or name in _key(l["name"])), None)
    else:
        text = shot.lower()
        loc = next((l for l in locs if _key(l["name"]) in text), None) \
            or next((l for l in locs if _key(l["name"]) == _key(scene.get("location") or "")), None)
    if loc and _is_exterior_shot(shot) and _is_interior(loc["look"]):
        return None  # e.g. a forest/river shot never gets the cabin block
    return loc


def _shot_characters(story: dict, shot: str) -> list[dict]:
    text = shot.lower()
    return [c for c in story.get("characters") or [] if _key(c.get("name", "")) and c.get("look")
            and _key(c["name"]) in text]


def _is_object_shot(shot: str, chars: list[dict]) -> bool:
    """A close-up of a thing (a note, a briefcase, money): the object is the subject, almost no setting."""
    head = " ".join(shot.split()[:14])
    return not chars and bool(_OBJECTS.search(head)) and (bool(_DETAIL.search(head))
                                                          or head.lower().startswith(("a ", "an ", "the ")))


def _clean_shot(shot: str) -> str:
    text = re.sub(r"\s{2,}", " ", _LABELS.sub("", shot)).strip()
    return re.sub(r"^[\W_]+", "", text).rstrip(".,; ")


def _bits(text: str) -> list[str]:
    return [b.strip().rstrip(".") for b in text.split(",") if b.strip().rstrip(".")]


def _join(parts: list[str]) -> str:
    return re.sub(r"\s{2,}", " ", ", ".join(p.strip().strip(",") for p in parts if p and p.strip())).strip()


def _shot_parts(story: dict, scene_i: int, shot: str, letter: str | None):
    """(shot text without framing words, camera framing, characters IN this shot, location OF this shot, object?)"""
    scene = story["scenes"][scene_i]
    letter = letter or _letter(scene, shot)
    shot = _no_text(_PANEL_WORDS.sub("", _clean_shot(shot)))
    chars = _shot_characters(story, shot)
    loc = _shot_location(story, scene_i, letter, shot)
    camera = scene.get("camera") or ", ".join(dict.fromkeys(m.group(0).lower() for m in _CAMERA.finditer(shot)))
    body = _CAMERA.sub("", shot)
    body = re.sub(r"^\W*(?:shot\s+)?of\s+", "", body.strip(), flags=re.IGNORECASE)  # "Wide shot of X" -> "X"
    body = re.sub(r"^[\W_]+", "", _join(_bits(body))) or shot
    return body, camera, chars, loc, _is_object_shot(shot, chars)


def shot_request(story: dict, scene_i: int, shot: str, letter: str | None = None) -> tuple[str, str]:
    """(what the image must show, its location name) for the QA question and the log."""
    body, _, _, loc, _ = _shot_parts(story, scene_i, shot, letter)
    return body, (loc or {}).get("name", "") if loc else ""


def build_prompt(story: dict, scene_i: int, shot: str, style: str | None = None, letter: str | None = None) -> str:
    """Cloudflare FLUX (handles long prompts): the shot's subject + action + key object first, then the full locked
    looks of the characters IN this shot, then this shot's locked location (object shots: 3 words at most), then
    the camera framing, then the rich `image_style_cf`. Natural comma-separated text, no labels."""
    style = _PANEL_WORDS.sub("", style or CONFIG.get("image_style_cf") or CONFIG.get("image_style", ""))
    body, camera, chars, loc, is_object = _shot_parts(story, scene_i, shot, letter)
    parts = [body] + [f"{c['name']}, {c['look'].strip().rstrip('.')}" for c in chars]
    if loc:
        look = loc["look"].strip().rstrip(".")
        parts.append(" ".join(_bits(look)[0].split()[:3]) if is_object else look)
    blank = "the surfaces blank, no legible text or lettering" if _TEXTY.search(body) else ""
    return _join(parts + [blank, camera, style])


CLIP_LIMIT = 77  # SD-Turbo's text encoder (and the CLIP half of FLUX) reads 77 tokens; the rest is cut off
_KEY_TRAIT = re.compile(r"\b(\d+s?|\w+-year-old|years?|old|young|teen\w*|elderly|aged?|child|boy|girl|man|woman|men|"
                        r"women|hair\w*|bald|beard\w*|mustache|blonde?|brunette|redhead|grey|gray|suit|jacket|coat|"
                        r"dress|shirt|blouse|sweater|hoodie|uniform|vest|tie|hat|cap|hood\w*|mask\w*|robe|cloak|"
                        r"jeans|trousers|pants|skirt|boots|glasses|sunglasses|scarf|gloves|apron|overalls)\b",
                        re.IGNORECASE)


def clip_tokens(text: str) -> int:
    """Token count as the CLIP text encoder sees it (incl. start/end tokens); a close estimate if the
    tokenizer isn't available."""
    if "tok" not in _STATE:
        try:
            from transformers import CLIPTokenizer
            _STATE["tok"] = CLIPTokenizer.from_pretrained(CONFIG.get("local_image_model", "stabilityai/sd-turbo"),
                                                          subfolder="tokenizer")
            # Counting only: drafts over 77 are measured while trimming, the "longer than the specified maximum"
            # warning they trigger is not a real overflow (the final prompt count is what's logged).
            _STATE["tok"].model_max_length = 10**6
        except Exception:  # noqa: BLE001
            _STATE["tok"] = None
    tok = _STATE["tok"]
    if tok is not None:
        return len(tok(text).input_ids)
    return int(len(re.findall(r"\w+|[^\w\s]", text)) * 1.15) + 2


def _key_traits(look: str, most: int = 6) -> list[str]:
    """3-6 key traits of a locked look: who it is (first detail) + age/hair/clothing details, in the sheet's order."""
    bits = _bits(look)
    if len(bits) <= 3:
        return bits
    keep = [bits[0]] + [b for b in bits[1:] if _KEY_TRAIT.search(b)]
    keep += [b for b in bits[1:] if b not in keep][: max(0, 3 - len(keep))]
    keep = set(keep[:most])
    return [b for b in bits if b in keep]


def _few_words(look: str, limit: int = 8) -> str:
    """At most `limit` words of a setting look, whole comma details first."""
    out, n = [], 0
    for b in _bits(look):
        w = len(b.split())
        if n + w > limit:
            if not out:
                out.append(" ".join(b.split()[:limit]))
            break
        out.append(b)
        n += w
    return ", ".join(out)


FALLBACK_TOKENS = 70  # stay comfortably below CLIP's 77


def build_short_prompt(story: dict, scene_i: int, shot: str, limit: int = FALLBACK_TOKENS,
                       letter: str | None = None) -> str:
    """Spaces / SD-Turbo (CLIP reads 77 tokens): the shot's subject + action + key object first (so it sits in the
    first ~40 tokens), then 3-6 key traits of each character IN the shot, then at most 8 words of this shot's
    location (none for object shots), then the camera framing, then the short `image_style_fallback`. Over the
    limit, trim in this order: style, camera, setting details, character details (down to 3 traits). The shot
    itself is never shortened. No labels, never "graphic novel" / "comic" / "panels"."""
    body, camera, chars, loc, is_object = _shot_parts(story, scene_i, shot, letter)
    if clip_tokens(body) > 42:  # the shot alone would push who/where past CLIP's reach: shorten it, never cut it
        body = _shorter_shot(body)
    style_bits = _bits(_PANEL_WORDS.sub("", CONFIG.get("image_style_fallback", SHORT_STYLE)))
    if _TEXTY.search(body):
        style_bits.insert(0, "blank unmarked surfaces")
    traits = [[c["name"]] + [_PANEL_WORDS.sub("", t).strip() for t in _key_traits(c["look"])] for c in chars]
    setting = "" if is_object or not loc else _PANEL_WORDS.sub("", _few_words(loc["look"], 8))
    compose = lambda: _join([body] + [", ".join(t) for t in traits] + [setting, camera] + style_bits)
    fits = lambda: clip_tokens(compose()) <= limit
    while not fits() and style_bits:          # 1) style
        style_bits.pop()
    if not fits():                            # 2) camera
        camera = ""
    while not fits() and setting:             # 3) non-essential setting details
        setting = ", ".join(_bits(setting)[:-1])
    for want in (5, 4, 3):                    # 4) non-essential character details, down to 3 key traits
        for t in traits:
            if not fits() and len(t) > want + 1:
                del t[want + 1:]
    if not fits() and len(body.split()) > 20:  # still over: the shot itself is too long, have it shortened
        body = _shorter_shot(body)
    text = compose()
    if not fits():
        log(f"Fallback prompt {clip_tokens(text)} tokens after trimming; the shot is first, so CLIP keeps it")
    return text


SHORTEN_PROMPT = """Shorten this image description to at most 20 words. Keep the main subject, the action and the key
object, in that order, and keep every person's name exactly as written. Whole phrases only, no cut-off words.
No readable text, signs or lettering. Return JSON: {{"shot": "<shortened description>"}}

{shot}"""


def _shorter_shot(body: str) -> str:
    """Gemini flash-lite rewrites an over-long shot to <= 20 words (subject, action, key object). Cached per shot.
    Without Gemini the shot stays whole (never cut mid-phrase)."""
    cache = _STATE.setdefault("short_shots", {})
    if body not in cache:
        models = CONFIG.get("llm_models") or []
        lite = [m for m in models if "lite" in m] or models[-1:]
        new = str((_gemini_json(SHORTEN_PROMPT.format(shot=body), lite) or {}).get("shot") or "").strip()
        ok = bool(new) and len(new.split()) <= 24
        cache[body] = _no_text(_PANEL_WORDS.sub("", new)).rstrip(".") if ok else body
        log(f"Shot shortened for the fallbacks: {cache[body]}" if ok else
            "Shot could not be shortened (Gemini unavailable), keeping it whole")
    return cache[body]


def build_simple_prompt(story: dict, scene_i: int, shot: str, letter: str | None = None) -> str:
    """Retry after a QA rejection: a materially simpler prompt built only around the requested subject: the shot's
    first ~12 words, who is in it (names + first trait), 4 words of location, a minimal style."""
    body, _, chars, loc, is_object = _shot_parts(story, scene_i, shot, letter)
    core = []
    for b in _bits(body) or [body]:
        if sum(len(x.split()) for x in core) >= 12:
            break
        core.append(b)
    who = [f"{c['name']}, {_bits(c['look'])[0]}" for c in chars if _bits(c["look"])]
    where = "" if is_object or not loc else _few_words(loc["look"], 4)
    return _join(core + who + [where, "single full-frame dark painterly illustration"])


DUP_PROMPT = """These image prompts for one short video are near-duplicates of an earlier shot, so the video would
show the same picture twice. Rewrite each one as a DIFFERENT shot of the same narration moment: a different
subject or a different angle/framing (e.g. the key object in close-up, the place as a wide establishing shot, a
reaction of another character). Rules: the main subject + action + key object in the first 12 words; 20-40 words;
refer to people by these exact names: {names}; one continuous film frame; no labels like "SHOT:"; no text in the
image; never an all-seeing eye or occult symbol.
Return JSON: {{"<id>": "<new prompt>", ...}}

{items}
"""
_DUP_STOP = set(("a an the of in on at to with and or his her their its is are was from by for into near behind "
                 "under over as while shot close-up close up medium wide establishing view light lighting dark "
                 "shadows shadow mood eerie tense cinematic frame angle eye level").split())


def _content_words(p: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", p.lower()) if w not in _DUP_STOP and len(w) > 2]


def near_duplicate(p1: str, p2: str) -> bool:
    import difflib
    a, b = _content_words(p1), _content_words(p2)
    if not a or not b:
        return False
    jac = len(set(a) & set(b)) / len(set(a) | set(b))
    return jac >= 0.6 or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def _gemini_json(prompt: str, models: list[str] | None = None) -> dict | None:
    key = env("GEMINI_API_KEY", required=False)
    for model in (models or (CONFIG.get("llm_models") or [])[:2]) if key else []:
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              headers={"x-goog-api-key": key}, timeout=60, json={
                                  "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                                  "generationConfig": {"temperature": 0.7, "responseMimeType": "application/json"}})
            if r.status_code == 200:
                return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            log(f"Gemini ({model}) HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            log(f"Gemini ({model}) failed ({str(e)[:80]})")
    return None


def _reframe(p: str, narration: str, taken: list[str]) -> str:
    """No Gemini: rebuild a duplicate shot around a key object from its narration (e.g. "briefcase containing cash
    on the seat" after "man opening a briefcase"); if there is none, at least flip the framing."""
    used = " ".join(taken).lower()
    for m in _OBJECTS.finditer(narration):
        obj = m.group(0).lower()
        cand = f"close-up of the {obj}, the {obj} alone fills the frame, dark moody light"
        if f"close-up of the {obj}" not in used:
            return cand
    body = _join(_bits(_CAMERA.sub("", p)))
    body = re.sub(r"^\W*(?:shot\s+)?of\s+", "", body, flags=re.IGNORECASE)
    return f"wide establishing shot, {body}" if re.search(r"close", p, re.IGNORECASE) else f"extreme close-up, {body}"


def _letters() -> str:
    """Shot letters generated per scene (config shots_per_scene, default 2: shot a + a different shot b)."""
    return "abcd"[: max(1, min(4, int(CONFIG.get("shots_per_scene", 2))))]


def dedupe_shots(story: dict) -> int:
    """Near-identical prompts in one video -> rewrite the later one to a different subject/angle. Returns count."""
    shots = [(i, l, sc[PROMPT_KEYS[l]]) for i, sc in enumerate(story.get("scenes") or [])
             for l in _letters() if (sc.get(PROMPT_KEYS[l]) or "").strip()]
    dups = []
    for n, (i, l, p) in enumerate(shots):
        first = next(((i2, l2, p2) for i2, l2, p2 in shots[:n] if near_duplicate(p, p2)), None)
        if first:
            dups.append(((i, l, p), first))
    if not dups:
        return 0
    names = ", ".join(c["name"] for c in story.get("characters") or [] if c.get("name")) or "(none)"
    items = "\n\n".join(f'id {i}{l}: "{p}"\n  duplicates shot {i2}{l2}: "{p2}"\n  narration of this moment: '
                        f'"{story["scenes"][i].get("narration", "")}"' for (i, l, p), (i2, l2, p2) in dups)
    new = _gemini_json(DUP_PROMPT.format(names=names, items=items)) or {}
    for (i, l, p), (i2, l2, _) in dups:
        cand = str(new.get(f"{i}{l}") or "").strip()
        others = [story["scenes"][a][PROMPT_KEYS[b]] for (a, b, _) in shots if (a, b) != (i, l)]
        if not cand or any(near_duplicate(cand, q) for q in others):
            cand = _reframe(p, story["scenes"][i].get("narration", ""), others)
        story["scenes"][i][PROMPT_KEYS[l]] = cand
        if cand.startswith("close-up of the "):
            story["scenes"][i][LOC_KEYS[l]] = "none"  # an object close-up: the object is the subject
        log(f"Image {i:02d}{l} was a near-duplicate of {i2:02d}{l2}; rewritten: {cand}")
    return len(dups)


def _virtual_shot(src: Path, dest: Path, shot: str) -> None:
    """A second framing of an image from the same scene (75% crop, placed per shot letter)."""
    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        cw, ch = int(w * 0.75), int(h * 0.75)
        x = {"a": 0, "b": w - cw, "c": (w - cw) // 2, "d": 0}.get(shot, 0)
        y = {"a": 0, "b": h - ch, "c": (h - ch) // 2, "d": h - ch}.get(shot, 0)
        im.crop((x, y, x + cw, y + ch)).resize((w, h), Image.LANCZOS).save(dest, "PNG")


QA_QUESTION = """Does this image clearly show the requested subject and action, in a setting that fits the request?
REQUEST: {request}
Answer exactly one:
YES
NO: <reason in 2-5 words>
Answer NO if: the main subject or action is different or missing; the setting clearly contradicts the request
(e.g. an airplane cabin when the request is outdoors, a factory when it asks for a hotel roof); it is several
panels, a comic page, a collage or a split screen instead of one single frame; or it shows garbled or fake text.
Do NOT require the identity of a specific real landmark, building, brand or person: a generic painterly version
is fine (any old downtown hotel for a named hotel, any 1970s airliner for a named flight).
Answer YES when the requested subject and action are clearly recognizable in one frame that fits the setting."""


def check_image(path: Path, request: str, wait: bool = True) -> tuple[bool | None, str]:
    """Strict Gemini vision check (same free key): (True, "") = PASS, (False, reason) = FAIL, (None, reason) = QA
    skipped. Paced to config image_check_per_minute (10): wait=True waits for the next slot (a few seconds),
    wait=False skips instead (used for Cloudflare images, so fallback checks keep the free quota).
    A 429 skips the check for this image only: no long sleep, no retry, never fails the build."""
    if not CONFIG.get("image_check", True):
        return None, "off"
    key = env("GEMINI_API_KEY", required=False)
    if not key:
        return None, "no_key"
    gap = 60 / max(1, float(CONFIG.get("image_check_per_minute", 10))) - (time.time() - _STATE.get("qa_last", 0))
    if gap > 0:
        if not wait:
            return None, "paced"
        time.sleep(gap)
    _STATE["qa_last"] = time.time()
    models = CONFIG.get("llm_models", [])
    model = CONFIG.get("image_check_model") or next((m for m in models if "lite" in m), models[0] if models else "")
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((512, 512))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                          headers={"x-goog-api-key": key}, timeout=15, json={
                              "contents": [{"role": "user", "parts": [
                                  {"inline_data": {"mime_type": "image/jpeg",
                                                   "data": base64.b64encode(buf.getvalue()).decode()}},
                                  {"text": QA_QUESTION.format(request=request)}]}],
                              "generationConfig": {"temperature": 0, "maxOutputTokens": 20}})
    except Exception as e:  # noqa: BLE001
        return None, f"error {str(e)[:60]}"
    if r.status_code == 429:
        return None, "rate_limited"
    if r.status_code != 200:
        return None, f"http_{r.status_code}"
    try:
        answer = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:  # noqa: BLE001
        return None, "no_answer"
    if answer.upper().startswith("YES"):
        return True, ""
    if answer.upper().startswith("NO"):
        return False, re.sub(r"^NO\W*", "", answer, flags=re.IGNORECASE).strip().lower()[:60] or "mismatch"
    return None, "unclear_answer"


_NAMES = {"_cloudflare": "cloudflare", "_hf_space": "hf_space", "_local_sd": "local_sd"}


class ImageQuotaWait(RuntimeError):
    """No free image quota for this video right now: stop early, the next build continues it."""


def test_cloudflare_images() -> int:
    """Test builds: how many real Cloudflare images to use (build.yml input test_cloudflare_images, 0-12)."""
    try:
        return max(0, min(12, int(os.environ.get("TEST_CF_IMAGES") or 0))) if test_mode() else 0
    except ValueError:
        return 0


def _quota_stop(detail: str) -> None:
    log(f"Waiting for image quota: {detail}")
    try:
        from notify import notify_text
        notify_text("Night Files: waiting for image quota", f"{detail}\nThe buffer covers the gap; Cloudflare resets "
                    "at 00:00 UTC (8 PM New York).", warn=True)
    except Exception as e:  # noqa: BLE001
        log(f"Quota alert not sent ({e})")
    raise ImageQuotaWait(f"waiting for image quota: {detail}")


def _place(story: dict, i: int, letter: str) -> tuple[str, bool]:
    """(location name of the shot or "", is it an outdoor shot) - decides which images may stand in for it."""
    shot = story["scenes"][i].get(PROMPT_KEYS[letter]) or ""
    loc = _shot_location(story, i, letter, _clean_shot(shot))
    return _key(loc["name"]) if loc else "", _is_exterior_shot(shot)


def _fits(story: dict, i: int, letter: str, j: int, other: str) -> bool:
    """May shot (j, other) stand in for (i, letter)? Same location, or both without one and both in- or outdoors.
    Never an airplane-cabin image for a forest shot."""
    (p1, out1), (p2, out2) = _place(story, i, letter), _place(story, j, other)
    return (p1 == p2 and bool(p1)) or (not p1 and not p2 and out1 == out2)


def generate_images(story: dict, outdir: Path) -> list[list[Path]]:
    """`shots_per_scene` images per scene (default 2: shot a = the narration's main visual, shot b = a different
    subject/angle of it). Returns [[a, b], ...]. Every image must pass the checks to be used: a valid portrait/square
    file, and (when Gemini QA is available) a strict "does it show this subject, action and location" check.
    Rejected images are never used; a missing shot is only covered by a fitting image from the same scene."""
    outdir.mkdir(parents=True, exist_ok=True)
    testing = test_mode()
    test_cf = test_cloudflare_images()
    if testing and not test_cf:
        cached = _cached_images(story, outdir)
        if cached:
            return cached
    style = CONFIG.get("image_style_cf") or CONFIG.get("image_style", "")
    dedupe_shots(story)  # the same picture twice in one video -> the later shot gets a different subject/angle
    base_seed = random.randint(1, 2_000_000_000)
    has_cf = bool(env("CLOUDFLARE_API_TOKEN", required=False)) and (not testing or test_cf > 0)
    qa_cf = CONFIG.get("image_check_cloudflare", True)
    local_max = int(CONFIG.get("local_image_max", 6))

    jobs = []  # (scene index, shot letter, prompt)
    for i, scene in enumerate(story["scenes"]):
        for letter in _letters():
            text = scene.get(PROMPT_KEYS[letter]) or ""
            if text.strip():
                jobs.append((i, letter, text))
    # Every scene's "a" shot first, then every "b", then any extra cuts: if a quota or the local time budget runs
    # out we lose cuts, never whole scenes.
    jobs.sort(key=lambda j: ("abcd".index(j[1]), j[0]))

    results: dict[tuple[int, str], Path | None] = {}
    rejected_files: dict[tuple[int, str], Path] = {}
    count = {"cloudflare": 0, "hf_space": 0, "local_sd": 0, "rejected": 0, "virtual_cached": 0}
    told_two = False
    done_shots: list[str] = []

    def cf_usable() -> bool:  # test builds: only the first `test_cloudflare_images` images
        return has_cf and not _STATE["cf_out"] and (not testing or count["cloudflare"] < test_cf)

    for n, (i, shot, raw_prompt) in enumerate(jobs):
        tag = f"{i:02d}{shot}"
        path = outdir / f"scene_{i:02d}{shot}.png"
        use_cf = cf_usable()
        # Production: SD-Turbo is only a gap filler (local_image_max, 6 per video). With Cloudflare and the Spaces
        # out, more local images than that = stop now (story + narration stay in the checkpoint) instead of
        # burning the time budget; the buffer covers the gap.
        if not testing and not use_cf and _STATE["spaces_out"]:
            have = {j for (j, _s), p in results.items() if p}
            needed = len({j for (j, s2, _) in jobs[n:] if j not in have
                          and not _is_image(outdir / f"scene_{j:02d}{s2}.png")})
            if needed > local_max - count["local_sd"]:
                _quota_stop(f"Cloudflare and the free Spaces are out; {needed} scenes still need an image but "
                            f"local SD-Turbo is a gap filler only ({local_max - count['local_sd']} of {local_max} "
                            "left). Stopped early; the story is kept and the next build continues it.")
        # Cloudflare out (or test mode): the fallbacks are slow/limited, so at most 2 shots per scene from here on.
        if shot in ("c", "d") and not use_cf and not _is_image(path):
            if not told_two:
                log("Cloudflare not available: 2 shots per scene for the rest of this run")
                told_two = True
            continue
        if _is_image(path):  # checkpoint from an earlier try of this same story (it passed its checks then)
            count["virtual_cached"] += 1
            results[(i, shot)] = path
            log(f"Image {tag}: provider=checkpoint")
            continue
        # Last guard before spending anything: a prompt nearly identical to one already made is rebuilt.
        if any(near_duplicate(raw_prompt, p) for p in done_shots):
            raw_prompt = _reframe(raw_prompt, story["scenes"][i].get("narration", ""), done_shots)
            story["scenes"][i][PROMPT_KEYS[shot]] = raw_prompt
            if raw_prompt.startswith("close-up of the "):
                story["scenes"][i][LOC_KEYS[shot]] = "none"
            log(f"Image {tag}: near-duplicate of an earlier shot, rebuilt as: {raw_prompt}")
        done_shots.append(raw_prompt)
        subject, place = shot_request(story, i, raw_prompt, shot)
        request = subject + (f", location: {place}" if place else "")
        prompts = {"full": build_prompt(story, i, raw_prompt, style, letter=shot),       # Cloudflare
                   "short": build_short_prompt(story, i, raw_prompt, letter=shot),       # Spaces / SD-Turbo
                   "simple": build_simple_prompt(story, i, raw_prompt, letter=shot)}     # after a QA rejection
        chain = (([_cloudflare] if use_cf else [])
                 + ([] if testing or _STATE["spaces_out"] else [_hf_space])
                 + ([] if _STATE["local_out"] else [_local_sd]))
        if not chain:
            if not _STATE.get("told_none"):
                log("No image source left (Cloudflare/Spaces out, local time budget used): using what exists")
                _STATE["told_none"] = True
            results[(i, shot)] = None
            continue
        ok, used, fallback_rejections, draws, last_kind = False, set(), 0, 0, ""
        # The hook shot (scene 0, shot a) is the thumbnail: up to 3 draws (new seed, then a simplified prompt)
        # with the last source that drew, before it is dropped.
        extra = 2 if (i, shot) == (0, "a") else 0
        last = None
        for k in range(len(chain) + extra):
            if k < len(chain):
                provider, retry = chain[k], 0
                if fallback_rejections >= 2:
                    continue  # one retry after a fallback rejection, then (hook only) the extra draws below
            else:
                if ok or last is None or draws >= 3:
                    break
                provider, retry = last, k - len(chain) + 1
            if (provider is _cloudflare and not cf_usable()) or (provider is _hf_space and _STATE["spaces_out"]) \
                    or (provider is _local_sd and _STATE["local_out"]):
                continue
            if provider is _local_sd and not testing and count["local_sd"] >= local_max:
                _STATE["local_out"] = True
                log(f"Local SD-Turbo gap-filler limit reached ({local_max} images this video)")
                continue
            name = _NAMES[provider.__name__]
            if retry == 1:  # hook: same prompt, new seed
                kind = last_kind
            elif retry == 2:  # hook: simplified prompt
                kind = "simple"
            else:
                kind = "full" if provider is _cloudflare else ("short" if not fallback_rejections else "simple")
                if prompts[kind] in used:  # never send the exact same prompt twice
                    kind = "simple"
                if prompts[kind] in used:
                    continue
            p = prompts[kind]
            neurons_before = _STATE["cf_neurons"]
            try:
                _save_valid(provider(p, base_seed + n * 7 + k), path)  # one try per provider, no blind retries
            except Exception as e:  # noqa: BLE001
                log(f"Image {tag}: provider={name} failed: {str(e)[:150]}")
                continue
            used.add(p)
            draws += 1
            last, last_kind = provider, kind
            tokens = clip_tokens(p)
            if provider is _cloudflare:
                count["cloudflare"] += 1
                if not qa_cf:
                    verdict, why = None, "off_for_cloudflare"
                else:  # only when a paced slot is free right now: fallback checks keep priority on the quota
                    verdict, why = check_image(path, request, wait=False)
            else:
                count[name] += 1
                verdict, why = check_image(path, request)
            qa = "PASS" if verdict else ("FAIL" if verdict is False else "SKIPPED")
            extra_log = f", neurons~{_STATE['cf_neurons'] - neurons_before:.1f}" if provider is _cloudflare else ""
            log(f"Image {tag}: provider={name}, tokens={tokens}, qa={qa}"
                + (f", reason={why}" if why else "") + f', subject="{subject[:60]}", location="{place or "-"}"'
                + extra_log + (f", hook retry {retry}" if retry else "") + f" | prompt: {p}")
            if verdict is False:  # clearly wrong: never used; the next source tries (once) with a simpler prompt
                count["rejected"] += 1
                bad = path.with_name(f"{path.stem}.rejected{draws}.png")
                path.replace(bad)
                rejected_files[(i, shot)] = bad
                if provider is not _cloudflare:
                    fallback_rejections += 1
                continue
            ok = True
            break
        results[(i, shot)] = path if ok else None
        if not ok:
            log(f"Image {tag}: no usable image")

    # A shot with no usable image: a virtual shot (crop) of a fitting image from the SAME scene, never another place.
    for (i, shot), p in list(results.items()):
        if p is not None:
            continue
        sib = next((s for s in _letters() if s != shot and results.get((i, s)) and _fits(story, i, shot, i, s)), None)
        if sib:
            _virtual_shot(results[(i, sib)], outdir / f"scene_{i:02d}{shot}.png", shot)
            results[(i, shot)] = outdir / f"scene_{i:02d}{shot}.png"
            count["virtual_cached"] += 1
            log(f"Image {i:02d}{shot}: virtual shot from {i:02d}{sib} (same scene, same place)")

    n_scenes = len(story["scenes"])
    empty = [i for i in range(n_scenes) if not any(results.get((i, s)) for s in "abcd")]
    log(f"Cloudflare images: {count['cloudflare']}")
    log(f"Cloudflare estimated neurons: {_STATE['cf_neurons']:.0f}")
    log(f"HF images: {count['hf_space']}")
    log(f"Local SD images: {count['local_sd']}" + (f" ({_STATE['local_secs']:.0f}s)" if _STATE["local_secs"] else ""))
    log(f"Rejected images: {count['rejected']}")
    log(f"Virtual/cached images: {count['virtual_cached']}")
    missing = len(jobs) - sum(1 for p in results.values() if p)
    if missing or empty:
        log(f"Missing {missing} of {len(jobs)} shots; {len(empty)} of {n_scenes} scenes have no image at all")
    if len(empty) > max(1, n_scenes // 4):
        raise RuntimeError(f"{len(empty)} of {n_scenes} scenes have no image; not rendering a broken video.")

    per_scene: list[list[Path]] = []
    for i in range(n_scenes):
        shots = [results[(i, s)] for s in "abcd" if results.get((i, s))]
        if not shots:  # emergency only (the run already allows at most max(1, scenes // 4) of these)
            near = sorted((j for j in range(n_scenes) if j != i), key=lambda j: abs(j - i))
            pick = next((results[(j, s)] for j in near for s in "abcd"
                         if results.get((j, s)) and _fits(story, i, "a", j, s)), None)
            own_bad = next((rejected_files[(i, s)] for s in "abcd" if (i, s) in rejected_files), None)
            if pick is None and own_bad:
                pick = own_bad
                log(f"Scene {i}: EMERGENCY, no fitting image anywhere; keeping its rejected image {pick.name}")
            if pick is None:
                pick = per_scene[-1][-1] if per_scene else next(p for p in results.values() if p)
                log(f"Scene {i}: EMERGENCY, borrowing {pick.name} (no image of this scene or its place exists)")
            else:
                log(f"Scene {i}: no image of its own, using {pick.name} (same place)")
            shots = [pick]
        per_scene.append(shots)
    return per_scene
