"""Daily feature-freeze summary (freeze_summary.yml, ~9 PM New York): what the bot did in the last 24 hours.

Posts (number, title, YouTube privacy / TikTok result), builds (buffered / skipped / failed runs), the buffer,
missed slots, the production hold and yesterday's Cloudflare use. Sent as one ntfy alert and appended to
data/freeze_log.md (the workflow commits it). The freeze lasts 7 days from the date in that file's header; after
that the script only says so and stops.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests

from common import ROOT, load_history, log

LOG = ROOT / "data" / "freeze_log.md"
DAYS = 7


def _when(stamp: str | None) -> datetime | None:
    try:
        return datetime.strptime(stamp or "", "%Y-%m-%d_%H%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _runs(since: datetime, workflow: str = "buffer_fill.yml") -> list[dict]:
    """Runs of one workflow in the last 24 h (GitHub API, the workflow's own token). build.yml is gone since Oct 2:
    buffer_fill.yml builds, daily.yml builds only when the buffer is empty and then posts."""
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not (repo and token):
        return []
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/runs", timeout=30,
                         headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                         params={"created": f">={since.strftime('%Y-%m-%dT%H:%M:%SZ')}", "per_page": 50})
        return r.json().get("workflow_runs", []) if r.ok else []
    except Exception as e:  # noqa: BLE001
        log(f"Build runs not readable ({e})")
        return []


def summary(now: datetime | None = None) -> tuple[str, str] | None:
    now = now or datetime.now(timezone.utc)
    head = LOG.read_text() if LOG.exists() else ""
    m = re.search(r"Freeze start: (\d{4}-\d{2}-\d{2})", head)
    start = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc) if m else now
    day = (now - start).days + 1
    if day > DAYS + 1:
        log(f"Feature freeze ended ({start:%Y-%m-%d} + {DAYS} days): no summary")
        return None
    since = now - timedelta(hours=24)
    hist = load_history()
    lines = []
    posts = [h for h in hist if (_when(h.get("posted")) or since) > since]
    for h in posts:
        yt = h.get("youtube") or {}
        tt = h.get("tiktok") or {}
        lines.append(f"Posted #{h.get('video_number')} {h.get('title')} ({h.get('mode')}): YouTube "
                     + (f"{yt.get('privacy')} {yt.get('url')}" if yt.get("url") else
                        "PAUSED (pending)" if yt.get("pending") else f"FAILED {yt.get('error', '')[:60]}")
                     + "; TikTok " + ("FAILED" if tt.get("error") else "ok"))
    if not posts:
        lines.append("Posted: nothing in the last 24 h")
    buffered = [h for h in hist if (_when(h.get("buffered")) or since) > since and not h.get("skipped")]
    skipped = [h for h in hist if h.get("skipped") and (_when(h.get("date")) or since) > since]
    for h in buffered:
        vs = h.get("visual_sources") or {}
        lines.append(f"Built: {h.get('title')} ({h.get('mode')}, writer {h.get('writer')}, critic "
                     f"{h.get('critic_score')}, {vs.get('ai', '?')} AI / {vs.get('archive_stock', '?')} real"
                     + (", LOW-QUOTA" if h.get("low_quota") else "") + ")")
    for h in skipped:
        lines.append(f"Skipped for good: {h.get('title')}: {str(h.get('reason'))[:120]}")
    for wf, label in (("buffer_fill.yml", "Build runs (buffer_fill.yml)"), ("daily.yml", "Slot runs (daily.yml)")):
        runs = _runs(since, wf)
        fails = [r for r in runs if r.get("conclusion") == "failure"]
        lines.append(f"{label}: {len(runs)} ({len(fails)} failed"
                     + (": " + ", ".join(r["html_url"].rsplit("/", 1)[-1] for r in fails[:5]) if fails else "") + ")")
    try:
        import buffer
        lines.append(f"Buffer now: {buffer.count()} video(s)")
    except Exception as e:  # noqa: BLE001
        lines.append(f"Buffer: not readable ({str(e)[:80]})")
    missed = ROOT / "data" / "missed_slot.json"
    if missed.exists():
        try:
            lines.append(f"Missed slot waiting for a make-up: {json.loads(missed.read_text()).get('slot')}")
        except ValueError:
            pass
    if (ROOT / "data" / "hold_builds.txt").exists():
        lines.append("Production HOLD is ON (data/hold_builds.txt)")
    try:
        import cf_budget
        yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        lines.append(f"Cloudflare {yday} UTC: {cf_budget.day_line(yday)}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"Cloudflare: no ledger ({str(e)[:60]})")
    title = f"Night Files freeze day {min(day, DAYS)}/{DAYS}" + (" (last day)" if day >= DAYS else "")
    return title, "\n".join(lines)


def main() -> int:
    got = summary()
    if not got:
        return 0
    title, body = got
    log(f"{title}\n{body}")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n## {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC: {title}\n"
                + "".join(f"- {x}\n" for x in body.splitlines()))
    try:
        from notify import notify_text
        notify_text(title, body)
    except Exception as e:  # noqa: BLE001
        log(f"Summary alert not sent ({e})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
