"""One-second monochrome story cover for Night Files, inserted at the final MP4 stage.

Only horror-shorts uses this module. The rendered movie and narration keep their
original duration. A separate image is saved for thumbnail selection; automatic
platform thumbnail choice cannot be guaranteed by a first-frame image.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import random
import subprocess
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from common import log, media_duration, run

COVER_SECONDS = 1.0
WIDTH, HEIGHT, FPS = 1080, 1920, 30


def cover_prompt(story: dict) -> str:
    """Build a photoreal visual concept from the strongest documented opening beat."""
    scenes = story.get("scenes") or []
    first = scenes[0] if scenes and isinstance(scenes[0], dict) else {}
    hook = " ".join(str(first.get("narration") or story.get("premise") or story.get("title") or "").split())[:340]
    shot = " ".join(str(first.get("image_prompt") or "").split())[:340]
    title = str(story.get("title") or "").strip()[:140]
    setting = str(story.get("setting") or "").strip()[:120]
    return (
        "Vertical 9:16 PHOTO-REALISTIC black-and-white cinematic still, high-end 35mm "
        "documentary thriller photography. ONE strong central subject or meaningful "
        "visual clue. Rich true grayscale, defined highlights, deep detailed shadows, "
        "crisp focal subject, realistic surfaces and period-accurate environment. "
        "Striking high-contrast composition immediately readable as a small mobile "
        "thumbnail. Restrained atmospheric dread rather than exaggerated horror. "
        "Represent the following story's opening mystery without inventing evidence "
        "or depicting a real historical reconstruction as an authentic archive photo. "
        "No text, captions, logos, watermarks, borders, panels, split frames or gore. "
        f"Story: {title}. Setting: {setting}. Opening: {hook}. Main visual: {shot}."
    )[:1950]


def _choose_existing(img_dir: Path, video: Path, workdir: Path) -> tuple[Path, str]:
    """Use the actual first story picture if generation cannot run, never other cases."""
    for glob_pattern in ("scene_00a.png", "scene_00b.png", "scene_00*.png", "scene_*.png", "*.png"):
        for p in sorted(img_dir.glob(glob_pattern)) if img_dir.is_dir() else ():
            if ".rejected" in p.name or ".qa." in p.name:
                continue
            try:
                with Image.open(p) as image:
                    image.verify()
                return p, "story_image"
            except (OSError, ValueError):
                continue
    # This fallback remains inside the already-rendered, provenance-gated story.
    destination = workdir / "cover_fallback_frame.png"
    run(["ffmpeg", "-y", "-v", "error", "-ss", "1.2", "-i", str(video),
         "-frames:v", "1", str(destination)])
    if not destination.is_file():
        raise RuntimeError("Could not extract a fallback cover from this video's real frames")
    return destination, "rendered_video_frame"


def make_cover(story: dict, workdir: Path, img_dir: Path, video: Path) -> dict:
    """Prefer one existing story-specific cover cache, then free Workers AI, then a real story frame.

    Always produce an actual grayscale 1080x1920 image, or fail before queueing.
    No paid providers or new secret names are involved.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / "cover_main.png"
    thumb = workdir / "cover_thumb.jpg"
    metadata = workdir / "cover_meta.json"
    story_id = str(story.get("story_id") or "")
    if out.exists() and thumb.exists() and metadata.exists():
        try:
            saved = json.loads(metadata.read_text(encoding="utf-8"))
            if saved.get("story_id") == story_id and saved.get("sha256") == hashlib.sha256(out.read_bytes()).hexdigest():
                with Image.open(out) as cached:
                    if cached.size == (WIDTH, HEIGHT):
                        return saved
        except (ValueError, OSError, KeyError):
            pass

    prompt = cover_prompt(story)
    source, source_file = "", ""
    base = None
    if os.environ.get("CLOUDFLARE_API_TOKEN") and os.environ.get("CLOUDFLARE_ACCOUNT_ID"):
        try:
            import images
            if not images._STATE.get("cf_out"):
                raw = images._cloudflare(prompt, random.SystemRandom().randrange(1, 2_147_483_647))
                with Image.open(io.BytesIO(raw)) as im:
                    base = im.convert("RGB").copy()
                source = "cloudflare_workers_ai"
        except Exception as exc:
            log(f"Night Files cover image generation unavailable ({type(exc).__name__}: {str(exc)[:130]}); "
                "using this story's own picture")
    if base is None:
        original, source = _choose_existing(img_dir, video, workdir)
        with Image.open(original) as image:
            base = image.convert("RGB").copy()
        source_file = original.name

    # Photographic treatment, even if the original scene was in color.
    fitted = ImageOps.fit(base, (WIDTH, HEIGHT), method=Image.Resampling.LANCZOS, centering=(0.5, 0.47))
    monochrome = ImageOps.autocontrast(ImageOps.grayscale(fitted), cutoff=1)
    monochrome = ImageEnhance.Contrast(monochrome).enhance(1.16)
    monochrome = monochrome.filter(ImageFilter.UnsharpMask(radius=1.4, percent=135, threshold=3))
    monochrome.convert("RGB").save(out, "PNG")
    monochrome.save(thumb, "JPEG", quality=92, optimize=True)

    result = {
        "story_id": story_id,
        "role": "night_files_one_second_opening_cover",
        "duration_seconds": COVER_SECONDS,
        "cover_image": out.name,
        "thumbnail_candidate": thumb.name,
        "source": source,
        "source_file": source_file or None,
        "generated": source == "cloudflare_workers_ai",
        "monochrome": True,
        "realistic_style_requested": True,
        "illustration_not_archival_evidence": bool(story.get("true_story")),
        "hook": " ".join(str((story.get("scenes") or [{}])[0].get("narration") or "").split())[:280],
        "prompt": prompt if source == "cloudflare_workers_ai" else None,
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
    }
    metadata.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"Night Files cover ready: {out.name}, source={source}, first {COVER_SECONDS:.1f}s")
    return result


def insert_cover(video: Path, workdir: Path, cover: Path) -> Path:
    """Hard-cut at exactly t=1 second, preserving the original audio and total runtime.

    The first 30 frames display the cover. The rest of the existing edit is unchanged
    in time, keeping captions and sound synchronized. Do not concatenate another
    second because the 61-68 second production gate must still pass.
    """
    if not cover.is_file():
        raise RuntimeError("Missing Night Files cover image")
    duration = media_duration(video)
    if duration <= COVER_SECONDS + 0.2:
        raise RuntimeError("Night Files video is too short for the 1-second cover")
    stage = workdir / "cover_stage.mp4"
    # Original video is the timeline source; audio is copied bit for bit from it.
    # overlay expression is 1 only on t < 1s, so the boundary is a hard cut.
    run([
        "ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(video),
        "-loop", "1", "-framerate", str(FPS), "-i", str(cover),
        "-filter_complex",
        "[1:v]format=yuv420p[hero];[0:v][hero]overlay=0:0:enable='lt(t,1)':"
        "eof_action=pass:format=auto,format=yuv420p[v]",
        "-map", "[v]", "-map", "0:a:0", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "copy", "-t", f"{duration:.3f}", "-movflags", "+faststart",
        str(stage),
    ])
    if not stage.is_file() or stage.stat().st_size < 1_024:
        raise RuntimeError("Night Files one-second cover output was not encoded")
    after = media_duration(stage)
    if abs(after - duration) > 0.15:
        raise RuntimeError(f"Night Files cover changed movie length: {duration:.3f} -> {after:.3f}s")
    # Atomic swap only after the new video has passed the basic integrity checks.
    streams = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                   "-of", "csv=p=0", str(stage)])
    if f"{WIDTH},{HEIGHT}" not in streams or "audio" not in streams:
        raise RuntimeError("Covered movie is missing the vertical video or audio")
    stage.replace(video)
    log("Night Files mandatory first-second cover applied, hard cut at 1.0s, audio unchanged")
    return video
