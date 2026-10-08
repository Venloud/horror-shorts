"""Isolated Testing the Flow preflight and script preservation.

Never invokes production main.py, history writes, buffer, or publishing.
This entry point intentionally does not spend Google Flow credits until a
working authenticated adapter is validated.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "testing-the-flow" / "checkpoint"
OUT = ROOT / "testing-the-flow" / "saved"
sys.path.insert(0, str(ROOT / "pipeline"))


def atomic_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def script_text(story):
    scenes = story.get("scenes") or []
    return "SCRIPT\n" + "\n\n".join(s.get("narration", "").strip() for s in scenes if s.get("narration", "").strip()) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate-story", action="store_true")
    parser.add_argument("--test-id", default="default")
    args = parser.parse_args()
    if not args.test_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("test-id must contain only letters, numbers, dashes, underscores")
    global STATE, OUT
    STATE = STATE / args.test_id
    OUT = OUT / args.test_id
    story_file = STATE / "story.json"
    log = {"test_id": args.test_id, "timestamp": datetime.now(timezone.utc).isoformat(),
           "story": "not_generated", "flow": "not_configured", "publishing": "disabled"}
    try:
        if story_file.is_file():
            story = json.loads(story_file.read_text(encoding="utf-8"))
            log["story"] = "restored_from_checkpoint"
        elif args.generate_story:
            from story import write_story
            story = write_story([])  # isolated input, no production history writes
            if not story.get("scenes"):
                raise RuntimeError("Story provider returned no scenes")
            atomic_text(story_file, json.dumps(story, ensure_ascii=False, indent=2))
            log["story"] = "generated_and_checkpointed"
        else:
            log["story"] = "dry_run_no_api_calls"
            print(json.dumps(log, indent=2))
            return
        script = script_text(story)
        digest = hashlib.sha256(script.encode()).hexdigest()[:16]
        target = OUT / ("flow-script-" + digest + ".txt")
        atomic_text(target, script)
        atomic_text(OUT / ("story-" + digest + ".json"), json.dumps(story, ensure_ascii=False, indent=2))
        log.update({"script_path": str(target.relative_to(ROOT)), "story_sha256_prefix": digest,
                    "scenes": len(story["scenes"]), "flow": "not_attempted_no_verified_adapter"})
        print(json.dumps(log, indent=2))
    finally:
        atomic_text(OUT / "last-run.json", json.dumps(log, indent=2))


if __name__ == "__main__":
    main()
