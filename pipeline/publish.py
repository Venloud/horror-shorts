"""Publish the oldest buffered video (daily.yml, after it generated one if the buffer was empty).

Empty buffer at a slot (the daily run's own generation failed too): data/missed_slot.json is written and the run
fails loudly. When buffer_fill.yml (within 24 h) puts a video in the buffer, main.py calls post_missed_slot(): it
makes the slot up only if the buffer then holds 2+ videos (the next regular slot keeps one) and no post is within
3 h before or after (last post / next slot); else the file waits for a later build. Every post is written to
history.json; a post whose history entry is missing gets one rebuilt from caption.json (and an alert).
"""

import json
import sys
import traceback
from datetime import datetime, timezone

from common import CONFIG, ROOT, load_history, log, save_history


MISSED = ROOT / "data" / "missed_slot.json"
MISSED_MAX_AGE_H = float(CONFIG.get("missed_slot_max_hours", 24))
MIN_GAP_H = float(CONFIG.get("min_post_gap_hours", 3))  # never two posts within 3 hours
SLOTS_UTC = CONFIG.get("publish_slots_utc", ["15:40", "00:40"])
_SLOT_SLACK = __import__("datetime").timedelta(minutes=10)
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
    wait = makeup_blocker()
    if wait:
        log(f"Missed slot ({info.get('slot')}) not made up yet: {wait}; a later build tries again")
        return
    log(f"Making up the missed slot ({info.get('slot')}, {age_h:.1f} h ago): posting now")
    try:
        rc = main(from_build=True)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        log(f"Make-up post crashed ({type(e).__name__}: {e}); missed_slot.json kept, a later build retries")
        return
    if rc != 0:
        log(f"Make-up post did not go out (exit {rc}); missed_slot.json kept, a later build retries")
        return
    MISSED.unlink(missing_ok=True)


def _last_post() -> datetime | None:
    times = []
    for h in load_history():
        try:
            times.append(datetime.strptime(h["posted"], "%Y-%m-%d_%H%M").replace(tzinfo=timezone.utc))
        except (KeyError, TypeError, ValueError):
            pass
    return max(times, default=None)


def _next_slot(now: datetime) -> datetime:
    from datetime import timedelta
    cands = []
    for s in SLOTS_UTC:
        hh, mm = (int(x) for x in s.split(":"))
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        cands.append(t if t > now else t + timedelta(days=1))
    return min(cands)


def _last_slot(now: datetime) -> datetime:
    """The latest regular slot time at or before now."""
    from datetime import timedelta
    cands = []
    for s in SLOTS_UTC:
        hh, mm = (int(x) for x in s.split(":"))
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        cands.append(t if t <= now else t - timedelta(days=1))
    return max(cands)


def _late_slot_served(now: datetime | None = None) -> None:
    """A slot run that posts late (GitHub's cron or a manual run) serves the most recent regular slot: if that
    slot is the one recorded as missed, it's done now and must not be made up a second time."""
    if not MISSED.exists():
        return
    now = now or datetime.now(timezone.utc)
    try:
        at = datetime.fromisoformat(json.loads(MISSED.read_text())["at"])
    except Exception:  # noqa: BLE001
        return
    if at >= _last_slot(now) - _SLOT_SLACK:
        log("This post served the missed slot (a late slot run): no make-up needed")
        MISSED.unlink(missing_ok=True)


def makeup_blocker(now: datetime | None = None, waiting: int | None = None) -> str:
    """Why a missed slot can't be made up right now ("" = it can): the buffer must hold 2+ videos so the next
    regular slot still has one, and no post may be within MIN_GAP_H hours before or after."""
    import buffer
    now = now or datetime.now(timezone.utc)
    waiting = buffer.count() if waiting is None else waiting
    if waiting < 2:
        return f"the buffer has {waiting} video(s), a make-up needs 2+ so the next slot keeps one"
    last = _last_post()
    if last and (now - last).total_seconds() < MIN_GAP_H * 3600:
        return f"the last post was {(now - last).total_seconds() / 3600:.1f} h ago (min {MIN_GAP_H:g} h)"
    nxt = _next_slot(now)
    if (nxt - now).total_seconds() < MIN_GAP_H * 3600:
        return f"the next slot is in {(nxt - now).total_seconds() / 3600:.1f} h (min {MIN_GAP_H:g} h)"
    return ""


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


def main(from_build: bool = False) -> int:
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
        if from_build:
            log("Buffer is empty, nothing to post")
            return 1
        now = datetime.now(timezone.utc)
        slot = _slot_label(now)
        MISSED.parent.mkdir(parents=True, exist_ok=True)
        MISSED.write_text(json.dumps({"slot": slot, "at": now.isoformat(timespec="seconds")}))
        notify_text(
            "Night Files: publish FAILED (slot missed)",
            f"The buffer is empty at the {slot} slot and this run's own build made no video. The slot is "
            "made up when buffer_fill.yml buffers a video (buffer 2+, never within 3 h of another post).",
            warn=True,
        )
        log(f"Buffer is empty after generation: missed slot {slot} recorded in data/missed_slot.json")
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

        # Re-validate the durable buffer asset after download. The producer gate
        # protects admission; this protects the publish boundary as well.
        from production_gate import validate_final_video, validate_buffer_metadata, validate_buffer_provenance
        validate_final_video(mp4)
        validate_buffer_metadata(out / "caption.json")
        validate_buffer_provenance(out / "caption.json")
        log("PRODUCTION GATE: buffered MP4 and provenance re-verified before publishing")

        h = _posted_entry(history, video["stamp"], meta.get("story_id"))
        if h:  # same story under another stamp (a rebuilt copy): never post it twice
            _drop_posted(buffer, video, h)
            save_history(history)
            return 1 if from_build else 0
        if not from_build:
            _late_slot_served()

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
    else:  # the builder's entry never reached history.json (Oct 3-5: buffer_fill.yml didn't save it): rebuild it
        history.append({
            "date": video["stamp"], "buffered": video["stamp"], "story_id": meta.get("story_id"),
            "title": meta["title"], "mode": meta.get("mode"), "true_story": meta.get("true_story"),
            "case": meta.get("case"), "source": meta.get("source"), "subgenre": meta.get("subgenre"),
            "premise": meta.get("premise"), "opening": meta.get("opening"),
            "visual_mode": meta.get("visual_mode"), "seconds": meta.get("seconds"),
            "video_number": number, "tiktok": result if result else {"error": tt_error},
            "youtube": yt if yt else ({"error": yt_error} if yt_error else None),
            "posted": datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M"),
            "yt_title": meta.get("yt_title"), "hashtags": meta.get("hashtags"), "yt_tags": meta.get("yt_tags"),
            "history_rebuilt": "from caption.json at post time",
            **({"removal_pending": True} if removal_pending else {}),
        })
        log(f"WARNING: no history entry for '{meta['title']}' ({video['stamp']}): rebuilt it from caption.json")
        notify_text("Night Files: history entry was missing",
                    f"#{number} '{meta['title']}' ({video['stamp']}) had no history entry; it was rebuilt from "
                    "caption.json. Check that the build that made it saved history.", warn=True)
    save_history(history)
    (ROOT / ".posted").write_text(json.dumps({"stamp": video["stamp"], "story_id": meta.get("story_id"),
                                              "video_number": number}))

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
