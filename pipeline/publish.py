"""Publisher (daily.yml at 11:40 AM / 8:40 PM New York): post the oldest buffered video. No generation here.

Download the oldest <stamp>.mp4 + <stamp>.json from the "buffer" release -> send to TikTok (drafts or direct) ->
delete it from the buffer -> record the TikTok result in history.json -> phone alert (+ warning when the buffer
is low). Takes about a minute.
"""
import json
import sys
import traceback
from datetime import datetime, timezone

from common import CONFIG, ROOT, load_history, log, save_history


def main() -> int:
    import buffer
    import tiktok
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

        if CONFIG.get("tiktok_mode") == "direct":
            try:
                result = tiktok.post_direct(mp4, meta["caption_text"])
            except Exception as e:  # noqa: BLE001
                log(f"Direct post failed ({str(e)[:300]}), sending it to drafts instead")
                result = tiktok.send_to_drafts(mp4)
                result["direct_error"] = str(e)[:300]
        else:
            result = tiktok.send_to_drafts(mp4)

        buffer.remove(video)
        history = load_history()
        for h in reversed(history):
            if h.get("buffered") == video["stamp"] or h.get("date") == video["stamp"]:
                h["tiktok"] = result
                h["posted"] = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
                break
        save_history(history)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        notify_text("Night Files: publish FAILED",
                    f"'{video['stamp']}' stays in the buffer and will be tried next slot. {type(e).__name__}: {e}",
                    warn=True)
        return 1

    notify({"title": meta["title"], "caption_text": meta["caption_text"],
            "pinned_comment": meta.get("pinned_comment", "")}, result)
    left = len(waiting) - 1
    log(f"Done. {left} video(s) left in the buffer.")
    if left <= 1:
        notify_text(f"Night Files: buffer low ({left} left)",
                    "build.yml refills it every 3 hours. If it stays low, check the build runs.", warn=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
