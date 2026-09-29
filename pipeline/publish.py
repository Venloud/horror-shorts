"""Publisher (daily.yml at 11:40 AM / 8:40 PM New York): post the oldest buffered video. No generation here.

Download the oldest <stamp>.mp4 + <stamp>.json from the "buffer" release -> TikTok (drafts or direct) and YouTube
Shorts, independently -> delete it from the buffer if at least one worked -> record both results in history.json
-> phone alert with the YouTube link (+ warning when the buffer is low). Takes about a minute or two.

Empty buffer: no failure. It writes data/missed_slot.json, alerts "building now", and daily.yml starts build.yml
right away (ROOT/.trigger_build tells it to). When that build (or any build within 6 h) puts a video in the buffer,
main.py calls post_missed_slot(), which posts it at once and deletes missed_slot.json.
"""
import json
import sys
import traceback
from datetime import datetime, timezone

from common import CONFIG, ROOT, load_history, log, save_history

MISSED = ROOT / "data" / "missed_slot.json"
MISSED_MAX_AGE_H = 6
COUNTER = ROOT / "data" / "counter.json"  # the channel's own post numbers (#26, #27...), not GitHub run numbers


def take_video_number() -> int:
    """Next post number, only called once a video really went out (test / failed / empty runs never use one).
    push_state.sh commits the file with history.json (it keeps the higher number if main moved on)."""
    try:
        n = int(json.loads(COUNTER.read_text())["next_video"])
    except Exception:  # noqa: BLE001
        n = 1 + sum(1 for h in load_history() if h.get("video_number"))
        log(f"counter.json missing or unreadable: continuing from #{n}")
    COUNTER.parent.mkdir(parents=True, exist_ok=True)
    COUNTER.write_text(json.dumps({"next_video": n + 1}) + "\n")
    return n


def _gh_output(key: str, value) -> None:
    """Hand a value to later workflow steps (e.g. the artifact name video-26)."""
    import os
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def _slot_label(now: datetime) -> str:
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo("America/New_York")).strftime("%a %b %d, %I:%M %p New York")
    except Exception:  # noqa: BLE001
        return now.strftime("%Y-%m-%d %H:%M UTC")


def post_missed_slot() -> None:
    """Called by the builder after a video entered the buffer: make up for a slot that found the buffer empty."""
    if not MISSED.exists():
        return
    try:
        info = json.loads(MISSED.read_text())
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(info["at"])).total_seconds() / 3600
    except Exception as e:  # noqa: BLE001
        log(f"missed_slot.json unreadable ({e}), deleting it")
        MISSED.unlink(missing_ok=True)
        return
    if age_h >= MISSED_MAX_AGE_H:
        log(f"Missed slot ({info.get('slot')}) is {age_h:.1f} h old: not posting now, the next slot posts normally")
        MISSED.unlink(missing_ok=True)
        return
    log(f"Making up the missed slot ({info.get('slot')}, {age_h:.1f} h ago): posting now")
    main(from_build=True)
    MISSED.unlink(missing_ok=True)


def main(from_build: bool = False) -> int:
    import buffer
    import tiktok
    import youtube
    from notify import notify, notify_text

    try:
        waiting = buffer.videos()
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        notify_text("Night Files: publish FAILED", f"Could not read the video buffer: {e}", warn=True)
        return 1
    if not waiting:
        if from_build:
            log("Buffer is empty, nothing to post")
            return 1
        now = datetime.now(timezone.utc)
        slot = _slot_label(now)
        MISSED.parent.mkdir(parents=True, exist_ok=True)
        MISSED.write_text(json.dumps({"slot": slot, "at": now.isoformat(timespec="seconds")}))
        (ROOT / ".trigger_build").write_text(slot)  # daily.yml starts build.yml right away
        log(f"Buffer empty at the {slot} slot: starting a build, it posts as soon as the video is ready")
        notify_text("Night Files: buffer empty",
                    "Buffer empty: building now, will post when ready (if it's ready within 6 hours).")
        return 0

    video = waiting[0]
    out = ROOT / "output" / "publish"
    out.mkdir(parents=True, exist_ok=True)
    try:
        mp4 = buffer.download(video["mp4"], out / "final.mp4")
        meta = json.loads(buffer.download(video["json"], out / "caption.json").read_text())
        (out / "caption.txt").write_text(meta["caption_text"] + "\n\nPIN: " + meta.get("pinned_comment", ""))
        log(f"Posting '{meta['title']}' ({video['stamp']}, {meta.get('mode')})")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        notify_text("Night Files: publish FAILED",
                    f"Could not download '{video['stamp']}' from the buffer; it stays there. {type(e).__name__}: {e}",
                    warn=True)
        return 1

    # TikTok and YouTube are independent: one failing never stops the other.
    result, tt_error = None, None
    try:
        if CONFIG.get("tiktok_mode") == "direct":
            try:
                result = tiktok.post_direct(mp4, meta["caption_text"])
            except Exception as e:  # noqa: BLE001
                log(f"Direct post failed ({str(e)[:300]}), sending it to drafts instead")
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
        log("YouTube: skipped (YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN secrets not set)")
    else:
        try:
            yt = youtube.upload(mp4, meta["title"], meta["caption_text"], meta.get("hashtags"))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            yt_error = f"{type(e).__name__}: {str(e)[:300]}"

    if result is None and yt is None:  # nothing went out anywhere: keep it for the next slot
        notify_text("Night Files: publish FAILED",
                    f"'{video['stamp']}' stays in the buffer and will be tried next slot.\n"
                    f"TikTok: {tt_error}\nYouTube: {yt_error or 'not set up'}", warn=True)
        return 1

    # At least one platform has it: take it out of the buffer so it's never posted twice.
    try:
        buffer.remove(video)
    except Exception as e:  # noqa: BLE001
        log(f"Could not remove it from the buffer ({e}); delete {video['stamp']} from the release by hand")
    number = take_video_number()
    _gh_output("video_number", number)
    log(f"Video #{number}: '{meta['title']}' (story {meta.get('story_id', '?')}, buffered {video['stamp']})")
    history = load_history()
    for h in reversed(history):
        if (meta.get("story_id") and h.get("story_id") == meta.get("story_id")) \
                or h.get("buffered") == video["stamp"] or h.get("date") == video["stamp"]:
            h["video_number"] = number
            h["tiktok"] = result if result else {"error": tt_error}
            h["youtube"] = yt if yt else ({"error": yt_error} if yt_error else None)
            h["posted"] = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
            break
    save_history(history)

    lines = []
    if yt:
        lines.append(f"YouTube: {yt['url']} ({yt['privacy']}"
                     + (", forced private: unverified API project, make it public in YouTube Studio" if
                        yt["privacy"] != yt["wanted"] else "") + ")")
    elif yt_error:
        lines.append(f"YouTube FAILED: {yt_error}")
    if tt_error:
        lines.append(f"TikTok FAILED: {tt_error}. Post it by hand from the download link below.")
    notify({"title": meta["title"], "caption_text": meta["caption_text"],
            "pinned_comment": meta.get("pinned_comment", "")}, result, note="\n".join(lines), video_number=number)
    left = len(waiting) - 1
    log(f"Done: video #{number} posted. {left} video(s) left in the buffer.")
    if left <= 1 and not from_build:  # after a make-up post the builder is refilling anyway
        notify_text(f"Night Files: buffer low ({left} left)",
                    "build.yml refills it every 3 hours. If it stays low, check the build runs.", warn=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
