"""Add Night Files background music as a separate post-render stage.

The visual/narration render produces a complete video first. This module then adds
only the approved soundtrack layer. Default music is an original locally
synthesized ambient bed, so the soundtrack can be changed without rerendering
visuals or narration.
"""
from pathlib import Path

from common import CONFIG, ROOT, log, media_duration, run

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}

def _pick_approved() -> Path | None:
    """Rotate config music_rotation (approved files + "procedural") by the number of videos in history.
    None = the generated ambient bed this time."""
    if str(CONFIG.get("music_policy", "procedural_only")).strip().lower() != "approved_files":
        return None
    approved = set(CONFIG.get("approved_music") or [])
    rotation = [x for x in CONFIG.get("music_rotation") or sorted(approved)
                if x == "procedural" or (x in approved and (ROOT / "assets" / "music" / x).is_file()
                                         and Path(x).suffix.lower() in AUDIO_EXTS)]
    if not rotation:
        return None
    from common import load_history
    pick = rotation[len(load_history()) % len(rotation)]
    return None if pick == "procedural" else ROOT / "assets" / "music" / pick

def _procedural_music(workdir: Path, seconds: float) -> Path:
    out = workdir / "background_music.mp3"
    duration = max(1.0, float(seconds))
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"sine=frequency=110:duration={duration:.2f}",
        "-f", "lavfi", "-i", f"sine=frequency=164.81:duration={duration:.2f}",
        "-f", "lavfi", "-i", f"anoisesrc=color=brown:amplitude=0.018:duration={duration:.2f}",
        "-filter_complex",
        "[0:a]volume=0.045[a];[1:a]volume=0.028[b];"
        "[2:a]lowpass=f=900,volume=0.20[c];"
        "[a][b][c]amix=inputs=3:duration=longest:normalize=0,"
        "lowpass=f=1400,afade=t=in:d=2,afade=t=out:"
        f"st={max(0.1, duration - 2):.2f}:d=2,alimiter=limit=0.85",
        "-ar", "48000", "-ac", "2", "-codec:a", "libmp3lame", "-b:a", "128k", str(out)
    ])
    return out

def add_background_music(video: Path, workdir: Path, story: dict) -> Path:
    """Add the soundtrack after the main render, preserving video frames."""
    total = media_duration(video)
    music = _pick_approved()
    source = "approved_configured_file" if music else "procedural_original"
    if music is None:
        music = _procedural_music(workdir, total)
    mv = CONFIG.get("track_volumes", {}).get(music.name, CONFIG.get("music_volume", 0.14))
    temp = workdir / "final_music.mp4"
    filter_complex = (
        "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[voice][sc];"
        f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{total:.2f},"
        "loudnorm=I=-18:TP=-2,"
        f"volume={mv},afade=t=in:d=1.5,afade=t=out:st={max(0.1,total-2.0):.2f}:d=2.0[music];"
        "[music][sc]sidechaincompress=threshold=0.04:ratio=5:attack=30:release=500[duck];"
        "[voice][duck]amix=inputs=2:normalize=0:duration=first,"
        f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,atrim=0:{total:.2f}[a]"
    )
    run([
        "ffmpeg","-y","-loglevel","error","-i",str(video),
        "-stream_loop","-1","-i",str(music),
        "-filter_complex",filter_complex,
        "-map","0:v:0","-map","[a]","-c:v","copy",
        "-c:a","aac","-b:a","192k","-movflags","+faststart",str(temp)
    ])
    if not temp.exists() or temp.stat().st_size < 5_000_000:
        raise RuntimeError("Background music stage produced no usable final MP4")
    video.unlink(missing_ok=True)
    temp.replace(video)
    story["music_file"] = music.name
    story["music_source"] = source
    story["music_stage"] = "separate_post_render"
    log(f"Background music added separately: {source} ({music.name})")
    return video
