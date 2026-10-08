"""Opt-in, standard-library-only Night Files scene readiness and repair manifest.

This tool does not publish, generate, or change the production pipeline.
CLI: python pipeline/scene_repair.py inspect --story PATH --workdir PATH
     python pipeline/scene_repair.py invalidate --manifest PATH --scene 3 --part visual
"""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

def probe(path, ffprobe="ffprobe"):
    if not path or not Path(path).is_file():
        return {"ok": False, "error": "missing asset"}
    try:
        p = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                            "-of", "json", str(path)], capture_output=True, text=True, timeout=20)
        if p.returncode:
            return {"ok": False, "error": p.stderr.strip()[:240]}
        duration = float(json.loads(p.stdout).get("format", {}).get("duration", 0))
        return {"ok": duration > 0, "duration": round(duration, 3)}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)[:240]}

def build(story, workdir):
    rows = []
    for i, scene in enumerate(story.get("scenes", [])):
        text = scene.get("narration", "")
        visual = workdir / "images" / f"{i:02d}.png"
        candidates = sorted((workdir / "images").glob(f"{i:02d}.*")) if (workdir / "images").is_dir() else []
        if candidates:
            visual = candidates[0]
        rows.append({"scene": i, "narration_hash": digest(text),
                     "narration": text, "visual": str(visual),
                     "visual_exists": visual.is_file(), "visual_dirty": not visual.is_file(),
                     "audio_dirty": False, "status": "ready" if visual.is_file() else "missing_visual"})
    return {"schema": 1, "title": story.get("title"), "story_id": story.get("story_id"),
            "created_utc": datetime.now(timezone.utc).isoformat(), "scenes": rows}

def invalidate(manifest, index, part):
    scenes = manifest["scenes"]
    if index < 0 or index >= len(scenes):
        raise ValueError(f"scene {index} outside range 0..{len(scenes)-1}")
    s = scenes[index]
    if part in ("visual", "both"):
        s["visual_dirty"] = True
    if part in ("audio", "both"):
        s["audio_dirty"] = True
    s["status"] = "needs_repair"
    return manifest

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inspect")
    p.add_argument("--story", required=True, type=Path)
    p.add_argument("--workdir", required=True, type=Path)
    p.add_argument("--out", type=Path)
    p = sub.add_parser("invalidate")
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--scene", required=True, type=int)
    p.add_argument("--part", choices=["visual", "audio", "both"], default="visual")
    args = parser.parse_args()
    if args.cmd == "inspect":
        report = build(json.loads(args.story.read_text()), args.workdir)
        output = args.out or args.workdir / "scene_repair_manifest.json"
    else:
        output = args.manifest
        report = invalidate(json.loads(output.read_text()), args.scene, args.part)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"manifest": str(output), "scenes": len(report["scenes"]),
                      "needs_repair": [s["scene"] for s in report["scenes"] if s["visual_dirty"] or s["audio_dirty"]]}))

if __name__ == "__main__":
    main()
