"""Legacy YouTube metadata formatting helpers. Direct Google uploads disabled.

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
    if "#shorts" in title.lower():  # packaging.py titles already end with #shorts (and are <= 70 chars)
        return title[:limit]
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


def upload(*args, **kwargs) -> dict:
    """Retired, fail closed for any old workflow or manual caller.

    Night Files now sends YouTube Shorts exclusively through Buffer.com.
    This function no longer reads Google credentials or invokes videos.insert.
    """
    raise RuntimeError("Direct YouTube API uploads retired: use Buffer.com")
