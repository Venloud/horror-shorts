"""Builder (build.yml): story -> voice -> images -> captions -> render -> into the video buffer.

Posting happens separately (publish.py, run by daily.yml), so a failed build wastes nothing: the inbox item or case
is only marked used (history.json) once its video is safely in the buffer.
  python main.py          normal build: add the video to the buffer and write history
  python main.py --test   test build: no Cloudflare, no buffer, no history; the mp4 is kept as an Actions artifact
"""
import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone

from common import CONFIG, ROOT, load_history, log, save_history


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="test build: no Cloudflare, no buffer, no history")
    ap.add_argument("--no-upload", action="store_true", help="old name for --test")
    args = ap.parse_args()
    testing = args.test or args.no_upload
    if testing:
        os.environ["TEST_MODE"] = "true"

    import buffer
    import images
    from captions import build_ass
    from notify import caption_text, notify
    from render import quality_check, render
    from story import write_story
    from voice import narrate

    prefix = "[TEST] " if testing else ""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    workdir = ROOT / "output" / stamp
    workdir.mkdir(parents=True, exist_ok=True)
    history = load_history()
    story: dict = {"title": "(no story yet)"}

    try:
        problem = images.preflight()  # don't spend Gemini + voice time if no image source works
        if problem:
            raise RuntimeError(problem)
        story = write_story(history)
        (workdir / "story.json").write_text(json.dumps(story, indent=2, ensure_ascii=False))

        narration = narrate(story, workdir)
        imgs = images.generate_images(story, workdir / "images")
        from render import END_CARD_DELAY, TAIL
        ass = build_ass(narration["words"], story.get("hook_overlay", ""),
                        narration["duration"] + TAIL, workdir / "captions.ass",
                        end_start=narration["duration"] + END_CARD_DELAY,
                        badge="TRUE STORY" if story.get("true_story") else None)
        video = render(story, imgs, narration, ass, workdir)
        quality_check(video)
        caption = caption_text(story)
        (workdir / "caption.txt").write_text(caption + "\n\nPIN: " + story.get("pinned_comment", ""))
        meta = workdir / "caption.json"
        meta.write_text(json.dumps({
            "stamp": stamp, "title": story["title"], "caption_text": caption,
            "pinned_comment": story.get("pinned_comment", ""), "mode": story.get("mode", "fiction"),
            "hashtags": story.get("hashtags", []),
            "true_story": bool(story.get("true_story")), "seconds": round(narration["duration"], 1),
        }, indent=2, ensure_ascii=False))

        if testing:
            log("TEST MODE: not adding to the buffer, not writing history")
            notify(story, None, prefix=prefix, note="Test video: download it from this run's artifacts.")
            log("Done (test).")
            return 0

        buffer.add(stamp, video, meta)
        # Used as soon as the video is safely in the buffer, so it can never be made twice.
        for sk in story.pop("_skipped", []):
            history.append({"date": stamp, **sk})
        history.append({
            "date": stamp,
            "title": story["title"],
            "premise": story.get("premise", ""),
            "subgenre": story.get("subgenre", ""),
            "mode": story.get("mode", "fiction"),
            "true_story": bool(story.get("true_story")),
            "case": story.get("case"),
            "source": story.get("source"),
            "prompt_file": story.get("prompt_file"),
            "setting": story.get("setting"),
            "threat": story.get("threat"),
            "twist": story.get("twist"),
            "score": story.get("score"),
            "seconds": round(narration["duration"], 1),
            "buffered": stamp,
            "tiktok": None,  # filled in by publish.py when it's posted
        })
        save_history(history)
        images.save_cache(story, imgs)
        (ROOT / ".built").write_text(stamp)  # tells build.yml to save the image cache
        log(f"Done: '{story['title']}' is in the buffer.")
        return 0
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        if testing:
            notify(story, None, error=f"{type(e).__name__}: {e}", prefix=prefix)
            return 1
        # Quiet failure: the next build (every 3 h) tries again. Only alert if nothing is waiting to be posted.
        try:
            waiting = buffer.count()
        except Exception as be:  # noqa: BLE001
            log(f"Could not check the buffer ({be})")
            waiting = 0
        if waiting == 0:
            notify(story, None, error=f"Buffer is EMPTY and the build failed. {type(e).__name__}: {e}")
            return 1
        log(f"Build failed, but {waiting} video(s) are still in the buffer: trying again next time, no alert.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
