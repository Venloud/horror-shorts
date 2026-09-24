"""TikTok Content Posting API: send the video to your drafts (inbox) or post it directly."""
import time
from pathlib import Path

import requests

from common import CONFIG, ROOT, env, log

API = "https://open.tiktokapis.com"
NEW_REFRESH_FILE = ROOT / ".new_refresh_token"


def get_access_token() -> str:
    """Trade the long-lived refresh token for a 24h access token."""
    r = requests.post(f"{API}/v2/oauth/token/", timeout=30,
                      headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={
                          "client_key": env("TIKTOK_CLIENT_KEY"),
                          "client_secret": env("TIKTOK_CLIENT_SECRET"),
                          "grant_type": "refresh_token",
                          "refresh_token": env("TIKTOK_REFRESH_TOKEN"),
                      })
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"TikTok token refresh failed: {data}")
    new_refresh = data.get("refresh_token")
    if new_refresh and new_refresh != env("TIKTOK_REFRESH_TOKEN"):
        NEW_REFRESH_FILE.write_text(new_refresh)  # workflow saves this back into the repo secret
        log("TikTok issued a new refresh token (will be saved)")
    return data["access_token"]


def _check(resp: requests.Response, what: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"{what}: HTTP {resp.status_code} {resp.text[:300]}")
    code = (data.get("error") or {}).get("code", "ok")
    if resp.status_code != 200 or code != "ok":
        raise RuntimeError(f"{what} failed: HTTP {resp.status_code} {data.get('error')}")
    return data.get("data") or {}


def _upload_file(upload_url: str, path: Path) -> None:
    size = path.stat().st_size
    with path.open("rb") as f:
        r = requests.put(upload_url, data=f, timeout=600, headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(size),
            "Content-Range": f"bytes 0-{size - 1}/{size}",
        })
    if r.status_code not in (200, 201, 206):
        raise RuntimeError(f"Video upload failed: HTTP {r.status_code} {r.text[:300]}")


def _source_info(path: Path) -> dict:
    size = path.stat().st_size
    if size > 64 * 1024 * 1024:
        raise RuntimeError("Video is over 64 MB; lower the CRF in render.py")
    return {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}


def _wait_status(token: str, publish_id: str, timeout: int = 300) -> str:
    deadline = time.time() + timeout
    status = "UNKNOWN"
    while time.time() < deadline:
        r = requests.post(f"{API}/v2/post/publish/status/fetch/", timeout=30,
                          headers={"Authorization": f"Bearer {token}",
                                   "Content-Type": "application/json; charset=UTF-8"},
                          json={"publish_id": publish_id})
        data = _check(r, "Status check")
        status = data.get("status", "UNKNOWN")
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            return status
        if status == "FAILED":
            raise RuntimeError(f"TikTok processing failed: {data.get('fail_reason')}")
        time.sleep(10)
    return status


def send_to_drafts(path: Path) -> dict:
    token = get_access_token()
    r = requests.post(f"{API}/v2/post/publish/inbox/video/init/", timeout=30,
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json; charset=UTF-8"},
                      json={"source_info": _source_info(path)})
    data = _check(r, "Draft upload init")
    _upload_file(data["upload_url"], path)
    status = _wait_status(token, data["publish_id"])
    log(f"TikTok draft: {status} ({data['publish_id']})")
    return {"publish_id": data["publish_id"], "status": status, "mode": "draft"}


def post_direct(path: Path, caption: str) -> dict:
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    info = _check(requests.post(f"{API}/v2/post/publish/creator_info/query/", headers=headers, timeout=30),
                  "Creator info")
    wanted = CONFIG.get("direct_privacy", "SELF_ONLY")
    options = info.get("privacy_level_options") or ["SELF_ONLY"]
    privacy = wanted if wanted in options else ("SELF_ONLY" if "SELF_ONLY" in options else options[0])
    body = {
        "post_info": {
            "title": caption[:2200],
            "privacy_level": privacy,
            "disable_comment": bool(info.get("comment_disabled", False)),
            "disable_duet": bool(info.get("duet_disabled", False)),
            "disable_stitch": bool(info.get("stitch_disabled", False)),
            "video_cover_timestamp_ms": 1500,
            "is_aigc": bool(CONFIG.get("tiktok_ai_label", True)),
        },
        "source_info": _source_info(path),
    }
    data = _check(requests.post(f"{API}/v2/post/publish/video/init/", headers=headers, json=body, timeout=30),
                  "Direct post init")
    _upload_file(data["upload_url"], path)
    status = _wait_status(token, data["publish_id"])
    log(f"TikTok direct post ({privacy}): {status}")
    return {"publish_id": data["publish_id"], "status": status, "mode": "direct", "privacy": privacy}
