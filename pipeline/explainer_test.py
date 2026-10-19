"""Explainer render-style TEST build (explainer_test.yml): one full video in the explainer style, nothing published.
Writes a story exactly like production (inbox file forced with INBOX_FILE, or a mode with STORY_MODE), adapts it to
the explainer style, voices + fits it, draws the painted plates (test share of the Cloudflare ledger), renders,
adds music, runs the QA gate (report only) and makes an 8-frame review sheet.
No buffer, no history, no checkpoint, no TikTok / YouTube.
  INBOX_FILE=le_prince_remake.txt python explainer_test.py
  STORY_MODE=lore python explainer_test.py
"""
import json
import os
import re
import shutil
import sys
import traceback
from datetime import datetime, timezone

from common import CONFIG, ROOT, load_history, log


def main() -> int:
    os.environ["TEST_MODE"] = "true"  # Cloudflare ledger: tests share
    os.environ["RENDER_STYLE"] = "explainer"
    import cf_budget
    import explainer
    from background_music import add_background_music
    from main import fit_duration
    from render import qa_gate
    from story import mark_true_story, write_story
    from voice import narrate

    workdir = ROOT / "output" / "explainer_test"
    workdir.mkdir(parents=True, exist_ok=True)
    explainer.Character()  # no character set = nothing to test (before any Gemini call)
    tests_before = cf_budget.load()["tests"]
    log(cf_budget.line())
    report = [f"EXPLAINER TEST (nothing published): inbox_file={os.environ.get('INBOX_FILE') or '-'} "
              f"story_mode={os.environ.get('STORY_MODE') or '-'}"]
    story: dict = {}
    try:
        story = write_story(load_history())
        before = [sc.get("narration", "") for sc in story["scenes"]]
        story = explainer.adapt(story)
        (workdir / "story_adapted.json").write_text(json.dumps(story, indent=2, ensure_ascii=False))
        snap = json.dumps(story.get("scenes"))
        story, narr = fit_duration(story, workdir, narrate, allow_rewrite=story.get("mode") != "inbox-script")
        if json.dumps(story.get("scenes")) != snap:
            mark_true_story(story)
        video = explainer.build(story, narr, workdir / "images", workdir)
        video = add_background_music(video, workdir, story)
        final = workdir / "explainer_final.mp4"
        shutil.move(str(video), final)
        problems = [p for p in qa_gate(final, None, narr, story) if not p.startswith("captions:")]  # drawn in-frame
        sheet = explainer.frame_sheet(final, workdir / "frame_sheet.png")
        slug = re.sub(r"[^a-z0-9]+", "_", (story.get("title") or "story").lower()).strip("_")[:40]
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        prev = ROOT / "previews" / "explainer"
        prev.mkdir(parents=True, exist_ok=True)
        if sheet:
            shutil.copy(sheet, prev / f"{stamp}_{story.get('mode')}_{slug}.png")
        used = cf_budget.load()["tests"] - tests_before
        words = sum(len(s["narration"].split()) for s in story["scenes"])
        from common import media_duration
        a = story.get("explainer_assets") or {}
        report += [
            f"Title: {story.get('title')}", f"Mode: {story.get('mode')}  true story: {story.get('true_story')}",
            f"Writer: {story.get('writer') or story.get('model')}",
            f"Words: {words}  narration {narr['duration']:.1f}s at speed {narr.get('speed')}  "
            f"video {media_duration(final):.1f}s (window {CONFIG.get('target_seconds')})",
            f"Cloudflare neurons this test: {used:.0f} ({used / cf_budget.IMAGE_NEURONS:.0f} images); "
            f"assets drawn {a.get('drawn')}, calls {a.get('cloudflare_images')}, fallbacks {a.get('fallback')}",
            f"Render: {story.get('explainer_render')}", f"HUD / chips: {story.get('explainer_plan')}",
            f"Visuals: {story.get('_visuals')}",
            "QA gate (report only): " + ("passed" if not problems else "; ".join(problems)),
            "", "SCRIPT (explainer):"] + [f"[{i + 1}] {s['narration']}" for i, s in enumerate(story["scenes"])] + [
            "", "BEFORE (as written for classic):"] + [f"[{i + 1}] {t}" for i, t in enumerate(before)]
        code = 0
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        report.append(f"FAILED: {type(e).__name__}: {str(e)[:500]}")
        code = 1
    (workdir / "story.json").write_text(json.dumps(story, indent=2, ensure_ascii=False, default=str))
    (workdir / "report.txt").write_text("\n".join(report) + "\n")
    log("\n" + "\n".join(report))
    log(cf_budget.line())
    return code


if __name__ == "__main__":
    sys.exit(main())
