"""Hard check after push_state.sh: every video this run buffered (.built) or posted (.posted) must have its
history.json entry on origin/main. Missing = loud failure + ntfy (Oct 3-5: four posts never reached history,
so the same topic kept being picked). Usage (repo root, Actions): python pipeline/history_check.py
"""
import json
import subprocess
import sys

from common import ROOT, log


def _main_history() -> list[dict]:
    subprocess.run(["git", "fetch", "-q", "origin", "main"], cwd=ROOT, check=False)
    p = subprocess.run(["git", "show", "origin/main:data/history.json"], cwd=ROOT, capture_output=True, text=True)
    return json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else []


def problems(history: list[dict]) -> list[str]:
    out = []
    built = ROOT / ".built"
    if built.exists():
        stamp = built.read_text().strip()
        if not any(h.get("buffered") == stamp or h.get("date") == stamp for h in history):
            out.append(f"buffered video {stamp} has no history entry on main")
    posted = ROOT / ".posted"
    if posted.exists():
        p = json.loads(posted.read_text())
        if not any((h.get("buffered") == p["stamp"] or h.get("date") == p["stamp"]
                    or (p.get("story_id") and h.get("story_id") == p["story_id"])) and h.get("posted")
                   for h in history):
            out.append(f"posted video #{p.get('video_number')} ({p['stamp']}) has no posted history entry on main")
    return out


def main() -> int:
    if not ((ROOT / ".built").exists() or (ROOT / ".posted").exists()):
        log("History check: nothing buffered or posted in this run")
        return 0
    bad = problems(_main_history())
    if not bad:
        log("History check: every buffered/posted video of this run is in history.json on main")
        return 0
    msg = "; ".join(bad)
    log(f"HISTORY CHECK FAILED: {msg}")
    try:
        from notify import notify_text
        notify_text("Night Files: history NOT saved", msg + ". Topics may repeat until it's fixed.", warn=True)
    except Exception as e:  # noqa: BLE001
        log(f"History alert not sent ({e})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
