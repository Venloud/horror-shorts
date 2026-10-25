"""Recover ONE older verified Night Files video for Buffer.com without Google's API.

Priority: unexpired original GitHub Actions artifact, then one public post
from the OWNER'S authorized TikTok account. The TikTok route follows the
source's Social Backfill discovery / yt-dlp / ffprobe pattern. Strict caption
matching prevents importing unrelated content or draft-only posts.
"""
import io
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

import requests

from auto_buffer_backfill import BACKFILL, GH_API, REPO, gh, release_assets

FIELDS = "id,create_time,title,video_description,share_url"
TT_LIST = "https://open.tiktokapis.com/v2/video/list/"


def norm(value):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(value or "").lower())).strip()


def allowed(record, queued):
    return (record.get("stamp") not in queued
            and record.get("tiktok_published") is True
            and record.get("status") != "skipped"
            and not record.get("remade")
            and not record.get("youtube_excluded")
            and not (record.get("youtube") or {}).get("id")
            and "mrbeast" not in norm(record.get("title")))


def legacy_candidates(queued):
    if not BACKFILL.exists():
        return []
    return sorted(
        (v for v in json.loads(BACKFILL.read_text()).get("videos", [])
         if allowed(v, queued)),
        key=lambda v: v["stamp"],
    )


def probe(mp4):
    """Reject corrupt/nonvideo media. Only original validated media reaches the release."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(mp4)],
        capture_output=True, text=True, timeout=90,
    )
    if proc.returncode:
        raise RuntimeError("Recovered MP4 fails ffprobe")
    info = json.loads(proc.stdout)
    streams = info.get("streams") or []
    if not any(s.get("codec_type") == "video" and int(s.get("width") or 0) > 0
               and int(s.get("height") or 0) > 0 for s in streams):
        raise RuntimeError("Recovered file has no usable video track")
    if float(info.get("format", {}).get("duration") or 0) <= 0:
        raise RuntimeError("Recovered file has no duration")


def metadata(record):
    return {"title": record.get("title") or "", "yt_title": record.get("yt_title") or record.get("title") or "",
            "yt_description": record.get("caption") or "",
            "caption_text": record.get("caption") or "",
            "source": "original Night Files TikTok publication (recovered)",
            "origin_stamp": record["stamp"]}


def upload_pair(stamp, mp4, meta):
    """Idempotent pair admission: JSON first, MP4 last. No delete or overwrite."""
    release = gh("/releases/tags/youtube-pending")
    have = {a["name"] for a in release.get("assets", [])}
    base = release["upload_url"].split("{")[0]
    token = os.environ["GITHUB_TOKEN"]
    headers = {"Authorization": "Bearer " + token}
    for name, file, mime in ((stamp + ".json", meta, "application/json"),
                             (stamp + ".mp4", mp4, "video/mp4")):
        if name in have:
            continue
        with open(file, "rb") as f:
            result = requests.post(base, params={"name": name},
                                   headers={**headers, "Content-Type": mime},
                                   data=f, timeout=600)
        result.raise_for_status()
    current = release_assets("youtube-pending")
    if stamp + ".mp4" not in current or stamp + ".json" not in current:
        raise RuntimeError("Recovered release assets not both visible yet")


def from_artifact(item):
    ident = item.get("artifact_id")
    if not ident:
        return False
    response = requests.get(
        GH_API + "/repos/" + REPO + "/actions/artifacts/" + str(ident) + "/zip",
        headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"]},
        timeout=240,
    )
    if response.status_code in (404, 410):
        print("Historical artifact expired:", item["stamp"])
        return False
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        # Never extract arbitrary archive paths. Read only the two intended basenames.
        media_names = [n for n in archive.namelist() if n.split("/")[-1] == "final.mp4"]
        json_names = [n for n in archive.namelist() if n.split("/")[-1] == "caption.json"]
        if not media_names:
            return False
        with tempfile.TemporaryDirectory() as temp:
            mp4 = Path(temp) / "final.mp4"
            mp4.write_bytes(archive.read(media_names[0]))
            probe(mp4)
            saved = metadata(item)
            if json_names:
                original = json.loads(archive.read(json_names[0]))
                saved.update(original)
            meta = Path(temp) / "caption.json"
            meta.write_text(json.dumps(saved, ensure_ascii=False) + "\n")
            upload_pair(item["stamp"], mp4, meta)
    print("Recovered", item["stamp"], "from original Actions artifact", ident)
    return True


def owned_public_posts():
    """Refresh the existing Night Files TikTok token, then query authorized video.list.

    The regular TikTok helper writes a rotated refresh token to .new_refresh_token.
    The caller's Action MUST securely persist it even if video recovery fails.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
    import tiktok
    token = tiktok.get_access_token()
    cursor, seen, results = None, set(), []
    for _ in range(100):
        body = {"max_count": 20}
        if cursor is not None:
            body["cursor"] = cursor
        response = requests.post(
            TT_LIST + "?fields=" + FIELDS,
            headers={"Authorization": "Bearer " + token}, json=body, timeout=30,
        )
        response.raise_for_status()
        reply = response.json()
        if (reply.get("error") or {}).get("code") not in ("ok", "OK", None):
            raise RuntimeError("TikTok video.list unavailable, confirm video.list permission")
        page = reply.get("data") or {}
        results.extend(page.get("videos") or [])
        if not page.get("has_more"):
            break
        nxt = page.get("cursor")
        if nxt is None or nxt == cursor or nxt in seen:
            raise RuntimeError("TikTok discovery cursor repeated")
        seen.add(nxt)
        cursor = nxt
    return sorted(results, key=lambda x: int(x.get("create_time") or 0))


def matches(post, record):
    """Require exact distinctive caption evidence, never fuzzy similarity alone."""
    description = norm(post.get("video_description") or post.get("title"))
    caption = norm(record.get("caption"))
    return len(caption) >= 28 and (caption in description or description in caption and len(description) >= 28)


def from_tiktok(items):
    if not all(os.environ.get(k) for k in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN")):
        print("No TikTok discovery credentials; original artifacts only")
        return False
    try:
        posts = owned_public_posts()
    except Exception as exc:
        print("TikTok discovery unavailable:", type(exc).__name__, str(exc)[:130])
        return False
    for item in items:
        found = [post for post in posts if matches(post, item)]
        if len(found) != 1:
            continue
        post = found[0]
        video_id = str(post.get("id") or "")
        url = str(post.get("share_url") or "").split("?", 1)[0]
        if not re.fullmatch(r"\d{10,25}", video_id):
            continue
        if "tiktok.com/" not in url.lower() or video_id not in url:
            continue
        try:
            import yt_dlp
            with tempfile.TemporaryDirectory() as tmp:
                with yt_dlp.YoutubeDL({
                    "outtmpl": str(Path(tmp) / (video_id + ".%(ext)s")),
                    "format": "b[ext=mp4][acodec!=none]/bv*+ba/b",
                    "merge_output_format": "mp4",
                    "noplaylist": True, "playlist_items": "1",
                    "quiet": True, "no_warnings": True,
                    "retries": 2, "socket_timeout": 30, "cachedir": False,
                }) as dl:
                    info = dl.extract_info(url, download=True)
                if str((info or {}).get("id") or video_id) != video_id:
                    raise RuntimeError("TikTok video ID changed during download")
                matches_mp4 = list(Path(tmp).glob(video_id + "*.mp4"))
                if not matches_mp4:
                    raise RuntimeError("TikTok extractor returned no MP4")
                mp4 = matches_mp4[0]
                probe(mp4)
                meta = Path(tmp) / "caption.json"
                saved = metadata(item)
                saved["source_tiktok_video_id"] = video_id
                meta.write_text(json.dumps(saved, ensure_ascii=False) + "\n")
                upload_pair(item["stamp"], mp4, meta)
            print("Recovered", item["stamp"], "from verified owned public TikTok", video_id)
            return True
        except Exception as exc:
            print("Public TikTok recovery failed:", item["stamp"],
                  type(exc).__name__, str(exc)[:150])
    return False


def recover_one(queued):
    items = legacy_candidates(queued)
    if not items:
        return False
    archive = release_assets("youtube-pending")
    # Do not retry files already archived, even if the caller has a stale receipt.
    eligible = [v for v in items if v["stamp"] + ".mp4" not in archive]
    for item in eligible:
        try:
            if from_artifact(item):
                return True
        except Exception as exc:
            print("Artifact recovery failed:", item["stamp"], type(exc).__name__, str(exc)[:120])
    return from_tiktok(eligible)
