"""Daily run: story -> voice -> images -> captions -> render -> TikTok -> notify."""
import argparse
import json
import sys
import traceback
from datetime import datetime, timezone

from common import CONFIG, ROOT, load_history, log, save_history


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true", help="make the video but don't send it to TikTok")
    args = ap.parse_args()

    from captions import build_ass
    from images import generate_images
    from notify import caption_text, notify
    from render import quality_check, render
    from story import write_story
    from voice import narrate

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    workdir = ROOT / "output" / stamp
    workdir.mkdir(parents=True, exist_ok=True)
    history = load_history()
    story: dict = {"title": "(no story yet)"}

    try:
        story = write_story(history)
        (workdir / "story.json").write_text(json.dumps(story, indent=2, ensure_ascii=False))

        narration = narrate(story, workdir)
        images = generate_images(story, workdir / "images")
        from render import END_CARD_DELAY, TAIL
        ass = build_ass(narration["words"], story.get("hook_overlay", ""),
                        narration["duration"] + TAIL, workdir / "captions.ass",
                        end_start=narration["duration"] + END_CARD_DELAY)
        video = render(story, images, narration, ass, workdir)
        quality_check(video)
        (workdir / "caption.txt").write_text(caption_text(story) + "\n\nPIN: " + story.get("pinned_comment", ""))

        result = None
        if args.no_upload:
            log("--no-upload set: skipping TikTok")
        else:
            import tiktok
            if CONFIG.get("tiktok_mode") == "direct":
                try:
                    result = tiktok.post_direct(video, caption_text(story))
                except Exception as e:  # noqa: BLE001
                    log(f"Direct post failed ({str(e)[:300]}), sending it to drafts instead")
                    result = tiktok.send_to_drafts(video)
                    result["direct_error"] = str(e)[:300]
            else:
                result = tiktok.send_to_drafts(video)

        for sk in story.pop("_skipped", []):
            history.append({"date": stamp, **sk})
        history.append({
            "date": stamp,
            "title": story["title"],
            "premise": story.get("premise", ""),
            "subgenre": story.get("subgenre", ""),
            "mode": story.get("mode", "fiction"),
            "case": story.get("case"),
            "source": story.get("source"),
            "prompt_file": story.get("prompt_file"),
            "setting": story.get("setting"),
            "threat": story.get("threat"),
            "twist": story.get("twist"),
            "score": story.get("score"),
            "seconds": round(narration["duration"], 1),
            "tiktok": result,
        })
        save_history(history)
        notify(story, result)
        log("Done.")
        return 0
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        notify(story, None, error=f"{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
