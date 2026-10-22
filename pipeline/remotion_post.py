"""Optional Remotion *editorial pass* on a video rendered by the existing Night Files pipeline.

The source shot renderer is still explainer.Renderer. This helper does not create
a second story system. Remotion handles typographic/caption/cut post-production,
FFmpeg restores the original voice/SFX/master audio without changes.
No API calls, cloud generation, publishing, or remote dependencies at runtime.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from common import ROOT


def manifest(source: Path, output: Path, segments: list[dict],
             narration: dict, fps: int, total_frames: int) -> dict[str, Any]:
    if int(fps) not in (24, 25, 30, 50, 60):
        raise ValueError("Unsupported polish FPS")
    if total_frames < 1:
        raise ValueError("Cannot post-process empty video")
    shots = []
    for i, seg in enumerate(segments):
        shot = seg.get("shot") or {}
        start = max(0, min(total_frames - 1, round(float(seg["start"]) * fps)))
        end = max(start + 1, min(total_frames, round(float(seg["end"]) * fps)))
        if end <= start:
            continue
        # The postprocessor never reads or fabricates text from an external source.
        shots.append({"startFrame": start, "endFrame": end,
                      "kind": str(shot.get("type") or "scene")[:24],
                      "template": str(shot.get("template") or "")[:32],
                      "label": str(shot.get("text") or "")[:64],
                      "index": i})
    words = [{"word": str(w.get("word") or "")[:32],
              "start": float(w["start"]), "end": float(w["end"])}
             for w in narration.get("words", [])
             if "start" in w and "end" in w and float(w["end"]) > float(w["start"])]
    return {"source": str(source.resolve()), "output": str(output.resolve()),
            "fps": fps, "totalFrames": int(total_frames),
            "shots": shots, "words": words}


def polish(source: Path, output: Path, segments: list[dict],
           narration: dict, fps: int, total_frames: int) -> Path:
    source, output = Path(source), Path(output)
    if not source.exists() or source.stat().st_size < 10000:
        raise FileNotFoundError(f"No valid source MP4 for Remotion: {source}")
    if source.resolve() == output.resolve():
        raise ValueError("Remotion output must not overwrite its input")
    job = manifest(source, output, segments, narration, fps, total_frames)
    input_json = output.with_suffix(".remotion.json")
    input_json.write_text(json.dumps(job, ensure_ascii=False, separators=(",", ":")))
    try:
        subprocess.run(["node", str(ROOT / "remotion" / "render_polish.mjs"),
                        str(input_json.resolve())], check=True, timeout=30 * 60)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        # Explicit failure, don't silently deliver video without expected captions.
        raise
    if not output.is_file() or output.stat().st_size < 10000:
        raise RuntimeError("Remotion output was empty")
    return output
