"""Renders the final 1080x1920 video with FFmpeg: Ken Burns scenes, crossfades, grade, grain, captions, music."""
import random
from pathlib import Path

from common import CONFIG, ROOT, log, media_duration, run
from captions import font_setup

W, H, FPS = 1080, 1920, 30
XFADE = 0.4      # transition length between scenes
TAIL = 1.8       # seconds of picture/music after the last word

MOTIONS = {
    "zoom_in":  ("1.0+0.14*on/{D}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "zoom_out": ("1.14-0.14*on/{D}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "pan_up":   ("1.12", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(1-on/{D})"),
    "pan_down": ("1.12", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*on/{D}"),
}


def _pick_file(folder: Path) -> Path | None:
    files = [p for p in folder.glob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg", ".flac"}]
    return random.choice(files) if files else None


def _scene_clip(img: Path, seconds: float, motion: str, out: Path) -> Path:
    frames = max(2, int(round(seconds * FPS)))
    z, x, y = (s.format(D=frames) for s in MOTIONS[motion])
    vf = (
        f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={W * 2}:{H * 2},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},"
        f"setsar=1,format=yuv420p"
    )
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(img), "-vf", vf,
         "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
         "-r", str(FPS), str(out)])
    return out


def render(story: dict, images: list[Path], narration: dict, ass_path: Path, workdir: Path) -> Path:
    total = narration["duration"] + TAIL
    starts = [0.0] + [st for st, _ in narration["scene_times"][1:]]
    seg = [starts[i + 1] - starts[i] for i in range(len(starts) - 1)] + [total - starts[-1]]

    # 1) One moving clip per scene (each clip is XFADE longer so crossfades don't eat time)
    motions = list(MOTIONS)
    clips, last = [], None
    for i, (img, s) in enumerate(zip(images, seg)):
        m = random.choice([mm for mm in motions if mm != last]); last = m
        length = s + (XFADE if i < len(images) - 1 else 0)
        clips.append(_scene_clip(img, length, m, workdir / f"clip_{i:02d}.mp4"))
        log(f"Clip {i}: {length:.1f}s {m}")

    # 2) Chain crossfades
    inputs, fc, prev = [], [], "[0:v]"
    for c in clips:
        inputs += ["-i", str(c)]
    for i in range(1, len(clips)):
        offset = sum(seg[:i])
        trans = random.choice(["fadeblack", "fade", "fadeblack", "dissolve"])
        label = f"[x{i}]"
        fc.append(f"{prev}[{i}:v]xfade=transition={trans}:duration={XFADE}:offset={offset:.3f}{label}")
        prev = label
    joined = workdir / "joined.mp4"
    if len(clips) == 1:
        joined = clips[0]
    else:
        run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fc),
             "-map", prev, "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-r", str(FPS), str(joined)])

    # 3) Final pass: colour grade, grain, vignette, captions, audio mix
    font, fontsdir = font_setup()
    ass_arg = str(ass_path).replace("\\", "/").replace(":", "\\:")
    ass_filter = f"ass='{ass_arg}'" + (f":fontsdir='{fontsdir}'" if fontsdir else "")
    vchain = (
        f"[0:v]eq=saturation=1.0:contrast=1.06:brightness=0.0:gamma=1.08,"
        f"colorbalance=bs=0.05:bm=0.03:rh=-0.02,"
        f"noise=alls=6:allf=t+u,vignette=PI/4.2,{ass_filter},"
        f"fade=t=out:st={total - 1.0:.2f}:d=1.0,format=yuv420p[v]"
    )

    music = _pick_file(ROOT / "assets" / "music")
    story["music_file"] = music.name if music else None
    sting = _pick_file(ROOT / "assets" / "stings")
    ins = ["-i", str(joined), "-i", str(narration["path"])]
    achain = ["[1:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[narr][key]"]
    mix = ["[narr]"]
    idx = 2
    if music:
        ins += ["-stream_loop", "-1", "-i", str(music)]
        mv = CONFIG.get("track_volumes", {}).get(music.name, CONFIG.get("music_volume", 0.22))
        achain.append(
            f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{total:.2f},"
            f"loudnorm=I=-18:TP=-2,"  # even out loud/quiet songs first
            f"volume={mv},afade=t=in:d=1.5,afade=t=out:st={total - 2.0:.2f}:d=2.0[mus]"
        )
        achain.append("[mus][key]sidechaincompress=threshold=0.04:ratio=5:attack=30:release=500[duck]")
        mix.append("[duck]")
        idx += 1
    else:
        achain.append("[key]anullsink")
    if sting:
        twist = int(story.get("twist_scene", len(starts) - 2))
        at_ms = int(max(0.0, starts[min(twist, len(starts) - 1)] - 0.15) * 1000)
        ins += ["-i", str(sting)]
        sv = CONFIG.get("sting_volume", 0.55)
        achain.append(
            f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={sv},"
            f"adelay={at_ms}|{at_ms}[st]"
        )
        mix.append("[st]")
        idx += 1
    # Scene sound effects (footsteps, knocking, door creak...) from assets/sfx/<name>.mp3
    sfx_dir = ROOT / "assets" / "sfx"
    fx_vol = CONFIG.get("sfx_volume", 0.6)
    fx_len = float(CONFIG.get("sfx_max_seconds", 4.5))
    for si, scene in enumerate(story.get("scenes", [])):
        name = (scene.get("sfx") or "none").strip().lower().replace(" ", "_")
        fx = sfx_dir / f"{name}.mp3"
        if name == "none" or si == 0 or not fx.exists() or si >= len(starts):
            continue
        at_ms = int((starts[si] + 0.25) * 1000)
        ins += ["-i", str(fx)]
        achain.append(
            f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"silenceremove=start_periods=1:start_threshold=-45dB,"  # start right on the sound
            f"atrim=0:{fx_len},afade=t=out:st={fx_len - 1.0}:d=1.0,"  # long recordings get cut + faded
            f"loudnorm=I=-20:TP=-3,volume={fx_vol},adelay={at_ms}|{at_ms}[fx{si}]"
        )
        mix.append(f"[fx{si}]")
        idx += 1
        log(f"Sound effect '{name}' on scene {si}")
    achain.append(
        f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=first,"
        f"apad,atrim=0:{total:.2f},loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
    )

    out = workdir / "final.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", *ins,
         "-filter_complex", vchain + ";" + ";".join(achain),
         "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high",
         "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    log(f"Rendered {out.name} ({media_duration(out):.1f}s, {out.stat().st_size / 1e6:.1f} MB)")
    return out


def quality_check(path: Path) -> None:
    dur = media_duration(path)
    size = path.stat().st_size
    streams = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                   "-of", "csv=p=0", str(path)])
    problems = []
    if not 15 <= dur <= 180:
        problems.append(f"duration {dur:.1f}s")
    if size < 500_000 or size > 250_000_000:
        problems.append(f"file size {size}")
    if "audio" not in streams:
        problems.append("no audio")
    if f"{W},{H}" not in streams:
        problems.append(f"resolution {streams!r}")
    if problems:
        raise RuntimeError("Quality check failed: " + ", ".join(problems))
    log("Quality check passed")
