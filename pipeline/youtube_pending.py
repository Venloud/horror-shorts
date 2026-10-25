"""Durable MP4 staging for Buffer.com YouTube delivery (no Google upload API).
The Daily publisher archives every accepted Night Files video here:

  data/youtube_pending.json  {"videos": [{stamp, story_id, title, video_number, posted, status, file, ...}],
                              "last_alert": "YYYY-MM-DD", "uploads": {"YYYY-MM-DD": n}}
  release "youtube-pending"  <stamp>.mp4 + <stamp>.json (caption.json: yt_title / yt_description / yt_tags ...)

The GitHub Release MP4 remains reachable after the TikTok video buffer item is removed;
Buffer.com queues the public release asset independently. Historical statuses remain intact.
The direct API uploader is permanently disabled.
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


# ---------- recording (publish.py, Buffer.com delivery) ----------

def _alert(d: dict) -> None:
    """Buffer.com delivery is automatic; no daily Google-OAuth pause alarms."""
    return


def record(stamp: str, mp4: Path, meta: Path, video_number: int | None) -> None:
    """Store accepted video for Buffer.com; never call Google. Never raises."""
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
        log(f"YouTube Buffer staging: #{video_number} '{entry['title']}' archived in {TAG}")
    except Exception as e:  # noqa: BLE001
        entry["file_error"] = str(e)[:200]
        log(f"YouTube Buffer staging failed for {stamp} ({e}); kept queue record")
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


# ---------- retired Google YouTube uploader ----------

def upload_some(per_run: int = 3) -> None:
    """Retired: direct YouTube API uploading is no longer a supported route.

    Legacy callers cannot silently re-enable Google uploads by switching config.
    The Daily workflow and the 15-minute Buffer worker handle YouTube delivery.
    """
    raise RuntimeError("Direct YouTube uploads retired; use Buffer.com queue")


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
