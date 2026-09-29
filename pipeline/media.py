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
    _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "3", "-i", str(mp4), "-frames:v", "1", str(png)])
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


def _fill(story: dict, outdir: Path, history: list[dict]) -> list[dict]:
    import images  # the same paced Gemini QA and the same shot letters as the AI images

    assets: list[dict] = []
    story["media_assets"] = assets
    if not enabled():
        log("Real media: off (config real_media)")
        return assets
    outdir.mkdir(parents=True, exist_ok=True)
    true = bool(story.get("true_story"))
    shots = [(i, l) for i, sc in enumerate(story["scenes"]) for l in images._letters()
             if (sc.get(PROMPT_KEYS[l]) or "").strip()]
    max_stock = int(len(shots) * float(CONFIG.get("stock_video_max_share", 0.4)))
    max_photo = int(CONFIG.get("real_photo_max", 3))
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
        query = (sc.get(QUERY_KEYS[l]) or "").strip() or " ".join(re.findall(r"[A-Za-z]+", sc[PROMPT_KEYS[l]])[:5])
        cands = []
        for provider in PROVIDERS[kind]:
            try:
                cands += provider(query)
            except Exception as e:  # noqa: BLE001
                log(f"Shot {i:02d}{l}: {provider.__name__} search failed ({str(e)[:120]})")
        cands = [c for c in cands if c["id"] not in used and c["id"] not in recent]
        if not cands:
            log(f"Shot {i:02d}{l}: no {kind} result for '{query}', using AI")
            continue
        request, _ = images.shot_request(story, i, sc[PROMPT_KEYS[l]], l)
        for c in cands[:3]:  # QA fail -> next result (max 3) -> AI image
            tried += 1
            try:
                (_video if c["kind"] == "video" else _photo)(c, png)
            except Exception as e:  # noqa: BLE001
                log(f"Shot {i:02d}{l}: {c['source']} {c['id']} unusable ({str(e)[:120]})")
                _remove(png)
                continue
            verdict, why = images.check_image(png, request)
            qa = "PASS" if verdict else ("FAIL" if verdict is False else "SKIPPED")
            log(f"Image {i:02d}{l}: provider={c['source']} ({c['kind']}), qa={qa}" + (f", reason={why}" if why else "")
                + f', query="{query}", url={c["url"]}')
            if verdict is False:
                _remove(png)
                continue
            meta = {"scene": i, "shot": l, "type": kind, "kind": c["kind"], "source": c["source"], "id": c["id"],
                    "url": c["url"], "author": c.get("author", ""), "license": c.get("license", ""),
                    "date": c.get("date", ""), "title": c.get("title", ""), "query": query}
            side.write_text(json.dumps(meta, ensure_ascii=False))
            assets.append(meta)
            used.add(c["id"])
            n[kind] += 1
            break
        else:
            log(f"Shot {i:02d}{l}: no usable {kind}, using AI")
    log(f"Real media: {n['stock_video']} stock video(s), {n['real_photo']} real photo(s) "
        f"({tried} candidate(s) tried; limits {max_stock} stock / {max_photo} photos)")
    return assets


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
