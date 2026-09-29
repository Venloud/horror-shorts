"""Real media first: stock video and real archive photos for the shots the scene plan marks, before any AI image.

Each shot of the scene plan has "image_source" (ai / stock_video / real_photo) and "image_query" (_2.._4 for the
other shots). This module fills the stock_video / real_photo shots; everything left over is drawn by images.py.
  stock_video  Pexels Videos (PEXELS_API_KEY) -> Pixabay Videos (PIXABAY_API_KEY): portrait, >= 1080 tall.
  real_photo   Wikimedia Commons (no key; Public domain / CC0 / CC BY only) -> Smithsonian Open Access (SI_API_KEY,
               CC0 only). TRUE stories only; never private people, victims or crime-scene photos (scene-plan rule).
Every candidate gets the same Gemini QA as the AI images (paced); a fail tries the next result (max 3), then the
shot falls back to an AI image. Real media is colour-graded to the channel look. Output per shot:
  scene_XXl.png   the (graded, 1080x1920) photo, or the stock clip's middle frame as a poster
  scene_XXl.mp4   stock clip (graded, 1080x1920, 30 fps, no audio), used by render.py as real motion
  scene_XXl.json  source, url, author, license, date (also collected in story["media_assets"])
Flags: real_media (whole feature), real_media_sources {pexels, pixabay, wikimedia, smithsonian}. Any error or a
missing key = that source is skipped and the shot stays AI; this module never stops a build.
"""
import hashlib
import html
import io
import json
import re
import subprocess
import time
from pathlib import Path

import requests
from PIL import Image

from common import CONFIG, ROOT, env, log

UA = "NightFilesBot/1.0 (https://github.com/Venloud/horror-shorts; automated short-video builder)"
CACHE = ROOT / "cache" / "media-search"   # search results, kept 24 h (build.yml saves it to the Actions cache)
CACHE_HOURS = 24
SRC_KEYS = {"a": "image_source", "b": "image_source_2", "c": "image_source_3", "d": "image_source_4"}
QUERY_KEYS = {"a": "image_query", "b": "image_query_2", "c": "image_query_3", "d": "image_query_4"}
PROMPT_KEYS = {"a": "image_prompt", "b": "image_prompt_2", "c": "image_prompt_3", "d": "image_prompt_4"}
W, H, FPS = 1080, 1920, 30
# Channel look: dark, desaturated, teal shadows / amber highlights, vignette (render adds grain + the global grade).
GRADE = ("eq=saturation=0.6:contrast=1.08:brightness=-0.05:gamma=0.95,"
         "colorbalance=rs=-0.06:bs=0.07:rh=0.07:gh=0.02:bh=-0.06,vignette=PI/4.5")
FIT = f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1"
NAMES = {"pexels": "Pexels", "pixabay": "Pixabay", "wikimedia": "Wikimedia Commons",
         "smithsonian": "Smithsonian Open Access"}


def enabled(source: str | None = None) -> bool:
    if not CONFIG.get("real_media", True):
        return False
    return source is None or bool((CONFIG.get("real_media_sources") or {}).get(source, True))


# ---------- search (cached 24 h) ----------

def _cached(provider: str, query: str, fetch) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{provider}_{hashlib.sha1(query.lower().encode()).hexdigest()[:16]}.json"
    if f.exists() and time.time() - f.stat().st_mtime < CACHE_HOURS * 3600:
        try:
            return json.loads(f.read_text())
        except ValueError:
            pass
    data = fetch()
    f.write_text(json.dumps(data))
    return data


def _pexels_slot() -> bool:
    """Pexels allows 200 requests/hour: keep a rolling log and stay under it (190)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / "pexels_calls.json"
    try:
        calls = [t for t in json.loads(f.read_text()) if time.time() - t < 3600] if f.exists() else []
    except ValueError:
        calls = []
    if len(calls) >= 190:
        return False
    f.write_text(json.dumps(calls + [time.time()]))
    return True


def pexels(query: str) -> list[dict]:
    key = env("PEXELS_API_KEY", required=False)
    if not key or not enabled("pexels"):
        return []

    def fetch():
        if not _pexels_slot():
            raise RuntimeError("Pexels hourly limit reached (200/h)")
        r = requests.get("https://api.pexels.com/v1/videos/search", timeout=30, headers={"Authorization": key},
                         params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 15})
        r.raise_for_status()
        return r.json()

    out = []
    for v in _cached("pexels", query, fetch).get("videos") or []:
        files = [f for f in v.get("video_files") or [] if f.get("link") and (f.get("height") or 0) >= 1080
                 and (f.get("height") or 0) > (f.get("width") or 0)]
        if not files:
            continue
        f = min(files, key=lambda x: abs((x.get("height") or 0) - H))  # closest to 1920 tall, not 4K
        out.append({"kind": "video", "source": "pexels", "id": f"pexels:{v.get('id')}", "url": v.get("url"),
                    "download": f["link"], "author": (v.get("user") or {}).get("name", ""),
                    "license": "Pexels License", "date": "", "duration": v.get("duration") or 0})
    return out


def pixabay(query: str) -> list[dict]:
    key = env("PIXABAY_API_KEY", required=False)
    if not key or not enabled("pixabay"):
        return []

    def fetch():
        r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={
            "key": key, "q": query[:100], "per_page": 30, "safesearch": "true", "video_type": "film"})
        r.raise_for_status()
        return r.json()

    out = []
    for v in _cached("pixabay", query, fetch).get("hits") or []:
        for size in ("large", "medium", "small"):
            f = (v.get("videos") or {}).get(size) or {}
            if f.get("url") and (f.get("height") or 0) > (f.get("width") or 0) and (f.get("height") or 0) >= 1080:
                out.append({"kind": "video", "source": "pixabay", "id": f"pixabay:{v.get('id')}",
                            "url": v.get("pageURL"), "download": f["url"], "author": v.get("user", ""),
                            "license": "Pixabay Content License", "date": "", "duration": v.get("duration") or 0})
                break  # vertical only (most Pixabay videos are landscape and get dropped)
    return out


def _strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def license_ok(name: str) -> bool:
    """Wikimedia: ONLY Public domain, CC0 and CC BY (no SA / NC / ND, no GFDL)."""
    n = (name or "").lower().replace("-", " ").strip()
    if any(x in n.split() for x in ("sa", "nc", "nd")) or "sharealike" in n or "gfdl" in n:
        return False
    return ("public domain" in n or n.startswith("pd") or "cc0" in n or n == "cc zero"
            or bool(re.fullmatch(r"cc by( \d(\.\d)?)?( [a-z]{2,3})?", n)))


_WM_LOCK = {"last": 0.0}


def _wikimedia_get(params: dict) -> dict:
    """One request at a time, a proper User-Agent, Retry-After honored (once, max 30 s)."""
    for attempt in range(2):
        wait = 1.0 - (time.time() - _WM_LOCK["last"])
        if wait > 0:
            time.sleep(wait)
        _WM_LOCK["last"] = time.time()
        r = requests.get("https://commons.wikimedia.org/w/api.php", params=params, timeout=30,
                         headers={"User-Agent": UA})
        if r.status_code in (429, 503) and attempt == 0:
            try:
                delay = min(30, int(float(r.headers.get("Retry-After", 5))))
            except ValueError:
                delay = 5
            log(f"Wikimedia asked to wait {delay}s")
            time.sleep(delay)
            continue
        r.raise_for_status()
        return r.json()
    return {}


def wikimedia(query: str) -> list[dict]:
    if not enabled("wikimedia"):
        return []
    params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
              "gsrnamespace": 6, "gsrlimit": 12, "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
              "iiurlwidth": 1600}
    data = _cached("wikimedia", query, lambda: _wikimedia_get(params))
    pages = sorted(((data.get("query") or {}).get("pages") or {}).values(), key=lambda p: p.get("index", 99))
    out = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata") or {}
        lic = _strip_html((meta.get("LicenseShortName") or {}).get("value", ""))
        if not license_ok(lic) or not (ii.get("mime") or "").startswith("image/"):
            continue
        if min(ii.get("width") or 0, ii.get("height") or 0) < 700:
            continue
        out.append({"kind": "photo", "source": "wikimedia", "id": f"wikimedia:{p.get('pageid')}",
                    "url": ii.get("descriptionurl"), "download": ii.get("thumburl") or ii.get("url"),
                    "title": p.get("title", ""), "author": _strip_html((meta.get("Artist") or {}).get("value", ""))[:120],
                    "license": lic, "date": _strip_html((meta.get("DateTimeOriginal") or {}).get("value", ""))[:40]})
    return out


def smithsonian(query: str) -> list[dict]:
    key = env("SI_API_KEY", required=False)
    if not key or not enabled("smithsonian"):
        return []

    def fetch():
        r = requests.get("https://api.si.edu/openaccess/api/v1.0/search", timeout=30, params={
            "q": f'{query} AND online_media_type:"Images"', "rows": 12, "api_key": key})
        r.raise_for_status()
        return r.json()

    out = []
    for row in ((_cached("smithsonian", query, fetch).get("response") or {}).get("rows") or []):
        dnr = (row.get("content") or {}).get("descriptiveNonRepeating") or {}
        for m in ((dnr.get("online_media") or {}).get("media") or []):
            if m.get("type") != "Images" or ((m.get("usage") or {}).get("access") or "").upper() != "CC0":
                continue  # CC0 only
            dl = m.get("content") or ""
            if not dl.startswith("http"):
                continue
            dates = (((row.get("content") or {}).get("indexedStructured") or {}).get("date") or [""])
            out.append({"kind": "photo", "source": "smithsonian", "id": f"smithsonian:{row.get('id')}",
                        "url": dnr.get("record_link") or dl, "download": dl, "title": row.get("title", ""),
                        "author": dnr.get("data_source", "Smithsonian Institution"), "license": "CC0",
                        "date": str(dates[0])[:40]})
            break
    return out


PROVIDERS = {"stock_video": (pexels, pixabay), "real_photo": (wikimedia, smithsonian)}


# ---------- download + grade ----------

def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-300:])


def _download(url: str, dest: Path, max_mb: int = 80) -> Path:
    with requests.get(url, headers={"User-Agent": UA}, timeout=120, stream=True) as r:
        r.raise_for_status()
        size = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                size += len(chunk)
                if size > max_mb * 1_000_000:
                    raise RuntimeError(f"file over {max_mb} MB")
                f.write(chunk)
    return dest


def _photo(c: dict, png: Path) -> None:
    """Crop the photo to 9:16 around the centre (never upscaled from a tiny crop), grade it, 1080x1920 PNG."""
    raw = png.with_suffix(".src")
    _download(c["download"], raw, max_mb=40)
    with Image.open(raw) as im:
        im = im.convert("RGB")
        w, h = im.size
        cw, ch = (w, int(w * 16 / 9)) if w * 16 / 9 <= h else (int(h * 9 / 16), h)
        if ch < 900:
            raise RuntimeError(f"too small for a vertical frame ({w}x{h})")
        x, y = (w - cw) // 2, (h - ch) // 2
        im.crop((x, y, x + cw, y + ch)).resize((W, H), Image.LANCZOS).save(raw.with_suffix(".crop.png"))
    raw.unlink(missing_ok=True)
    src = raw.with_suffix(".crop.png")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", f"{GRADE},noise=alls=5", "-frames:v", "1",
          str(png)])
    src.unlink(missing_ok=True)


def _video(c: dict, png: Path) -> Path:
    """Trim (skip the first second, max 8 s), 1080x1920, 30 fps, no audio, graded + grain; poster frame to png."""
    raw = png.with_suffix(".src.mp4")
    _download(c["download"], raw)
    mp4 = png.with_suffix(".mp4")
    start = 1.0 if (c.get("duration") or 0) > 5 else 0.0
    _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start}", "-i", str(raw), "-t", "8", "-map", "0:v:0", "-an",
          "-vf", f"{FIT},fps={FPS},{GRADE},noise=alls=8:allf=t+u,format=yuv420p", "-c:v", "libx264",
          "-preset", "veryfast", "-crf", "23", str(mp4)])
    raw.unlink(missing_ok=True)
    # ONE single frame from the middle of the clip for the poster + QA (never a tiled / multi-frame picture)
    try:
        mid = max(0.0, float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                             "default=nw=1:nk=1", str(mp4)], capture_output=True,
                                            text=True).stdout.strip() or 6) / 2)
    except ValueError:
        mid = 3.0
    _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{mid:.2f}", "-i", str(mp4), "-frames:v", "1",
          "-update", "1", str(png)])
    return mp4


# ---------- main entry ----------

def _recent_ids(history: list[dict], window: int) -> set[str]:
    ids: set[str] = set()
    for h in [h for h in history if h.get("buffered")][-window:]:
        ids.update(h.get("media_ids") or [])
    return ids


def _remove(png: Path) -> None:
    for p in (png, png.with_suffix(".mp4"), png.with_suffix(".json")):
        p.unlink(missing_ok=True)


def fill_shots(story: dict, outdir: Path, history: list[dict]) -> list[dict]:
    """Fill the scene plan's stock_video / real_photo shots with real media. Returns story["media_assets"].
    Never raises: any problem leaves the shot to the AI images."""
    try:
        return _fill(story, outdir, history)
    except Exception as e:  # noqa: BLE001
        log(f"Real media skipped ({type(e).__name__}: {str(e)[:200]})")
        return story.setdefault("media_assets", [])


_PERSON = re.compile(r"\b(man|men|woman|women|girl|boy|guest|guests|officer|officers|police|policeman|detective|"
                     r"receptionist|clerk|worker|workers|staff|people|person|crowd|child|children|he|she|they|his|"
                     r"her|him|figure|hijacker|passenger|passengers|pilot|nurse|doctor|victim|stranger|narrator|"
                     r"family|couple|friends|someone|anyone)\b", re.IGNORECASE)
_ATMOS = re.compile(r"\b(fog|mist|rain|storm|night|sky|moon|clouds?|forest|woods|trees?|river|lake|sea|ocean|waves|"
                    r"road|street|city|skyline|hallway|corridor|stairs|staircase|doors?|window|room|building|hotel|"
                    r"house|exterior|tank|water|faucet|sink|lights?|candle|lamp|shadows?|smoke|fire|snow|field|bridge|"
                    r"alley|elevator|rooftop|roof|calendar|clock|keys?|phone|screen|tv|monitor|tape|camera|car|"
                    r"airplane|plane|aircraft|cabin|ship|boat|church|cemetery|grave|lighthouse|tunnel|basement)\b",
                    re.IGNORECASE)
_PROPER = re.compile(r"\b((?:[A-Z][a-z]+|[A-Z]\.)(?:\s+(?:[A-Z][a-z]+|[A-Z]\.|of|the|de))*\s+[A-Z][a-z]+)\b")
_STOP = set(("a an the of in on at to with and or its his her their is are was from by for into near under over as "
             "while shot close up close-up medium wide establishing view light lighting dark shadow shadows mood eerie "
             "tense cinematic frame angle eye level atmosphere soft warm cold dim harsh casting glow uneasy ominous "
             "unsettling mysterious quiet silent faint hinting where which that vague slowly against into onto inside "
             "outside turned highlighted flickers flickering glistening catching").split())


# Words that make stock search imprecise ("rooftop water tank exterior" returned a flag video): framing, mood,
# colour and vague adjectives. A stock query is 2-4 concrete nouns.
_VAGUE = set(("exterior interior closeup close up shot view scene background foreground low high flow stuck open "
              "opened dark darkness eerie creepy scary spooky old vintage empty lonely strange weird small large big "
              "huge tiny heavy thin thick long short black white grey gray red blue green yellow brown pale bright "
              "dripping running leaking moving slow fast night-time daytime evening morning afternoon very some many "
              "every one two three single double little tall wide narrow").split())


def clean_query(query: str, most: int = 4) -> str:
    """2-4 concrete nouns for stock search: no framing, mood, colour or vague words."""
    words = [w for w in re.findall(r"[A-Za-z]+", query.lower())
             if w not in _STOP and w not in _VAGUE and len(w) > 2]
    words = list(dict.fromkeys(words))[:most]
    return " ".join(words) if words else " ".join(re.findall(r"[A-Za-z]+", query.lower())[:3])


def _stock_query(text: str) -> str:
    return clean_query(text, 3)


def honest_place_shots(story: dict) -> int:
    """Cloudflare-out days: a scene whose every shot shows a story character can't get real media, so its
    SECOND shot becomes an honest place shot: the scene's own location, empty (e.g. "the Cecil Hotel lobby").
    Only when the scene has a known location; never invents a place. Flag honest_place_shots."""
    if not CONFIG.get("honest_place_shots", True):
        return 0
    import images
    locs = {l.get("name", "").lower().removeprefix("the "): l for l in story.get("locations") or [] if l.get("look")}
    n = 0
    for i, sc in enumerate(story.get("scenes") or []):
        filled = [l for l in images._letters() if (sc.get(PROMPT_KEYS[l]) or "").strip()]
        if not filled or any((sc.get(SRC_KEYS[l]) or "ai") != "ai" for l in filled):
            continue  # already has a real-media shot
        name = ""
        for key in (images.LOC_KEYS.get("b", ""), images.LOC_KEYS.get("a", ""), "location"):
            cand = (sc.get(key) or "").lower().removeprefix("the ").strip()
            if cand in locs:
                name = cand
                break
        if not name:
            continue
        loc = locs[name]
        proper = [m.group(1) for m in _PROPER.finditer(loc.get("name", ""))]
        real = bool(story.get("true_story")) and bool(proper)
        sc[PROMPT_KEYS["b"]] = f"{loc['look'].strip().rstrip('.')}, empty, no people"
        sc[images.LOC_KEYS["b"]] = loc["name"]
        sc[SRC_KEYS["b"]] = "real_photo" if real else "stock_video"
        sc[QUERY_KEYS["b"]] = loc["name"] if real else clean_query(loc["look"], 3)
        n += 1
        log(f"Shot {i:02d}b: every shot showed a character; now an honest place shot of '{loc['name']}' "
            f"({sc[SRC_KEYS['b']]}, query \"{sc[QUERY_KEYS['b']]}\")")
    return n


def auto_tag(story: dict) -> int:
    """Re-classify EVERY shot in code after planning (the planner's own tag is not trusted: Groq tagged every shot
    "ai", even "empty hotel hallway"): no story character / person in the shot + atmosphere, place or object ->
    stock_video; a named real place or object in a TRUE story -> real_photo; else ai. Runs for every story,
    inbox SCRIPT / TRUE SCRIPT included. Flag real_media_auto_tag. The hook (scene 1 shot a) always stays ai.
    Returns how many shots got real media."""
    if not CONFIG.get("real_media_auto_tag", True):
        return 0
    import images
    true = bool(story.get("true_story"))
    names = [c.get("name", "").lower().removeprefix("the ") for c in story.get("characters") or [] if c.get("name")]
    changed = 0
    for i, sc in enumerate(story.get("scenes") or []):
        for l in images._letters():
            text = (sc.get(PROMPT_KEYS[l]) or "").strip()
            cur = (sc.get(SRC_KEYS[l]) or "").strip().lower()
            if not text:
                continue
            if (i, l) == (0, "a"):
                sc[SRC_KEYS[l]] = "ai"
                continue
            low = text.lower()
            if _PERSON.search(text) or any(nm and nm in low for nm in names):
                new, query = "ai", ""
            else:
                proper = [m.group(1) for m in _PROPER.finditer(text)
                          if not any(nm and nm in m.group(1).lower() for nm in names)]
                if true and proper:
                    new, query = "real_photo", proper[0]
                elif _ATMOS.search(text) or images._OBJECTS.search(text):
                    new, query = "stock_video", _stock_query(text)
                else:
                    new, query = "ai", ""
            sc[SRC_KEYS[l]] = new
            if new != "ai":
                if new != cur or not (sc.get(QUERY_KEYS[l]) or "").strip():
                    sc[QUERY_KEYS[l]] = (sc.get(QUERY_KEYS[l]) or "").strip() if new == cur else query
                changed += 1
            if new != (cur or "ai"):
                log(f"Shot {i:02d}{l}: planner said {cur or 'nothing'}, re-classified {new}"
                    + (f' (query "{sc.get(QUERY_KEYS[l])}")' if new != "ai" else ""))
    return changed


def _cloudflare_out() -> bool:
    """Is Cloudflare unusable for this run (daily limit, no token, or a test build without Cloudflare images)?"""
    import images
    if images._STATE.get("cf_out"):
        return True
    if not env("CLOUDFLARE_API_TOKEN", required=False):
        return True
    if images.test_mode():
        if not images.test_cloudflare_images():
            return True
        if images.cloudflare_has_quota() is False:  # test builds skip preflight: ask now (a few neurons)
            images._STATE["cf_out"] = True
            return True
    return False


def _fill(story: dict, outdir: Path, history: list[dict]) -> list[dict]:
    import images  # the same paced Gemini QA and the same shot letters as the AI images

    assets: list[dict] = []
    story["media_assets"] = assets
    if not enabled():
        log("Real media: off (config real_media)")
        return assets
    outdir.mkdir(parents=True, exist_ok=True)
    true = bool(story.get("true_story"))
    images.sanitize_victim_shots(story)  # never a real victim's body, before anything is searched or drawn
    cf_out = _cloudflare_out() and CONFIG.get("real_media_when_cf_out", True)
    tagged = auto_tag(story)
    if cf_out:
        tagged += honest_place_shots(story)
    log(f"Shot sources re-classified: {tagged} shot(s) for real media")
    shots = [(i, l) for i, sc in enumerate(story["scenes"]) for l in images._letters()
             if (sc.get(PROMPT_KEYS[l]) or "").strip()]
    share = float(CONFIG.get("stock_video_max_share_cf_out", 1.0) if cf_out else CONFIG.get("stock_video_max_share", 0.4))
    max_stock = int(len(shots) * share)
    max_photo = int(CONFIG.get("real_photo_max", 3))
    if cf_out:
        log(f"Cloudflare is out: real media first for every eligible shot (stock limit {max_stock}), then Spaces, "
            f"then SD-Turbo (max {CONFIG.get('local_image_max', 6)})")
    recent = _recent_ids(history, int(CONFIG.get("stock_reuse_window", 20)))
    n = {"stock_video": 0, "real_photo": 0}
    used: set[str] = set()
    tried = 0
    for i, l in shots:
        sc = story["scenes"][i]
        png = outdir / f"scene_{i:02d}{l}.png"
        side = png.with_suffix(".json")
        if side.exists() and png.exists():  # checkpoint from an earlier try of this story
            meta = json.loads(side.read_text())
            assets.append(meta)
            used.add(meta["id"])
            n[meta["type"]] = n.get(meta["type"], 0) + 1
            continue
        kind = (sc.get(SRC_KEYS[l]) or "ai").strip().lower()
        if kind not in PROVIDERS or (i, l) == (0, "a"):  # the hook stays AI: thumbnail + AI animation
            continue
        if kind == "real_photo" and not true:
            log(f"Shot {i:02d}{l}: real_photo asked for a fiction story, using AI")
            continue
        if n[kind] >= (max_photo if kind == "real_photo" else max_stock):
            continue
        raw_q = (sc.get(QUERY_KEYS[l]) or "").strip() or sc[PROMPT_KEYS[l]]
        # stock: 2-4 concrete nouns; archive photos keep the real name ("Cecil Hotel Los Angeles")
        queries = [clean_query(raw_q)] if kind == "stock_video" else [raw_q]
        if kind == "stock_video" and len(queries[0].split()) > 2:
            queries.append(" ".join(queries[0].split()[:2]))  # second, broader try: the two main nouns
        request, _ = images.shot_request(story, i, sc[PROMPT_KEYS[l]], l)
        done = False
        for query in queries:
            cands = []
            for provider in PROVIDERS[kind]:
                try:
                    cands += provider(query)
                except Exception as e:  # noqa: BLE001
                    log(f"Shot {i:02d}{l}: {provider.__name__} search failed ({str(e)[:120]})")
            cands = [c for c in cands if c["id"] not in used and c["id"] not in recent]
            if not cands:
                log(f"Shot {i:02d}{l}: no {kind} result for '{query}'")
                continue
            done = _try_candidates(cands[:3], i, l, kind, query, request, png, side, assets, used, n, images)
            tried += min(3, len(cands))
            if done:
                break
        if not done:
            log(f"Shot {i:02d}{l}: no usable {kind}, using AI")
    log(f"Real media: {n['stock_video']} stock video(s), {n['real_photo']} real photo(s) "
        f"({tried} candidate(s) tried; limits {max_stock} stock / {max_photo} photos)")
    return assets


def _try_candidates(cands, i, l, kind, query, request, png, side, assets, used, n, images) -> bool:
    """QA fail -> next result (max 3). True = one was accepted."""
    for c in cands:
        try:
            (_video if c["kind"] == "video" else _photo)(c, png)
        except Exception as e:  # noqa: BLE001
            log(f"Shot {i:02d}{l}: {c['source']} {c['id']} unusable ({str(e)[:120]})")
            _remove(png)
            continue
        # real-media QA: one frame, judged on subject / setting / text / real faces / panels, never on colour
        verdict, why = images.check_image(png, request, kind="real")
        qa = "PASS" if verdict else ("FAIL" if verdict is False else "SKIPPED")
        log(f"Image {i:02d}{l}: provider={c['source']} ({c['kind']}), qa={qa}" + (f", reason={why}" if why else "")
            + f', query="{query}", url={c["url"]}')
        if verdict is False:
            _remove(png)
            used.add(c["id"])  # never retried by the second, broader query
            continue
        meta = {"scene": i, "shot": l, "type": kind, "kind": c["kind"], "source": c["source"], "id": c["id"],
                "url": c["url"], "author": c.get("author", ""), "license": c.get("license", ""),
                "date": c.get("date", ""), "title": c.get("title", ""), "query": query}
        side.write_text(json.dumps(meta, ensure_ascii=False))
        assets.append(meta)
        used.add(c["id"])
        n[kind] += 1
        return True
    return False


def credits(assets: list[dict]) -> tuple[str, str]:
    """(short line for the TikTok caption, full list for the YouTube description). Empty strings if none."""
    if not assets:
        return "", ""
    names = list(dict.fromkeys(NAMES.get(a["source"], a["source"]) for a in assets))
    short = "Visuals: " + ", ".join(names)
    lines = []
    for a in assets:
        what = "Video" if a.get("kind") == "video" else "Photo"
        title = f" \"{a['title'].replace('File:', '')}\"" if a.get("title") else ""
        by = f" by {a['author']}" if a.get("author") else ""
        lines.append(f"{what}{title}{by} ({a.get('license', '')}), {NAMES.get(a['source'], a['source'])}: {a['url']}")
    return short, "\n".join(dict.fromkeys(lines))
