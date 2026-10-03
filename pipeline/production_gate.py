"""Hard production gates for final media and provenance.

Stricter than the existing report-only QA: a file cannot enter the durable
buffer unless it is a real, decodable MP4 with the expected portrait format,
audio, duration and size. No network calls are made here.
"""
import json
import subprocess
from pathlib import Path

from common import CONFIG, log


def _run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"Command failed: {' '.join(cmd[:8])}: {p.stderr[-1200:]}")
    return p.stdout


def validate_final_video(path: Path) -> dict:
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"final video is missing: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError("final video is zero bytes")
    if size < 5_000_000 or size >= 256_000_000:
        raise RuntimeError(f"final video size {size / 1e6:.2f} MB is outside the hard 5-256 MB safety range")

    duration = float(_run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path)
    ]).strip())
    lo, hi = CONFIG.get("target_seconds", [61, 68])
    if duration < float(lo) or duration > float(hi) + 0.5:
        raise RuntimeError(f"final video duration {duration:.2f}s is outside {lo}-{hi}s")

    streams = _run([
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,width,height,codec_name,pix_fmt",
        "-of", "csv=p=0", str(path)
    ])
    lines = streams.splitlines()
    video = [x for x in lines if ",video," in f",{x},"]
    audio = [x for x in lines if ",audio," in f",{x},"]
    if not video:
        raise RuntimeError("final video contains no video stream")
    if not audio:
        raise RuntimeError("final video contains no audio stream")
    if not any("1080,1920" in x for x in video):
        raise RuntimeError(f"final video is not 1080x1920: {streams!r}")

    # Full decode tests catch truncated/corrupt files that only have a valid MP4 header.
    _run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"])
    _run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "null", "-"])

    evidence = {
        "path": str(path), "bytes": size, "duration_seconds": round(duration, 3),
        "resolution": "1080x1920", "video_stream": True, "audio_stream": True,
        "decoded_video": True, "decoded_audio": True,
    }
    log(f"PRODUCTION GATE: final.mp4 verified ({duration:.1f}s, {size / 1e6:.1f} MB, 1080x1920, video+audio, full decode)")
    return evidence


_REAL_SOURCES = {"pexels", "pixabay", "wikimedia", "smithsonian", "loc", "openverse", "archive", "stock", "real_media"}


def validate_provenance(story: dict) -> dict:
    assets = story.get("media_assets") or []
    if not isinstance(assets, list):
        raise RuntimeError("media_assets is not a list")

    missing = []
    checked = 0
    for i, asset in enumerate(assets):
        if not isinstance(asset, dict):
            missing.append(f"media_assets[{i}] is not an object")
            continue
        source = str(asset.get("source") or asset.get("provider") or "").strip().lower()
        external = source in _REAL_SOURCES or bool(asset.get("license")) or bool(asset.get("rights"))
        if not external:
            continue
        checked += 1
        url = str(asset.get("url") or asset.get("source_url") or "").strip()
        license_name = str(asset.get("license") or asset.get("rights") or "").strip()
        if not source:
            missing.append(f"media_assets[{i}] missing source")
        if not url.startswith(("http://", "https://")):
            missing.append(f"media_assets[{i}] missing source URL")
        if not license_name:
            missing.append(f"media_assets[{i}] missing license/rights")

    policy = str(CONFIG.get("music_policy", "procedural_only")).strip().lower()
    if policy not in {"procedural_only", "approved_files"}:
        missing.append(f"unsupported music_policy: {policy}")
    if policy == "approved_files" and not CONFIG.get("approved_music"):
        missing.append("music_policy=approved_files but approved_music is empty")

    if missing:
        raise RuntimeError("provenance gate failed: " + "; ".join(missing[:12]))

    result = {"external_assets_checked": checked, "music_policy": policy, "rights_gate": "passed"}
    log(f"PRODUCTION GATE: provenance verified ({checked} external asset(s), music_policy={policy})")
    return result


def validate_buffer_metadata(meta_path: Path) -> dict:
    if not meta_path.exists() or meta_path.stat().st_size <= 0:
        raise RuntimeError(f"buffer metadata is missing or empty: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    required = ("stamp", "story_id", "title", "caption_text")
    missing = [key for key in required if not meta.get(key)]
    if missing:
        raise RuntimeError("buffer metadata missing: " + ", ".join(missing))
    return {"metadata_valid": True, "story_id": meta["story_id"], "title": meta["title"]}


def validate_buffer_provenance(meta_path: Path) -> dict:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    provenance = meta.get("provenance") or {}
    assets = provenance.get("media_assets") or []
    story = {"media_assets": assets}
    result = validate_provenance(story)
    result["buffer_provenance"] = True
    return result


def gate_final_video(video: Path, story: dict, meta: Path | None = None) -> dict:
    evidence = {"video": validate_final_video(video), "provenance": validate_provenance(story)}
    if meta:
        evidence["metadata"] = validate_buffer_metadata(meta)
        evidence["provenance"] = validate_buffer_provenance(meta)
    return evidence


def write_gate_report(workdir: Path, evidence: dict) -> Path:
    out = workdir / "production_gate.json"
    out.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--story", type=Path, required=True)
    args = parser.parse_args()
    story = json.loads(args.story.read_text(encoding="utf-8"))
    print(json.dumps(gate_final_video(args.video, story), indent=2))
