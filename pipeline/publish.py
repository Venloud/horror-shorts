"""Publisher (daily.yml at 11:40 AM / 8:40 PM New York): post the oldest buffered video. No generation here.

Download the oldest <stamp>.mp4 + <stamp>.json from the "buffer" release -> TikTok (drafts or direct) and YouTube
Shorts, independently -> delete it from the buffer if at least one worked -> record both results in history.json
-> phone alert with the YouTube link (+ warning when the buffer is low). Takes about a minute or two.

Empty buffer: no failure. It writes data/missed_slot.json, alerts "building now", and daily.yml starts build.yml
right away (ROOT/.trigger_build tells it to). When a build (within 24 h) puts a video in the buffer, main.py calls
post_missed_slot(): it makes the slot up only if the buffer then holds 2+ videos (the next regular slot keeps one)
and no post is within 3 h before or after (last post / next slot); else the file waits for a later build.
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
    wait = makeup_blocker()
    if wait:
        log(f"Missed slot ({info.get('slot')}) not made up yet: {wait}; a later build tries again")
        return
    log(f"Making up the missed slot ({info.get('slot')}, {age_h:.1f} h ago): posting now")
    main(from_build=True)
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


def main(from_build: bool = False) -> int:
    import buffer
    import tiktok
    import youtube
    from notify import notify, notify_text

    buffer.purge_old()  # never post a video made before the image fix (config buffer_purge_before)
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
                    "Buffer empty: building now. The slot is made up once the buffer holds 2+ videos, never "
                    "within 3 h of another post.")
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
            # packaging.py fields (new videos); older buffer entries fall back to the title + TikTok caption
            yt = youtube.upload(mp4, meta.get("yt_title") or meta["title"],
                                meta.get("yt_description") or meta["caption_text"], meta.get("hashtags"),
                                credits=meta.get("visual_credits") or "", tags=meta.get("yt_tags"))
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
            if meta.get("yt_title"):
                h["yt_title"], h["hashtags"], h["yt_tags"] = meta["yt_title"], meta.get("hashtags"), meta.get("yt_tags")
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
