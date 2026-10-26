"""Night Files -> Buffer.com YouTube queue, one verified video per invocation.

The Daily workflow uses --stamp-file .posted to queue the same completed video.
The 15-minute workflow drains newer Night Files inventory, then historical
backfill, then attempts artifact/TikTok recovery. NO Google/YouTube upload API.
The GitHub queue receipt is persisted BEFORE the Buffer mutation to fail closed.
"""
import argparse
import base64
import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data/buffer_backfill_queue.json"
BACKFILL = ROOT / "data/backfill.json"
HISTORY = ROOT / "data/history.json"
GH_API = "https://api.github.com"
BUF_API = "https://api.buffer.com"
REPO = os.environ.get("GITHUB_REPOSITORY", "Venloud/horror-shorts")
CHANNEL = os.environ.get("BUFFER_YOUTUBE_CHANNEL_ID", "6ad2d7d2778b240e2f331d8e")


def gh(path):
    response = requests.get(
        GH_API + "/repos/" + REPO + path,
        headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                 "Accept": "application/vnd.github+json"},
        timeout=45,
    )
    response.raise_for_status()
    return response.json()


def graph(query):
    token = os.environ.get("BUFFER_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("BUFFER_ACCESS_TOKEN missing: cannot queue YouTube through Buffer")
    response = requests.post(
        BUF_API, json={"query": query},
        headers={"Authorization": "Bearer " + token}, timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError("Buffer GraphQL errors: " + str(payload["errors"])[:350])
    return payload["data"]


def posts(org_id, status):
    result, cursor, seen = [], None, set()
    for _ in range(200):
        after = (" after: " + json.dumps(cursor)) if cursor else ""
        query = ("query { posts(first: 50" + after + ", input: { organizationId: "
                 + json.dumps(org_id) + " filter: { status: [" + status
                 + "], channelIds: [" + json.dumps(CHANNEL)
                 + "] } }) { edges { node { id text channelId } }"
                 + " pageInfo { hasNextPage endCursor } } }")
        page = graph(query)["posts"]
        result.extend(edge["node"] for edge in page["edges"])
        if not page["pageInfo"]["hasNextPage"]:
            return result
        cursor = page["pageInfo"].get("endCursor")
        if not cursor or cursor in seen:
            raise RuntimeError("Buffer pagination did not advance; aborting to avoid duplicates")
        seen.add(cursor)
    raise RuntimeError("Buffer pagination limit reached")


def existing_posts():
    orgs = graph("query { account { organizations { id name } } }")["account"]["organizations"]
    if len(orgs) != 1:
        raise RuntimeError("Buffer must resolve exactly one organization")
    org_id = orgs[0]["id"]
    return posts(org_id, "scheduled") + posts(org_id, "sent")


def read_state():
    """Use the HEAD state, not a stale Actions checkout; return contents-API SHA."""
    try:
        response = gh("/contents/data/buffer_backfill_queue.json?ref=main")
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return {"queued": {}}, None
        raise
    data = json.loads(base64.b64decode(response["content"]))
    data.setdefault("queued", {})
    return data, response["sha"]


def persist(state, sha):
    """Durable write-ahead to the authoritative GitHub branch; fail on concurrent changes."""
    payload = {
        "message": "Record Night Files Buffer queue attempt/receipt",
        "branch": "main",
        "content": base64.b64encode(
            (json.dumps(state, indent=2, ensure_ascii=False) + "\n").encode()
        ).decode(),
    }
    if sha:
        payload["sha"] = sha
    response = requests.put(
        GH_API + "/repos/" + REPO + "/contents/data/buffer_backfill_queue.json",
        json=payload,
        headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                 "Accept": "application/vnd.github+json"}, timeout=45,
    )
    response.raise_for_status()
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    return response.json()["content"]["sha"]


def release_assets(tag):
    try:
        release = gh("/releases/tags/" + tag)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return {}
        raise
    return {a["name"]: a for a in release.get("assets", [])}


def pairs(assets, queued, after=None):
    """Return completed MP4+metadata release pairs, never partial uploads."""
    result = []
    for name, asset in assets.items():
        if not name.endswith(".mp4"):
            continue
        stamp = name[:-4]
        if stamp in queued or (after and stamp[:10] < after):
            continue
        if stamp + ".json" in assets:
            result.append((stamp, asset, assets[stamp + ".json"]))
    return sorted(result)


def public_asset(url, mime):
    if not url.startswith("https://github.com/"):
        raise RuntimeError("Only public Night Files GitHub Release assets may reach Buffer")
    response = requests.get(url, stream=True, timeout=45)
    try:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if mime not in content_type and "octet-stream" not in content_type:
            raise RuntimeError("Public asset is not downloadable " + mime + ": " + content_type)
    finally:
        response.close()


def safe_history():
    return json.loads(HISTORY.read_text()) if HISTORY.exists() else []


def already_youtube(stamp):
    """Skip confirmed direct uploads and already excluded legacy stories."""
    for entry in safe_history():
        if (entry.get("buffered") or entry.get("date")) == stamp:
            if isinstance(entry.get("youtube"), dict) and entry["youtube"].get("id"):
                return True
    if BACKFILL.exists():
        for item in json.loads(BACKFILL.read_text()).get("videos", []):
            if item.get("stamp") == stamp:
                return bool(item.get("youtube", {}).get("id") or item.get("youtube_excluded")
                            or item.get("remade") or item.get("status") == "skipped")
    return False


def candidates(queued, only_stamp=None):
    """The same source order for daily and scheduled queueing, no duplicates."""
    incoming = []
    for tag in ("youtube-pending", "buffer"):
        for stamp, mp4, metadata in pairs(release_assets(tag), queued, after="2026-10-19"):
            if not already_youtube(stamp) and (only_stamp is None or stamp == only_stamp):
                incoming.append((stamp, mp4, metadata))
    # Important: prefer durable youtube-pending after a TikTok draft removes the normal buffer asset.
    by_stamp = {}
    for item in incoming:
        by_stamp.setdefault(item[0], item)
    if only_stamp is not None:
        return [by_stamp[only_stamp]] if only_stamp in by_stamp else []
    return [by_stamp[k] for k in sorted(by_stamp)]


def historical_candidates(queued):
    """Oldest valid originals, including October YouTube-pending and September backfill."""
    out = []
    # Earlier YouTube-pending MP4s were retained when Google uploads stopped.
    # They are first-party accepted Night Files content, not arbitrary TikTok clips.
    for stamp, mp4, meta in pairs(release_assets("youtube-pending"), queued):
        if stamp[:10] < "2026-10-19" and not already_youtube(stamp):
            out.append((stamp, mp4, meta))
    if not BACKFILL.exists():
        return sorted(out)
    assets = release_assets("backfill")
    records = json.loads(BACKFILL.read_text()).get("videos", [])
    for v in sorted(records, key=lambda x: x["stamp"]):
        stamp = v["stamp"]
        if (stamp in queued or not v.get("tiktok_published")
                or v.get("status") == "skipped" or v.get("remade")
                or already_youtube(stamp)):
            continue
        if stamp + ".mp4" in assets and stamp + ".json" in assets:
            out.append((stamp, assets[stamp + ".mp4"], assets[stamp + ".json"]))
    return sorted(out)


def queue_one(stamp, mp4, json_asset, record, sha, remote_posts):
    queued = record["queued"]
    if stamp in queued:
        return False, sha
    from public_buffer_media import ensure_public_video
    # The GitHub Release remains the durable private workflow source, not Buffer's
    # scheduled delivery URL. Mirror to a verified, stable public host before the
    # write-ahead receipt; failing this check must NOT create a Buffer post.
    media = ensure_public_video(mp4["browser_download_url"], stamp)
    meta_url = json_asset["browser_download_url"]
    public_asset(meta_url, "json")
    response = requests.get(meta_url, timeout=45)
    response.raise_for_status()
    metadata = response.json()
    title = (metadata.get("yt_title") or metadata.get("title") or "").strip()
    desc = (metadata.get("yt_description") or metadata.get("caption_text")
            or metadata.get("caption") or "").strip()
    if not title or not desc:
        raise RuntimeError("Missing approved YouTube title/description for " + stamp)
    # Remote matches are a secondary guard for historical queues whose GitHub receipt was lost.
    if any(stamp in (p.get("text") or "") or title.lower() in (p.get("text") or "").lower()
           for p in remote_posts if p.get("channelId") == CHANNEL):
        queued[stamp] = {"status": "already_in_buffer", "title": title}
        return False, persist(record, sha)
    mutation = ("mutation { createPost(input: { text: " + json.dumps(desc[:4500])
                + " channelId: " + json.dumps(CHANNEL)
                + " schedulingType: automatic mode: addToQueue"
                + " metadata: { youtube: { title: " + json.dumps(title[:100])
                + ' categoryId: "24" madeForKids: false isAiGenerated: true } }'
                + " assets: [{ video: { url: " + json.dumps(media)
                + " } }] }) { ... on PostActionSuccess { post { id dueAt } }"
                + " ... on MutationError { message } } }")
    # Important: persist BEFORE sending. A timeout/runner crash must never blindly duplicate.
    queued[stamp] = {"status": "attempt_started", "title": title,
                     "source_url": media}
    sha = persist(record, sha)
    result = graph(mutation)["createPost"]
    post = result.get("post")
    if not post or not post.get("id"):
        raise RuntimeError("Buffer outcome uncertain for " + stamp + ", inspect manually; not retrying")
    queued[stamp] = {"status": "queued", "buffer_post_id": post["id"],
                     "due_at": post.get("dueAt"), "title": title}
    sha = persist(record, sha)
    print("Queued", stamp, "through Buffer.com:", post["id"])
    return True, sha


def read_stamp_file(path):
    if not path:
        return None
    f = Path(path)
    if not f.exists():
        print("No accepted Daily video; skipping same-run Buffer enqueue")
        return ""
    value = json.loads(f.read_text()).get("stamp")
    if not value:
        raise RuntimeError("Daily receipt missing stamp")
    return value


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp-file", help="Queue only the Daily run's accepted video")
    ap.add_argument("--production-only", action="store_true",
                    help="Daily workflow does not do historical backfill")
    args = ap.parse_args(argv)
    stamp = read_stamp_file(args.stamp_file)
    if stamp == "":
        return 0
    record, sha = read_state()
    queued = record["queued"]
    remote = None

    def attempt(options):
        nonlocal remote, sha
        for key, mp4, meta in options:
            if key in queued:
                continue
            if remote is None:
                remote = existing_posts()
            done, sha = queue_one(key, mp4, meta, record, sha, remote)
            if done:
                return True
        return False

    if attempt(candidates(queued, only_stamp=stamp)):
        return 0
    if stamp is not None or args.production_only:
        print("No new production video to queue")
        return 0
    if attempt(historical_candidates(queued)):
        return 0
    # Only when eligible inventories are exhausted: restore an older verified Night Files
    # video from its build artifact or authenticated TikTok public post. Never fetch other accounts.
    from buffer_recovery import recover_one
    recovered = recover_one(queued)
    if recovered:
        assets = release_assets("youtube-pending")
        stamp = str(recovered)
        if (stamp + ".mp4") in assets and (stamp + ".json") in assets:
            if attempt([(stamp, assets[stamp + ".mp4"], assets[stamp + ".json"])]):
                return 0
    print("Buffer queue caught up; no recoverable verified Night Files video")


if __name__ == "__main__":
    raise SystemExit(main())
