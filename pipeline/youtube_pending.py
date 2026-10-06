"""YouTube paused (config youtube_paused; Oct 6: the Google account behind the YouTube project is restricted, appeal
pending). While paused, publish.py posts to TikTok only and every video that skipped YouTube is recorded here:

  data/youtube_pending.json  {"videos": [{stamp, story_id, title, video_number, posted, status, file, ...}],
                              "last_alert": "YYYY-MM-DD", "uploads": {"YYYY-MM-DD": n}}
  release "youtube-pending"  <stamp>.mp4 + <stamp>.json (caption.json: yt_title / yt_description / yt_tags ...)

The buffer deletes a posted video and build artifacts expire after 7 days, so the mp4 is kept in the release.
At most ONE ntfy alert per UTC day about the pause. Once the owner says YouTube is back (youtube_paused false),
upload_some() uploads the pending videos oldest first, max youtube_pending_per_day (6) per UTC day, and writes the
YouTube result into history.json. Nothing here raises into the publisher: a failure is logged and retried later.
"""
import json
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from common import CONFIG, ROOT, load_history, log, save_history

PATH = ROOT / "data" / "youtube_pending.json"
TAG = "youtube-pending"
API = "https://api.github.com"


def paused() -> bool:
    return bool(CONFIG.get("youtube_paused", False))


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load() -> dict:
    try:
        d = json.loads(PATH.read_text())
    except (OSError, ValueError):
        d = {}
    d.setdefault("videos", [])
    d.setdefault("uploads", {})
    return d


def save(d: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")


# ---------- the "youtube-pending" release ----------

def _repo() -> str:
    return os.environ["GITHUB_REPOSITORY"]


def _h(extra: dict | None = None) -> dict:
    h = {"Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN', '')}",
         "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    h.update(extra or {})
    return h


def _release(create: bool = False) -> dict | None:
    r = requests.get(f"{API}/repos/{_repo()}/releases/tags/{TAG}", headers=_h(), timeout=30)
    if r.status_code == 200:
        return r.json()
    if r.status_code != 404 or not create:
        return None
    r = requests.post(f"{API}/repos/{_repo()}/releases", headers=_h(), timeout=30, json={
        "tag_name": TAG, "name": TAG, "prerelease": True,
        "body": "Night Files: videos posted on TikTok while YouTube was paused, waiting for their YouTube upload."})
    r.raise_for_status()
    return r.json()


def _upload(rel: dict, name: str, path: Path, ctype: str) -> None:
    base = rel["upload_url"].split("{")[0]
    with open(path, "rb") as f:
        r = requests.post(f"{base}?name={name}", data=f, timeout=600, headers=_h({"Content-Type": ctype}))
    if r.status_code not in (200, 201):
        raise RuntimeError(f"{name}: HTTP {r.status_code} {r.text[:200]}")


def _assets() -> dict:
    rel = _release()
    return {a["name"]: a for a in (rel or {}).get("assets", [])}


def _store(stamp: str, mp4: Path, meta: Path) -> None:
    rel = _release(create=True)
    have = {a["name"] for a in rel.get("assets", [])}
    if f"{stamp}.json" not in have:
        _upload(rel, f"{stamp}.json", meta, "application/json")  # json first: a half upload has no mp4
    if f"{stamp}.mp4" not in have:
        _upload(rel, f"{stamp}.mp4", mp4, "video/mp4")


# ---------- recording (publish.py, while paused) ----------

def _alert(d: dict) -> None:
    """At most one ntfy per UTC day about the pause."""
    if d.get("last_alert") == _today():
        return
    waiting = [v for v in d["videos"] if v.get("status") == "pending"]
    try:
        from notify import notify_text
        notify_text("Night Files: YouTube paused",
                    f"{len(waiting)} video(s) wait for YouTube (Google account restricted, appeal pending): "
                    + ", ".join(f"#{v.get('video_number')} {v.get('title')}" for v in waiting[-8:])
                    + ". They post to TikTok as usual and upload to YouTube (max "
                    f"{CONFIG.get('youtube_pending_per_day', 6)}/day) once you say it's restored.")
        d["last_alert"] = _today()
    except Exception as e:  # noqa: BLE001
        log(f"YouTube pause alert not sent ({e})")


def record(stamp: str, mp4: Path, meta: Path, video_number: int | None) -> None:
    """A video went to TikTok while YouTube is paused: keep it for the later upload. Never raises."""
    d = load()
    if any(v["stamp"] == stamp for v in d["videos"]):
        return
    try:
        m = json.loads(Path(meta).read_text())
    except Exception:  # noqa: BLE001
        m = {}
    entry = {"stamp": stamp, "story_id": m.get("story_id"), "title": m.get("title"), "video_number": video_number,
             "posted": datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M"), "status": "pending", "file": False}
    try:
        _store(stamp, Path(mp4), Path(meta))
        entry["file"] = True
        log(f"YouTube paused: #{video_number} '{entry['title']}' kept in the {TAG} release for the later upload")
    except Exception as e:  # noqa: BLE001
        entry["file_error"] = str(e)[:200]
        log(f"YouTube paused: could not keep the mp4 of {stamp} ({e}); recorded anyway")
    d["videos"].append(entry)
    _alert(d)
    save(d)


def stash() -> None:
    """Entries whose mp4 is only in a 7-day build artifact (e.g. #38, posted before the pause existed): copy it
    into the release. Needs actions: read. Never raises."""
    d = load()
    todo = [v for v in d["videos"] if v.get("status") == "pending" and not v.get("file") and v.get("artifact_id")]
    if not todo:
        return
    for v in todo:
        try:
            r = requests.get(f"{API}/repos/{_repo()}/actions/artifacts/{v['artifact_id']}/zip", headers=_h(),
                             timeout=900, stream=True)
            if r.status_code in (404, 410):
                v["file_error"] = "artifact expired"
                continue
            r.raise_for_status()
            with tempfile.TemporaryDirectory() as tmp:
                z = Path(tmp) / "a.zip"
                with open(z, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                with zipfile.ZipFile(z) as zf:
                    zf.extractall(tmp)
                mp4 = next(Path(tmp).rglob("final.mp4"))
                meta = next(Path(tmp).rglob("caption.json"))
                _store(v["stamp"], mp4, meta)
            v["file"] = True
            v.pop("file_error", None)
            log(f"YouTube pending: stashed #{v.get('video_number')} '{v.get('title')}' from its build artifact")
        except Exception as e:  # noqa: BLE001
            v["file_error"] = str(e)[:200]
            log(f"YouTube pending: stash of {v['stamp']} failed ({e})")
    save(d)


# ---------- backfill (only when youtube_paused is false) ----------

def upload_some(per_run: int = 3) -> None:
    """Upload pending videos, oldest first: max youtube_pending_per_day per UTC day (and `per_run`). Never raises."""
    if paused():
        return
    d = load()
    waiting = [v for v in d["videos"] if v.get("status") == "pending" and v.get("file")]
    if not waiting:
        return
    import youtube
    if not youtube.configured():
        log("YouTube pending: YT_* secrets not set, nothing uploaded")
        return
    cap = int(CONFIG.get("youtube_pending_per_day", 6))
    done = int(d["uploads"].get(_today(), 0))
    assets = _assets()
    for v in waiting[:max(0, min(per_run, cap - done))]:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                mp4, meta = Path(tmp) / "v.mp4", Path(tmp) / "m.json"
                for name, dest in ((f"{v['stamp']}.mp4", mp4), (f"{v['stamp']}.json", meta)):
                    r = requests.get(assets[name]["url"], headers=_h({"Accept": "application/octet-stream"}),
                                     timeout=600, stream=True)
                    r.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                m = json.loads(meta.read_text())
                yt = youtube.upload(mp4, m.get("yt_title") or m["title"], m.get("yt_description") or m["caption_text"],
                                    m.get("hashtags"), credits=m.get("visual_credits") or "", tags=m.get("yt_tags"))
        except Exception as e:  # noqa: BLE001 (quota / auth / network: stays pending, next run tries again)
            v["last_error"] = f"{type(e).__name__}: {str(e)[:200]}"
            log(f"YouTube pending: #{v.get('video_number')} upload failed ({v['last_error']}); stays pending")
            break
        v.update(status="uploaded", youtube=yt, uploaded=datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M"))
        v.pop("last_error", None)
        d["uploads"][_today()] = d["uploads"].get(_today(), 0) + 1
        log(f"YouTube pending: #{v.get('video_number')} '{v.get('title')}' uploaded: {yt.get('url')}")
        hist = load_history()
        for h in reversed(hist):
            if h.get("buffered") == v["stamp"] or h.get("date") == v["stamp"] or (
                    v.get("story_id") and h.get("story_id") == v["story_id"] and h.get("video_number")):
                h["youtube"] = yt
                break
        save_history(hist)
        save(d)
        for name in (f"{v['stamp']}.mp4", f"{v['stamp']}.json"):  # uploaded: free the release space
            try:
                if name in assets:
                    requests.delete(f"{API}/repos/{_repo()}/releases/assets/{assets[name]['id']}", headers=_h(),
                                    timeout=30)
            except Exception as e:  # noqa: BLE001
                log(f"YouTube pending: could not delete {name} from the release ({e})")
    save(d)


def merge(base: dict, ours: dict, theirs: dict) -> dict:
    """push_state.sh: combine this run's file with origin/main's (entries by stamp; uploaded beats pending)."""
    rank = {"pending": 0, "uploaded": 1}
    out = {v["stamp"]: v for v in theirs.get("videos", [])}
    for v in ours.get("videos", []):
        cur = out.get(v["stamp"])
        if not cur or rank.get(v.get("status"), 0) > rank.get(cur.get("status"), 0) or (
                v.get("status") == cur.get("status") and v != (next((b for b in base.get("videos", [])
                                                                     if b["stamp"] == v["stamp"]), None))):
            out[v["stamp"]] = v
    uploads = dict(theirs.get("uploads", {}))
    for k, n in ours.get("uploads", {}).items():
        uploads[k] = max(n, uploads.get(k, 0))
    return {"videos": sorted(out.values(), key=lambda v: v["stamp"]), "uploads": uploads,
            "last_alert": max(ours.get("last_alert") or "", theirs.get("last_alert") or "") or None}


if __name__ == "__main__":  # push_state.sh: python youtube_pending.py merge BASE OURS THEIRS OUT
    import sys

    def _read(p: str) -> dict:
        try:
            return json.loads(Path(p).read_text())
        except (OSError, ValueError):
            return {}
    _, cmd, base, ours, theirs, out = sys.argv
    Path(out).write_text(json.dumps(merge(_read(base), _read(ours), _read(theirs)), indent=2, ensure_ascii=False) + "\n")
