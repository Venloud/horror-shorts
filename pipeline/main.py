"""Production video generator: story -> voice -> images -> captions -> render -> QA -> hard production gate -> buffer.

The daily workflow runs this generator and then runs publish.py. Diagnostic visual QA remains report-only, but the
hard production gate rejects invalid/corrupt media or missing provenance before anything reaches the durable buffer.
"""
import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from common import CONFIG, ROOT, env, load_history, log, save_history
import yt_packaging as packaging  # NOT "packaging": that name shadows the pip package transformers needs


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
    from render import narration_window
    lo, hi = narration_window()  # the video's target minus the end card
    smin, smax = CONFIG.get("voice_speed_range", [1.0, 1.2])
    narr = narrate(story, workdir)

    def inside(n: dict) -> bool:
        return lo <= n["duration"] <= hi

    def speed_for(n: dict) -> float:
        want = hi - 1.5 if n["duration"] > hi else lo + 1.5
        return round(max(smin, min(smax, n["speed"] * n["duration"] / want)), 3)

    if inside(narr):
        return story, narr
    # Kokoro's length doesn't scale 1:1 with speed (1.157x only took 67.7s to 61.1s), so re-voice up to 3 times,
    # each time using the speed response measured so far, until it fits or the speed hits its limit.
    first = narr
    for _ in range(3):
        speed = speed_for(narr)
        if narr is not first and first["speed"] != narr["speed"] and first["duration"] != narr["duration"]:
            import math  # duration ~ speed^-k, k measured from the two voicings
            k = -math.log(narr["duration"] / first["duration"]) / math.log(narr["speed"] / first["speed"])
            if 0.2 < k < 2:
                want = hi - 1.5 if narr["duration"] > hi else lo + 1.5
                speed = round(max(smin, min(smax, narr["speed"] * (narr["duration"] / want) ** (1 / k))), 3)
        if abs(speed - narr["speed"]) <= 0.005:
            break  # at the speed limit already
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


def write_summary(workdir: Path, story: dict, video: Path, problems: list[str]) -> None:
    """summary.txt next to final.mp4 (build artifact): mode, duration, visual sources, QA, fallbacks."""
    try:
        from common import media_duration
        cut = story.get("cutout") or {}
        vs = story.get("_visual_sources") or {}
        lines = [f"story: {story.get('title')} ({story.get('story_id')}, mode {story.get('mode')})",
                 f"render style: {story.get('render_style', 'classic')}  visual mode: {story.get('visual_mode')}",
                 f"duration: {media_duration(video):.1f}s",
                 "QA gate: " + ("PASSED" if not problems else "FAILED: " + "; ".join(problems))]
        if story.get("render_style") == "cutout":
            lines += [f"cutout shots: {cut.get('counts')}", f"Cloudflare images: {cut.get('cloudflare_images')}",
                      f"characters / poses: {cut.get('poses')}", f"plates: {cut.get('plates')}",
                      "cutout fallbacks: " + ("; ".join(cut.get("fallbacks") or []) or "none")]
        else:
            lines.append(f"visual sources: {vs.get('reused', 0)} reused, {vs.get('archive_stock', 0)} archive/stock, "
                         f"{vs.get('ai', 0)} AI")
        if story.get("_cutout_error"):
            lines.append(f"CUTOUT FAILED, rendered classic instead: {story['_cutout_error']}")
        lines.append(f"visuals: {story.get('_visuals')}")
        lines.append(f"research sources: {[s.get('domain') for s in story.get('sources') or []]}")
        if story.get("remake_of"):
            lines.append(f"remake of: {story['remake_of']} (angle: {story.get('remake_angle', '')[:120]})")
        (workdir / "summary.txt").write_text("\n".join(lines) + "\n")
        log("summary.txt: " + " | ".join(lines[:4]))
    except Exception as e:  # noqa: BLE001
        log(f"summary.txt failed ({e})")


def main() -> int:
    # Production-only builder: every invocation creates a real buffered video.
    testing = False

    import buffer
    import checkpoint
    import cutout
    import images
    import media
    from captions import build_ass
    from notify import caption_text, notify
    from render import pick_visual_mode, qa_gate, render
    from story import mark_true_story, write_story
    from voice import narrate

    prefix = ""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    workdir = ROOT / "output" / stamp
    workdir.mkdir(parents=True, exist_ok=True)
    from artifacts import RunManifest
    from provider_registry import snapshot as provider_snapshot
    manifest = RunManifest(workdir)
    manifest.provider_snapshot(provider_snapshot())
    history = load_history()
    story: dict = {"title": "(no story yet)"}

    try:
        problem = images.preflight()  # don't spend Gemini + voice time if no image source works
        if problem:
            raise RuntimeError(problem)
        if (os.environ.get("RENDER_STYLE") or "").strip().lower() == "cutout":
            # cutout draws everything on Cloudflare: check before spending Gemini + voice on a story
            import cf_budget
            need = int(CONFIG.get("cutout_hard_max_images", 20)) * cf_budget.IMAGE_NEURONS
            cf_out = images.cloudflare_has_quota() is False
            if testing and (cf_out or cf_budget.test_room() < need):
                why = ("Cloudflare's daily limit is used up" if cf_out else
                       f"it needs ~{need:.0f} neurons and tests have {cf_budget.test_room():.0f} left today")
                defer_test(workdir, why)
                return 0
            if cf_out:
                raise RuntimeError("Cutout render was forced but Cloudflare's daily limit is used up (resets 00:00 UTC)")

        story, reused = None, False
        if testing and not images.test_cloudflare_images():  # zero-config test: the last built story + images
            story = images.cached_story()
            if story:
                reused = True
                log(f"Test: reused story {story.get('story_id') or checkpoint.story_id(story)} "
                    f"('{story.get('title')}'); tick fresh_images for a new story + images")
            else:
                os.environ["TEST_FRESH"] = "true"  # nothing cached yet: a new story with real images
                log("Test: nothing cached yet, writing a new story with fresh images")
        elif not testing:
            story = checkpoint.resume(history)
        if story is None:
            manifest.stage("story", "started")
            story = write_story(history)
            manifest.stage("story", "complete", writer=story.get("writer") or story.get("model"))
            if not testing:
                checkpoint.start(story)
        if not reused:  # creature on screen (legends), real subjects for the hook + twist, no filler shots
            if CONFIG.get("story_bible", True):
                import story_bible
                story_bible.build(story)
                log(story_bible.summary(story))
            import shot_rules
            shot_rules.apply(story)
            if not testing:
                checkpoint.save_story(story)
            manifest.stage("story_bible", "complete" if CONFIG.get("story_bible", True) else "skipped")
            manifest.stage("shot_rules", "complete")
        # Until it's posted, a video is known by its story id (the post number is given by publish.py).
        story["story_id"] = story.get("story_id") or checkpoint.story_id(story)
        if not story.get("visual_mode"):  # A/B test: classic -> fast -> analog (kept on a checkpoint resume)
            story["visual_mode"] = pick_visual_mode(history)
            if not testing:
                checkpoint.save_story(story)
        _gh_output("story_id", story["story_id"])
        log(f"Story {story['story_id']}: '{story['title']}' (mode {story.get('mode')}, "
            f"source {story.get('source') or story.get('case') or 'rotation'}, true story: {bool(story.get('true_story'))}, "
            f"written by {story.get('writer') or story.get('model')}, visual mode {story.get('visual_mode')})")
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

        log(f"Final narration: {narration['duration']:.1f}s at speed {narration.get('speed')}")
        img_dir = workdir / "images" if testing else checkpoint.IMAGES  # images are kept as soon as they exist
        imgs = None
        if cutout.style_for(story) == "cutout":  # EXPERIMENTAL: pose-set characters on background plates
            try:
                if story.get("visual_mode") == "fast":
                    story["visual_mode"] = "classic"  # fast mode's crops would cut the characters apart
                imgs = cutout.build(story, img_dir, workdir)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                story["_cutout_error"] = f"{type(e).__name__}: {str(e)[:300]}"
                if (os.environ.get("RENDER_STYLE") or "").strip().lower() == "cutout":
                    # a FORCED cutout run (test build input) never ships a classic video in its place
                    raise RuntimeError(f"Cutout render was forced but failed in cutout.build: {story['_cutout_error']}")
                log(f"Cutout mode failed ({story['_cutout_error']}); rendering this video classic")
                imgs = None
        if imgs is None and reused:  # test build: the cached images belong to this very story
            story["render_style"] = "classic"
            img_dir.mkdir(parents=True, exist_ok=True)
            imgs = images._cached_images(story, img_dir)
        if imgs is None:
            story["render_style"] = "classic"
            if testing and images.test_cloudflare_images() and not images._STATE["cf_out"]:
                import cf_budget  # tests may use 35% of the day's neurons; the rest is production's
                need = len(story["scenes"]) * int(CONFIG.get("shots_per_scene", 2)) * cf_budget.IMAGE_NEURONS
                if cf_budget.test_room() < need:
                    images._STATE["cf_out"] = True
                    log(f"Test cap: this video needs ~{need:.0f} neurons, tests have {cf_budget.test_room():.0f} "
                        f"left ({cf_budget.line()}): no Cloudflare, real media + library + local gap fillers only")
            import library
            library.fill_shots(story, img_dir, history)  # 1) asset library reuse (never raises)
            media.fill_shots(story, img_dir, history)  # 2) stock video / archive photos + prints (never raises)
            manifest.stage("visual_sources", "started")
            imgs = images.generate_images(story, img_dir)  # 3) AI for the rest
            manifest.stage("visual_sources", "complete", summary=library.summary(img_dir))
            vs = library.summary(img_dir)
            story["_visual_sources"] = vs
            log(f"Visual sources: {vs['reused']} reused, {vs['archive_stock']} archive/stock, {vs['ai']} AI")
            if images._STATE["cf_out"]:
                story["_low_quota"] = True
                log(f"Low-quota build: {vs['reused'] + vs['archive_stock']} real, {vs['ai']} AI")
        from render import END_CARD_DELAY, tail_for
        ass = build_ass(narration["words"], story.get("hook_overlay", ""),
                        narration["duration"] + tail_for(narration["duration"]), workdir / "captions.ass",
                        end_start=narration["duration"] + END_CARD_DELAY,
                        badge="TRUE STORY" if story.get("true_story") else None)
        manifest.stage("render", "started")
        video = render(story, imgs, narration, ass, workdir)
        manifest.artifact(video, "rendered-video-no-music")
        manifest.stage("render", "complete")

        # Music is a separate post-render layer. The visual/narration render
        # can be reused if a soundtrack is ever rejected.
        from background_music import add_background_music
        manifest.stage("background_music", "started")
        video = add_background_music(video, workdir, story)
        manifest.artifact(video, "final-video")
        manifest.stage("background_music", "complete",
                       music_source=story.get("music_source"),
                       music_file=story.get("music_file"))
        if story.get("render_style") == "cutout":  # review sheet for the owner (artifact)
            try:
                cutout.contact_sheet(video, workdir / "contact_sheet.png")
            except Exception as e:  # noqa: BLE001
                log(f"Contact sheet failed ({e})")
        (workdir / "story.json").write_text(json.dumps(story, indent=2, ensure_ascii=False))  # + media_assets
        if CONFIG.get("packaging", True):  # curiosity title + hook description + validated tags (packaging.py)
            packaging.package(story)
            caption = packaging.tiktok_caption(story)
        else:
            caption = caption_text(story)
        _short_credit, visual_credits = media.credits(story.get("media_assets") or [])
        (workdir / "caption.txt").write_text(caption + "\n\nPIN: " + story.get("pinned_comment", ""))

        problems = qa_gate(video, ass, narration, story)
        manifest.stage("qa", "complete" if not problems else "report", problems=problems)
        write_summary(workdir, story, video, problems)
        if problems:
            # QA is report-only in production. A rendered video is still buffered and posted.
            # This keeps QA useful for diagnostics without turning it into a publishing gate.
            reason = "; ".join(problems)
            log(f"QA gate REPORT ONLY: {reason}")
            try:
                notify(story, None, error=f"QA report only: {reason}")
            except Exception as e:
                log(f"QA report alert failed ({e})")

        meta = workdir / "caption.json"
        meta.write_text(json.dumps({
            "stamp": stamp, "story_id": story["story_id"], "title": story["title"], "caption_text": caption,
            "pinned_comment": story.get("pinned_comment", ""), "mode": story.get("mode", "fiction"),
            "hashtags": story.get("hashtags", []),
            **({"yt_title": story["packaging"]["yt_title"], "yt_tags": story["packaging"]["yt_tags"],
                "yt_description": packaging.youtube_description(story)} if story.get("packaging") else {}),
            "true_story": bool(story.get("true_story")), "seconds": round(narration["duration"], 1),
            "visual_credits": visual_credits, "visual_mode": story.get("visual_mode"),
            "render_style": story.get("render_style", "classic"),
            "provenance": {
                "media_assets": story.get("media_assets") or [],
                "visual_sources": story.get("_visual_sources") or {},
                "rights_policy": "external-media-requires-source-url-and-license",
            },
        }, indent=2, ensure_ascii=False))

        # Hard production boundary: only a real, fully decodable final MP4 with
        # provenance evidence may enter the durable FIFO buffer.
        from production_gate import gate_final_video, write_gate_report
        gate_evidence = gate_final_video(video, story, meta)
        gate_report = write_gate_report(workdir, gate_evidence)
        manifest.artifact(gate_report, "production-gate")
        manifest.stage("production_gate", "complete", evidence=gate_evidence)

        buffer.add(stamp, video, meta)
        manifest.artifact(meta, "caption")
        manifest.artifact(workdir / "story.json", "story")
        manifest.stage("buffer", "complete", buffer_count=buffer.count())
        manifest.finish("success")
        if story.get("render_style", "classic") == "classic":  # QA-passed pictures go into the asset library
            import library
            library.record_video(story, img_dir)
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
            "writer": story.get("writer") or story.get("model"),  # which provider wrote it (gemini / groq)
            "media_ids": [a["id"] for a in story.get("media_assets") or []],
            "visual_mode": story.get("visual_mode"),  # A/B test: classic / fast / analog
            "render_style": story.get("render_style", "classic"),  # classic / cutout (experimental)
            "story_shape": story.get("story_shape"),  # fiction shape rotation
            "research_sources": [x.get("domain") or x.get("url") for x in story.get("sources") or []],
            "visual_sources": story.get("_visual_sources"),  # reused / archive+stock / AI shots
            "low_quota": bool(story.get("_low_quota")),  # built with Cloudflare out (real media + gap fillers)
            "remake_of": story.get("remake_of"),  # inbox REMAKE: the old video's title
            "remake_angle": story.get("remake_angle"),
            "critic_score": story.get("critic_score"),
            "visuals": story.get("_visuals"),  # distinct pictures + the longest one on screen
            "yt_title": (story.get("packaging") or {}).get("yt_title"),  # packaging, for tag/title analytics
            "hashtags": story.get("hashtags"),
            "yt_tags": (story.get("packaging") or {}).get("yt_tags"),
            "buffered": stamp,
            "tiktok": None,  # filled in by publish.py when it's posted
        })
        save_history(history)
        images.save_cache(story, imgs)
        checkpoint.finish(story)
        (ROOT / ".built").write_text(stamp)  # tells build.yml to save the image cache
        # Optional AutoClip repurposing runs only when explicitly enabled and never blocks production.
        if CONFIG.get("autoclip", {}).get("enabled"):
            try:
                import autoclip_adapter
                autoclip_adapter.run(story, video, narration.get("words") or [], workdir / "autoclip")
            except Exception as e:  # noqa: BLE001
                log(f"AUTOCLIP: non-fatal integration error ({type(e).__name__}: {str(e)[:240]})")
        log(f"Done: '{story['title']}' is in the buffer.")
        return 0
    except Exception as e:  # noqa: BLE001
        manifest.stage("run", "failed", error=f"{type(e).__name__}: {str(e)[:400]}")
        manifest.finish("failed")
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


def defer_test(workdir: Path, why: str) -> None:
    """A forced cutout test that doesn't fit today's Cloudflare test share: hand its inputs to deferred_test.yml
    (build.yml commits output/*/deferred_test.json to data/), which starts it right after 00:00 UTC."""
    inputs = {"test": "true", "fresh_images": os.environ.get("TEST_FRESH") or "false",
              "render_style": os.environ.get("RENDER_STYLE") or "", "visual_mode": os.environ.get("VISUAL_MODE") or "",
              "inbox_file": os.environ.get("INBOX_FILE") or ""}
    (workdir / "deferred_test.json").write_text(json.dumps({k: v for k, v in inputs.items() if v}, indent=1))
    log(f"Cutout test deferred: {why}. It starts automatically right after 00:00 UTC (deferred_test.yml).")
    try:
        from notify import notify_text
        notify_text("[TEST] Night Files: cutout test deferred",
                    f"{why}. It starts automatically right after 00:00 UTC (8 PM New York).")
    except Exception as e:  # noqa: BLE001
        log(f"Deferral alert not sent ({e})")


if __name__ == "__main__":
    sys.exit(main())
