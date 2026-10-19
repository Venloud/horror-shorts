"""Story-only dry run (story_dry_run.yml): write ONE story exactly like production would (inbox file forced with
INBOX_FILE, research, editor, critic, fact check), voice it with Kokoro and fit the duration, then print the script,
its length and the critic / fact-check results. No images, no render, no buffer, no history, no checkpoint, no
TikTok / YouTube: nothing is published or marked used.
  INBOX_FILE=le_prince_remake.txt python story_dry_run.py
"""
import json
import os
import sys

from common import CONFIG, ROOT, load_history, log


def main() -> int:
    if not os.environ.get("INBOX_FILE"):
        print("Set INBOX_FILE (e.g. le_prince_remake.txt)")
        return 2
    from main import fit_duration
    from render import tail_for
    from story import mark_true_story, write_story
    from voice import narrate

    workdir = ROOT / "output" / "dry_run"
    workdir.mkdir(parents=True, exist_ok=True)
    story = write_story(load_history())
    before = json.dumps(story.get("scenes"))
    story, narr = fit_duration(story, workdir, narrate, allow_rewrite=story.get("mode") != "inbox-script")
    if json.dumps(story.get("scenes")) != before:
        mark_true_story(story)
    total = narr["duration"] + tail_for(narr["duration"])
    lo, hi = CONFIG.get("target_seconds", [61, 68])
    try:
        import yt_packaging
        pack = yt_packaging.package(story)
    except Exception as e:  # noqa: BLE001
        pack = {"error": str(e)[:200]}
    script = "\n\n".join(f"[{i + 1}] {sc.get('narration', '').strip()}" for i, sc in enumerate(story["scenes"]))
    words = sum(len(sc.get("narration", "").split()) for sc in story["scenes"])
    report = (f"DRY RUN (nothing published): {os.environ['INBOX_FILE']}\n"
              f"Title: {story.get('title')}\nYouTube title: {pack.get('yt_title')}\nYouTube tags: {pack.get('yt_tags')}\n"
              f"Mode: {story.get('mode')}  true story: {story.get('true_story')}  remake of: {story.get('remake_of')}\n"
              f"Writer: {story.get('writer') or story.get('model')}  critic: {story.get('critic_score')}\n"
              f"Words: {words}  narration: {narr['duration']:.1f}s at speed {narr.get('speed')}  "
              f"finished video: {total:.1f}s (window {lo}-{hi}s)\n"
              f"Sources: {[s.get('domain') or s.get('url') for s in story.get('sources') or []]}\n"
              f"Hook overlay: {story.get('hook_overlay')}\n\nSCRIPT:\n{script}\n")
    (workdir / "story.json").write_text(json.dumps(story, indent=2, ensure_ascii=False))
    (workdir / "report.txt").write_text(report)
    log("\n" + report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
