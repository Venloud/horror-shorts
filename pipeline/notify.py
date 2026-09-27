"""Phone notification via ntfy.sh (free app) + GitHub run summary with the caption to copy."""
import os

import requests

from common import CONFIG, env, log


def caption_text(story: dict) -> str:
    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in story.get("hashtags", []))
    credit = CONFIG.get("music_credits", {}).get(story.get("music_file") or "", "")
    credit = f"\n{credit}" if credit else ""
    caption = story["caption"].strip()
    if story.get("true_story") and not caption.upper().startswith("TRUE STORY"):
        caption = f"TRUE STORY: {caption}"
    return f"{caption}{credit}\n\n{tags}".strip()


def run_url() -> str | None:
    """This GitHub Actions run's page (only set when running on GitHub)."""
    repo, run_id = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    if not (repo and run_id):
        return None
    return f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{run_id}"


def notify(story: dict, result: dict | None, error: str | None = None) -> None:
    url = run_url()
    download = f"{url}#artifacts" if url else None
    if error:
        title = "Horror video FAILED"
        body = error[:1500]
    else:
        title = f"New TikTok {'draft' if result and result.get('mode') == 'draft' else 'post'}: {story['title']}"
        body = (
            f"CAPTION (copy this):\n{caption_text(story)}\n\n"
            f"PIN THIS COMMENT:\n{story.get('pinned_comment', '')}"
        )
        if download:  # backup in case TikTok never delivers the draft (kept 7 days)
            body += (f"\n\nNOT IN TIKTOK? Download it (7 days): {download} "
                     f"-> video-{os.environ.get('GITHUB_RUN_NUMBER', '')} (final.mp4 + caption.txt)")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## {title}\n\n```\n{body}\n```\n")

    topic = env("NTFY_TOPIC", required=False)
    if not topic:
        return
    try:
        headers = {"Title": title.encode("ascii", "ignore").decode(),
                   "Tags": "ghost" if not error else "warning"}
        if url:  # tap the notification = open the run; button = straight to the video download
            headers["Click"] = download if not error else url
            headers["Actions"] = (f"view, Download video, {download}" if not error else f"view, Open run log, {url}")
        requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), timeout=20, headers=headers)
        log("Phone notification sent")
    except Exception as e:  # noqa: BLE001
        log(f"Notification failed (not fatal): {e}")
