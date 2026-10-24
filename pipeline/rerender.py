"""TEST-ONLY re-render of an EXISTING story with the current explainer (explainer_rerender.yml). Nothing is buffered,
posted or written to history; the production checkpoint is not touched (this run's checkpoint lives in its own
output folder). No new story is written: the story file's narration, fact ledger and shot prompts are used as they are.

  python rerender.py ../tests/fixtures/amelia_f8f477b53755.json

Narration: the buffered video's checkpoint was cleared when it entered the buffer (checkpoint.finish keeps no
narration), so the SAME text is voiced again with the production voice (Kokoro, config voice) at the speed the
video was made with (history voice_speed). Pictures / graphics / host / QA = explainer.build, exactly as production.
Outputs in output/rerender/<story id>/: rerender_final.mp4, frame_sheet.png, shot_manifest.json, provenance.json,
visual_qa.json, report.txt. Exit 1 when the visual QA fails (the artifacts are still written).
"""
import json
import shutil
import sys
import traceback
from pathlib import Path

from common import CONFIG, ROOT, load_history, log


def main(argv: list[str]) -> int:
    src = Path(argv[1] if len(argv) > 1 else ROOT / "tests" / "fixtures" / "amelia_f8f477b53755.json")
    story = json.loads(src.read_text())
    sid = story.get("story_id") or "unknown"
    workdir = ROOT / "output" / "rerender" / sid
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    import checkpoint
    checkpoint.CK = workdir / "ckpt"  # isolated: the production checkpoint / buffer / history stay untouched
    checkpoint.IMAGES = checkpoint.CK / "images"
    checkpoint.start(story)
    report = [f"TEST-ONLY RE-RENDER (nothing buffered / posted / in history) of {sid}: '{story.get('title')}'",
              f"Story file: {src.relative_to(ROOT) if src.is_relative_to(ROOT) else src}"]
    hist = next((h for h in load_history() if h.get("story_id") == sid), {})
    speed = float(hist.get("voice_speed") or CONFIG.get("voice_speed", 1.1))
    missing = ["original narration WAV + word timings (checkpoint cleared when the video was buffered)",
               "original 4 Cloudflare plates (same reason; the new style does not use location plates)"]
    report.append("Not available from the original run: " + "; ".join(missing))
    code = 0
    try:
        from voice import narrate
        narr = narrate(story, workdir, speed=speed)
        report.append(f"Narration: same text re-voiced with {CONFIG.get('voice')} at speed {speed} "
                      f"({narr['duration']:.1f}s; original {hist.get('seconds')}s)")
        import background_music
        import explainer
        music = hist.get("music_file") or story.get("music_file")
        if music and (ROOT / "assets" / "music" / music).is_file():  # the same soundtrack as the original
            background_music._pick_approved = lambda: ROOT / "assets" / "music" / music
        try:
            video = explainer.build(story, narr, checkpoint.IMAGES, workdir)
        except explainer.VisualQAFailed as e:
            report.append(f"VISUAL QA FAILED: {e}")
            code = 1
            video = workdir / ("explainer_polished.mp4" if (workdir / "explainer_polished.mp4").exists()
                               else "explainer.mp4")
        video = background_music.add_background_music(video, workdir, story)
        final = workdir / "rerender_final.mp4"
        shutil.move(str(video), final)
        from render import qa_gate
        problems = [p for p in qa_gate(final, None, narr, story) if not p.startswith("captions:")]
        report.append("QA gate (production rules, report): " + ("passed" if not problems else "; ".join(problems)))
        explainer.frame_sheet(final, workdir / "frame_sheet.png")
        qa = json.loads((workdir / "visual_qa.json").read_text())
        report += [f"Shots: {qa['shots']}", f"Runtime share: {qa['runtime_share']}",
                   f"AI images: {qa['ai_images']}", f"Media used: {qa['media_used']}",
                   f"Character assets: {qa['character_assets']}",
                   "Visual QA failures: " + ("none" if not qa["failures"] else "; ".join(qa["failures"])),
                   "Exceptions: " + ("none" if not qa["exceptions"] else "; ".join(qa["exceptions"]))]
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        report.append(f"FAILED: {type(e).__name__}: {str(e)[:600]}")
        code = 1
    (workdir / "story.json").write_text(json.dumps(story, indent=1, ensure_ascii=False, default=str))
    (workdir / "report.txt").write_text("\n".join(report) + "\n")
    log("\n" + "\n".join(report))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
