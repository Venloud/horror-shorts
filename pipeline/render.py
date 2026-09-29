"""Renders the final 1080x1920 video with FFmpeg: Ken Burns scenes, crossfades, grade, grain, captions, music."""
import random
import re
import subprocess
from pathlib import Path

from common import CONFIG, ROOT, log, media_duration, run
from captions import font_setup
import ai_motion
import effects

W, H, FPS = 1080, 1920, 30
XFADE = 0.4      # transition length between scenes
MIN_SHOT = 1.2   # shortest a single picture stays on screen (seconds)
TAIL = 3.4       # seconds after the last word (end card lives here)
END_CARD_DELAY = 0.7  # end card appears this long after the last word

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


# Every clip is forced to this exact format before the crossfades: xfade fails on any size / fps / pixel format /
# SAR / timebase mismatch (AI Spaces return all sorts: 480x832, 24 fps, odd SAR, audio tracks).
NORMALIZE = (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},"
             f"fps={FPS},setsar=1,format=yuv420p,settb=AVTB")


def _fit_clip(src: Path, seconds: float, out: Path) -> Path:
    """Fit an AI clip to the shot: fill 1080x1920, stretch up to 1.5x slower if short, then hold the last frame.
    Only the first video stream is used (audio dropped), output is 1080x1920 / 30 fps / yuv420p / SAR 1."""
    have = media_duration(src)
    slow = min(1.5, max(1.0, seconds / max(0.1, have)))
    vf = (f"setpts={slow:.3f}*PTS,{NORMALIZE},tpad=stop_mode=clone:stop_duration={seconds:.2f}")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-map", "0:v:0", "-vf", vf, "-an",
         "-t", f"{seconds:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-r", str(FPS),
         "-pix_fmt", "yuv420p", str(out)])
    return out


def _join(clips: list[Path], seg: list[float], scene_cut: list[bool], out: Path) -> Path:
    """Crossfade all shots into one silent video. Every input is normalized first (see NORMALIZE)."""
    inputs, fc = [], []
    for i, c in enumerate(clips):
        inputs += ["-i", str(c)]
        fc.append(f"[{i}:v]{NORMALIZE}[n{i}]")
    prev = "[n0]"
    for i in range(1, len(clips)):
        offset = sum(seg[:i])
        trans = random.choice(["fadeblack", "fade", "fadeblack"]) if scene_cut[i] else random.choice(["fade", "dissolve"])
        label = f"[x{i}]"
        fc.append(f"{prev}[n{i}]xfade=transition={trans}:duration={XFADE}:offset={offset:.3f}{label}")
        prev = label
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fc),
         "-map", prev, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-r", str(FPS),
         "-pix_fmt", "yuv420p", str(out)])
    return out


def _split_points(words: list[dict], scene: int, s_start: float, s_end: float, n: int) -> list[float]:
    """Where to cut between the n shots of a scene: phrase ends (punctuation) near equal divisions,
    otherwise the nearest word start. Every shot lasts at least MIN_SHOT seconds."""
    sw = [w for w in words if w.get("scene") == scene]
    dur = s_end - s_start
    n = max(1, min(n, int(dur // MIN_SHOT), len(sw) // 2 or 1))
    cuts: list[float] = []
    for k in range(1, n):
        target = s_start + dur * k / n
        prev = cuts[-1] if cuts else s_start
        window = dur / n * 0.35
        ok = lambda t: t - prev >= MIN_SHOT and s_end - t >= MIN_SHOT * (n - k)
        ends = [w["end"] + 0.05 for w in sw[:-1]
                if re.search(r"[.!?,;:\u2026]$", w["word"]) and abs(w["end"] - target) <= window and ok(w["end"] + 0.05)]
        starts = [w["start"] for w in sw[1:] if ok(w["start"])]
        pick = min(ends, key=lambda t: abs(t - target)) if ends else (min(starts, key=lambda t: abs(t - target)) if starts else None)
        if pick is None:
            break
        cuts.append(pick)
    return cuts


def render(story: dict, images: list[list[Path]], narration: dict, ass_path: Path, workdir: Path) -> Path:
    total = narration["duration"] + TAIL
    starts = [0.0] + [st for st, _ in narration["scene_times"][1:]]

    # Build the shot list: each scene is 1 to 4 shots
    shot_imgs, shot_starts, scene_cut = [], [], []
    for i, shots in enumerate(images):
        s_start = starts[i]
        s_end = starts[i + 1] if i + 1 < len(starts) else total
        cuts = _split_points(narration["words"], i, s_start, s_end, len(shots)) if len(shots) > 1 else []
        shot_imgs.append(shots[0]); shot_starts.append(s_start); scene_cut.append(True)
        if 0 < len(cuts) < len(shots) - 1:  # not enough time for every picture: spread the ones we keep
            keep = [round(j * (len(shots) - 1) / len(cuts)) for j in range(len(cuts) + 1)]
            shots = [shots[j] for j in keep]
        for j, cut in enumerate(cuts, start=1):
            shot_imgs.append(shots[j]); shot_starts.append(cut); scene_cut.append(False)
    seg = [shot_starts[k + 1] - shot_starts[k] for k in range(len(shot_starts) - 1)] + [total - shot_starts[-1]]

    # 1) One moving clip per shot (each clip is XFADE longer so crossfades don't eat time)
    motions = list(MOTIONS)
    clips, last = [], None
    depths: dict = {}
    ai_cfg = CONFIG.get("ai_motion", {})
    ai_shots = int(ai_cfg.get("max_shots", 1)) if ai_cfg.get("enabled", True) else 0
    hook_shots = next((j for j in range(1, len(scene_cut)) if scene_cut[j]), len(scene_cut))
    sc0 = (story.get("scenes") or [{}])[0]
    hook_prompts = [sc0.get(k2, "") for k2 in ("image_prompt", "image_prompt_2", "image_prompt_3", "image_prompt_4")]
    for k, (img, s) in enumerate(zip(shot_imgs, seg)):
        length = s + (XFADE if k < len(shot_imgs) - 1 else 0)
        out = workdir / f"clip_{k:02d}.mp4"
        # Real AI animation on the hook (first shots of scene 1), if a free Space is available
        if k < min(ai_shots, hook_shots):
            ai = ai_motion.animate(img, hook_prompts[k] if k < len(hook_prompts) else "", workdir / f"ai_{k:02d}.mp4")
            if ai:
                try:
                    clips.append(_fit_clip(ai, length, out))
                    log(f"Shot {k}: {length:.1f}s AI animated")
                    continue
                except Exception as e:  # noqa: BLE001
                    log(f"Shot {k}: AI clip unusable ({str(e)[:100]})")
        clip = Path(img).with_suffix(".mp4")
        if CONFIG.get("real_media", True) and clip.exists():  # stock video (media.py): real motion, not parallax
            try:
                clips.append(_fit_clip(clip, length, out))
                log(f"Shot {k}: {length:.1f}s stock video")
                continue
            except Exception as e:  # noqa: BLE001
                log(f"Shot {k}: stock video unusable ({str(e)[:100]}), using its still")
        if img not in depths:
            depths[img] = effects.depth_map(img)
        if depths[img] is not None:
            m = random.choice([mm for mm in effects.PARALLAX_MOVES if mm != last]); last = m
            try:
                clips.append(effects.parallax_clip(img, depths[img], length, m, out))
                log(f"Shot {k}: {length:.1f}s 3D {m}")
                continue
            except Exception as e:  # noqa: BLE001
                log(f"Shot {k}: 3D failed ({str(e)[:100]}), using a normal zoom")
        m = random.choice([mm for mm in motions if mm != last]); last = m
        clips.append(_scene_clip(img, length, m, out))
        log(f"Shot {k}: {length:.1f}s {m}")

    # 2) Chain crossfades (every clip normalized to 1080x1920 / 30 fps / yuv420p / SAR 1, audio dropped)
    joined = _join(clips, seg, scene_cut, workdir / "joined.mp4")

    # 3) Final pass: colour grade, grain, vignette, captions, audio mix
    font, fontsdir = font_setup()
    ass_arg = str(ass_path).replace("\\", "/").replace(":", "\\:")
    ass_filter = f"ass='{ass_arg}'" + (f":fontsdir='{fontsdir}'" if fontsdir else "")
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
        # Optional variants: <sound>_echo, <sound>_muffled, <sound>_distant
        variant = ""
        for v in ("_echo", "_muffled", "_distant"):
            if name.endswith(v):
                name, variant = name[: -len(v)], v
        fx = sfx_dir / f"{name}.mp3"
        if name == "none" or si == 0 or not fx.exists() or si >= len(starts):
            continue
        vf = {
            "_echo": "aecho=0.8:0.8:140|290|480:0.45|0.3|0.2,",               # big empty room / hallway
            "_muffled": "lowpass=f=650,volume=1.6,",                            # behind a wall / door / under a blanket
            "_distant": "lowpass=f=1400,aecho=0.8:0.6:260|520:0.3|0.2,volume=0.55,",  # far away
        }.get(variant, "")
        at_ms = int((starts[si] + 0.25) * 1000)
        ins += ["-i", str(fx)]
        achain.append(
            f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"silenceremove=start_periods=1:start_threshold=-45dB,"  # start right on the sound
            f"atrim=0:{fx_len},afade=t=out:st={fx_len - 1.0}:d=1.0,"  # long recordings get cut + faded
            f"loudnorm=I=-20:TP=-3,{vf}volume={fx_vol},adelay={at_ms}|{at_ms}[fx{si}]"
        )
        mix.append(f"[fx{si}]")
        idx += 1
        log(f"Sound effect '{name}{variant}' on scene {si}")
    # Click on the end card's FOLLOW
    click = ROOT / "assets" / "sfx" / "ui_click.mp3"
    if click.exists():
        c_ms = int((narration["duration"] + END_CARD_DELAY + 0.25) * 1000)
        ins += ["-i", str(click)]
        achain.append(
            f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"silenceremove=start_periods=1:start_threshold=-45dB,atrim=0:1.0,"
            f"loudnorm=I=-18:TP=-3,volume={CONFIG.get('click_volume', 0.7)},adelay={c_ms}|{c_ms}[click]"
        )
        mix.append("[click]")
        idx += 1
    achain.append(
        f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=first,"
        f"apad,atrim=0:{total:.2f},loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
    )

    # Video: grade + grain, then mascot intro flash, corner logo, end card, then captions
    end_start = narration["duration"] + END_CARD_DELAY
    base = ("[0:v]eq=saturation=1.0:contrast=1.06:brightness=0.0:gamma=1.08,"
            "colorbalance=bs=0.05:bm=0.03:rh=-0.02,noise=alls=6:allf=t+u,vignette=PI/4.2")
    mascot = ROOT / "assets" / "mascot.png"
    logo = ROOT / "assets" / "mascot_round.png"
    vparts, cur = [], "[vb]"
    vparts.append(f"{base}[vb]")
    # Free "alive" effects: camera shake on the twist, light flicker, drifting fog and dust
    shake = effects.shake_expr(story, starts)
    if shake:
        vparts.append(f"{cur}scale={int(W * 1.04)}:{int(H * 1.04)},crop={W}:{H}:x='{shake[0]}':y='{shake[1]}'[vs]"); cur = "[vs]"
    flick = effects.flicker_expr(story, starts, total)
    if flick:
        vparts.append(f"{cur}eq=brightness='{flick}':eval=frame[vf]"); cur = "[vf]"
    tex = effects.make_textures(workdir)
    if "fog" in tex:
        ins += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.2f}", "-i", str(tex["fog"])]
        vparts.append(f"{cur}[{idx}:v]overlay=x='-mod(t*22,{W})':y=0:shortest=1[vfog]"); cur = "[vfog]"; idx += 1
    if "dust" in tex:
        ins += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.2f}", "-i", str(tex["dust"])]
        vparts.append(f"{cur}[{idx}:v]overlay=x='6*sin(t/3)':y='-mod(t*26,{H})':shortest=1[vdust]"); cur = "[vdust]"; idx += 1
    if CONFIG.get("mascot", True) and mascot.exists() and logo.exists():
        ins += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.2f}", "-i", str(mascot)]
        m_idx = idx; idx += 1
        ins += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.2f}", "-i", str(logo)]
        l_idx = idx; idx += 1
        if CONFIG.get("mascot_intro", False):
            vparts.append(f"[{m_idx}:v]format=rgba,split=2[m1][m2]")
        else:
            vparts.append(f"[{m_idx}:v]format=rgba[m2]")
        # 1) optional intro flash (off by default: the hook image must be on screen from frame one)
        logo_from = 0.0
        if CONFIG.get("mascot_intro", False):
            vparts.append(f"[m1]scale={W}:{W},fade=t=out:st=0.45:d=0.35:alpha=1[intro]")
            vparts.append(f"{cur}[intro]overlay=0:(H-h)/2:enable='lt(t,0.85)'[v1]"); cur = "[v1]"
            logo_from = 0.85
        # 2) small round logo in the top-left corner during the story
        vparts.append(f"[{l_idx}:v]format=rgba,scale=150:150,colorchannelmixer=aa=0.92[logo]")
        vparts.append(f"{cur}[logo]overlay=36:96:enable='between(t,{logo_from:.2f},{end_start:.2f})'[v2]"); cur = "[v2]"
        # 3) end card: darken the last shot, mascot fades in (text comes from the captions file)
        vparts.append(f"{cur}drawbox=x=0:y=0:w=iw:h=ih:color=black@0.72:t=fill:enable='gte(t,{end_start:.2f})'[v3]"); cur = "[v3]"
        vparts.append(f"[m2]scale=640:640,fade=t=in:st={end_start:.2f}:d=0.4:alpha=1[endimg]")
        vparts.append(f"{cur}[endimg]overlay=(W-w)/2:360:enable='gte(t,{end_start:.2f})'[v4]"); cur = "[v4]"
    vparts.append(f"{cur}{ass_filter},fade=t=out:st={total - 0.6:.2f}:d=0.6,format=yuv420p[v]")
    vchain = ";".join(vparts)

    out = workdir / "final.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", *ins,
         "-filter_complex", vchain + ";" + ";".join(achain),
         "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-maxrate", "4500k", "-bufsize", "9000k",
         "-profile:v", "high",
         "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    log(f"Rendered {out.name} ({media_duration(out):.1f}s, {out.stat().st_size / 1e6:.1f} MB)")
    return out


def qa_gate(path: Path, ass_path: Path, narration: dict) -> list[str]:
    """Checks a finished video must pass before it may enter the buffer. Returns the problems (empty = pass)."""
    problems = []
    lo, hi = CONFIG.get("target_seconds", [50, 60])
    dur = media_duration(path)
    if not lo <= dur <= hi + TAIL + 0.5:  # narration target + the end-card tail
        problems.append(f"duration {dur:.1f}s (want {lo}-{hi + TAIL + 0.5:.1f}s)")
    streams = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                   "-of", "csv=p=0", str(path)])
    if f"{W},{H}" not in streams:
        problems.append(f"resolution {streams.strip()!r} (want {W}x{H})")
    if "audio" not in streams:
        problems.append("no audio stream")
    else:
        p = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-map", "0:a:0",
                            "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
        m = re.findall(r"I:\s+(-?\d+(?:\.\d+)?) LUFS", p.stderr)
        lufs = float(m[-1]) if m else None
        if lufs is None or not -18 <= lufs <= -12:
            problems.append(f"loudness {lufs} LUFS (want -18..-12)")
    # Captions: the render always burns in this .ass file; check it really has the word captions in it.
    cap_lines = sum(1 for ln in Path(ass_path).read_text(encoding="utf-8").splitlines()
                    if ln.startswith("Dialogue:") and ",Cap," in ln) if Path(ass_path).exists() else 0
    n_words = len(narration.get("words") or [])
    if n_words and cap_lines < 0.8 * n_words:
        problems.append(f"captions: {cap_lines} caption lines for {n_words} words")
    size = path.stat().st_size
    if not 5_000_000 < size < 64_000_000:
        problems.append(f"file size {size / 1e6:.1f} MB (want 5-64 MB)")
    log("QA gate: " + ("passed" if not problems else "FAILED: " + "; ".join(problems))
        + f" ({dur:.1f}s, {size / 1e6:.1f} MB)")
    return problems


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
