"""Optional video-generation broker.

Current free-capable hosted lane: NVIDIA Cosmos3-Nano. Existing HF Spaces and
local/3D motion remain the normal fallbacks. This broker never becomes mandatory.
"""
from __future__ import annotations
import os
from pathlib import Path
from common import CONFIG, log


def generate_text_video(prompt: str, out: Path) -> Path | None:
    if not os.environ.get("NVIDIA_API_KEY") and not os.environ.get("NVIDIA_NIM_API_KEY"):
        log("Video broker: NVIDIA standby (no NVIDIA_API_KEY)")
        return None
    settings = CONFIG.get("nvidia_video", {})
    if not settings.get("enabled", True):
        return None
    try:
        from providers import nvidia
        raw = nvidia.generate_video(
            prompt,
            resolution=settings.get("resolution", "480_16_9"),
            num_frames=int(settings.get("num_frames", 25)),
            steps=int(settings.get("steps", 35)),
            fps=int(settings.get("fps", 24)),
        )
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(raw)
        if tmp.stat().st_size < 100_000:
            raise RuntimeError("NVIDIA video response is unexpectedly small")
        tmp.replace(out)
        log(f"Video broker: NVIDIA Cosmos3-Nano produced {out.name}")
        return out
    except Exception as e:
        log(f"Video broker: NVIDIA failed, preserving existing motion fallback ({type(e).__name__}: {str(e)[:180]})")
        out.unlink(missing_ok=True)
        return None
