"""Merge this run's data/history.json changes onto the newest origin/main version (no git conflicts).

Used by build.yml / daily.yml before pushing: both workflows append to or update history.json, and a plain rebase
conflicts when they touch the end of the same JSON list. Instead: take origin/main's file, then apply what THIS
run changed compared with the commit it started from (new entries appended, changed entries replaced).
  python pipeline/merge_history.py BASE OURS   (repo root, after `git fetch origin main`; BASE = history.json of
                                                the commit the run started from, OURS = this run's history.json)
"""
import json
import subprocess
import sys
from pathlib import Path

FILE = "data/history.json"


def _git_json(ref: str) -> list:
    p = subprocess.run(["git", "show", f"{ref}:{FILE}"], capture_output=True, text=True)
    return json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else []


def _key(e: dict) -> str:
    return json.dumps([e.get("date"), e.get("title"), e.get("source"), e.get("case")], ensure_ascii=False)


def merge(base: list, ours: list, theirs: list) -> list:
    base_by = {_key(e): e for e in base}
    out = list(theirs)
    index = {_key(e): i for i, e in enumerate(out)}
    for e in ours:
        k = _key(e)
        if k not in base_by:            # new in this run
            if k in index:
                out[index[k]] = e
            else:
                index[k] = len(out)
                out.append(e)
        elif e != base_by[k]:           # changed in this run (e.g. TikTok result added)
            if k in index:
                out[index[k]] = {**out[index[k]], **e}
            else:
                index[k] = len(out)
                out.append(e)
    return out


def _load(path: str) -> list:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() and p.read_text().strip() else []


def main() -> int:
    base = _load(sys.argv[1]) if len(sys.argv) > 1 else _git_json("HEAD")
    ours = _load(sys.argv[2]) if len(sys.argv) > 2 else _load(FILE)
    merged = merge(base, ours, _git_json("origin/main"))
    Path(FILE).write_text(json.dumps(merged, indent=2, ensure_ascii=False))
    print(f"history.json merged: {len(merged)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
