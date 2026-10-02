"""Night Files media-production test that queues the finished video in the production buffer.

This workflow deliberately does not publish. It exercises the generator, HyperFrames, and
Premiere MCP handoff, while leaving the finished video/caption in the same FIFO buffer that
the scheduled daily publisher consumes later.
"""
from __future__ import annotations

import json
import os


def main() -> int:
    os.environ["NIGHT_FILES_MEDIA_TEST"] = "1"
    os.environ.setdefault("HYPERFRAMES_VERSION", "0.8.100")

    import checkpoint
    import images
    import library
    import main as pipeline_main

    # Isolate checkpoint/cache/history side effects, but DO NOT disable buffer.add().
    checkpoint.resume = lambda history: None
    checkpoint.start = lambda *args, **kwargs: None
    checkpoint.save_story = lambda *args, **kwargs: None
    checkpoint.save_narration = lambda *args, **kwargs: None
    checkpoint.finish = lambda *args, **kwargs: None
    images.save_cache = lambda *args, **kwargs: None
    library.record_video = lambda *args, **kwargs: None

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
    import buffer

    hf_out = workdir / "hyperframes_test.mp4"
    hf = render_video(video, hf_out, workdir)
    premiere = handoff(video, workdir)

    queued = buffer.videos()
    queued_stamp = workdir.name
    queued_item = next((v for v in queued if v["stamp"] == queued_stamp), None)

    report = {
        "source_video": str(video),
        "hyperframes": hf,
        "premiere_mcp": premiere,
        "buffer": {
            "queued": queued_item is not None,
            "stamp": queued_stamp,
            "waiting_count": len(queued),
        },
        "published": False,
        "publish_owner": "scheduled daily workflow",
    }
    (workdir / "media_production_test.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
