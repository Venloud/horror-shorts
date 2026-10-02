"""Optional AutoClip repurposing adapter.

AutoClip is a separate MIT-licensed project for AI highlight extraction and short-form
repurposing. Night Files already creates a finished short, so this adapter is deliberately
OFF by default and does not replace the production renderer.

When enabled in an environment that has the AutoClip CLI installed, it can analyze a
finished Night Files video plus its SRT transcript and export a publish kit. Failures are
non-fatal: the normal Night Files video remains the production output.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from common import CONFIG, ROOT, log


def _settings() -> dict:
    return CONFIG.get("autoclip") or {}


def enabled() -> bool:
    return bool(_settings().get("enabled"))


def _binary() -> str:
    return str(_settings().get("binary") or os.environ.get("AUTOCLIP_BIN") or "autoclip")


def _srt_from_words(words: list[dict], out: Path) -> Path:
    def ts(seconds: float) -> str:
        ms = max(0, int(round(seconds * 1000)))
        h, rem = divmod(ms, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    groups = []
    group = []
    for word in words or []:
        text = str(word.get("word") or "").strip()
        if not text:
            continue
        group.append(word)
        if len(group) >= 7 or text.endswith((".", "!", "?", ",")):
            groups.append(group)
            group = []
    if group:
        groups.append(group)

    lines = []
    for i, g in enumerate(groups, 1):
        start = float(g[0].get("start") or 0)
        end = float(g[-1].get("end") or start + 0.4)
        text = " ".join(str(x.get("word") or "").strip() for x in g).strip()
        lines.append(f"{i}\n{ts(start)} --> {ts(end)}\n{text}\n")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def run(story: dict, video: Path, words: list[dict], workdir: Path) -> Path | None:
    if not enabled():
        return None

    binary = _binary()
    if not shutil.which(binary) and not Path(binary).exists():
        log("AUTOCLIP: enabled but CLI is not installed; skipping")
        return None

    workdir.mkdir(parents=True, exist_ok=True)
    srt = _srt_from_words(words, workdir / "autoclip.srt")
    platform = str(_settings().get("platform") or "tiktok")
    style = str(_settings().get("portrait_style") or "podcast")
    timeout = int(_settings().get("timeout") or 600)

    cmd = [
        binary, "produce", str(video),
        "--srt", str(srt),
        "--platform", platform,
        "--portrait-style", style,
        "--json",
    ]
    log(f"AUTOCLIP: starting repurpose analysis for '{story.get('title')}'")
    log(f"AUTOCLIP: command={' '.join(cmd)}")
    try:
        p = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True,
                           timeout=timeout, check=True)
    except Exception as e:
        log(f"AUTOCLIP: FAILED ({type(e).__name__}: {str(e)[:240]})")
        return None

    raw = (p.stdout or "").strip()
    try:
        result = json.loads(raw.splitlines()[-1])
    except Exception:
        log("AUTOCLIP: command succeeded but returned no parseable JSON")
        return None

    project_id = result.get("project_id") or result.get("id")
    if not project_id:
        log("AUTOCLIP: no project_id returned; leaving production video unchanged")
        return None

    out_dir = workdir / "autoclip_outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    export_cmd = [binary, "outputs", str(project_id), "--export-kits"]
    log(f"AUTOCLIP: exporting project {project_id}")
    try:
        subprocess.run(export_cmd, cwd=workdir, capture_output=True, text=True,
                       timeout=timeout, check=True)
    except Exception as e:
        log(f"AUTOCLIP: export FAILED ({type(e).__name__}: {str(e)[:240]})")
        return None

    candidates = sorted(
        [p for p in workdir.rglob("*.mp4") if p.resolve() != video.resolve()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        log("AUTOCLIP: export completed but no alternate MP4 was found")
        return None

    selected = candidates[:max(1, int(_settings().get("max_outputs") or 3))]
    target = out_dir / "latest"
    target.mkdir(parents=True, exist_ok=True)
    manifest = {"project_id": project_id, "source": str(video), "outputs": []}
    for src in selected:
        dst = target / src.name
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        manifest["outputs"].append(str(dst))
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(f"AUTOCLIP: SUCCESS ({len(selected)} alternate clip(s))")
    return target
