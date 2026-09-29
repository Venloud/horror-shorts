"""Video buffer: finished videos wait as assets on a GitHub Release named "buffer" until daily.yml posts them.

Each video is two assets with the same stamp: <stamp>.mp4 and <stamp>.json (caption, pinned comment, title...).
build.yml fills the buffer (up to config "buffer_size" videos); daily.yml takes the oldest one, sends it to
TikTok and deletes it. Needs GITHUB_TOKEN (contents: write) and GITHUB_REPOSITORY, both set inside Actions.
"""
import os
from pathlib import Path

import requests

from common import CONFIG, log

TAG = "buffer"
API = "https://api.github.com"


def _repo() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        raise RuntimeError("GITHUB_REPOSITORY not set (buffer only works inside GitHub Actions)")
    return repo


def _headers(extra: dict | None = None) -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    h.update(extra or {})
    return h


def _release(create: bool = False) -> dict | None:
    r = requests.get(f"{API}/repos/{_repo()}/releases/tags/{TAG}", headers=_headers(), timeout=30)
    if r.status_code == 200:
        return r.json()
    if r.status_code != 404:
        raise RuntimeError(f"GitHub release lookup: HTTP {r.status_code} {r.text[:200]}")
    if not create:
        return None
    r = requests.post(f"{API}/repos/{_repo()}/releases", headers=_headers(), timeout=30, json={
        "tag_name": TAG, "name": TAG, "prerelease": True,
        "body": "Night Files video buffer: finished videos waiting to be posted. Managed by the bot; don't edit."})
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub release create: HTTP {r.status_code} {r.text[:200]}")
    return r.json()


def videos() -> list[dict]:
    """Waiting videos, oldest first: [{"stamp", "mp4": asset, "json": asset}, ...] (only complete pairs)."""
    rel = _release()
    if not rel:
        return []
    by_stamp: dict[str, dict] = {}
    for a in rel.get("assets", []):
        stem, _, ext = a["name"].rpartition(".")
        if ext in ("mp4", "json"):
            by_stamp.setdefault(stem, {"stamp": stem})[ext] = a
    return [v for _, v in sorted(by_stamp.items()) if "mp4" in v and "json" in v]


def count() -> int:
    return len(videos())


def add(stamp: str, mp4: Path, meta: Path) -> None:
    """Upload a finished video + its caption file (json first, so a half upload is never a complete pair)."""
    rel = _release(create=True)
    base = rel["upload_url"].split("{")[0]
    for path, ctype in ((meta, "application/json"), (mp4, "video/mp4")):
        with open(path, "rb") as f:
            r = requests.post(f"{base}?name={stamp}.{path.suffix.lstrip('.')}", data=f, timeout=600,
                              headers=_headers({"Content-Type": ctype}))
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Buffer upload of {path.name}: HTTP {r.status_code} {r.text[:200]}")
    log(f"Added {stamp} to the buffer")


def download(asset: dict, dest: Path) -> Path:
    r = requests.get(asset["url"], headers=_headers({"Accept": "application/octet-stream"}), timeout=600,
                     stream=True)
    if r.status_code != 200:
        raise RuntimeError(f"Buffer download of {asset['name']}: HTTP {r.status_code}")
    with open(dest, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    return dest


def remove(video: dict) -> None:
    for key in ("mp4", "json"):
        r = requests.delete(f"{API}/repos/{_repo()}/releases/assets/{video[key]['id']}", headers=_headers(),
                            timeout=30)
        if r.status_code not in (204, 404):
            raise RuntimeError(f"Buffer delete of {video[key]['name']}: HTTP {r.status_code}")
    log(f"Removed {video['stamp']} from the buffer")


def purge_old() -> list[str]:
    """Delete every buffered video built before config "buffer_purge_before" (ISO time; videos made with the old,
    broken images). Flag "buffer_purge" (on by default). Returns the removed stamps; never raises."""
    cutoff = CONFIG.get("buffer_purge_before") if CONFIG.get("buffer_purge", True) else None
    if not cutoff:
        return []
    removed = []
    try:
        for v in videos():
            built = v["mp4"].get("created_at") or ""
            if built and built < cutoff:  # both are ISO-8601 UTC ("...Z"), so text order = time order
                remove(v)
                log(f"Buffer cleanup: deleted {v['stamp']} (mp4 + json, built {built}, before {cutoff})")
                removed.append(v["stamp"])
    except Exception as e:  # noqa: BLE001
        log(f"Buffer cleanup skipped ({e})")
        return removed
    if not removed:
        log(f"Buffer cleanup: nothing built before {cutoff}")
    return removed


if __name__ == "__main__":  # buffer_cleanup.yml
    purge_old()
