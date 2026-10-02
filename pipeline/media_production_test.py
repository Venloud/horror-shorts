"""Isolated Night Files media-production test.
Runs the existing generator without allowing the result into the production buffer,
then exercises HyperFrames and creates a local Premiere MCP handoff.
"""
from __future__ import annotations
import json
import os


def main() -> int:
    os.environ["NIGHT_FILES_MEDIA_TEST"] = "1"
    os.environ.setdefault("HYPERFRAMES_VERSION", "0.8.100")

    import buffer
    import checkpoint
    import images
    import library
    import main as pipeline_main

    buffer.add = lambda *args, **kwargs: None
    buffer.count = lambda: 1
    checkpoint.resume = lambda history: None
    checkpoint.start = lambda *args, **kwargs: None
    checkpoint.save_story = lambda *args, **kwargs: None
    checkpoint.save_narration = lambda *args, **kwargs: None
    checkpoint.finish = lambda *args, **kwargs: None
    images.save_cache = lambda *args, **kwargs: None
    library.record_video = lambda *args, **kwargs: None
    pipeline_main.save_history = lambda *args, **kwargs: None

    result = pipeline_main.main()
    if result != 0:
        return result

    from pathlib import Path
    root = pipeline_main.ROOT / "output"
    videos = sorted(root.glob("*/final.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not videos:
        raise RuntimeError("media test produced no output/**/final.mp4")

    video = videos[0]
    workdir = video.parent

    from hyperframes_adapter import render_video
    from premiere_mcp_adapter import handoff

    hf_out = workdir / "hyperframes_test.mp4"
    hf = render_video(video, hf_out, workdir)
    premiere = handoff(video, workdir)

    report = {
        "source_video": str(video),
        "hyperframes": hf,
        "premiere_mcp": premiere,
        "production_side_effects_blocked": True,
        "published": False,
    }
    (workdir / "media_production_test.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
