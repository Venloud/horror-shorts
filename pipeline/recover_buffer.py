"""Recover one finished build artifact into the buffer without rendering or posting."""
import argparse
import io
import json
import zipfile
from pathlib import Path
import requests
import buffer
import checkpoint
from common import ROOT, load_history, save_history, opening_line, log
from production_gate import gate_final_video, write_gate_report

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-id", type=int, required=True)
    ap.add_argument("--story-id", required=True)
    a = ap.parse_args()
    repo = buffer._repo()
    response = requests.get(
        f"https://api.github.com/repos/{repo}/actions/artifacts/{a.artifact_id}/zip",
        headers=buffer._headers(), timeout=600)
    response.raise_for_status()
    out = ROOT / "output" / f"recover-{a.artifact_id}"
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        finals = [name for name in archive.namelist() if name.endswith("/final.mp4") or name == "final.mp4"]
        if len(finals) != 1:
            raise RuntimeError("Expected exactly one final video")
        prefix = finals[0][:-len("final.mp4")]
        for filename in ("final.mp4", "story.json", "caption.txt", "caption.json", "summary.txt"):
            name = prefix + filename
            if name in archive.namelist():
                (out / filename).write_bytes(archive.read(name))
    story = json.loads((out / "story.json").read_text())
    if story.get("story_id") != a.story_id:
        raise RuntimeError("Artifact belongs to a different story")
    history = load_history()
    existing = next((h for h in history if h.get("story_id") == a.story_id), None)
    if existing and existing.get("tiktok"):
        log("Story already posted; no duplicate buffer upload")
        return
    meta_path = out / "caption.json"
    if not meta_path.exists():
        text = (out / "caption.txt").read_text()
        caption, _, pinned = text.partition("\n\nPIN: ")
        stamp = Path(prefix.rstrip("/")).name
        if not stamp or not stamp[0].isdigit():
            raise RuntimeError("Cannot recover the original build stamp")
        meta = {
            "stamp": stamp, "story_id": a.story_id, "title": story["title"],
            "caption_text": caption.strip(), "pinned_comment": pinned.strip(),
            "mode": story.get("mode", "fiction"), "source": story.get("source"),
            "case": story.get("case"), "opening": opening_line(story),
            "true_story": bool(story.get("true_story")),
            "provenance": {"media_assets": story.get("media_assets") or []},
        }
        meta_path.write_text(json.dumps(meta, indent=2))
    meta = json.loads(meta_path.read_text())
    if meta["story_id"] != a.story_id:
        raise RuntimeError("Caption belongs to a different story")
    summary = (out / "summary.txt").read_text() if (out / "summary.txt").exists() else ""
    if any(p in summary for p in ("one picture", "the finished video shows the same picture", "blurry start")):
        raise RuntimeError("Artifact failed a visual hard gate")
    evidence = gate_final_video(out / "final.mp4", story, meta_path)
    write_gate_report(out, evidence)
    stamp = meta["stamp"]
    waiting = buffer.videos()
    if not any(v["stamp"] == stamp for v in waiting):
        buffer.add(stamp, out / "final.mp4", meta_path)
    verified = next((v for v in buffer.videos() if v["stamp"] == stamp), None)
    if not verified:
        raise RuntimeError("Buffer pair not found after recovery")
    buffer.download(verified["json"], out / "verified-caption.json")
    if json.loads((out / "verified-caption.json").read_text())["story_id"] != a.story_id:
        raise RuntimeError("Buffered metadata verification failed")
    if not existing:
        history.append({
            "date": stamp, "story_id": a.story_id, "title": story["title"],
            "buffered": stamp, "tiktok": None, "mode": story.get("mode"),
            "source": story.get("source"), "premise": story.get("premise", ""),
            "opening": opening_line(story),
            "seconds": evidence["video"]["duration_seconds"],
            "recovered_from_artifact": a.artifact_id,
        })
        save_history(history)
    checkpoint.finish(story)
    log(f"RECOVERED: {story['title']} is verified in the buffer; {buffer.count()} waiting")

if __name__ == "__main__":
    main()
