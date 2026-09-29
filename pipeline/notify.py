"""Phone notification via ntfy.sh (free app) + GitHub run summary with the caption to copy."""
import os

import requests

from common import CONFIG, env, log


FICTION_MODES = ("fiction", "coldcase", "inbox-fiction")


def is_fiction(story: dict) -> bool:
    """Made-up story: fiction fallback, coldcase, inbox FICTION or a too-sensitive case retold as original fiction.
    Never a true story (TRUE STORY badge) and never lore (legends are told as legends)."""
    if story.get("true_story"):
        return False
    mode = str(story.get("mode") or "")
    return mode in FICTION_MODES or mode.endswith("fiction")


def caption_text(story: dict) -> str:
    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in story.get("hashtags", []))
    credit = CONFIG.get("music_credits", {}).get(story.get("music_file") or "", "")
    credit = f"\n{credit}" if credit else ""
    caption = story["caption"].strip()
    if story.get("true_story") and not caption.upper().startswith("TRUE STORY"):
        caption = f"TRUE STORY: {caption}"
    if is_fiction(story):  # anything made up (inbox FICTION, coldcase, fiction fallback): say so
        if "fiction" not in caption.lower():
            caption = f"{caption} (fictional story)"
        if "#fiction" not in tags.lower():
            tags = f"{tags} #fiction".strip()
    if story.get("media_assets"):  # real stock video / archive photos used: name the sources
        try:
            from media import credits
            credit += "\n" + credits(story["media_assets"])[0]
        except Exception as e:  # noqa: BLE001
            log(f"Visual credit line skipped ({e})")
    return f"{caption}{credit}\n\n{tags}".strip()


def run_url() -> str | None:
    """This GitHub Actions run's page (only set when running on GitHub)."""
    repo, run_id = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    if not (repo and run_id):
        return None
    return f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{run_id}"


def notify_text(title: str, body: str, warn: bool = False) -> None:
    """Plain phone alert (buffer low/empty, publish failed)."""
    _send(title, body, warn=warn, url=run_url())


def notify(story: dict, result: dict | None, error: str | None = None, prefix: str = "", note: str = "",
           video_number: int | None = None) -> None:
    """video_number: the channel's own post counter (data/counter.json), only for videos that actually went out."""
    url = run_url()
    download = f"{url}#artifacts" if url else None
    caption = story.get("caption_text") or (caption_text(story) if story.get("caption") else "")
    num = f"#{video_number} " if video_number else ""
    if error:
        title = f"{prefix}Horror video FAILED"
        body = error[:1500]
    else:
        kind = "draft" if result and result.get("mode") == "draft" else ("video" if not result else "post")
        title = f"{prefix}{num}New TikTok {kind}: {story['title']}"
        body = (
            (f"{note}\n\n" if note else "") +
            f"CAPTION (copy this):\n{caption}\n\n"
            f"PIN THIS COMMENT:\n{story.get('pinned_comment', '')}"
        )
        if download:  # backup in case TikTok never delivers the draft (kept 7 days)
            name = f"video-{video_number}" if video_number else "the artifact of this run"
            body += f"\n\nNOT IN TIKTOK? Download it (7 days): {download} -> {name} (final.mp4 + caption.txt)"

    _send(title, body, warn=bool(error), url=url, download=None if error else download)


def _send(title: str, body: str, warn: bool = False, url: str | None = None, download: str | None = None) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## {title}\n\n```\n{body}\n```\n")

    topic = env("NTFY_TOPIC", required=False)
    if not topic:
        return
    try:
        headers = {"Title": title.encode("ascii", "ignore").decode(), "Tags": "warning" if warn else "ghost"}
        if download:  # tap the notification or its button = straight to the video download
            headers["Click"] = download
            headers["Actions"] = f"view, Download video, {download}"
        elif url:
            headers["Click"] = url
            headers["Actions"] = f"view, Open run log, {url}"
        requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), timeout=20, headers=headers)
        log("Phone notification sent")
    except Exception as e:  # noqa: BLE001
        log(f"Notification failed (not fatal): {e}")
