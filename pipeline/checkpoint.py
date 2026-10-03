"""Build checkpoints: a failed build keeps its story, narration and images so the next try only redoes what's missing.

Files live in cache/checkpoint/ (saved/restored by build.yml with the Actions cache, keys "ckpt-<run id>"):
  story.json            the story (with its story_id)
  narration.wav/.json   the voiceover + word timings, tied to a hash of the narration text and speed
  images/               every finished image, kept as soon as it's made
  done.json             written after a successful build so an older cache entry is never resumed
Test builds never read or write checkpoints.
"""
import hashlib
import json
import shutil
from pathlib import Path

from common import ROOT, log

CK = ROOT / "cache" / "checkpoint"
IMAGES = CK / "images"


def story_id(story: dict) -> str:
    key = "|".join(str(story.get(k) or "") for k in ("title", "mode", "source", "case"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _narr_hash(story: dict, speed: float) -> str:
    text = "\n".join(s.get("narration", "") for s in story.get("scenes", []))
    return hashlib.sha1(f"{speed:.3f}|{text}".encode("utf-8")).hexdigest()[:16]


def resume(history: list[dict]) -> dict | None:
    """The unfinished story from an earlier failed build, unless it was finished (or used) since."""
    f = CK / "story.json"
    if (CK / "done.json").exists() or not f.exists():
        return None
    try:
        story = json.loads(f.read_text())
    except Exception:  # noqa: BLE001
        return None
    sid = story.get("story_id")
    used = {h.get("story_id") for h in history} | {(h.get("title"), h.get("mode")) for h in history}
    if not sid or sid in used or (story.get("title"), story.get("mode")) in used:
        log("Checkpoint story was already finished: starting fresh")
        clear()
        return None
    n = len(list(IMAGES.glob("*.png"))) if IMAGES.exists() else 0
    log(f"Resuming checkpoint '{story.get('title')}' ({sid}): {n} images kept"
        f"{', narration kept' if (CK / 'narration.wav').exists() else ''}")
    return story


def start(story: dict) -> None:
    """New story: wipe any old checkpoint and save this one."""
    clear()
    story["story_id"] = story.get("story_id") or story_id(story)
    save_story(story)


def save_story(story: dict) -> None:
    CK.mkdir(parents=True, exist_ok=True)
    (CK / "story.json").write_text(json.dumps(story, ensure_ascii=False, indent=1))


def save_narration(story: dict, narration: dict) -> None:
    CK.mkdir(parents=True, exist_ok=True)
    shutil.copy(narration["path"], CK / "narration.wav")
    meta = {k: v for k, v in narration.items() if k != "path"}
    meta["hash"] = _narr_hash(story, narration.get("speed", 1.0))
    (CK / "narration.json").write_text(json.dumps(meta))


def load_narration(story: dict, workdir: Path) -> dict | None:
    wav, meta_f = CK / "narration.wav", CK / "narration.json"
    if not (wav.exists() and meta_f.exists()):
        return None
    meta = json.loads(meta_f.read_text())
    if meta.get("hash") != _narr_hash(story, meta.get("speed", 1.0)):
        return None
    dest = workdir / "narration.wav"
    shutil.copy(wav, dest)
    meta.pop("hash", None)
    meta["path"] = dest
    meta["scene_times"] = [tuple(x) for x in meta.get("scene_times", [])]
    log(f"Narration reused from checkpoint ({meta['duration']:.1f}s)")
    return meta


def qa_failed(story: dict, problems: list[str]) -> int:
    """Count QA failures for this story; a duration problem also drops the narration so it's re-fitted."""
    story["qa_fails"] = int(story.get("qa_fails", 0)) + 1
    save_story(story)
    if any(p.startswith("duration") for p in problems):
        for f in ("narration.wav", "narration.json"):
            (CK / f).unlink(missing_ok=True)
    return story["qa_fails"]


def finish(story: dict) -> None:
    """Build succeeded: drop the heavy files, leave a marker so this story is never resumed."""
    clear()
    CK.mkdir(parents=True, exist_ok=True)
    (CK / "done.json").write_text(json.dumps({"story_id": story.get("story_id")}))


def finish_from_artifact(story_id_value: str, artifact_name: str = "final.mp4") -> None:
    """Mark a verified uploaded final video complete, even if a later queue step failed."""
    clear()
    CK.mkdir(parents=True, exist_ok=True)
    (CK / "done.json").write_text(json.dumps({
        "story_id": story_id_value,
        "completed_via": "workflow_artifact",
        "artifact": artifact_name,
    }, indent=2))
def clear() -> None:
    shutil.rmtree(CK, ignore_errors=True)
