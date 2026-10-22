#!/usr/bin/env python3
"""Manual, offline Night Files visual-direction preview.

Exercises the production Renderer and Noir motion templates with ORIGINAL approved
character assets. Writes a self-contained MP4 + shot list + contact sheet; never
imports main.py, publish.py, buffer code, Cloudflare, or any social API.

The sample narration uses espeak-ng solely for voice/timing PLACEHOLDER.
Do not judge production voice quality by this technical preview. Text/visuals
are original fiction and do not make claims about a real historical case.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import wave
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import explainer  # noqa: E402

OUTPUT = ROOT / "output" / "manual-cinematic-preview"
SAMPLE = (
    "A photograph was found inside a locked room.",
    "Nobody could explain the shadow standing behind the camera.",
    "At midnight, the clock stopped, and the photograph changed.",
    "Now there were two shadows. But only one person had entered."
)


def run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr[-1700:]}")
    return result.stdout.strip()


def synthesize_voice() -> tuple[dict, float]:
    """Scene-aligned espeak placeholder audio, fully offline."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    words = []
    spans = []
    payloads = []
    rate = None
    total_frames = 0
    for i, text in enumerate(SAMPLE):
        p = OUTPUT / f"temporary_voice_scene_{i}.wav"
        run(["espeak-ng", "-v", "en-us", "-s", "149", "-p", "46", "-w", str(p), text])
        with wave.open(str(p), "rb") as stream:
            assert stream.getnchannels() == 1 and stream.getsampwidth() == 2, "espeak WAV format"
            if rate is None:
                rate = stream.getframerate()
            assert stream.getframerate() == rate
            frames = stream.readframes(stream.getnframes())
        p.unlink(missing_ok=True)
        begin = total_frames / rate
        pad = int(.31 * rate)
        count = len(frames) // 2
        duration = count / rate
        group = text.split()
        mass = max(1, sum(max(1, len(w.strip(",."))) for w in group))
        cursor = begin
        for w in group:
            portion = duration * max(1, len(w.strip(",."))) / mass
            words.append({"word": w, "start": round(cursor, 3), "end": round(cursor+portion, 3), "scene": i})
            cursor += portion
        total_frames += count + pad
        spans.append((round(begin, 3), round(total_frames / rate, 3)))
        payloads.append(frames + bytes(2*pad))
    dst = OUTPUT / "preview_voice_placeholder.wav"
    with wave.open(str(dst), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(b"".join(payloads))
    duration = total_frames / rate
    return {"path": str(dst), "words": words, "scene_times": spans,
            "duration": duration}, duration


def scene_shot(expression: str, frame: str, prop: str = "none", label: str = "") -> dict:
    return {"type": "scene", "location": "blank studio", "insert": "",
            "primary": "you", "action": "standing", "expression": expression,
            "view": "front", "facing": "right", "secondary": "",
            "action2": "standing", "shot_type": frame, "motion": "none",
            "prop": prop, "text_mode": "evidence" if label else "none",
            "text": label, "accent": ""}


def segments_for_voice(narration: dict) -> list[dict]:
    spans = narration["scene_times"]
    segments: list[dict] = []
    storyboard = (
        [(0.00, {"type": "title", "text": "THE LAST PHOTOGRAPH", "accent": "LAST"}),
         (0.39, scene_shot("neutral", "medium")),
         (0.71, {"type": "graphic", "template": "impact", "fields": {
             "text": "A LOCKED ROOM", "accent": "LOCKED"}})],
        [(0.00, scene_shot("suspicious", "close")),
         (0.46, {"type": "graphic", "template": "evidence", "fields": {
             "kicker": "THE EVIDENCE", "text": "A SECOND SHADOW", "accent": "SHADOW",
             "note": "INSIDE THE PHOTOGRAPH"}})],
        [(0.00, scene_shot("worried", "close")),
         (0.53, {"type": "graphic", "template": "impact", "fields": {
             "text": "MIDNIGHT", "accent": "MIDNIGHT"}})],
        [(0.00, scene_shot("serious", "close")),
         (0.46, {"type": "graphic", "template": "closing", "fields": {
             "kicker": "YOUR CALL", "text": "WHO WAS THE SECOND SHADOW?",
             "accent": "SECOND"}})],
    )
    for i, ((start, end), beats) in enumerate(zip(spans, storyboard)):
        duration = end - start
        starts = [start + ratio * duration for ratio, _ in beats] + [end]
        for j, (_, shot) in enumerate(beats):
            segments.append({"start": starts[j], "end": starts[j+1],
                             "scene": i, "shot": shot})
    return segments


def main() -> None:
    import sprites
    reg = sprites.approved_registry()
    expected = {"M01", "M05", "F02", "F04", "F08"}
    present = {r["id"] for r in reg.get("approved", []) if sprites._approved_path(r["id"])}
    if not expected <= present:
        raise RuntimeError(f"Missing original approved images: {sorted(expected-present)}")

    narration, total = synthesize_voice()
    story = {"title": "THE LAST PHOTOGRAPH", "mode": "fiction", "true_story": False,
             "scenes": [{"narration": text} for text in SAMPLE]}
    segs = segments_for_voice(narration)
    p = {"cast": {}, "locations": [{"name": "blank studio"}],
         "inserts": [], "scenes": [{"shots": [s["shot"] for s in segs if s["scene"] == i]}
                                   for i in range(len(SAMPLE))]}
    renderer = explainer.Renderer(story, narration, p, {"plates": {}, "inserts": {}}, segs)

    # 24fps is a preview quality setting, NOT an alteration to production rendering.
    fps = 24
    final = OUTPUT / "night-files-cinematic-preview.mp4"
    video = OUTPUT / "temporary-video-only.mp4"
    encoder = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", "1080x1920", "-r", str(fps), "-i", "-",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video)], stdin=subprocess.PIPE)
    samples = []
    try:
        for frame_index in range(math.ceil(total * fps)):
            t = frame_index / fps
            im = renderer.frame_at(t, total + 20).convert("RGB")
            encoder.stdin.write(im.tobytes())
            if frame_index % (fps * 2) == 0:
                samples.append(im.copy())
                print(f"frame {frame_index}/{math.ceil(total*fps)}", flush=True)
    finally:
        encoder.stdin.close()
        encoder.wait()
    if encoder.returncode or not video.is_file() or video.stat().st_size < 10000:
        raise RuntimeError(f"FFmpeg preview encode failed, exit {encoder.returncode}")

    # This is a timing guide voice, not the production Kokoro narrator.
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", narration["path"],
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
         "-movflags", "+faststart", str(final)])
    video.unlink(missing_ok=True)

    tile_w, tile_h, columns = 216, 384, 5
    board = Image.new("RGB", (columns * tile_w, 2 * tile_h+60), "#23252b")
    d = ImageDraw.Draw(board)
    for k, im in enumerate(samples[:10]):
        mini = im.resize((tile_w, tile_h), Image.Resampling.LANCZOS)
        x, y = (k % columns) * tile_w, (k // columns) * tile_h
        board.paste(mini, (x, y))
        d.text((x+10, y+tile_h-26), f"{2*k}s", fill="white")
    board.save(OUTPUT / "contact-sheet.jpg", quality=90)
    info = {"purpose": "isolated cinematic style review, NOT production",
            "status": "preview_generated", "fictional_sample": True,
            "duration_seconds": round(total, 2), "fps": fps, "resolution": [1080, 1920],
            "original_assets": sorted(expected),
            "voice": "espeak-ng placeholder, NOT production narration quality",
            "cloudflare_calls": 0, "posting": False, "buffer_changes": False,
            "shots": segs}
    (OUTPUT / "shot-list.json").write_text(json.dumps(info, indent=2))
    print(f"READY {final} ({final.stat().st_size} bytes) {total:.1f}s")


if __name__ == "__main__":
    main()
