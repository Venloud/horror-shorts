"""Builder (build.yml): story -> voice -> images -> captions -> render -> QA gate -> into the video buffer.

Posting happens separately (publish.py, run by daily.yml), so a failed build wastes nothing: the inbox item or case
is only marked used (history.json) once its video is safely in the buffer, and a failed build keeps its story,
narration and images as a checkpoint (checkpoint.py) so the next try only redoes what's missing.
  python main.py          normal build: add the video to the buffer and write history
  python main.py --test   test build: no Cloudflare, no buffer, no history, no checkpoints; mp4 kept as an artifact
"""
import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone

from common import CONFIG, ROOT, env, load_history, log, save_history


def _gh_output(key: str, value) -> None:
    """Hand a value to later workflow steps (build artifacts are named by story id)."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def fit_duration(story: dict, workdir, narrate, allow_rewrite: bool) -> tuple[dict, dict]:
    """Voice it, then get the narration into config target_seconds: first by voice speed (config voice_speed_range),
    then, if still outside, by asking Gemini to trim/extend by the needed word count (max 2 tries)."""
    from story import resize_story
    lo, hi = CONFIG.get("target_seconds", [50, 60])
    smin, smax = CONFIG.get("voice_speed_range", [1.0, 1.2])
    narr = narrate(story, workdir)

    def inside(n: dict) -> bool:
        return lo <= n["duration"] <= hi

    def speed_for(n: dict) -> float:
        want = hi - 1.5 if n["duration"] > hi else lo + 1.5
        return round(max(smin, min(smax, n["speed"] * n["duration"] / want)), 3)

    if inside(narr):
        return story, narr
    speed = speed_for(narr)
    if abs(speed - narr["speed"]) > 0.005:
        log(f"Narration {narr['duration']:.1f}s is outside {lo}-{hi}s: re-voicing at speed {speed}")
        narr = narrate(story, workdir, speed=speed)
        if inside(narr):
            return story, narr
    if not allow_rewrite:
        log(f"Exact-words script: keeping it at {narr['duration']:.1f}s (speed {narr['speed']}), no rewrite")
        return story, narr
    for attempt in range(1, 3):
        want = hi - 1.5 if narr["duration"] > hi else lo + 1.5
        words = sum(len(s["narration"].split()) for s in story["scenes"])
        want_words = max(60, round(words * want / narr["duration"]))
        log(f"Still {narr['duration']:.1f}s: asking for {want_words} words instead of {words} ({attempt}/2)")
        try:
            story = resize_story(story, env("GEMINI_API_KEY"), want_words)
        except Exception as e:  # noqa: BLE001
            log(f"Resize failed ({str(e)[:150]}): keeping the current script")
            break
        narr = narrate(story, workdir, speed=narr["speed"])
        if inside(narr):
            break
        speed = speed_for(narr)
        if abs(speed - narr["speed"]) > 0.005:
            narr = narrate(story, workdir, speed=speed)
            if inside(narr):
                break
    if not inside(narr):
        log(f"Narration is {narr['duration']:.1f}s after all tries; the QA gate will decide")
    return story, narr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="test build: no Cloudflare, no buffer, no history")
    ap.add_argument("--no-upload", action="store_true", help="old name for --test")
    args = ap.parse_args()
    testing = args.test or args.no_upload
    if testing:
        os.environ["TEST_MODE"] = "true"

    import buffer
    import checkpoint
    import images
    from captions import build_ass
    from notify import caption_text, notify
    from render import qa_gate, render
    from story import mark_true_story, write_story
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

        story = None if testing else checkpoint.resume(history)
        if story is None:
            story = write_story(history)
            if not testing:
                checkpoint.start(story)
        # Until it's posted, a video is known by its story id (the post number is given by publish.py).
        story["story_id"] = story.get("story_id") or checkpoint.story_id(story)
        _gh_output("story_id", story["story_id"])
        log(f"Story {story['story_id']}: '{story['title']}' ({story.get('mode')})")
        (workdir / "story.json").write_text(json.dumps(story, indent=2, ensure_ascii=False))

        narration = None if testing else checkpoint.load_narration(story, workdir)
        if narration is None:
            before = json.dumps(story.get("scenes"))
            story, narration = fit_duration(story, workdir, narrate,
                                            allow_rewrite=story.get("mode") != "inbox-script")
            if json.dumps(story.get("scenes")) != before:  # resized: re-check the TRUE STORY line
                mark_true_story(story)
            if not testing:
                checkpoint.save_story(story)
                checkpoint.save_narration(story, narration)

        img_dir = workdir / "images" if testing else checkpoint.IMAGES  # images are kept as soon as they exist
        imgs = images.generate_images(story, img_dir)
        from render import END_CARD_DELAY, TAIL
        ass = build_ass(narration["words"], story.get("hook_overlay", ""),
                        narration["duration"] + TAIL, workdir / "captions.ass",
                        end_start=narration["duration"] + END_CARD_DELAY,
                        badge="TRUE STORY" if story.get("true_story") else None)
        video = render(story, imgs, narration, ass, workdir)
        caption = caption_text(story)
        (workdir / "caption.txt").write_text(caption + "\n\nPIN: " + story.get("pinned_comment", ""))

        problems = qa_gate(video, ass, narration)
        if problems:  # never let a broken video into the buffer
            reason = "; ".join(problems)
            if testing:
                notify(story, None, prefix=prefix, error=f"QA gate failed: {reason}")
                return 1
            fails = checkpoint.qa_failed(story, problems)
            if fails >= 2:  # same story failed twice: skip it for good so the builder can't loop on it
                history.append({"date": stamp, "story_id": story.get("story_id"), "title": story["title"],
                                "mode": story.get("mode"), "source": story.get("source"), "case": story.get("case"),
                                "skipped": True, "reason": f"QA gate: {reason}"})
                save_history(history)
                checkpoint.finish(story)
                notify(story, None, error=f"QA gate failed twice, story skipped for good: {reason}")
            else:
                notify(story, None, error=f"QA gate failed, not added to the buffer (next build retries): {reason}")
            return 0  # alert already sent; exit 0 so build.yml still saves history + checkpoint

        meta = workdir / "caption.json"
        meta.write_text(json.dumps({
            "stamp": stamp, "story_id": story["story_id"], "title": story["title"], "caption_text": caption,
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
            "story_id": story.get("story_id"),
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
            "voice_speed": narration.get("speed"),
            "buffered": stamp,
            "tiktok": None,  # filled in by publish.py when it's posted
        })
        save_history(history)
        images.save_cache(story, imgs)
        checkpoint.finish(story)
        (ROOT / ".built").write_text(stamp)  # tells build.yml to save the image cache
        log(f"Done: '{story['title']}' is in the buffer.")
        try:  # a publish slot found the buffer empty in the last 6 h: post this video right away
            import publish
            publish.post_missed_slot()
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            log(f"Make-up post failed ({e}); the video stays in the buffer for the next slot")
        return 0
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        if testing:
            notify(story, None, error=f"{type(e).__name__}: {e}", prefix=prefix)
            return 1
        # Quiet failure: the checkpoint is kept and the next build (every 3 h) continues from it.
        # Only alert if nothing is waiting to be posted.
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
