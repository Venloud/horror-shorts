"""Public Night Files channel snapshot: subscribers, video count and every listed Short's view count, read from the
public YouTube channel page (no login, no API key, no AI). Appends one JSON line to data/growth/snapshots.jsonl so
growth can be measured per video and per day. Run: python tools/channel_snapshot.py [--handle @MonkeyTellsStories]

Public page numbers are rounded by YouTube ("1.2K views") and lag a little; they are a baseline, not Studio analytics.
"""
import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "growth" / "snapshots.jsonl"


def _count(text: str | None) -> int | None:
    """'1.2K views' -> 1200, 'No views' -> 0, '33 subscribers' -> 33."""
    if not text:
        return None
    if text.lower().startswith("no "):
        return 0
    m = re.match(r"([\d.,]+)\s*([KMB]?)", text.strip(), flags=re.I)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return int(round(n * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2).upper()]))


def _page(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def parse(html: str) -> dict:
    subs = re.search(r"([\d.,]+[KMB]?) subscribers?", html)
    vids = max((_count(v) or 0 for v in re.findall(r"[\d.,]+[KMB]? videos", html)), default=None)  # header count
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", html)
    shorts = []

    def walk(o):
        if isinstance(o, dict):
            v = o.get("shortsLockupViewModel")
            if v:
                meta = v.get("overlayMetadata", {})
                vid = (v.get("onTap", {}).get("innertubeCommand", {}).get("reelWatchEndpoint", {}).get("videoId"))
                views = meta.get("secondaryText", {}).get("content")
                shorts.append({"id": vid, "title": meta.get("primaryText", {}).get("content"),
                               "views": _count(views), "views_text": views})
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    if m:
        walk(json.loads(m.group(1)))
    return {"subscribers": _count(subs.group(0)) if subs else None,
            "videos": vids, "shorts": shorts}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--handle", default="@MonkeyTellsStories")
    ap.add_argument("--dry-run", action="store_true", help="print, do not append")
    a = ap.parse_args()
    snap = parse(_page(f"https://www.youtube.com/{a.handle}/shorts"))
    snap = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "handle": a.handle, **snap}
    if not snap["shorts"] and snap["subscribers"] is None:
        print("Channel page could not be read (layout changed?)", file=sys.stderr)
        return 1
    views = [s["views"] for s in snap["shorts"] if s["views"] is not None]
    print(f"{snap['at']}: {snap['subscribers']} subscribers, {snap['videos']} videos, {len(views)} Shorts listed, "
          f"median views {sorted(views)[len(views) // 2] if views else '-'}")
    if not a.dry_run:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(snap, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
