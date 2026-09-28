"""YouTube Shorts upload (YouTube Data API v3, scope youtube.upload). Same final mp4 and caption as TikTok.

Secrets: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (get the token once with connect_youtube.py).
Note: videos uploaded by an UNVERIFIED Google Cloud project are forced to private until the project passes
YouTube's API audit, whatever privacyStatus we ask for. upload() logs the status YouTube actually returns.
"""
import re
from pathlib import Path

from common import CONFIG, env, log

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def configured() -> bool:
    return all(env(k, required=False) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))


def _clean(text: str) -> str:
    return text.replace("<", "").replace(">", "")  # YouTube rejects < and > in titles/descriptions


def make_title(title: str, limit: int = 100) -> str:
    """Story title + " #Shorts", max 100 chars, cut at a word boundary (never mid-emoji or mid-word)."""
    suffix = " #Shorts"
    title = _clean(title).strip()
    room = limit - len(suffix)
    if len(title) > room:
        cut = title[:room]
        title = (cut.rsplit(" ", 1)[0] if " " in cut else cut).rstrip(" ,.:;-")
    return title + suffix


def make_description(caption_text: str) -> str:
    desc = _clean(caption_text).strip()
    if "#shorts" not in desc.lower():
        desc += "\n#Shorts"
    return desc.encode("utf-8")[:4900].decode("utf-8", "ignore")  # limit is 5000 bytes


def make_tags(hashtags: list[str], caption_text: str = "") -> list[str]:
    tags = [t.lstrip("#") for t in hashtags] or re.findall(r"#(\w+)", caption_text)
    out, total = [], 0
    for t in dict.fromkeys(t for t in tags if t and t.lower() != "shorts"):
        if total + len(t) + 2 > 450:  # YouTube caps all tags together at 500 chars
            break
        out.append(t)
        total += len(t) + 2
    return out


def upload(mp4: Path, title: str, caption_text: str, hashtags: list[str] | None = None) -> dict:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(None, refresh_token=env("YT_REFRESH_TOKEN"), client_id=env("YT_CLIENT_ID"),
                        client_secret=env("YT_CLIENT_SECRET"), token_uri="https://oauth2.googleapis.com/token",
                        scopes=SCOPES)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    wanted = CONFIG.get("youtube_privacy", "public")
    body = {
        "snippet": {"title": make_title(title), "description": make_description(caption_text),
                    "tags": make_tags(hashtags or [], caption_text), "categoryId": "24"},
        "status": {"privacyStatus": wanted, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
    }
    media = MediaFileUpload(str(mp4), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            log(f"YouTube upload {int(status.progress() * 100)}%")
    vid = resp["id"]
    got = (resp.get("status") or {}).get("privacyStatus", "?")
    url = f"https://youtube.com/shorts/{vid}"
    log(f"YouTube: {url} (privacy: {got})")
    if got != wanted:
        log(f"YouTube set it to '{got}', not '{wanted}': an unverified API project's uploads stay private until "
            "the project passes YouTube's API audit. Make it public by hand in YouTube Studio meanwhile.")
    return {"id": vid, "url": url, "privacy": got, "wanted": wanted}
