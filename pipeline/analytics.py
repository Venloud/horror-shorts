"""Daily YouTube Shorts analytics (analytics.yml): per-Short stats from the YouTube Analytics API, matched to our
own history (video_number, mode, visual_mode, story shape, writer), saved to data/analytics.json.

Needs the refresh token to include the scope https://www.googleapis.com/auth/yt-analytics.readonly (re-run
connect_youtube.py once; it now asks for it). Without it: logs "analytics scope missing" and exits 0. Any other
API / token failure: prints the exact error and exits 1 (red run).
Flag analytics (on). Never touches history.json, the buffer or any posting.
"""
import json
import sys
from datetime import date, datetime, timezone

import requests

from common import CONFIG, ROOT, env, load_history, log

API = "https://youtubeanalytics.googleapis.com/v2/reports"
METRICS = ["views", "engagedViews", "averageViewDuration", "averageViewPercentage", "likes", "comments", "shares",
           "subscribersGained"]
OUT = ROOT / "data" / "analytics.json"


def _token() -> str:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    creds = Credentials(None, refresh_token=env("YT_REFRESH_TOKEN"), client_id=env("YT_CLIENT_ID"),
                        client_secret=env("YT_CLIENT_SECRET"), token_uri="https://oauth2.googleapis.com/token")
    creds.refresh(Request())  # no scopes asked: the token keeps whatever it was granted
    return creds.token


def _report(token: str, start: str, end: str) -> dict:
    r = requests.get(API, timeout=60, headers={"Authorization": f"Bearer {token}"}, params={
        "ids": "channel==MINE", "startDate": start, "endDate": end, "metrics": ",".join(METRICS),
        "dimensions": "video", "filters": "creatorContentType==SHORTS", "sort": "-views", "maxResults": 200})
    if r.status_code == 403 and any(k in r.text for k in ("insufficient", "SCOPE", "scope", "Permission")):
        raise PermissionError(r.text[:300])
    if r.status_code != 200:
        raise RuntimeError(f"YouTube Analytics HTTP {r.status_code}: {r.text[:3000]}")
    return r.json()


def _summary(rows: list[dict], key: str) -> dict:
    out: dict = {}
    for row in rows:
        k = str(row.get(key) or "unknown")
        g = out.setdefault(k, {"videos": 0, "views": 0, "engagedViews": 0, "_pct": 0.0})
        g["videos"] += 1
        g["views"] += row.get("views", 0)
        g["engagedViews"] += row.get("engagedViews", 0)
        g["_pct"] += row.get("averageViewPercentage", 0)
    for g in out.values():
        g["avgViewPercentage"] = round(g.pop("_pct") / max(1, g["videos"]), 1)
        g["avgViews"] = round(g["views"] / max(1, g["videos"]), 1)
    return out


def main() -> int:
    if not CONFIG.get("analytics", True):
        log("Analytics: off (config analytics)")
        return 0
    if not all(env(k, required=False) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")):
        log("Analytics: YouTube secrets missing, nothing to do")
        return 0
    try:
        token = _token()
        data = _report(token, CONFIG.get("analytics_start", "2026-09-01"), date.today().isoformat())
    except PermissionError as e:
        log(f"analytics scope missing: re-run connect_youtube.py to add yt-analytics.readonly ({str(e)[:160]})")
        return 0
    except Exception as e:  # noqa: BLE001 (a real failure: red run with the exact error)
        log(f"Analytics FAILED, nothing saved. {type(e).__name__}: {e}")
        return 1
    cols = [c["name"] for c in data.get("columnHeaders", [])]
    by_id = {}
    for h in load_history():
        vid = (h.get("youtube") or {}).get("id") if isinstance(h.get("youtube"), dict) else None
        if vid:
            by_id[vid] = h
    rows = []
    for values in data.get("rows") or []:
        row = dict(zip(cols, values))
        h = by_id.get(row.get("video"), {})
        row.update({"video_number": h.get("video_number"), "title": h.get("title"), "mode": h.get("mode"),
                    "visual_mode": h.get("visual_mode"), "story_shape": h.get("story_shape"),
                    "writer": h.get("writer"), "true_story": h.get("true_story"), "posted": h.get("posted"),
                    "yt_title": h.get("yt_title"), "hashtags": h.get("hashtags")})
        rows.append(row)
    OUT.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "videos": rows,
        "by_mode": _summary(rows, "mode"),
        "by_visual_mode": _summary(rows, "visual_mode"),
        # one row per hashtag a video carried (packaging.py videos only): which tags go with more views
        "by_hashtag": _summary([{**r, "tag": t} for r in rows for t in r.get("hashtags") or []], "tag"),
    }, indent=2, ensure_ascii=False) + "\n")
    log(f"Analytics: {len(rows)} Shorts saved to data/analytics.json "
        f"({sum(1 for r in rows if r.get('video_number'))} matched to our video numbers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
