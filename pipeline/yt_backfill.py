"""YouTube backfill (yt_backfill.yml): videos that went out on TikTok before the YouTube upload worked get uploaded
to YouTube Shorts, at most 1 per run / config yt_backfill_per_day (3) per day, oldest first.

State: data/backfill.json (inventory + uploaded / skipped + reason), so nothing uploads twice.
  python yt_backfill.py stash   -> copy every queued video out of its build artifact (kept only 7 days) into the
                                   GitHub release "backfill" (<stamp>.mp4 + <stamp>.json). No YouTube calls.
  python yt_backfill.py upload  -> one upload, only when:
     - data/tiktok_posted.txt exists (the owner's list of videos he actually PUBLISHED on TikTok, one title or
       caption per line). Without it the backfill is paused (a TikTok publish_id only means "sent to drafts").
     - not within 60 min of a publish slot (daily.yml crons) or a post in history.json, and no daily.yml run active.
     - fewer than yt_backfill_per_day backfill uploads today (UTC).
     - the title isn't on the channel already (history ids, backfill.json, the channel's uploads when the token
       may list them).
     - the mp4 passes render.qa_gate(backfill=True): visuals / frozen frames, audio, loudness, size; the 61 s
       floor is not applied to these older videos (Shorts take them).
     Title / description / tags: the same as daily posts (notify.caption_text + youtube.upload).
When nothing is left to upload, the workflow disables itself. Never touches history.json, counter.json, the
buffer or TikTok.
"""
import json
import os
import re
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

import requests

from common import CONFIG, ROOT, load_history, log

STATE = ROOT / "data" / "backfill.json"
POSTED = ROOT / "data" / "tiktok_posted.txt"
TAG = "backfill"
API = "https://api.github.com"
MATCH_MIN = 0.6
GAP = timedelta(minutes=60)
STOP = set("a an and the of in on at to for from is was were be it its this that what who why how did do you your "
           "would could my me i he she they we his her their story legend true".split())


# ---------- GitHub ----------

def _repo() -> str:
    return os.environ["GITHUB_REPOSITORY"]


def _h(extra: dict | None = None) -> dict:
    h = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    h.update(extra or {})
    return h


def _release(create: bool = False) -> dict | None:
    r = requests.get(f"{API}/repos/{_repo()}/releases/tags/{TAG}", headers=_h(), timeout=30)
    if r.status_code == 200:
        return r.json()
    if r.status_code != 404 or not create:
        if r.status_code != 404:
            raise RuntimeError(f"release lookup: HTTP {r.status_code} {r.text[:200]}")
        return None
    r = requests.post(f"{API}/repos/{_repo()}/releases", headers=_h(), timeout=30, json={
        "tag_name": TAG, "name": TAG, "prerelease": True,
        "body": "YouTube backfill: old TikTok videos waiting for their YouTube upload (yt_backfill.yml). "
                "Managed by the bot; assets are deleted once uploaded."})
    if r.status_code not in (200, 201):
        raise RuntimeError(f"release create: HTTP {r.status_code} {r.text[:200]}")
    return r.json()


def _assets() -> dict:
    rel = _release()
    return {a["name"]: a for a in (rel or {}).get("assets", [])}


def _upload_asset(rel: dict, name: str, path: Path, ctype: str) -> None:
    base = rel["upload_url"].split("{")[0]
    with open(path, "rb") as f:
        r = requests.post(f"{base}?name={name}", data=f, timeout=900, headers=_h({"Content-Type": ctype}))
    if r.status_code not in (200, 201):
        raise RuntimeError(f"asset upload {name}: HTTP {r.status_code} {r.text[:200]}")


def _download_asset(asset: dict, dest: Path) -> None:
    with requests.get(asset["url"], headers=_h({"Accept": "application/octet-stream"}), stream=True,
                      timeout=900) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def _delete_asset(asset: dict) -> None:
    requests.delete(asset["url"], headers=_h(), timeout=30)


def _runs_active(workflow: str) -> bool:
    for status in ("in_progress", "queued"):
        r = requests.get(f"{API}/repos/{_repo()}/actions/workflows/{workflow}/runs", headers=_h(),
                         params={"status": status, "per_page": 5}, timeout=30)
        if r.status_code == 200 and r.json().get("total_count"):
            return True
    return False


def _disable_self() -> None:
    r = requests.put(f"{API}/repos/{_repo()}/actions/workflows/yt_backfill.yml/disable", headers=_h(), timeout=30)
    log("yt_backfill.yml disabled (backfill done)" if r.status_code == 204
        else f"Could not disable yt_backfill.yml (HTTP {r.status_code}); it will keep exiting early")


# ---------- state ----------

def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"videos": []}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- stash: artifact -> release ----------

def stash(state: dict) -> None:
    """Copy queued videos out of their 7-day build artifacts into the "backfill" release (idempotent)."""
    have = _assets()
    rel = None
    for v in state["videos"]:
        if v["status"] != "queued":
            continue
        if f"{v['stamp']}.mp4" in have and f"{v['stamp']}.json" in have:
            v["stashed"] = True
            continue
        log(f"Stashing {v['stamp']} {v['title']!r} from artifact {v.get('artifact')} ({v.get('artifact_id')})")
        r = requests.get(f"{API}/repos/{_repo()}/actions/artifacts/{v['artifact_id']}/zip", headers=_h(),
                         timeout=900, stream=True)
        if r.status_code in (404, 410):
            v.update(status="skipped", reason="artifact expired before it was stashed", stashed=False)
            log(f"  expired: {v['stamp']}")
            continue
        r.raise_for_status()
        with tempfile.TemporaryDirectory() as tmp:
            z = Path(tmp) / "a.zip"
            with open(z, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
            with zipfile.ZipFile(z) as zf:
                zf.extractall(tmp)
            mp4 = next(Path(tmp).rglob("final.mp4"), None)
            cap = next(Path(tmp).rglob("caption.txt"), None)
            st = next(Path(tmp).rglob("story.json"), None)
            if not mp4:
                v.update(status="skipped", reason="artifact has no final.mp4")
                continue
            meta = json.loads(st.read_text(encoding="utf-8")) if st else {}
            meta["_caption_txt"] = cap.read_text(encoding="utf-8") if cap else ""
            mj = Path(tmp) / "meta.json"
            mj.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            rel = rel or _release(create=True)
            _upload_asset(rel, f"{v['stamp']}.json", mj, "application/json")  # json first: half upload = no pair
            _upload_asset(rel, f"{v['stamp']}.mp4", mp4, "video/mp4")
        v["stashed"] = True
        log(f"  stashed {v['stamp']}")


# ---------- matching the owner's TikTok list ----------

def _norm(s: str) -> str:
    s = re.sub(r"#\w+", " ", s.lower())
    s = re.sub(r"\btrue story\b|illustrated horror story|\(fictional story\)", " ", s)
    return " ".join(re.findall(r"[a-z0-9à-ÿ]+", s))


def _score(line: str, text: str) -> float:
    a, b = _norm(line), _norm(text)
    if not a or not b:
        return 0.0
    ta, tb = set(a.split()) - STOP, set(b.split()) - STOP
    contain = len(ta & tb) / max(1, min(len(ta), len(tb)))  # a title inside a longer caption still matches
    return max(SequenceMatcher(None, a, b).ratio(), contain if min(len(ta), len(tb)) >= 3 else 0.0)


def match_posted(state: dict) -> bool:
    """Mark the videos the owner PUBLISHED on TikTok, from data/tiktok_posted.txt only (no file = paused)."""
    if not POSTED.exists():
        # A TikTok publish_id only means "sent to the owner's drafts", not "published": no list = backfill paused.
        log("Backfill PAUSED: data/tiktok_posted.txt is missing (only videos the owner published on TikTok are "
            "uploaded; a publish_id only means 'sent to drafts')")
        return False
    lines = [ln.strip() for ln in POSTED.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.strip().startswith("//")]
    for v in state["videos"]:
        v["tiktok_published"] = False
        v.pop("tiktok_line", None)
    unmatched = []
    for ln in lines:
        best, best_s = None, 0.0
        for v in state["videos"]:
            s = max(_score(ln, v.get("title", "")), _score(ln, v.get("caption", "")))
            if s > best_s:
                best, best_s = v, s
        if best and best_s >= MATCH_MIN:
            best["tiktok_published"] = True
            best["tiktok_line"] = ln
            log(f"TikTok line {ln[:60]!r} -> {best['stamp']} {best['title']!r} ({best_s:.2f})")
        else:
            unmatched.append(ln)
            log(f"TikTok line NOT matched: {ln[:80]!r}" + (f" (closest {best['title']!r} {best_s:.2f})" if best else ""))
    state["unmatched_lines"] = unmatched
    return True


def _title_key(t: str) -> str:
    return _norm(re.sub(r"#shorts", "", t, flags=re.IGNORECASE))


def channel_titles() -> dict | None:
    """{normalized title: video id} of the channel's uploads, or None when the token may not list them."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"], client_id=os.environ["YT_CLIENT_ID"],
                            client_secret=os.environ["YT_CLIENT_SECRET"],
                            token_uri="https://oauth2.googleapis.com/token")
        creds.refresh(Request())  # no scopes asked: the token keeps whatever it was granted
        h = {"Authorization": f"Bearer {creds.token}"}
    except Exception as e:  # noqa: BLE001
        log(f"Channel list: token refresh failed ({str(e)[:120]})")
        return None
    out = {}
    r = requests.get("https://www.googleapis.com/youtube/v3/channels", headers=h, timeout=30,
                     params={"part": "contentDetails", "mine": "true"})
    if r.status_code == 200 and r.json().get("items"):
        pl = r.json()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        token = None
        for _ in range(10):
            r = requests.get("https://www.googleapis.com/youtube/v3/playlistItems", headers=h, timeout=30,
                             params={"part": "snippet", "playlistId": pl, "maxResults": 50, "pageToken": token or ""})
            if r.status_code != 200:
                break
            for it in r.json().get("items", []):
                sn = it["snippet"]
                out[_title_key(sn["title"])] = sn["resourceId"]["videoId"]
            token = r.json().get("nextPageToken")
            if not token:
                break
        log(f"Channel list: {len(out)} uploads (Data API)")
        return out
    # youtube.upload alone may not list uploads: the Analytics API (yt-analytics.readonly) gives the ids,
    # the public oEmbed endpoint their titles (public videos only).
    today = _now().date().isoformat()
    r2 = requests.get("https://youtubeanalytics.googleapis.com/v2/reports", headers=h, timeout=30, params={
        "ids": "channel==MINE", "startDate": "2026-01-01", "endDate": today, "metrics": "views",
        "dimensions": "video", "sort": "-views", "maxResults": 200})
    if r2.status_code != 200:
        log(f"Channel list unavailable (Data API HTTP {r.status_code}, Analytics HTTP {r2.status_code}): "
            "using history.json + backfill.json only")
        return None
    for row in r2.json().get("rows") or []:
        vid = row[0]
        o = requests.get("https://www.youtube.com/oembed", timeout=20,
                         params={"url": f"https://www.youtube.com/shorts/{vid}", "format": "json"})
        if o.status_code == 200:
            out[_title_key(o.json().get("title", ""))] = vid
    log(f"Channel list: {len(out)} uploads (Analytics API + oEmbed; uploads from the last ~2 days may be missing)")
    return out


def _quota_error(e: Exception) -> bool:
    return any(k in str(e) for k in ("quotaExceeded", "uploadLimitExceeded", "rateLimitExceeded"))


# ---------- guards ----------

def slot_times() -> list[tuple[int, int]]:
    """(hour, minute) UTC of daily.yml's publish crons."""
    wf = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    return [(int(h), int(m)) for m, h in re.findall(r'cron:\s*"(\d+)\s+(\d+)\s+\*\s+\*\s+\*"', wf)]


def too_close(now: datetime) -> str | None:
    for h, m in slot_times():
        for day in (-1, 0, 1):
            t = (now + timedelta(days=day)).replace(hour=h, minute=m, second=0, microsecond=0)
            if abs(now - t) < GAP:
                return f"publish slot {h:02d}:{m:02d} UTC is under 60 min away"
    for e in load_history():
        p = e.get("posted")
        if p:
            try:
                t = datetime.strptime(p, "%Y-%m-%d_%H%M").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if abs(now - t) < GAP:
                return f"a video was posted at {p} UTC (under 60 min ago)"
    return None


# ---------- upload ----------

def upload_one(state: dict) -> None:
    import yt_packaging as packaging
    import render
    import youtube

    now = _now()
    today = now.date().isoformat()
    per_day = int(CONFIG.get("yt_backfill_per_day", 3))
    done_today = sum(1 for v in state["videos"] if (v.get("uploaded_at") or "").startswith(today))
    if done_today >= per_day:
        log(f"Backfill: {done_today} uploaded today already (max {per_day}); next run continues")
        return
    why = too_close(now)
    if why:
        log(f"Backfill waits: {why}")
        return
    if _runs_active("daily.yml"):
        log("Backfill waits: a daily.yml run is active")
        return
    if not youtube.configured():
        log("YouTube secrets missing: nothing uploaded")
        return

    todo = [v for v in state["videos"] if v["status"] == "queued" and v.get("tiktok_published")
            and not v.get("remade")]  # remade topics: the new video replaces the old one, never upload the old
    todo.sort(key=lambda v: v["stamp"])  # oldest first
    if not todo:
        log("Backfill: nothing left to upload")
        return
    on_yt = {_title_key(e.get("title", "")): (e.get("youtube") or {}).get("id")
             for e in load_history() if (e.get("youtube") or {}).get("id")}
    on_yt.update({_title_key(v["title"]): (v.get("youtube") or {}).get("id")
                  for v in state["videos"] if v["status"] == "uploaded"})
    listed = channel_titles()
    if listed:
        on_yt.update(listed)
    assets = _assets()

    for v in todo:
        key = _title_key(v["title"])
        if key in on_yt:
            v.update(status="skipped", reason=f"already on YouTube ({on_yt[key]})")
            log(f"Skip {v['stamp']} {v['title']!r}: already on YouTube ({on_yt[key]})")
            continue
        a_mp4, a_json = assets.get(f"{v['stamp']}.mp4"), assets.get(f"{v['stamp']}.json")
        if not (a_mp4 and a_json):
            log(f"Skip for now {v['stamp']}: not stashed in the backfill release")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            mp4, mj = Path(tmp) / "final.mp4", Path(tmp) / "meta.json"
            _download_asset(a_mp4, mp4)
            _download_asset(a_json, mj)
            meta = json.loads(mj.read_text(encoding="utf-8"))
            problems = render.qa_gate(mp4, None, {}, None, backfill=True)
            v["qa"] = "passed" if not problems else "; ".join(problems)
            if problems:
                v.update(status="skipped", reason="QA: " + "; ".join(problems))
                log(f"Skip {v['stamp']}: QA failed ({v['reason']})")
                continue
            story = {k: val for k, val in meta.items() if not k.startswith("_")}
            search = None
            if story.get("scenes") or story.get("caption"):  # same packaging as daily posts (packaging.py)
                story.setdefault("true_story", story.get("mode") in ("case", "mystery", "inbox-true"))
                story.setdefault("title", v["title"])
                pack = packaging.package(story)
                title, text, tags, search = (pack["yt_title"], packaging.youtube_description(story),
                                             pack["hashtags"], pack["yt_tags"])
                v.update(yt_title=title, hashtags=tags, yt_tags=search)
            else:  # no story.json in the artifact: the posted caption as it was
                title = v["title"]
                text = meta.get("_caption_txt", "").split("\n\nPIN: ")[0].strip()
                tags = re.findall(r"#(\w+)", text)
            log(f"Uploading {v['stamp']} {title!r}")
            try:
                yt = youtube.upload(mp4, title, text, tags, tags=search)
            except Exception as e:  # noqa: BLE001
                if _quota_error(e):
                    log(f"YouTube quota/limit reached, the next run retries: {str(e)[:200]}")
                    return
                v["attempts"] = v.get("attempts", 0) + 1
                v["last_error"] = str(e)[:300]
                if v["attempts"] >= 3:
                    v.update(status="skipped", reason=f"upload failed 3 times: {v['last_error']}")
                log(f"YouTube upload failed ({v['attempts']}/3): {str(e)[:200]}")
                return
        v.update(status="uploaded", youtube=yt, uploaded_at=now.strftime("%Y-%m-%dT%H:%MZ"), reason=None)
        log(f"Backfilled {v['title']!r}: {yt['url']} (privacy {yt['privacy']})")
        save_state(state)
        _delete_asset(a_mp4)
        _delete_asset(a_json)
        return  # one per run


def finish_if_done(state: dict, have_list: bool) -> None:
    if not have_list:
        return
    left = [v for v in state["videos"] if v["status"] == "queued" and v.get("tiktok_published")
            and not v.get("remade")]
    if left:
        log(f"Backfill queue: {len(left)} left: " + ", ".join(v["title"] for v in left))
        return
    for v in state["videos"]:
        if v["status"] == "queued":  # recovered, but the owner's TikTok list doesn't have it: a draft
            v.update(status="skipped", reason="not in data/tiktok_posted.txt (never published on TikTok)")
    state["done"] = _now().strftime("%Y-%m-%dT%H:%MZ")
    log("Backfill done: every published video is uploaded or skipped")
    _disable_self()


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "upload"
    state = load_state()
    if state.get("done"):
        log(f"Backfill finished on {state['done']}; nothing to do")
        return
    try:
        stash(state)  # every run: artifacts expire after 7 days
    finally:
        save_state(state)
    if cmd == "stash":
        return
    if CONFIG.get("youtube_paused"):
        log("YouTube PAUSED (config youtube_paused): artifacts stashed, no upload this run")
        return
    have_list = match_posted(state)
    save_state(state)
    if not have_list:
        return
    try:
        upload_one(state)
    finally:
        save_state(state)
    finish_if_done(state, have_list)
    save_state(state)


if __name__ == "__main__":
    main()
