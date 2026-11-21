"""One-way export: Night Files asset library -> the shared local asset library (Venloud/vandam-assets).

Reads the "assets" release index.json (or a LIBRARY_DIR folder with --dir) and copies into $VANDAM_ASSET_LIBRARY
only the assets other projects may reuse:
  - not character_specific, no story subjects (a named person / creature never leaves Night Files)
  - not AI-generated
  - a licence vandam_assets verifies (CC0, PDM, CC BY, Pexels, Pixabay, Mixkit, Coverr); unknown / NC / ND / SA skipped
Never writes the Night Files library or its release. Downloads go through the local `gh` login (no token in code).
Dry run by default: prints what would be exported. --apply copies.

  python tools/export_shared_library.py [--dir LIBRARY_DIR] [--limit N] [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "Venloud/horror-shorts"
TAG = "assets"
PROJECT = "nightfiles"


def exportable(a: dict, license_key) -> tuple[bool, str]:
    if a.get("character_specific") or a.get("subjects"):
        return False, "story character"
    if a.get("source") in (None, "", "ai") or "ai-generated" in str(a.get("license", "")).lower():
        return False, "AI-generated"
    if a.get("kind") not in ("image", "video"):
        return False, f"kind {a.get('kind')!r}"
    if not a.get("url"):
        return False, "no source URL"
    if not license_key(a.get("license")):
        return False, f"licence not reusable: {a.get('license')!r}"
    return True, "ok"


def record(a: dict) -> dict:
    return {"kind": a["kind"], "provider": a["source"], "source_url": a["url"], "license": a["license"],
            "license_url": a.get("license_url") or None, "creator": a.get("author") or None,
            "attribution": a.get("attribution") or None, "title": a.get("title") or None,
            "description": a.get("description"), "tags": a.get("tags") or [],
            "era": a.get("era"), "nightfiles_id": a["id"]}


def fetch(name: str, dest: Path, src_dir: Path | None) -> bool:
    if src_dir:
        f = src_dir / name
        if not f.is_file():
            return False
        dest.write_bytes(f.read_bytes())
        return True
    r = subprocess.run(["gh", "release", "download", TAG, "--repo", REPO, "-p", name, "-O", str(dest), "--clobber"],
                       capture_output=True, text=True)
    return r.returncode == 0 and dest.is_file()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", type=Path, help="read a LIBRARY_DIR folder instead of the release")
    ap.add_argument("--limit", type=int, default=0, help="export at most N assets (0 = all)")
    ap.add_argument("--apply", action="store_true", help="copy (default: dry run)")
    args = ap.parse_args(argv)
    try:
        from vandam_assets import Library, license_key
    except ImportError:
        print("vandam_assets is not installed (pip install -e <vandam-assets checkout>)")
        return 2
    if args.apply and not os.environ.get("VANDAM_ASSET_LIBRARY"):
        print("Set VANDAM_ASSET_LIBRARY to the shared library folder")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="nf_export_"))
    if not fetch("index.json", tmp / "index.json", args.dir):
        print("Could not read the Night Files index.json")
        return 1
    assets = json.loads((tmp / "index.json").read_text(encoding="utf-8")).get("assets", [])
    lib = Library() if args.apply else None
    known = {r.get("nightfiles_id") for r in lib.records().values()} if lib else set()
    counts, done = {}, 0
    for a in assets:
        ok, why = exportable(a, license_key)
        if ok and a["id"] in known:
            ok, why = False, "already exported"
        counts[why] = counts.get(why, 0) + 1
        if not ok:
            continue
        if args.limit and done >= args.limit:
            counts["over --limit"] = counts.get("over --limit", 0) + 1
            continue
        done += 1
        print(f"{'export' if args.apply else 'would export'} {a['id']} {a['kind']} {a['source']} {a['license']!r}")
        if not args.apply:
            continue
        f = tmp / a["file"]
        if not fetch(a["file"], f, args.dir):
            print(f"  download failed: {a['file']}")
            counts["download failed"] = counts.get("download failed", 0) + 1
            continue
        rec = lib.add(f, record(a), PROJECT)
        print(f"  -> {rec['id'][:12]} {rec['rights_status']}")
    print(json.dumps({"assets": len(assets), **counts}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
