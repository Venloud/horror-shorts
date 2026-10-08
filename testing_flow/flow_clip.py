"""Prepare and archive one manually exported Google Flow clip, without API charges.

Flow is a browser product. This tool never signs in or invokes undocumented endpoints.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT = (
    "Vertical 9:16 cinematic horror footage, 6 to 8 seconds. Interior of a lived-in "
    "Philadelphia rowhouse at night, Sunday football gathering. Camera slowly dollies "
    "toward a dark, open hallway closet with NO door, while blurry people watch a game "
    "in the distant living room. A sudden sequence of three ominous knocks seems to "
    "come from the empty opening. Practical warm lamps, deep shadow, natural handheld "
    "cinematography, photorealistic, unsettling but restrained. No text, captions, "
    "logos, visible hands, jump cuts, or music. Maintain a single continuous shot."
)

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--test-id", required=True)
    p.add_argument("--clip-path", default="")
    args = p.parse_args()
    if not args.test_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Invalid test id")
    dest = ROOT / "testing-the-flow" / "saved" / args.test_id
    checkpoint = ROOT / "testing-the-flow" / "checkpoint" / args.test_id
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {
        "test_id": args.test_id,
        "story_id": "flow-001-ten-seconds-ahead",
        "shot_id": "shot-001-open-closet",
        "provider": "Google Flow browser, manual export",
        "prompt": PROMPT,
        "target_aspect_ratio": "9:16",
        "target_duration_seconds": "6-8",
        "status": "awaiting_manual_flow_export",
        "note": "No video-generation API calls or charges performed by this workflow.",
    }
    if args.clip_path:
        src = (ROOT / args.clip_path).resolve()
        allowed = (ROOT / "testing_flow" / "imports").resolve()
        if not src.is_relative_to(allowed):
            raise ValueError("Clip must be inside testing_flow/imports/")
        if src.suffix.lower() != ".mp4" or not src.is_file():
            raise ValueError("Expected an existing MP4 in testing_flow/imports/")
        if src.stat().st_size < 1024:
            raise ValueError("MP4 too small")
        with src.open("rb") as f:
            if b"ftyp" not in f.read(64):
                raise ValueError("File does not appear to be an MP4")
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        target = dest / ("flow-" + digest[:16] + ".mp4")
        shutil.copyfile(src, target)
        manifest.update(status="clip_archived", sha256=digest, bytes=src.stat().st_size,
                        archived_clip=str(target.relative_to(ROOT)))
        write_json(checkpoint / "flow-clip.json", manifest)
    write_json(dest / "flow-shot-001.json", manifest)
    (dest / "flow-shot-001-prompt.txt").write_text(PROMPT + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))

if __name__ == "__main__":
    main()
