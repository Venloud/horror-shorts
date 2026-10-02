"""Publish the newest successfully rendered production video immediately after daily generation.

The daily workflow runs main.py first, then calls this module in the same job. The GitHub Release
buffer is only durable storage and duplicate protection. There is no separate build workflow,
missed-slot builder, or make-up build path here.
"""

import json
import sys
import traceback
from datetime import datetime, timezone

from common import CONFIG, ROOT, load_history, log, save_history


COUNTER = ROOT / "data" / "counter.json"


def take_video_number() -> int:
    """Allocate the next channel post number only after at least one platform succeeds."""
    try:
        n = int(json.loads(COUNTER.read_text())["next_video"])
    except Exception:  # noqa: BLE001
        n = 1 + sum(1 for h in load_history() if h.get("video_number"))
        log(f"counter.json missing or unreadable: continuing from #{n}")
    COUNTER.parent.mkdir(parents=True, exist_ok=True)
    COUNTER.write_text(json.dumps({"next_video": n + 1}) + "\n")
    return n


def _gh_output(key: str, value) -> None:
    """Pass values to later GitHub Actions steps."""
    import os

    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def _posted_entry(history: list[dict], stamp: str, story_id: str | None = None) -> dict | None:
    """Return the history entry if this buffered video/story was already posted."""
    for h in reversed(history):
        same = (
            h.get("buffered") == stamp
            or h.get("date") == stamp
            or (story_id and h.get("story_id") == story_id)
        )
        if same and h.get("posted"):
            return h
    return None


def _drop_posted(buffer, video: dict, h: dict) -> None:
    """Remove a video that is already posted, never post it again."""
    log(
        f"'{h.get('title')}' ({video['stamp']}) was already posted as "
        f"#{h.get('video_number')} at {h.get('posted')}: not posting again"
    )
    try:
        buffer.remove(video)
        if h.pop("removal_pending", None):
            log("Buffer removal pending flag cleared")
    except Exception as e:  # noqa: BLE001
        h["removal_pending"] = True
        log(f"Buffer removal failed again ({e}); still marked removal pending")


def main() -> int:
    import buffer
    import tiktok
    import youtube
    from notify import notify, notify_text

    # Keep the existing safety purge policy. This is not a manual buffer clear.
    buffer.purge_old()

    try:
        waiting = buffer.videos()
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        notify_text(
            "Night Files: publish FAILED",
            f"Could not read the video buffer: {e}",
            warn=True,
        )
        return 1

    # Duplicate guard: posted videos are removed, never reposted.
    history = load_history()
    fresh = []
    for video in waiting:
        h = _posted_entry(history, video["stamp"])
        if h:
            _drop_posted(buffer, video, h)
        else:
            fresh.append(video)

    if len(fresh) != len(waiting):
        save_history(history)
        waiting = fresh

    if not waiting:
        notify_text(
            "Night Files: publish FAILED",
            "The generation step completed without a video available in the buffer. "
            "Nothing was posted and nothing was deleted.",
            warn=True,
        )
        log("Buffer is empty after generation; publish stops safely")
        return 1

    # main.py puts the newly rendered video in the buffer before this function runs.
    # Sort defensively so the oldest waiting production video is posted first.
    video = waiting[0]
    out = ROOT / "output" / "publish"
    out.mkdir(parents=True, exist_ok=True)

    try:
        mp4 = buffer.download(video["mp4"], out / "final.mp4")
        meta = json.loads(
            buffer.download(video["json"], out / "caption.json").read_text()
        )
        (out / "caption.txt").write_text(
            meta["caption_text"] + "\n\nPIN: " + meta.get("pinned_comment", "")
        )

        h = _posted_entry(history, video["stamp"], meta.get("story_id"))
        if h:
            _drop_posted(buffer, video, h)
            save_history(history)
            return 0

        log(
            f"Posting '{meta['title']}' "
            f"({video['stamp']}, {meta.get('mode')})"
        )
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        notify_text(
            "Night Files: publish FAILED",
            f"Could not download '{video['stamp']}' from the buffer; "
            f"it stays there. {type(e).__name__}: {e}",
            warn=True,
        )
        return 1

    # TikTok and YouTube are independent. One failure never prevents the other.
    result, tt_error = None, None
    try:
        if CONFIG.get("tiktok_mode") == "direct":
            try:
                result = tiktok.post_direct(mp4, meta["caption_text"])
            except Exception as e:  # noqa: BLE001
                # Keep the existing safe fallback. Direct-post failure does not
                # throw away the video or prevent a YouTube upload.
                log(
                    f"Direct post failed ({str(e)[:300]}), "
                    "sending it to drafts instead"
                )
                result = tiktok.send_to_drafts(mp4)
                result["direct_error"] = str(e)[:300]
        else:
            result = tiktok.send_to_drafts(mp4)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        tt_error = f"{type(e).__name__}: {str(e)[:300]}"

    yt, yt_error = None, None
    if not CONFIG.get("youtube_enabled", True):
        log("YouTube: off (config youtube_enabled)")
    elif not youtube.configured():
        log(
            "YouTube: skipped "
            "(YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN secrets not set)"
        )
    else:
        try:
            yt = youtube.upload(
                mp4,
                meta.get("yt_title") or meta["title"],
                meta.get("yt_description") or meta["caption_text"],
                meta.get("hashtags"),
                credits=meta.get("visual_credits") or "",
                tags=meta.get("yt_tags"),
            )
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            yt_error = f"{type(e).__name__}: {str(e)[:300]}"

    if result is None and yt is None:
        notify_text(
            "Night Files: publish FAILED",
            f"'{video['stamp']}' stays in the buffer and will be tried on the next run.\n"
            f"TikTok: {tt_error or 'not posted'}\n"
            f"YouTube: {yt_error or 'not posted'}",
            warn=True,
        )
        return 1

    # At least one platform has the video. Remove it from the buffer so it
    # cannot be posted twice. If removal fails, history records that fact.
    removal_pending = False
    try:
        buffer.remove(video)
    except Exception as e:  # noqa: BLE001
        removal_pending = True
        log(
            f"Could not remove it from the buffer ({e}); "
            "recorded as posted with removal pending"
        )

    number = take_video_number()
    _gh_output("video_number", number)
    log(
        f"Video #{number}: '{meta['title']}' "
        f"(story {meta.get('story_id', '?')}, buffered {video['stamp']})"
    )

    history = load_history()
    for h in reversed(history):
        if (
            (meta.get("story_id") and h.get("story_id") == meta.get("story_id"))
            or h.get("buffered") == video["stamp"]
            or h.get("date") == video["stamp"]
        ):
            h["video_number"] = number
            h["tiktok"] = result if result else {"error": tt_error}
            h["youtube"] = yt if yt else ({"error": yt_error} if yt_error else None)
            h["posted"] = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
            if removal_pending:
                h["removal_pending"] = True
            if meta.get("yt_title"):
                h["yt_title"] = meta["yt_title"]
                h["hashtags"] = meta.get("hashtags")
                h["yt_tags"] = meta.get("yt_tags")
            break
    save_history(history)

    lines = []
    if yt:
        lines.append(
            f"YouTube: {yt['url']} ({yt['privacy']}"
            + (
                ", forced private: unverified API project, make it public in YouTube Studio"
                if yt["privacy"] != yt["wanted"]
                else ""
            )
            + ")"
        )
    elif yt_error:
        lines.append(f"YouTube FAILED: {yt_error}")

    if tt_error:
        lines.append(
            f"TikTok FAILED: {tt_error}. "
            "The video remains available in the GitHub Actions artifact."
        )

    notify(
        {
            "title": meta["title"],
            "caption_text": meta["caption_text"],
            "pinned_comment": meta.get("pinned_comment", ""),
        },
        result,
        note="\n".join(lines),
        video_number=number,
    )

    left = len(waiting) - 1
    log(f"Done: video #{number} posted. {left} video(s) left in the buffer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
