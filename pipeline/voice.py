"""Free narration with Kokoro TTS, plus word-level timings for captions."""
import re
from pathlib import Path

import numpy as np
import soundfile as sf

from common import CONFIG, log

SR = 24000
SCENE_GAP = 0.35   # seconds of silence between scenes
LEAD_IN = 0.0      # first word at 0.0 s: the hook must be heard instantly


def _clean(text: str) -> str:
    text = text.replace("—", ", ").replace("–", ", ").replace("...", "…")
    return re.sub(r"\s+", " ", text).strip()


def _proportional_words(text: str, start: float, dur: float) -> list[dict]:
    """Fallback timing: spread words over the chunk by character length."""
    words = text.split()
    if not words:
        return []
    weights = [len(w) + 2 for w in words]
    total = sum(weights)
    out, t = [], start
    for w, wt in zip(words, weights):
        d = dur * wt / total
        out.append({"word": w, "start": t, "end": t + d})
        t += d
    return out


def _tokens_to_words(tokens, offset: float) -> list[dict]:
    """Merge Kokoro tokens (punctuation is separate) into caption words."""
    words: list[dict] = []
    for tok in tokens or []:
        text = getattr(tok, "text", "") or ""
        st, et = getattr(tok, "start_ts", None), getattr(tok, "end_ts", None)
        if not text.strip():
            continue
        is_punct = not re.search(r"[A-Za-z0-9]", text)
        if is_punct and words:
            words[-1]["word"] += text
            continue
        if st is None or et is None:
            return []  # timings missing -> caller falls back
        words.append({"word": text, "start": offset + float(st), "end": offset + float(et)})
    return words


def narrate(story: dict, outdir: Path) -> dict:
    from kokoro import KPipeline  # heavy import, keep local

    pipe = KPipeline(lang_code=CONFIG.get("voice_lang", "a"))
    voice, speed = CONFIG["voice"], float(CONFIG.get("voice_speed", 1.0))

    pieces = [np.zeros(int(LEAD_IN * SR), dtype=np.float32)]
    t = LEAD_IN
    words: list[dict] = []
    scene_times: list[tuple[float, float]] = []

    for i, scene in enumerate(story["scenes"]):
        text = _clean(scene["narration"])
        scene_start = t
        for result in pipe(text, voice=voice, speed=speed, split_pattern=r"\n+"):
            audio = result.audio
            if audio is None:
                continue
            audio = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            audio = audio.astype(np.float32).flatten()
            trim = 0.0
            if not words and len(audio):  # very first chunk: cut the TTS's own leading silence
                loud = np.flatnonzero(np.abs(audio) > 0.02 * (float(np.max(np.abs(audio))) or 1.0))
                cut = max(0, int(loud[0]) - int(0.02 * SR)) if len(loud) else 0
                audio, trim = audio[cut:], cut / SR
            dur = len(audio) / SR
            chunk_words = _tokens_to_words(getattr(result, "tokens", None), t - trim)
            for w in chunk_words:
                w["start"], w["end"] = max(0.0, w["start"]), max(0.05, w["end"])
            if not chunk_words:
                chunk_words = _proportional_words(getattr(result, "graphemes", text) or text, t, dur)
            for w in chunk_words:
                w["scene"] = i
            words.extend(chunk_words)
            pieces.append(audio)
            t += dur
        gap = SCENE_GAP if i < len(story["scenes"]) - 1 else 0.0
        pieces.append(np.zeros(int(gap * SR), dtype=np.float32))
        t += gap
        scene_times.append((scene_start, t))

    wav = np.concatenate(pieces)
    peak = float(np.max(np.abs(wav))) or 1.0
    wav = wav / peak * 0.9
    path = outdir / "narration.wav"
    sf.write(path, wav, SR)
    log(f"Narration: {t:.1f}s, {len(words)} words timed")
    return {"path": path, "duration": t, "words": words, "scene_times": scene_times}
