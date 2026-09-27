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


def notify(story: dict, result: dict | None, error: str | None = None) -> None:
    if error:
        title = "Horror video FAILED"
        body = error[:1500]
    else:
        title = f"New TikTok {'draft' if result and result.get('mode') == 'draft' else 'post'}: {story['title']}"
        body = (
            f"CAPTION (copy this):\n{caption_text(story)}\n\n"
            f"PIN THIS COMMENT:\n{story.get('pinned_comment', '')}"
        )

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## {title}\n\n```\n{body}\n```\n")

    topic = env("NTFY_TOPIC", required=False)
    if not topic:
        return
    try:
        requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), timeout=20,
                      headers={"Title": title.encode("ascii", "ignore").decode(),
                               "Tags": "ghost" if not error else "warning"})
        log("Phone notification sent")
    except Exception as e:  # noqa: BLE001
        log(f"Notification failed (not fatal): {e}")
