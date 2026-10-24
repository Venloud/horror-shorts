"""Build checkpoints: a failed build keeps its story, narration, shot list and images so the next run resumes the
SAME story and only redoes what is missing or invalid. Every run checks for one before picking a new story.

cache/checkpoint/ (Actions cache, key "ckpt-<story id>-<run id>", restored by prefix: buffer_fill.yml / daily.yml):
  manifest.json         {story_id, created_at, stages: {story | narration | shot_list | images: {at, files:
                        {relative path: sha256}}}, attempts: [{at, stage, error}]}
  story.json            the story (with its story_id)
  narration.wav/.json   the voiceover + word timings, tied to a hash of the narration text and speed
  images/               plates / inserts / the explainer storyboard, registered as soon as each one passes
  done.json             written ONLY after the final video passed validation AND entered the buffer
Every file is written atomically (temp file -> re-read + sha256 check -> rename). On resume the hashes are checked:
a corrupt or changed stage is dropped and redone, never trusted; a checkpoint of another story is cleared.

Failures: each failed run adds an attempt (stage + error). After MAX_ATTEMPTS the story is parked in
data/failed_stories/<story_id>/ (story, narration timings, shot list, validated asset list, attempts) and the next
run starts a new story; buffer_fill.yml's retry_story_id input brings it back. Parked stories are not "used" in
history and are never posted.
"""
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT, log

CK = ROOT / "cache" / "checkpoint"
IMAGES = CK / "images"
FAILED = ROOT / "data" / "failed_stories"
MAX_ATTEMPTS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def story_id(story: dict) -> str:
    key = "|".join(str(story.get(k) or "") for k in ("title", "mode", "source", "case"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_atomic(path: Path, data: str | bytes) -> None:
    """temp file in the same folder -> fsync -> re-read and compare sha256 -> rename over the target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = data.encode("utf-8") if isinstance(data, str) else data
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    if sha256(tmp) != hashlib.sha256(raw).hexdigest():
        tmp.unlink(missing_ok=True)
        raise OSError(f"checkpoint write of {path.name} did not verify")
    os.replace(tmp, path)


def _copy_atomic(src: Path, dest: Path) -> None:
    write_atomic(dest, Path(src).read_bytes())


# ---------------------------------------------------------------- manifest

def _mf_path() -> Path:
    return CK / "manifest.json"


def manifest() -> dict:
    try:
        return json.loads(_mf_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_manifest(m: dict) -> None:
    write_atomic(_mf_path(), json.dumps(m, indent=1, ensure_ascii=False))


def _rel(path: Path) -> str | None:
    try:
        return Path(path).resolve().relative_to(CK.resolve()).as_posix()
    except ValueError:
        return None


def commit(stage: str, files: list[Path], replace: bool = True, **data) -> None:
    """Record a finished stage: its files' sha256 (paths inside the checkpoint only) + when + small extra data."""
    m = manifest()
    if not m.get("story_id"):
        return
    st = {"at": _now(), "files": {}} if replace else m.get("stages", {}).get(stage) or {"at": _now(), "files": {}}
    for f in files:
        rel = _rel(f)
        if rel and Path(f).exists():
            st["files"][rel] = sha256(f)
    st["at"] = _now()
    st.update(data)
    m.setdefault("stages", {})[stage] = st
    _save_manifest(m)


def register_image(path: Path, stage: str = "images") -> None:
    """A plate / insert / storyboard that passed: add it to the manifest (no-op outside the checkpoint)."""
    if _rel(path):
        commit(stage, [Path(path)], replace=False)


def verify() -> dict:
    """Check every recorded file against its sha256. A bad story stage = the checkpoint is unusable (False); a bad
    narration / shot list drops that stage; a bad image is deleted on its own. Unrecorded images that don't open are
    deleted too. Returns {"ok": bool, "dropped": [...], "kept": n}."""
    m = manifest()
    out = {"ok": True, "dropped": [], "kept": 0}
    for stage, st in list((m.get("stages") or {}).items()):
        bad = [rel for rel, h in st.get("files", {}).items()
               if not (CK / rel).exists() or sha256(CK / rel) != h]
        if not bad:
            out["kept"] += len(st.get("files", {}))
            continue
        if stage == "story":
            out["ok"] = False
            out["dropped"].append("story")
            return out
        if stage in ("images", "shot_list"):
            for rel in bad:
                (CK / rel).unlink(missing_ok=True)
                st["files"].pop(rel, None)
                out["dropped"].append(rel)
            out["kept"] += len(st["files"])
        else:
            for rel in st.get("files", {}):
                (CK / rel).unlink(missing_ok=True)
            m["stages"].pop(stage)
            out["dropped"].append(stage)
    known = set((m.get("stages") or {}).get("images", {}).get("files", {}))
    if IMAGES.exists():
        from PIL import Image
        for f in IMAGES.glob("*.png"):
            if _rel(f) in known:
                continue
            try:
                with Image.open(f) as im:
                    im.verify()
            except Exception:  # noqa: BLE001
                f.unlink(missing_ok=True)
                out["dropped"].append(_rel(f))
    if m:
        _save_manifest(m)
    return out


# ---------------------------------------------------------------- lifecycle

def resume(history: list[dict], buffered: set | None = None) -> dict | None:
    """The unfinished story of an earlier run, verified; None (and the checkpoint cleared) when it was finished,
    is already in history / the buffer, belongs to another story (stale manifest) or its story file is corrupt."""
    f = CK / "story.json"
    if (CK / "done.json").exists() or not f.exists():
        return None
    try:
        story = json.loads(f.read_text())
    except (OSError, ValueError):
        log("Checkpoint story.json is unreadable: cleared, starting a new story")
        clear()
        return None
    sid = story.get("story_id")
    m = manifest()
    if not m:  # checkpoint from before the manifest (Oct 23): adopt it, its images are checked by opening them
        m = {"story_id": sid, "created_at": _now(), "stages": {}, "attempts": []}
        _save_manifest(m)
        commit("story", [f])
    if not sid or m.get("story_id") != sid:
        log(f"Checkpoint is stale (manifest story {m.get('story_id')} vs story.json {sid}): cleared")
        clear()
        return None
    used = {h.get("story_id") for h in history if not h.get("parked")} | \
        {(h.get("title"), h.get("mode")) for h in history if not h.get("parked")}
    if sid in used or (story.get("title"), story.get("mode")) in used or sid in (buffered or set()):
        log(f"Checkpoint story {sid} is already buffered / in history: no second video, checkpoint closed")
        finish(story)
        return None
    v = verify()
    if not v["ok"]:
        log("Checkpoint story.json does not match its sha256 (corrupt): cleared, starting a new story")
        clear()
        return None
    n = len(list(IMAGES.glob("x_*.png"))) + len(list(IMAGES.glob("scene_*.png"))) if IMAGES.exists() else 0
    log(f"Resuming checkpoint '{story.get('title')}' ({sid}), attempt {len(m.get('attempts', [])) + 1}: {n} images "
        f"kept{', narration kept' if (CK / 'narration.wav').exists() else ''}"
        + (f"; dropped (corrupt): {', '.join(v['dropped'])}" if v["dropped"] else ""))
    return story


def start(story: dict) -> None:
    """New story: wipe any old checkpoint and save this one."""
    clear()
    story["story_id"] = story.get("story_id") or story_id(story)
    CK.mkdir(parents=True, exist_ok=True)
    _save_manifest({"story_id": story["story_id"], "created_at": _now(), "stages": {}, "attempts": []})
    save_story(story)


def save_story(story: dict) -> None:
    CK.mkdir(parents=True, exist_ok=True)
    if not manifest().get("story_id"):
        story["story_id"] = story.get("story_id") or story_id(story)
        _save_manifest({"story_id": story["story_id"], "created_at": _now(), "stages": {}, "attempts": []})
    write_atomic(CK / "story.json", json.dumps(story, ensure_ascii=False, indent=1))
    commit("story", [CK / "story.json"])


def _narr_hash(story: dict, speed: float) -> str:
    text = "\n".join(s.get("narration", "") for s in story.get("scenes", []))
    return hashlib.sha1(f"{speed:.3f}|{text}".encode("utf-8")).hexdigest()[:16]


def save_narration(story: dict, narration: dict) -> None:
    CK.mkdir(parents=True, exist_ok=True)
    _copy_atomic(narration["path"], CK / "narration.wav")
    meta = {k: v for k, v in narration.items() if k != "path"}
    meta["hash"] = _narr_hash(story, narration.get("speed", 1.0))
    write_atomic(CK / "narration.json", json.dumps(meta, default=str))
    commit("narration", [CK / "narration.wav", CK / "narration.json"])


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


def drop_narration() -> None:
    """A duration failure: the narration is re-fitted next time."""
    for f in ("narration.wav", "narration.json"):
        (CK / f).unlink(missing_ok=True)
    m = manifest()
    if m.get("stages", {}).pop("narration", None) is not None:
        _save_manifest(m)


# ---------------------------------------------------------------- failures, parking, retry

def record_failure(stage: str, error: str) -> int:
    """One failed run of the checkpoint's story: returns the number of failed attempts so far."""
    m = manifest()
    if not m.get("story_id"):
        return 0
    m.setdefault("attempts", []).append({"at": _now(), "stage": stage, "error": str(error)[:600]})
    _save_manifest(m)
    return len(m["attempts"])


def failed_attempt(story: dict, stage: str, error: str) -> bool:
    """main.py: count a failed run of the checkpoint's story; at MAX_ATTEMPTS park it in data/failed_stories and send
    the ntfy alert (the next run starts a new story). True when it was parked."""
    if not manifest().get("story_id"):
        return False
    n = record_failure(stage, error)
    log(f"Story {story.get('story_id')}: failed attempt {n}/{MAX_ATTEMPTS} at stage {stage}")
    if n < MAX_ATTEMPTS:
        return False
    dest = park(story)
    try:
        from notify import notify_text
        notify_text(f"Night Files: story {story.get('story_id')} parked after {n} fails at stage {stage}",
                    f"'{story.get('title')}': {error[:300]}\nSaved in {dest.relative_to(ROOT)}. Retry it with "
                    f"buffer_fill.yml input retry_story_id={story.get('story_id')}.", warn=True)
    except Exception as e:  # noqa: BLE001
        log(f"Parked-story alert not sent ({e})")
    return True


def attempts() -> list[dict]:
    return manifest().get("attempts", [])


def _export(story: dict, dest: Path, status: str, reason: str) -> Path:
    """data/failed_stories/<id>/: story, narration timings, shot list, validated assets, attempts, status."""
    dest.mkdir(parents=True, exist_ok=True)
    m = manifest()
    write_atomic(dest / "story.json", json.dumps(story, ensure_ascii=False, indent=1))
    if (CK / "narration.json").exists():
        shutil.copy(CK / "narration.json", dest / "narration.json")
    board = IMAGES / "explainer_storyboard.json"
    if board.exists():
        shutil.copy(board, dest / "shot_list.json")
    files = {rel: h for st in (m.get("stages") or {}).values() for rel, h in st.get("files", {}).items()}
    write_atomic(dest / "assets.json", json.dumps({"validated": files}, indent=1))
    write_atomic(dest / "attempts.json", json.dumps(m.get("attempts", []), indent=1))
    last = (m.get("attempts") or [{}])[-1]
    write_atomic(dest / "status.json", json.dumps({
        "story_id": story.get("story_id"), "title": story.get("title"), "status": status, "reason": reason,
        "at": _now(), "last_stage": last.get("stage"), "last_error": last.get("error")}, indent=1))
    return dest


def park(story: dict) -> Path:
    """After MAX_ATTEMPTS fails: move the story to data/failed_stories/<id>/ and clear the checkpoint."""
    sid = story.get("story_id") or manifest().get("story_id")
    last = (attempts() or [{}])[-1]
    dest = _export(story, FAILED / sid, "parked", f"{len(attempts())} failed attempts")
    clear()
    log(f"Story {sid} parked after {MAX_ATTEMPTS} failed attempts (last at stage {last.get('stage')}): {dest}")
    return dest


def retry(sid: str) -> dict:
    """buffer_fill.yml retry_story_id: make <sid> the active checkpoint (the restored cache entry if it is that
    story, else data/failed_stories/<sid>/story.json) with its attempt count reset. Another unfinished story in the
    checkpoint is shelved to data/failed_stories first so it can be retried by id too."""
    sid = sid.strip()
    cur = None
    try:
        cur = json.loads((CK / "story.json").read_text()) if not (CK / "done.json").exists() else None
    except (OSError, ValueError):
        cur = None
    if cur and cur.get("story_id") == sid and manifest().get("story_id") == sid:
        m = manifest()
        m["attempts_before_retry"] = m.get("attempts_before_retry", []) + m.get("attempts", [])
        m["attempts"] = []
        _save_manifest(m)
        log(f"Retry {sid}: resuming its checkpoint (attempts reset)")
        return cur
    parked = FAILED / sid / "story.json"
    if not parked.exists():
        raise RuntimeError(f"retry_story_id {sid}: no parked story in data/failed_stories and no checkpoint of it")
    if cur and cur.get("story_id"):
        _export(cur, FAILED / cur["story_id"], "shelved", f"shelved for the retry of {sid}")
        log(f"Retry {sid}: the unfinished story {cur['story_id']} was shelved to data/failed_stories")
    story = json.loads(parked.read_text())
    start(story)
    status = FAILED / sid / "status.json"
    st = json.loads(status.read_text()) if status.exists() else {}
    write_atomic(status, json.dumps({**st, "status": "retrying", "retry_at": _now()}, indent=1))
    log(f"Retry {sid}: '{story.get('title')}' restored from data/failed_stories (narration and images are redone "
        "unless the restored cache still has them)")
    return story


def finish(story: dict) -> None:
    """The final video passed validation AND is in the buffer: drop the heavy files, leave a marker so this story is
    never resumed; a parked / shelved copy is marked recovered."""
    sid = story.get("story_id")
    clear()
    CK.mkdir(parents=True, exist_ok=True)
    write_atomic(CK / "done.json", json.dumps({"story_id": sid, "at": _now()}))
    status = FAILED / str(sid) / "status.json"
    if sid and status.exists():
        st = json.loads(status.read_text())
        write_atomic(status, json.dumps({**st, "status": "recovered", "recovered_at": _now()}, indent=1))


def clear() -> None:
    shutil.rmtree(CK, ignore_errors=True)
