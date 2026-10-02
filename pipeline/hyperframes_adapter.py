"""Night Files HyperFrames integration.

Uses the official HyperFrames CLI as an isolated video-composition/render stage.
This adapter never publishes and never changes the production buffer by itself.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

VERSION = os.environ.get("HYPERFRAMES_VERSION", "0.8.100")


def _run(cmd: list[str], cwd: Path, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True, timeout=timeout)


def render_video(source: Path, output: Path, workdir: Path) -> dict:
    """Wrap an existing Night Files video in a deterministic HyperFrames composition and render it.

    Audio is intentionally disabled here because Night Files' existing final FFmpeg pass
    remains responsible for narration/music/SFX mixing.
    """
    source = Path(source).resolve()
    output = Path(output).resolve()
    project = Path(workdir).resolve() / "hyperframes"
    assets = project / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    asset = assets / "night-files-source.mp4"
    shutil.copy2(source, asset)

    composition = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <style>
    html, body {{ margin: 0; width: 1080px; height: 1920px; overflow: hidden; background: #000; }}
    #root {{ position: relative; width: 1080px; height: 1920px; overflow: hidden; }}
    video {{ position: absolute; inset: 0; width: 1080px; height: 1920px; object-fit: cover; }}
  </style>
</head>
<body>
  <div id="root" data-composition-id="night-files-test"
       data-start="0" data-width="1080" data-height="1920">
    <video id="night-files-source" src="./assets/night-files-source.mp4"
           data-start="0" data-track-index="0" muted playsinline></video>
  </div>
</body>
</html>
"""
    (project / "index.html").write_text(composition, encoding="utf-8")

    lint = _run(["npx", f"hyperframes@{VERSION}", "lint", "."], project, timeout=300)
    render = _run([
        "npx", f"hyperframes@{VERSION}", "render",
        "--output", str(output),
        "--quality", "draft",
    ], project, timeout=1200)

    return {
        "version": VERSION,
        "project": str(project),
        "source": str(source),
        "output": str(output),
        "lint": lint.stdout[-4000:],
        "render": render.stdout[-4000:],
    }
