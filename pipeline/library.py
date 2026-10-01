"""Asset library (flag `asset_library`): every picture / clip that passed QA in a finished video is kept for reuse.

Storage: GitHub release "assets" (free, no repo bloat): one file per asset (<id>.jpg, or <id>.mp4 + <id>.jpg poster)
and index.json with the metadata: source, license, attribution, url, description (the shot), tags, style, setting
(interior/exterior + place words), era, subjects, character_specific, embedding (CLIP ViT-B/32, float16 base64),
times_used, last_used_video, last_used_seq, uses [{story, seq, position, crop, grade, move}].
Embedding model: openai/clip-vit-base-patch32 (benchmarked on 4 CPUs against google/siglip-base-patch16-224:
same accuracy on our test set, top-1 0.93 / P@3 0.69 both, but 60 vs 237 ms per image and no sentencepiece).

Before an image is generated (library first, then real media / archives, then AI), fill_shots() looks for a match:
  hard filters  not character-specific (a named person / creature is never reused across stories), the shot itself
                shows no story character or person, style allowed for this story, interior/exterior equal, same era
                bucket (or either is "any"), times_used < 4, not used in the last 10 videos, not used before at the
                same position (early / middle / late) of a video
  similarity    CLIP text (the shot) vs image >= asset_min_similarity (0.27: 63% of true matches, 1% false)
  QA            the same Gemini / Groq vision check as every other picture
A reuse gets a different crop, grade and camera move than its earlier uses (scene_XXl.reuse.json tells render.py
which moves to avoid). Log "Reused asset <id> (use N)". Test builds may reuse but never write the library.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import requests

from common import CONFIG, ROOT, log

TAG = "assets"
MODEL = "openai/clip-vit-base-patch32"
LOCAL = ROOT / "cache" / "assets"
API = "https://api.github.com"
PROMPT_KEYS = {"a": "image_prompt", "b": "image_prompt_2", "c": "image_prompt_3", "d": "image_prompt_4"}
CROPS = ["left", "right", "tight", "top", "bottom", "center"]  # first reuse = a clearly different framing
GRADES = {  # small, visible differences; the channel look stays (render adds grain + the global grade)
    "cool": "eq=brightness=-0.03:saturation=0.85,colorbalance=bs=0.05:rs=-0.03",
    "warm": "eq=brightness=-0.02:saturation=0.9,colorbalance=rh=0.05:bh=-0.04",
    "dark": "eq=brightness=-0.07:contrast=1.08",
    "faded": "eq=contrast=0.92:saturation=0.7:brightness=-0.02",
    "base": "eq=contrast=1.0",
}
_STATE = {"index": None, "store": None, "model": None, "proc": None, "reused": 0, "readonly": False}


# ---------- storage: the "assets" release (or a local folder for tests: LIBRARY_DIR) ----------

class DirStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def get(self, name: str, dest: Path) -> bool:
        src = self.path / name
        if not src.exists():
            return False
        shutil.copy(src, dest)
        return True

    def put(self, name: str, src: Path) -> None:
        shutil.copy(src, self.path / name)

    def delete(self, name: str) -> None:
        (self.path / name).unlink(missing_ok=True)


class ReleaseStore:
    def __init__(self):
        self.repo = os.environ["GITHUB_REPOSITORY"]
        self.h = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json",
                  "X-GitHub-Api-Version": "2022-11-28"}
        self.rel = self._release()

    def _release(self) -> dict:
        r = requests.get(f"{API}/repos/{self.repo}/releases/tags/{TAG}", headers=self.h, timeout=30)
        if r.status_code == 200:
            return r.json()
        r = requests.post(f"{API}/repos/{self.repo}/releases", headers=self.h, timeout=30, json={
            "tag_name": TAG, "name": TAG, "prerelease": True,
            "body": "Night Files asset library: pictures / clips that passed QA, for reuse (pipeline/library.py). "
                    "Managed by the bot; index.json holds the metadata."})
        r.raise_for_status()
        return r.json()

    def _assets(self) -> dict:
        out, page = {}, 1
        while True:
            r = requests.get(f"{API}/repos/{self.repo}/releases/{self.rel['id']}/assets", headers=self.h,
                             params={"per_page": 100, "page": page}, timeout=30)
            r.raise_for_status()
            batch = r.json()
            out.update({a["name"]: a for a in batch})
            if len(batch) < 100:
                return out
            page += 1

    def get(self, name: str, dest: Path) -> bool:
        a = self._assets().get(name)
        if not a:
            return False
        with requests.get(a["url"], headers={**self.h, "Accept": "application/octet-stream"}, stream=True,
                          timeout=300) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        return True

    def put(self, name: str, src: Path) -> None:
        self.delete(name)
        base = self.rel["upload_url"].split("{")[0]
        ctype = {"json": "application/json", "mp4": "video/mp4"}.get(name.rsplit(".", 1)[-1], "image/jpeg")
        with open(src, "rb") as f:
            r = requests.post(f"{base}?name={name}", data=f, timeout=600, headers={**self.h, "Content-Type": ctype})
        if r.status_code not in (200, 201):
            raise RuntimeError(f"asset upload {name}: HTTP {r.status_code} {r.text[:150]}")

    def delete(self, name: str) -> None:
        a = self._assets().get(name)
        if a:
            requests.delete(a["url"], headers=self.h, timeout=30)


def _store():
    if _STATE["store"] is None:
        if os.environ.get("LIBRARY_DIR"):
            _STATE["store"] = DirStore(Path(os.environ["LIBRARY_DIR"]))
        elif os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY"):
            _STATE["store"] = ReleaseStore()
        else:
            raise RuntimeError("no GITHUB_TOKEN / LIBRARY_DIR")
    return _STATE["store"]


def load_index() -> dict:
    if _STATE["index"] is None:
        idx = {"seq": 0, "assets": []}
        try:
            LOCAL.mkdir(parents=True, exist_ok=True)
            if _store().get("index.json", LOCAL / "index.json"):
                idx = json.loads((LOCAL / "index.json").read_text())
        except Exception as e:  # noqa: BLE001
            log(f"Asset library unavailable ({str(e)[:120]}): no reuse this run")
            _STATE["readonly"] = True
        _STATE["index"] = idx
    return _STATE["index"]


def save_index() -> None:
    if _STATE["readonly"] or _STATE["index"] is None:
        return
    f = LOCAL / "index.json"
    f.write_text(json.dumps(_STATE["index"], ensure_ascii=False))
    _store().put("index.json", f)


# ---------- embeddings (CLIP ViT-B/32) ----------

def _model():
    if _STATE["model"] is None:
        from transformers import CLIPModel, CLIPProcessor
        _STATE["model"] = CLIPModel.from_pretrained(MODEL).eval()
        _STATE["proc"] = CLIPProcessor.from_pretrained(MODEL)
    return _STATE["model"], _STATE["proc"]


def _norm(v):
    import numpy as np
    v = np.asarray(v, dtype="float32")
    return v / (np.linalg.norm(v) + 1e-9)


def embed_image(path: Path):
    import torch
    from PIL import Image
    m, p = _model()
    with torch.no_grad():
        out = m.get_image_features(**p(images=[Image.open(path).convert("RGB")], return_tensors="pt"))
    return _norm(getattr(out, "pooler_output", out)[0].numpy())


def embed_text(text: str):
    import torch
    m, p = _model()
    with torch.no_grad():
        out = m.get_text_features(**p(text=[text[:300]], return_tensors="pt", padding=True, truncation=True))
    return _norm(getattr(out, "pooler_output", out)[0].numpy())


def _pack(v) -> str:
    import numpy as np
    return base64.b64encode(np.asarray(v, dtype="float16").tobytes()).decode()


def _unpack(s: str):
    import numpy as np
    return _norm(np.frombuffer(base64.b64decode(s), dtype="float16").astype("float32"))


# ---------- metadata ----------

_NATURE = re.compile(r"\b(fog|mist|sky|moon|clouds?|forest|woods|trees?|river|lake|sea|ocean|waves|snow|field|"
                     r"mountains?|stars?|rain|storm|lightning|night sky|swamp|marsh|desert|cave)\b", re.I)


_OUTDOOR = re.compile(r"\b(churchyard|cemetery|graveyard|gravestones?|tombstones?|street|road|path|village|town|"
                      r"outside|exterior|rooftops?|courtyard|garden|bridge|harbor|shore|beach|cliff|hill|valley|"
                      r"meadow|ruins|well)\b|" + _NATURE.pattern, re.I)


def era_of(story: dict) -> str:
    """Era bucket of the story: pre1800 / 1800s / 1900-1949 / 1950-1999 / modern; legends without a year: folk."""
    text = " ".join([story.get("setting") or ""] + [str(x) for x in story.get("fact_ledger") or []]
                    + [sc.get("narration", "") for sc in story.get("scenes") or []])
    years = sorted(int(y) for y in re.findall(r"\b(1[0-9]{3}|20[0-2][0-9])\b", text))
    words = re.findall(r"\b(eighteen|nineteen|seventeen|sixteen) (hundreds|[a-z]+ty)", text.lower())
    if not years and words:
        years = [{"sixteen": 1650, "seventeen": 1750, "eighteen": 1850, "nineteen": 1950}[w[0]] for w in words]
    if not years:
        return "folk" if story.get("mode") == "lore" else "modern"
    y = years[len(years) // 2]
    return ("pre1800" if y < 1800 else "1800s" if y < 1900 else "1900-1949" if y < 1950
            else "1950-1999" if y < 2000 else "modern")


def archive_story(story: dict) -> bool:
    """Lore, or a story set before 1950: archive prints / engravings fit it."""
    return story.get("mode") == "lore" or era_of(story) in ("pre1800", "1800s", "1900-1949", "folk")


def _position(i: int, n: int) -> str:
    return "early" if i < n / 3 else ("middle" if i < 2 * n / 3 else "late")


def _story_names(story: dict) -> list[str]:
    names = [c.get("name", "").lower().removeprefix("the ") for c in story.get("characters") or [] if c.get("name")]
    for x in (story.get("case"), story.get("remake_of")):
        if x:
            names.append(str(x).lower().removeprefix("the "))
    return [n for n in names if n]


def _shot_has_person(story: dict, text: str) -> bool:
    import media
    low = text.lower()
    return bool(media._PERSON.search(text)) or any(n and n in low for n in _story_names(story))


def _setting(story: dict, i: int, l: str, text: str) -> tuple[str, str]:
    import images
    loc = images._shot_location(story, i, l, images._clean_shot(text))
    look = (loc or {}).get("look", "")
    if _OUTDOOR.search(text) and not re.search(r"\b(inside|interior|room|hall|indoors)\b", text, re.I):
        inside = False
    else:
        inside = images._is_interior(look) if look else not images._is_exterior_shot(text)
    words = " ".join(images._content_words(f"{(loc or {}).get('name', '')} {look}")[:8])
    return ("interior" if inside else "exterior"), words


def _style_of(source: str, kind: str) -> str:
    if source in ("pexels", "pixabay"):
        return "stock_video"
    if source in ("loc", "openverse") and kind == "print":
        return "archive_print"
    if source in ("wikimedia", "smithsonian", "loc", "openverse"):
        return "photo"
    return "painted"


def _allowed_styles(story: dict) -> set:
    s = {"painted", "stock_video"}
    if archive_story(story):
        s.add("archive_print")
    if story.get("true_story"):
        s.add("photo")
    return s


# ---------- reuse ----------

def _variant(src: Path, dest: Path, crop: str, grade: str, video: bool) -> None:
    """A different crop + grade than earlier uses (the picture must not look identical to its last use)."""
    W, H = 1080, 1920
    box = {"center": (0.9, 0.5, 0.5), "left": (0.85, 0.3, 0.5), "right": (0.85, 0.7, 0.5),
           "top": (0.85, 0.5, 0.3), "bottom": (0.85, 0.5, 0.7), "tight": (0.75, 0.5, 0.45)}[crop]
    z, cx, cy = box
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"crop=iw*{z}:ih*{z}:(iw-iw*{z})*{cx}:(ih-ih*{z})*{cy},scale={W}:{H}:flags=lanczos,setsar=1,"
          f"{GRADES[grade]}")
    if video:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", vf + ",format=yuv420p", "-an",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", str(dest)]
    else:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", vf, "-frames:v", "1", str(dest)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-200:])


def fill_shots(story: dict, outdir: Path, history: list[dict] | None = None) -> int:
    """Reuse library assets for shots before anything is searched or drawn. Never raises; returns reuses."""
    if not CONFIG.get("asset_library", True):
        return 0
    try:
        return _fill(story, outdir)
    except Exception as e:  # noqa: BLE001
        log(f"Asset library skipped ({type(e).__name__}: {str(e)[:160]})")
        return 0


def _fill(story: dict, outdir: Path) -> int:
    import images
    idx = load_index()
    pool = [a for a in idx.get("assets", []) if not a.get("character_specific")]
    if not pool:
        log(f"Asset library: {len(idx.get('assets', []))} assets, none reusable yet")
        return 0
    outdir.mkdir(parents=True, exist_ok=True)
    seq, era, styles = idx.get("seq", 0), era_of(story), _allowed_styles(story)
    window, max_uses = int(CONFIG.get("asset_reuse_window", 10)), int(CONFIG.get("asset_max_uses", 4))
    thr = float(CONFIG.get("asset_min_similarity", 0.27))
    limit = int(CONFIG.get("asset_reuse_max_per_video", 6))
    n_scenes = len(story.get("scenes") or [])
    taken: set[str] = set()
    reused = 0
    for i, sc in enumerate(story.get("scenes") or []):
        for l in images._letters():
            text = (sc.get(PROMPT_KEYS[l]) or "").strip()
            png = outdir / f"scene_{i:02d}{l}.png"
            if not text or (i, l) == (0, "a") or png.exists() or reused >= limit:
                continue  # the hook stays a fresh picture; checkpoints / real media already placed stay
            if _shot_has_person(story, text):
                continue  # people / story characters: never a picture from another story
            inside, _words = _setting(story, i, l, text)
            pos = _position(i, n_scenes)
            cands = []
            for a in pool:
                if a["id"] in taken or a.get("style") not in styles or a.get("setting") != inside:
                    continue
                if not (a.get("era") == era or "any" in (a.get("era"), era)):
                    continue
                if a.get("times_used", 0) >= max_uses or seq - a.get("last_used_seq", -999) < window:
                    continue
                if pos in {u.get("position") for u in a.get("uses", [])}:
                    continue
                cands.append(a)
            if not cands:
                continue
            q = embed_text(text)
            scored = sorted(((float(q @ _unpack(a["embedding"])), a) for a in cands if a.get("embedding")),
                            key=lambda x: -x[0])
            for sim, a in scored[:3]:
                if sim < thr:
                    break
                if _try_reuse(story, i, l, text, a, sim, outdir, png, pos):
                    taken.add(a["id"])
                    reused += 1
                    break
    _STATE["reused"] = reused
    if reused:
        log(f"Asset library: {reused} shot(s) reused ({len(pool)} reusable assets)")
    return reused


def _try_reuse(story, i, l, text, a, sim, outdir, png, pos) -> bool:
    import images
    video = a.get("kind") == "video"
    raw = LOCAL / a["file"]
    if not raw.exists() and not _store().get(a["file"], raw):
        return False
    used = a.get("uses", [])
    crop = next((c for c in CROPS if c not in {u.get("crop") for u in used}), CROPS[len(used) % len(CROPS)])
    grade = next((g for g in GRADES if g not in {u.get("grade") for u in used}), list(GRADES)[len(used) % len(GRADES)])
    try:
        if video:
            _variant(raw, png.with_suffix(".mp4"), crop, grade, True)
            _variant(png.with_suffix(".mp4"), png, crop="center", grade="base", video=False)  # poster frame
        else:
            _variant(raw, png, crop, grade, False)
    except Exception as e:  # noqa: BLE001
        log(f"Reuse of {a['id']} failed ({str(e)[:100]})")
        return False
    subject, place = images.shot_request(story, i, text, l)
    request = subject + (f", location: {place}" if place else "")
    verdict, why = images.check_image(png, request, kind="ai" if a.get("style") == "painted" else "real")
    if verdict is False:
        log(f"Shot {i:02d}{l}: library asset {a['id']} failed QA ({why}); not reused")
        for p in (png, png.with_suffix(".mp4")):
            p.unlink(missing_ok=True)
        return False
    side = {"asset": a["id"], "use": a.get("times_used", 0) + 1, "crop": crop, "grade": grade, "position": pos,
            "similarity": round(sim, 3), "avoid_moves": [u.get("move") for u in used if u.get("move")]}
    png.with_suffix(".reuse.json").write_text(json.dumps(side))
    if a.get("style") != "painted":  # real media keeps its credit line (story["media_assets"] / description)
        meta = {"scene": i, "shot": l, "type": "stock_video" if video else "real_photo", "kind": "video" if video
                else "photo", "source": a.get("source"), "id": a.get("source_id") or a["id"], "url": a.get("url", ""),
                "author": a.get("author", ""), "license": a.get("license", ""), "license_url": a.get("license_url", ""),
                "date": a.get("date", ""), "title": a.get("title", ""), "query": "library", "qa": "PASS",
                "library_asset": a["id"]}
        png.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False))
        story.setdefault("media_assets", []).append(meta)
    log(f"Reused asset {a['id']} (use {side['use']}) for shot {i:02d}{l}: similarity {sim:.2f}, crop {crop}, "
        f"grade {grade}, qa={'PASS' if verdict else 'SKIPPED'}")
    return True


# ---------- adding a finished video's pictures ----------

def record_video(story: dict, outdir: Path) -> None:
    """After a video entered the buffer: new QA-passed pictures go into the library, reused ones get their use
    recorded (crop / grade / camera move / position). Never raises."""
    if not CONFIG.get("asset_library", True):
        return
    try:
        _record(story, outdir)
    except Exception as e:  # noqa: BLE001
        log(f"Asset library not updated ({type(e).__name__}: {str(e)[:160]})")


def _record(story: dict, outdir: Path) -> None:
    import images
    idx = load_index()
    if _STATE["readonly"]:
        return
    idx["seq"] = seq = idx.get("seq", 0) + 1
    by_id = {a["id"]: a for a in idx.setdefault("assets", [])}
    qa = story.get("_shot_qa") or {}
    n_scenes = len(story.get("scenes") or [])
    era, sid = era_of(story), story.get("story_id", "")
    added = updated = 0
    for i, sc in enumerate(story.get("scenes") or []):
        for l in images._letters():
            text = (sc.get(PROMPT_KEYS[l]) or "").strip()
            png = outdir / f"scene_{i:02d}{l}.png"
            if not text or not png.exists() or png.with_suffix(".origin").exists():
                continue  # virtual crops are not new pictures
            reuse = png.with_suffix(".reuse.json")
            if reuse.exists():
                r = json.loads(reuse.read_text())
                a = by_id.get(r["asset"])
                if a:
                    a["times_used"] = a.get("times_used", 0) + 1
                    a["last_used_video"], a["last_used_seq"] = sid, seq
                    a.setdefault("uses", []).append({"story": sid, "seq": seq, "position": r.get("position"),
                                                     "crop": r.get("crop"), "grade": r.get("grade"),
                                                     "move": r.get("move")})
                    updated += 1
                continue
            side = png.with_suffix(".json")
            meta = json.loads(side.read_text()) if side.exists() else {}
            passed = (meta.get("qa") == "PASS") if meta else (qa.get(f"{i:02d}{l}") == "PASS")
            if not passed:
                continue  # only pictures that clearly passed QA (SKIPPED / checkpoint / unknown are left out)
            video = png.with_suffix(".mp4").exists()
            src = png.with_suffix(".mp4") if video else png
            aid = hashlib.sha1(src.read_bytes()).hexdigest()[:16]
            if aid in by_id:
                continue
            inside, words = _setting(story, i, l, text)
            source = meta.get("source") or (story.get("_shot_provider") or {}).get(f"{i:02d}{l}", "ai")
            char = _shot_has_person(story, text) or any(n in text.lower() for n in _story_names(story))
            jpg = LOCAL / f"{aid}.jpg"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(png), "-q:v", "3", str(jpg)], check=True)
            files = [(f"{aid}.jpg", jpg)]
            if video:
                shutil.copy(src, LOCAL / f"{aid}.mp4")
                files.append((f"{aid}.mp4", LOCAL / f"{aid}.mp4"))
            for name, f in files:
                _store().put(name, f)
            import images as im
            entry = {
                "id": aid, "file": f"{aid}.mp4" if video else f"{aid}.jpg", "poster": f"{aid}.jpg",
                "kind": "video" if video else "image", "source": source, "source_id": meta.get("id", ""),
                "license": meta.get("license") or ("AI-generated (Night Files)" if not meta else ""),
                "license_url": meta.get("license_url", ""), "author": meta.get("author", ""),
                "attribution": meta.get("attribution") or (f"{meta.get('title', '')} by {meta.get('author', '')}"
                                                           .strip(" by") if meta else ""),
                "url": meta.get("url", ""), "title": meta.get("title", ""), "date": meta.get("date", ""),
                "description": text, "tags": im._content_words(text)[:12],
                "style": _style_of(source, meta.get("archive_kind", "photo")) if meta else "painted",
                "setting": inside, "setting_words": words,
                "era": "any" if _NATURE.search(text) and not re.search(r"\b(house|room|car|street|city)\b", text, re.I)
                else era,
                "subjects": [n for n in _story_names(story) if n in text.lower()],
                "character_specific": bool(char), "story_id": sid, "mode": story.get("mode"),
                "embedding": _pack(embed_image(png)), "times_used": 1, "last_used_video": sid,
                "last_used_seq": seq, "created": time.strftime("%Y-%m-%d"),
                "uses": [{"story": sid, "seq": seq, "position": _position(i, n_scenes), "crop": "original",
                          "grade": "original", "move": _move_of(png)}],
            }
            idx["assets"].append(entry)
            by_id[aid] = entry
            added += 1
    _prune(idx)
    save_index()
    log(f"Asset library: +{added} new, {updated} reuse(s) recorded, {len(idx['assets'])} assets total (video {seq})")


def _move_of(png: Path) -> str | None:
    """The camera move render.py gave this picture (render writes scene_XXl.move)."""
    f = png.with_suffix(".move")
    return f.read_text().strip() or None if f.exists() else None


def _prune(idx: dict) -> None:
    """Keep the library under asset_library_max: drop used-up assets first, then the least recently used."""
    cap = int(CONFIG.get("asset_library_max", 800))
    assets = idx["assets"]
    if len(assets) <= cap:
        return
    max_uses = int(CONFIG.get("asset_max_uses", 4))
    assets.sort(key=lambda a: (a.get("times_used", 0) < max_uses, a.get("last_used_seq", 0)))
    for a in assets[:len(assets) - cap]:
        for name in {a["file"], a.get("poster")}:
            if name:
                try:
                    _store().delete(name)
                except Exception:  # noqa: BLE001
                    pass
    idx["assets"] = assets[len(assets) - cap:]


def summary(outdir: Path) -> dict:
    """{"reused", "archive_stock", "ai"} for the shots of a finished video (log + history)."""
    out = {"reused": 0, "archive_stock": 0, "ai": 0}
    for png in sorted(outdir.glob("scene_*.png")):
        if re.search(r"\.(rejected\d*|qa\d*)$", png.stem) or not re.fullmatch(r"scene_\d{2}[a-d]", png.stem):
            continue
        if png.with_suffix(".reuse.json").exists():
            out["reused"] += 1
        elif png.with_suffix(".json").exists():
            out["archive_stock"] += 1
        else:
            out["ai"] += 1
    return out
