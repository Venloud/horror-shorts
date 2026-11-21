"""Night Files editing memory: the editor gets better after every video.

Every editing technique (camera moves, transitions, overlay effects) has a weight, 1.0 to start. After each video
(main.py, next to hollywood.learn) the techniques it used are recorded; then three signals move the weights:
  - automatic QA: a technique on screen when a QA check failed loses weight (qa_penalty)
  - the owner's verdict: `python pipeline/edit_memory.py approve|reject <story_id>` (+/- verdict_step)
  - audience: data/analytics.json (YouTube) or data/buffer_metrics.json rows {story_id, views, retention}
    -- a video above the channel median raises the weight of what it used, below lowers it (metric_step)
The renderer reads the weights: a technique's per-video cap scales with its weight, and below `off_below` it is
not used at all until a later signal brings it back. Nothing is hard-coded per story: only weights per technique.
Stored in data/hollywood/memory.json under "editing" (already saved back to main after every run).
"""
import json
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# NIGHT_FILES_EDIT_MEMORY points a local test at its own file; record() learns only in a real run (GitHub
# Actions) or when that variable is set, so unit tests never change the production memory.
MEMORY = Path(os.environ.get("NIGHT_FILES_EDIT_MEMORY") or ROOT / "data" / "hollywood" / "memory.json")


def _learning() -> bool:
    return bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("NIGHT_FILES_EDIT_MEMORY"))
STEP = {"qa_penalty": 0.15, "verdict_step": 0.2, "metric_step": 0.1}
LO, HI, OFF_BELOW = 0.2, 2.0, 0.45


def _load() -> dict:
    try:
        return json.loads(MEMORY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"videos": 0, "entries": {}, "places": {}, "unmatched": {}, "log": []}


def _save(mem: dict) -> None:
    MEMORY.parent.mkdir(parents=True, exist_ok=True)
    MEMORY.write_text(json.dumps(mem, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def editing(mem: dict | None = None) -> dict:
    mem = _load() if mem is None else mem
    ed = mem.setdefault("editing", {})
    ed.setdefault("weights", {})
    ed.setdefault("videos", {})
    ed.setdefault("history", [])
    return ed


def weight(technique: str, mem: dict | None = None) -> float:
    return float(editing(mem)["weights"].get(technique, 1.0))


def allowed(technique: str, base_cap: int, mem: dict | None = None) -> int:
    """How many times this technique may appear in one video: base cap scaled by what has worked."""
    w = weight(technique, mem)
    if w < OFF_BELOW:
        return 0
    return max(1, round(base_cap * w)) if base_cap > 0 else 0


def techniques(story: dict, segs: list[dict] | None = None) -> dict:
    """{technique: count} used in a finished video."""
    out: dict = {}
    for e in story.get("explainer_effects") or []:
        k = "fx:" + str(e.get("kind"))
        out[k] = out.get(k, 0) + 1
    for s in segs or story.get("explainer_segments") or []:
        for pre, key in (("move:", "motion"), ("cut:", "transition")):
            v = s.get(key)
            if v:
                out[pre + v] = out.get(pre + v, 0) + 1
    return out


def _nudge(ed: dict, used, delta: float, why: str, ref: str) -> None:
    for t in used:
        w = min(HI, max(LO, float(ed["weights"].get(t, 1.0)) + delta))
        ed["weights"][t] = round(w, 3)
    ed["history"].append({"ref": ref, "why": why, "delta": delta, "techniques": sorted(used)})
    ed["history"] = ed["history"][-200:]


def record(story: dict, segs: list[dict] | None = None, qa_failures: list | None = None, stamp: str = "") -> dict:
    """After a video: remember what it used; QA failures penalise what was on screen. Never raises."""
    if not _learning():
        return techniques(story, segs)
    try:
        mem = _load()
        ed = editing(mem)
        used = techniques(story, segs)
        key = str(story.get("story_id") or stamp or len(ed["videos"]))
        ed["videos"][key] = {"stamp": stamp, "title": story.get("title"), "used": used, "verdict": None,
                             "metric": None}
        if len(ed["videos"]) > 120:
            for old in list(ed["videos"])[:-120]:
                ed["videos"].pop(old)
        if qa_failures:
            _nudge(ed, used, -STEP["qa_penalty"], "qa: " + "; ".join(map(str, qa_failures))[:160], key)
        _save(mem)
        return used
    except Exception as e:  # noqa: BLE001
        print(f"Editing memory not updated ({e})")
        return {}


def verdict(story_id: str, approved: bool) -> None:
    mem = _load()
    ed = editing(mem)
    v = ed["videos"].get(story_id)
    if v is None:
        raise SystemExit(f"no video {story_id!r} in editing memory")
    if v.get("verdict") is not None:  # changing your mind undoes the earlier verdict first
        _nudge(ed, v["used"], -STEP["verdict_step"] if v["verdict"] else STEP["verdict_step"], "undo", story_id)
    v["verdict"] = bool(approved)
    _nudge(ed, v["used"], STEP["verdict_step"] if approved else -STEP["verdict_step"],
           "owner " + ("approved" if approved else "rejected"), story_id)
    _save(mem)


def learn_metrics(rows: list[dict]) -> int:
    """rows: [{"story_id", "retention" (avg % viewed) or "views"}]. Each video is scored once, against the median
    of the rows given. Returns how many videos moved weights."""
    mem = _load()
    ed = editing(mem)
    score = lambda r: float(r.get("retention") if r.get("retention") is not None else r.get("views") or 0)  # noqa: E731
    known = [r for r in rows if str(r.get("story_id")) in ed["videos"]]
    if len(known) < 3:
        return 0
    med = statistics.median(score(r) for r in known)
    moved = 0
    for r in known:
        v = ed["videos"][str(r["story_id"])]
        if v.get("metric") is not None or score(r) == med:
            continue
        v["metric"] = score(r)
        _nudge(ed, v["used"], STEP["metric_step"] if score(r) > med else -STEP["metric_step"],
               f"audience {score(r):.1f} vs median {med:.1f}", str(r["story_id"]))
        moved += 1
    _save(mem)
    return moved


def learn_from_files() -> int:
    """Read data/buffer_metrics.json and data/analytics.json if present (rows with story_id)."""
    rows = []
    for name in ("buffer_metrics.json", "analytics.json"):
        try:
            data = json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = data.get("videos", data) if isinstance(data, dict) else data
        for r in items if isinstance(items, list) else []:
            if isinstance(r, dict) and r.get("story_id"):
                rows.append({"story_id": r["story_id"],
                             "retention": r.get("retention", r.get("averageViewPercentage")),
                             "views": r.get("views")})
    return learn_metrics(rows) if rows else 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd in ("approve", "reject"):
        verdict(sys.argv[2], cmd == "approve")
    elif cmd == "metrics":
        print("videos scored:", learn_from_files())
    w = editing()["weights"]
    print(json.dumps(dict(sorted(w.items(), key=lambda kv: -kv[1])), indent=1))
