"""Renders the final 1080x1920 video with FFmpeg: Ken Burns scenes, crossfades, grade, grain, captions, music."""
import json
import random
import re
import subprocess
from pathlib import Path

from common import CONFIG, ROOT, log, media_duration, run
from captions import font_setup
import ai_motion
import cutout
import effects

W, H, FPS = 1080, 1920, 30
XFADE = 0.4      # transition length between scenes
MIN_SHOT = 1.2   # shortest a single picture stays on screen (seconds)
TAIL = 3.4       # seconds after the last word (end card lives here)
# config target_seconds = the FINISHED VIDEO's length (TikTok Creator Rewards needs > 60 s): [61, 68]. The narration
# gets that minus the end-card tail; a narration that is still too short gets a longer end card, never a video
# under the minimum.


def narration_window() -> tuple[float, float]:
    lo, hi = CONFIG.get("target_seconds", [61, 68])
    return lo - TAIL, hi - TAIL


def tail_for(narration_seconds: float) -> float:
    """End-card tail: TAIL, or longer if the narration alone would leave the video under the minimum length."""
    lo = CONFIG.get("target_seconds", [61, 68])[0]
    return max(TAIL, lo + 0.3 - narration_seconds)
END_CARD_DELAY = 0.7  # end card appears this long after the last word

MOTIONS = {
    "zoom_in":  ("1.0+0.14*on/{D}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "zoom_out": ("1.14-0.14*on/{D}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "pan_up":   ("1.12", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(1-on/{D})"),
    "pan_down": ("1.12", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*on/{D}"),
}


VISUAL_MODES = ("classic", "fast", "analog")
# fast mode: crops of the same picture (x, y, size as fractions of the 9:16 frame; square fractions keep 9:16)
FRAMINGS = {"full": (0.0, 0.0, 1.0), "punch": (0.14, 0.14, 0.72), "detail_top": (0.2, 0.06, 0.6),
            "detail_low": (0.2, 0.34, 0.6), "left": (0.0, 0.18, 0.66), "right": (0.34, 0.18, 0.66)}
FAST_SHOT = (1.5, 2.0)  # fast mode: a new framing every 1.5-2 s
KEY_WORDS = {"never", "gone", "vanished", "missing", "dead", "died", "nobody", "no", "one", "only", "last", "first",
             "alone", "still", "everyone", "every", "nothing", "found", "disappeared", "locked", "empty", "real", "true"}


def pick_visual_mode(history: list[dict]) -> str:
    """A/B test: rotate classic -> fast -> analog per buffered video (flag visual_ab; env VISUAL_MODE overrides)."""
    import os
    forced = (os.environ.get("VISUAL_MODE") or "").strip().lower()
    if forced in VISUAL_MODES:
        return forced
    if not CONFIG.get("visual_ab", True):
        return "classic"
    modes = [m for m in CONFIG.get("visual_modes", list(VISUAL_MODES)) if m in VISUAL_MODES] or ["classic"]
    return modes[sum(1 for h in history if h.get("buffered")) % len(modes)]


def _pick_file(folder: Path) -> Path | None:
    files = [p for p in folder.glob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg", ".flac"}]
    return random.choice(files) if files else None


def _scene_clip(img: Path, seconds: float, motion: str, out: Path, framing: str = "full") -> Path:
    frames = max(2, int(round(seconds * FPS)))
    z, x, y = (s.format(D=frames) for s in MOTIONS[motion])
    fx, fy, fs = FRAMINGS.get(framing, FRAMINGS["full"])
    box = "" if framing == "full" else (f"crop={int(W * 2 * fs)}:{int(H * 2 * fs)}:{int(W * 2 * fx)}:{int(H * 2 * fy)},"
                                        f"scale={W * 2}:{H * 2}:flags=lanczos,")
    vf = (
        f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={W * 2}:{H * 2},{box}"
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


AI_MIN_WIDTH = 400  # narrower AI clips look like mush at 1080x1920: use the parallax still instead
AI_MAX_SECONDS = 2.0
AI_FADE = 0.5


def _ai_into_still(ai: Path, img: Path, depth, length: float, out: Path, move: str) -> Path | None:
    """The hook's AI clip, then the ORIGINAL high-res still it was made from: max ~2 s of the clip (upscaled with
    lanczos + a light sharpen; the final pass puts the same grain on it as on every still), a 0.5 s crossfade into
    the still, which carries on with the normal parallax. None = clip too small / broken: caller uses parallax."""
    width = ai_motion._width(ai)
    if width < AI_MIN_WIDTH:
        log(f"AI clip is only {width} px wide (< {AI_MIN_WIDTH}): using the 3D still instead")
        return None
    have = media_duration(ai)
    a = min(AI_MAX_SECONDS, have, max(0.8, length - AI_FADE - 0.3))
    up = out.with_name(out.stem + "_ai.mp4")
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},"
          f"unsharp=5:5:0.6:5:5:0.0,setsar=1,fps={FPS},format=yuv420p")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(ai), "-map", "0:v:0", "-an", "-t", f"{a:.3f}", "-vf", vf,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", str(up)])
    rest = length - a + AI_FADE  # the still overlaps the clip by the crossfade
    if rest < AI_FADE + 0.2:  # shot too short for a handover: just the clip, held on its last frame
        return _fit_clip(up, length, out)
    still = out.with_name(out.stem + "_still.mp4")
    if depth is not None:
        effects.parallax_clip(img, depth, rest, move, still)
    else:
        _scene_clip(img, rest, next(iter(MOTIONS)), still)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(up), "-i", str(still), "-filter_complex",
         f"[0:v]{NORMALIZE}[a];[1:v]{NORMALIZE}[b];"
         f"[a][b]xfade=transition=fade:duration={AI_FADE}:offset={a - AI_FADE:.3f},format=yuv420p[v]",
         "-map", "[v]", "-an", "-t", f"{length:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
         "-r", str(FPS), str(out)])
    up.unlink(missing_ok=True)
    still.unlink(missing_ok=True)
    return out


def _transitions(scene_cut: list[bool], mode: str) -> list[tuple[str, float]]:
    """(xfade transition, duration) into each shot (index 0 unused). classic/analog: soft crossfades.
    fast: hard cuts inside a scene (one frame), a whip-pan or a white flash at scene changes."""
    out = [("fade", 0.0)]
    for i in range(1, len(scene_cut)):
        if mode == "fast":
            out.append((random.choice(["slideleft", "slideup", "fadewhite"]), 0.2) if scene_cut[i] else ("fade", 1 / FPS))
        else:
            out.append((random.choice(["fadeblack", "fade", "fadeblack"]) if scene_cut[i]
                        else random.choice(["fade", "dissolve"]), XFADE))
    return out


def _remotion_join(clips: list[Path], scene_cut: list[bool], out: Path,
                    trans: list[tuple[str, float]]) -> Path:
    """Join silent shot clips with Remotion. FFmpeg remains the production fallback if Remotion fails."""
    import shutil
    import uuid

    project = ROOT / "remotion"
    if not (project / "package.json").exists():
        raise RuntimeError("Remotion project is missing")
    if not clips:
        raise RuntimeError("no clips to join")

    frames = [_frame_count(c) for c in clips]
    timeline = []
    acc = frames[0]
    timeline.append({
        "source": str(clips[0].resolve()),
        "file": "clip_000.mp4",
        "startFrame": 0,
        "durationFrames": frames[0],
        "fadeInFrames": 0,
        "fadeOutFrames": 0,
    })
    for i in range(1, len(clips)):
        _kind, seconds = trans[i]
        fade = max(0, min(int(round(seconds * FPS)), frames[i] - 1, acc - 1))
        start = acc - fade
        timeline.append({
            "source": str(clips[i].resolve()),
            "file": f"clip_{i:03d}.mp4",
            "startFrame": start,
            "durationFrames": frames[i],
            "fadeInFrames": fade,
            "fadeOutFrames": fade,
        })
        acc += frames[i] - fade

    job_id = f"join_{uuid.uuid4().hex[:12]}"
    manifest = project / "public" / f"{job_id}.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "clips": timeline,
        "totalFrames": acc,
        "fps": FPS,
        "output": str(out.resolve()),
    }), encoding="utf-8")

    try:
        subprocess.run(
            ["npm", "run", "render:join", "--", str(manifest)],
            cwd=project,
            check=True,
            timeout=900,
        )
        if not out.exists() or out.stat().st_size < 100_000:
            raise RuntimeError("Remotion returned without a usable joined video")
        got = media_duration(out)
        want = acc / FPS
        if got < want - 0.5:
            raise RuntimeError(f"Remotion joined video is {got:.1f}s but expected about {want:.1f}s")
        log(f"Remotion joined {len(clips)} shots into {got:.1f}s")
        return out
    finally:
        manifest.unlink(missing_ok=True)
        shutil.rmtree(project / "public" / "night-files-join", ignore_errors=True)


def _join(clips: list[Path], seg: list[float], scene_cut: list[bool], out: Path,
          trans: list[tuple[str, float]] | None = None) -> Path:
    """Join shots with Remotion first, with the mature FFmpeg xfade path as a production fallback."""
    trans = trans or _transitions(scene_cut, "classic")
    if CONFIG.get("remotion_join", True):
        try:
            return _remotion_join(clips, scene_cut, out, trans)
        except Exception as e:  # noqa: BLE001
            log(f"Remotion join failed ({type(e).__name__}: {str(e)[:240]}), falling back to FFmpeg")

    inputs, fc = [], []
    for i, c in enumerate(clips):
        inputs += ["-i", str(c)]
        fc.append(f"[{i}:v]{NORMALIZE}[n{i}]")
    frames = [_frame_count(c) for c in clips]
    prev, acc = "[n0]", frames[0]
    for i in range(1, len(clips)):
        kind, dur = trans[i]
        d = max(1, min(int(round(dur * FPS)), frames[i] - 1, acc - 1))
        offset = acc - d
        label = f"[x{i}]"
        fc.append(f"{prev}[n{i}]xfade=transition={kind}:duration={d / FPS:.6f}:offset={offset / FPS:.6f}{label}")
        prev, acc = label, acc + frames[i] - d
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fc),
         "-map", prev, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-r", str(FPS),
         "-pix_fmt", "yuv420p", str(out)])
    want, got = acc / FPS, media_duration(out)
    if got < want - 0.5:
        raise RuntimeError(f"joined video is {got:.1f}s but the shots add up to {want:.1f}s: xfade chain broke")
    return out


def _frame_count(path: Path) -> int:
    """Exact number of video frames in a clip (counted packets; falls back to duration x FPS)."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                              "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return max(2, int(out.split()[0]))
    except Exception:  # noqa: BLE001
        return max(2, int(round(media_duration(path) * FPS)))


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


def _next_fast_cut(t: float, end: float, words: list[dict]) -> float | None:
    """fast mode: the next cut 1.5-2 s after t, on punctuation, else on a key word, else at ~1.75 s."""
    lo, hi = t + FAST_SHOT[0], t + FAST_SHOT[1]
    if end - lo < 1.0:
        return None
    punct = [w["end"] + 0.05 for w in words
             if lo <= w["end"] + 0.05 <= hi and re.search(r"[.!?,;:\u2026]$", w["word"])]
    keyw = [w["start"] for w in words if lo <= w["start"] <= hi and _is_key(w["word"])]
    pick = min(punct) if punct else (min(keyw) if keyw else lo + 0.25)
    return pick if end - pick >= 1.0 else None


def _is_key(word: str) -> bool:
    w = word.lower().strip(".,!?;:\"'\u2026")
    return w in KEY_WORDS or any(ch.isdigit() for ch in w)


def _fast_shots(shot_imgs, shot_starts, scene_cut, shot_scene, seg, words):
    """fast mode: split every picture into 1.5-2 s shots with different framings of the same image (never the
    same framing twice in a row). Stock video shots stay whole (they already move)."""
    imgs, starts, cuts, scenes, framing = [], [], [], [], []
    for img, st, cut, sc, dur in zip(shot_imgs, shot_starts, scene_cut, shot_scene, seg):
        t, prev, first = st, None, True
        while True:
            f = "full" if first else random.choice([k for k in FRAMINGS if k not in (prev, "full")])
            imgs.append(img); starts.append(t); cuts.append(cut if first else False); scenes.append(sc)
            framing.append(f)
            prev, first = f, False
            nxt = None if Path(img).with_suffix(".mp4").exists() else _next_fast_cut(t, st + dur, words)
            if nxt is None:
                break
            t = nxt
    return imgs, starts, cuts, scenes, framing


def _scanlines(workdir: Path) -> Path:
    """analog mode: faint horizontal VHS scanlines (a transparent PNG laid over the whole video)."""
    from PIL import Image
    import numpy as np
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[::4, :, 3] = 38
    rgba[1::4, :, 3] = 18
    out = workdir / "scanlines.png"
    Image.fromarray(rgba, "RGBA").save(out)
    return out


def _vhs_ass(ass_path: Path, story: dict, total: float, workdir: Path) -> Path:
    """analog mode: a small camcorder timestamp in the bottom-left corner (a running clock, one ASS event per
    second) and "PLAY" in the top-right, added to a copy of the captions file. No emergency-broadcast screens."""
    import hashlib
    seed = int(hashlib.sha1(str(story.get("story_id") or story.get("title")).encode()).hexdigest()[:8], 16)
    month = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")[seed % 12]
    day, year, hour, minute = 1 + seed % 28, 1987 + seed % 12, 1 + seed % 11, seed % 60
    text = Path(ass_path).read_text(encoding="utf-8")
    style = ("Style: VHS,DejaVu Sans Mono,46,&H00E8E8E8,&H00E8E8E8,&H00101010,&H00000000,-1,0,0,0,100,100,2,0,1,"
             "3,1,1,70,70,150,1")
    text = re.sub(r"(\[V4\+ Styles\][^\n]*\n(?:Format:[^\n]*\n)?)", lambda m: m.group(1) + style + "\n", text, count=1)

    def ts(t: float) -> str:
        return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"

    lines = [f"Dialogue: 5,{ts(0)},{ts(min(total, 4.0))},VHS,,0,0,0,,{{\\an9}}PLAY \u25b6"]
    for sec in range(int(total) + 1):
        clock = f"{'PM' if seed % 2 else 'AM'} {hour}:{(minute + (sec // 60)) % 60:02d}:{sec % 60:02d}"
        lines.append(f"Dialogue: 5,{ts(sec)},{ts(min(total, sec + 1))},VHS,,0,0,0,,"
                     f"{{\\an1}}{clock}\\N{month}. {day:02d} {year}")
    out = workdir / "captions_vhs.ass"
    out.write_text(text.rstrip("\n") + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return out


def _pick_move(img, choices: list, last):
    """random.choice of a camera move, never the previous shot's; a reused library asset (scene_XXl.reuse.json)
    also avoids the moves of its earlier uses, and the chosen move is written back for the library."""
    side = Path(img).with_suffix(".reuse.json")
    avoid = set()
    meta = None
    if side.exists():
        try:
            meta = json.loads(side.read_text())
            avoid = set(meta.get("avoid_moves") or [])
        except ValueError:
            meta = None
    pool = [m for m in choices if m != last and m not in avoid] or [m for m in choices if m != last] or list(choices)
    m = random.choice(pool)
    if meta is not None:
        meta["move"] = m
        side.write_text(json.dumps(meta))
    try:  # the asset library remembers every picture's move, so a later reuse moves differently
        Path(img).with_suffix(".move").write_text(m)
    except OSError:
        pass
    return m


def render(story: dict, images: list[list[Path]], narration: dict, ass_path: Path, workdir: Path) -> Path:
    total = narration["duration"] + tail_for(narration["duration"])
    starts = [0.0] + [st for st, _ in narration["scene_times"][1:]]
    mode = story.get("visual_mode") if story.get("visual_mode") in VISUAL_MODES else "classic"

    # Build the shot list: each scene is 1 to 4 shots
    shot_imgs, shot_starts, scene_cut, shot_scene = [], [], [], []
    for i, shots in enumerate(images):
        s_start = starts[i]
        s_end = starts[i + 1] if i + 1 < len(starts) else total
        cuts = _split_points(narration["words"], i, s_start, s_end, len(shots)) if len(shots) > 1 else []
        shot_imgs.append(shots[0]); shot_starts.append(s_start); scene_cut.append(True); shot_scene.append(i)
        if 0 < len(cuts) < len(shots) - 1:  # not enough time for every picture: spread the ones we keep
            keep = [round(j * (len(shots) - 1) / len(cuts)) for j in range(len(cuts) + 1)]
            shots = [shots[j] for j in keep]
        for j, cut in enumerate(cuts, start=1):
            shot_imgs.append(shots[j]); shot_starts.append(cut); scene_cut.append(False); shot_scene.append(i)
    seg = [shot_starts[k + 1] - shot_starts[k] for k in range(len(shot_starts) - 1)] + [total - shot_starts[-1]]
    framings = ["full"] * len(shot_imgs)
    if mode == "fast":
        shot_imgs, shot_starts, scene_cut, shot_scene, framings = _fast_shots(
            shot_imgs, shot_starts, scene_cut, shot_scene, seg, narration["words"])
        seg = [shot_starts[k + 1] - shot_starts[k] for k in range(len(shot_starts) - 1)] + [total - shot_starts[-1]]
    trans = _transitions(scene_cut, mode)
    log(f"Visual mode: {mode} ({len(shot_imgs)} shots)")
    story["_visuals"] = visual_summary(shot_imgs, seg, total)

    # 1) One moving clip per shot (each clip is XFADE longer so crossfades don't eat time)
    motions = list(MOTIONS)
    clips, last = [], None
    depths: dict = {}
    ai_cfg = CONFIG.get("ai_motion", {})
    ai_shots = int(ai_cfg.get("max_shots", 1)) if ai_cfg.get("enabled", True) else 0
    hook_shots = next((j for j in range(1, len(scene_cut)) if scene_cut[j]), len(scene_cut))
    sc0 = (story.get("scenes") or [{}])[0]
    hook_prompts = [sc0.get(k2, "") for k2 in ("image_prompt", "image_prompt_2", "image_prompt_3", "image_prompt_4")]
    ai_targets = {k: hook_prompts[k] if k < len(hook_prompts) else "" for k in range(min(ai_shots, hook_shots))}
    if mode == "fast" and ai_shots:  # fast: AI motion on the hook AND the twist (max 2)
        tw = int(story.get("twist_scene", -1))
        first_tw = next((k for k, sc in enumerate(shot_scene) if sc == tw and scene_cut[k]), None)
        ai_targets = {0: hook_prompts[0]}
        if first_tw and 0 < tw < len(story.get("scenes", [])):
            ai_targets[first_tw] = story["scenes"][tw].get("image_prompt", "")
    for k, (img, s) in enumerate(zip(shot_imgs, seg)):
        length = s + (trans[k + 1][1] if k < len(shot_imgs) - 1 else 0)
        out = workdir / f"clip_{k:02d}.mp4"
        spec = cutout.spec_for(img)  # cutout mode: an animated stage (plate + character) or a drawn screen
        if spec:
            try:
                clips.append(cutout.render_shot(spec, length, out))
                log(f"Shot {k}: {length:.1f}s cutout {spec['type']}"
                    + (f" ({spec.get('pose_name')}, {spec.get('action')})" if spec.get("pose") else ""))
                continue
            except Exception as e:  # noqa: BLE001
                log(f"Shot {k}: cutout shot failed ({str(e)[:100]}), using its preview still")
        if framings[k] != "full":  # fast mode: a punch-in / detail / pan crop of the same picture
            m = _pick_move(img, motions, last); last = m
            clips.append(_scene_clip(img, length, m, out, framings[k]))
            log(f"Shot {k}: {length:.1f}s {framings[k]} {m}")
            continue
        # Real AI animation on the hook (first shots of scene 1; fast mode: + the twist), if a free Space is available
        if k in ai_targets:
            ai = ai_motion.animate(img, ai_targets[k], workdir / f"ai_{k:02d}.mp4")
            if ai:
                try:
                    if img not in depths:
                        depths[img] = effects.depth_map(img)
                    m = _pick_move(img, effects.PARALLAX_MOVES, last); last = m
                    done = _ai_into_still(ai, img, depths[img], length, out, m)
                    if done:
                        clips.append(done)
                        log(f"Shot {k}: {length:.1f}s AI animated (max {AI_MAX_SECONDS:.0f}s) -> still with 3D {m}")
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
            m = _pick_move(img, effects.PARALLAX_MOVES, last); last = m
            try:
                clips.append(effects.parallax_clip(img, depths[img], length, m, out))
                log(f"Shot {k}: {length:.1f}s 3D {m}")
                continue
            except Exception as e:  # noqa: BLE001
                log(f"Shot {k}: 3D failed ({str(e)[:100]}), using a normal zoom")
        m = _pick_move(img, motions, last); last = m
        clips.append(_scene_clip(img, length, m, out))
        log(f"Shot {k}: {length:.1f}s {m}")

    # 2) Chain crossfades (every clip normalized to 1080x1920 / 30 fps / yuv420p / SAR 1, audio dropped)
    joined = _join(clips, seg, scene_cut, workdir / "joined.mp4", trans)

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
    if mode == "analog":  # VHS: softer, colour bleed, heavier grain (scanlines + timestamp below)
        base = ("[0:v]eq=saturation=0.82:contrast=1.1:brightness=-0.01:gamma=1.05,gblur=sigma=0.7,"
                "chromashift=cbh=4:crh=-4,colorbalance=rs=0.04:bs=-0.02,noise=alls=14:allf=t+u,vignette=PI/3.8")
        ass_path = _vhs_ass(ass_path, story, total, workdir)
        ass_arg = str(ass_path).replace("\\", "/").replace(":", "\\:")
        ass_filter = f"ass='{ass_arg}'" + (f":fontsdir='{fontsdir}'" if fontsdir else "")
    mascot = ROOT / "assets" / "mascot.png"
    logo = ROOT / "assets" / "mascot_round.png"
    vparts, cur = [], "[vb]"
    vparts.append(f"{base}[vb]")
    # Free "alive" effects: camera shake on the twist, light flicker, drifting fog and dust
    if mode == "fast":  # quick zoom punch on key words
        hits, lastp = [], -9.0
        for w in narration["words"]:
            if _is_key(w["word"]) and w["start"] - lastp >= 2.5 and len(hits) < 12:
                hits.append(w["start"]); lastp = w["start"]
        if hits:
            p = "+".join(f"between(on/{FPS},{t:.2f},{t + 0.25:.2f})" for t in hits)
            vparts.append(f"{cur}zoompan=z='1+0.07*({p})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:"
                          f"s={W}x{H}:fps={FPS}[vz]"); cur = "[vz]"
            log(f"Zoom punches on {len(hits)} key words")
    hook_end = [max(0.0, starts[1] - 0.45)] if mode == "fast" and len(starts) > 1 else []
    shake = effects.shake_expr(story, starts, extra=hook_end)
    if shake:
        vparts.append(f"{cur}scale={int(W * 1.04)}:{int(H * 1.04)},crop={W}:{H}:x='{shake[0]}':y='{shake[1]}'[vs]"); cur = "[vs]"
    flick = effects.flicker_expr(story, starts, total)
    if flick:
        vparts.append(f"{cur}eq=brightness='{flick}':eval=frame[vf]"); cur = "[vf]"
    tex = effects.make_textures(workdir)
    if "fog" in tex:
        ins += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.2f}", "-i", str(tex["fog"])]
        vparts.append(f"{cur}[{idx}:v]overlay=x='-mod(t*22,{W})':y=0:shortest=1[vfog]"); cur = "[vfog]"; idx += 1
    if mode == "analog":
        ins += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.2f}", "-i", str(_scanlines(workdir))]
        vparts.append(f"{cur}[{idx}:v]overlay=0:0:shortest=1[vscan]"); cur = "[vscan]"; idx += 1
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


def visual_summary(shot_imgs: list, seg: list[float], total: float) -> dict:
    """Seconds each SOURCE picture is on screen (virtual crops, fast-mode framings, borrowed and copied files all
    count as their source) -> distinct visuals and the longest one. Logged for every video."""
    import images
    secs: dict[str, float] = {}
    names: dict[str, str] = {}
    for img, s in zip(shot_imgs, seg):
        key = images.source_key(Path(img))
        secs[key] = secs.get(key, 0.0) + s
        names.setdefault(key, images.source_of(Path(img)).name)
    top = max(secs, key=secs.get) if secs else ""
    out = {"distinct": len(secs), "longest_s": round(secs.get(top, 0.0), 1),
           "longest_share": round(secs.get(top, 0.0) / max(total, 0.1), 3), "longest_name": names.get(top, "")}
    log(f"Visuals: {out['distinct']} distinct picture(s); longest on screen: {out['longest_name']} "
        f"{out['longest_s']:.1f}s ({out['longest_share']:.0%} of {total:.1f}s)")
    return out


def frame_visuals(path: Path, fps: float = 2.0) -> dict:
    """What viewers actually see: frames sampled from the FINISHED video (2 per second, captions / logo / bottom
    strip masked, contrast-normalised) grouped into near-identical pictures. Catches render bugs a shot list can't
    (video #28 froze on one frame for 56 s although its shot list had 14 different images)."""
    import numpy as np
    w, h = 36, 64
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={w}:{h},format=rgb24",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(np.float32)  # colour too: same layout != same picture
    rows = np.r_[int(h * .15):int(h * .38), int(h * .62):int(h * .88)]
    reps, counts, prev, run_n, best_run, blank = [], [], None, 0, 0, 0
    for f in fr:
        f = f[rows]
        sd = float(f.std())
        if sd < 4:  # black / blank frame (fade to black): not a picture
            blank += 1; prev = None; run_n = 0
            continue
        z = (f - f.mean()) / sd
        run_n = run_n + 1 if prev is not None and float(np.abs(z - prev).mean()) < 0.35 else 1
        best_run, prev = max(best_run, run_n), z
        for k, r in enumerate(reps):
            if float(np.abs(z - r).mean()) < 0.35:
                counts[k] += 1
                break
        else:
            reps.append(z); counts.append(1)
    n = max(1, len(fr))
    return {"distinct": len(reps), "top_share": round(max(counts) / n, 3) if counts else 1.0,
            "longest_run_s": best_run / fps, "blank_s": blank / fps}


def visual_problems(path: Path, story: dict | None, dur: float) -> list[str]:
    """No single picture may be on screen > qa_max_visual_share (20%) of the video, and a ~60 s video needs
    >= qa_min_visuals (8) distinct pictures: checked on the shot list (source pictures) AND on the final frames."""
    share = float(CONFIG.get("qa_max_visual_share", 0.2))
    need = max(4, round(float(CONFIG.get("qa_min_visuals", 8)) * dur / 60))
    problems = []
    v = (story or {}).get("_visuals")
    if v:
        if v["longest_share"] > share:
            problems.append(f"one picture ({v['longest_name']}) is on screen {v['longest_s']:.1f}s = "
                            f"{v['longest_share']:.0%} of the video (max {share:.0%})")
        if v["distinct"] < need:
            problems.append(f"only {v['distinct']} distinct pictures (need {need})")
    try:
        f = frame_visuals(path)
        log(f"Final frames: {f['distinct']} distinct looks, biggest {f['top_share']:.0%} of the video, "
            f"longest unchanged {f['longest_run_s']:.1f}s, blank {f['blank_s']:.1f}s")
        if f["top_share"] > share or f["longest_run_s"] > share * dur:
            problems.append(f"the finished video shows the same picture for {f['top_share']:.0%} of it "
                            f"(longest unchanged {f['longest_run_s']:.1f}s): frozen or one-image video")
        if f["distinct"] < need:
            problems.append(f"the finished video has only {f['distinct']} distinct looks (need {need})")
    except Exception as e:  # noqa: BLE001 (the check itself must never be skipped silently)
        problems.append(f"visual check failed to run ({str(e)[:100]})")
    return problems


def qa_gate(path: Path, ass_path: Path | None, narration: dict, story: dict | None = None,
            backfill: bool = False) -> list[str]:
    """Checks a finished video must pass before it may enter the buffer. Returns the problems (empty = pass).

    backfill=True (yt_backfill.py, videos already posted on TikTok before YouTube worked): no 61 s floor and no
    TikTok size cap (Shorts take up to 180 s); captions are checked only when the render's .ass still exists."""
    problems = []
    lo, hi = CONFIG.get("target_seconds", [61, 68])
    dur = media_duration(path)
    problems += visual_problems(path, story, dur)
    if backfill:
        if not 15 <= dur <= 180:
            problems.append(f"duration {dur:.1f}s (Shorts: 15-180s)")
    elif dur < lo:  # hard floor: never a video under the minimum (TikTok Creator Rewards: > 60 s)
        problems.append(f"duration {dur:.1f}s is under the {lo}s minimum")
    elif dur > hi + 0.5:
        problems.append(f"duration {dur:.1f}s (want {lo}-{hi}s)")
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
                    if ln.startswith("Dialogue:") and ",Cap," in ln) if ass_path and Path(ass_path).exists() else 0
    n_words = len(narration.get("words") or [])
    if n_words and cap_lines < 0.8 * n_words:
        problems.append(f"captions: {cap_lines} caption lines for {n_words} words")
    size = path.stat().st_size
    if not 5_000_000 < size < (256_000_000 if backfill else 64_000_000):
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
