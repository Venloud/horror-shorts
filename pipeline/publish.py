"""Publisher (daily.yml at 11:40 AM / 8:40 PM New York): post the oldest buffered video. No generation here.

Download the oldest <stamp>.mp4 + <stamp>.json from the "buffer" release -> TikTok (drafts or direct) and YouTube
Shorts, independently -> delete it from the buffer if at least one worked -> record both results in history.json
-> phone alert with the YouTube link (+ warning when the buffer is low). Takes about a minute or two.
"""
import json
import sys
import traceback
from datetime import datetime, timezone

from common import CONFIG, ROOT, load_history, log, save_history


def main() -> int:
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
        notify_text("Night Files: buffer EMPTY", "Nothing to post this slot. Check the last build.yml runs.",
                    warn=True)
        return 1

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
    history = load_history()
    for h in reversed(history):
        if h.get("buffered") == video["stamp"] or h.get("date") == video["stamp"]:
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
            "pinned_comment": meta.get("pinned_comment", "")}, result, note="\n".join(lines))
    left = len(waiting) - 1
    log(f"Done. {left} video(s) left in the buffer.")
    if left <= 1:
        notify_text(f"Night Files: buffer low ({left} left)",
                    "build.yml refills it every 3 hours. If it stays low, check the build runs.", warn=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
