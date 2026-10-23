"""Queue one new production video or eligible historical video through Buffer per run.

Runs unattended through GitHub Actions. Distinguishes queueing from published.
Maintains data/buffer_backfill_queue.json with Buffer IDs and never deletes MP4s.
"""
import json
import os
from pathlib import Path
import sys

import requests

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data/buffer_backfill_queue.json"
BACKFILL = ROOT / "data/backfill.json"
GH_API = "https://api.github.com"
BUF_API = "https://api.buffer.com"
REPO = os.environ.get("GITHUB_REPOSITORY", "Venloud/horror-shorts")
CHANNEL = os.environ.get("BUFFER_YOUTUBE_CHANNEL_ID", "6ad2d7d2778b240e2f331d8e")
TOKEN = os.environ["BUFFER_ACCESS_TOKEN"]


def graph(query):
    r = requests.post(BUF_API, json={"query": query},
                      headers={"Authorization": "Bearer " + TOKEN}, timeout=45)
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise RuntimeError("Buffer GraphQL: " + repr(body["errors"]))
    return body["data"]


def gh(path):
    r = requests.get(GH_API + "/repos/" + REPO + path,
                     headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                              "Accept": "application/vnd.github+json"}, timeout=45)
    r.raise_for_status()
    return r.json()


def posts(organization_id, status):
    found = []
    cursor = None
    seen_cursors = set()
    for _ in range(200):
        after = (" after: " + json.dumps(cursor)) if cursor else ""
        query = ("query { posts(first: 50" + after + ", input: { organizationId: "
                 + json.dumps(organization_id) + " filter: { status: [" + status
                 + "], channelIds: [" + json.dumps(CHANNEL)
                 + "] } }) { edges { node { id text channelId } }"
                 + " pageInfo { hasNextPage endCursor } } }")
        data = graph(query)["posts"]
        found.extend(edge["node"] for edge in data["edges"])
        page = data["pageInfo"]
        if not page["hasNextPage"]:
            return found
        cursor = page.get("endCursor")
        if not cursor or cursor in seen_cursors:
            raise RuntimeError("Buffer pagination cursor missing or repeated, refusing duplicates")
        seen_cursors.add(cursor)
    raise RuntimeError("Buffer pagination exceeded safe page limit")


def existing_posts():
    orgs = graph("query { account { organizations { id name } } }")["account"]["organizations"]
    if len(orgs) != 1:
        raise RuntimeError("Expected exactly one Buffer organization")
    org_id = orgs[0]["id"]
    return posts(org_id, "scheduled") + posts(org_id, "sent")


def public_asset(url, expected_type):
    r = requests.get(url, stream=True, timeout=45)
    try:
        r.raise_for_status()
        mime = r.headers.get("Content-Type", "").lower()
        if expected_type not in mime and "octet-stream" not in mime:
            raise RuntimeError("Unexpected content type: " + mime)
    finally:
        r.close()


def production_videos(queued):
    """Read finished production assets; never replay older 2026-10-18 publications."""
    out = []
    for tag in ("buffer", "youtube-pending"):
        try:
            release = gh("/releases/tags/" + tag)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                continue
            raise
        assets = {a["name"]: a for a in release.get("assets", [])}
        for name in sorted(assets):
            if not name.endswith(".mp4"):
                continue
            stamp = name[:-4]
            if stamp[:10] < "2026-10-19" or stamp in queued:
                continue
            if stamp + ".json" not in assets:
                continue
            out.append((stamp, assets[name], assets[stamp + ".json"]))
    # Oldest first; prefer the live production buffer over archived pending assets.
    return sorted(out, key=lambda v: (v[0], 0 if "/buffer/" in v[1].get("browser_download_url", "") else 1))


def queue_one(stamp, mp4, json_asset, queued, remote_texts, record, fallback_title=""):
    """Use the working Buffer GraphQL mutation and durable queue receipts."""
    media = mp4["browser_download_url"]
    public_asset(media, "video")
    meta_url = json_asset["browser_download_url"]
    public_asset(meta_url, "json")
    response = requests.get(meta_url, timeout=45)
    response.raise_for_status()
    metadata = response.json()
    title = (metadata.get("yt_title") or metadata.get("title") or fallback_title).strip()
    desc = (metadata.get("yt_description") or metadata.get("caption_text") or
            metadata.get("caption") or "").strip()
    if not title or not desc:
        raise RuntimeError("Missing required YouTube title or description for " + stamp)
    if any(title.lower() in text or (fallback_title and fallback_title.lower() in text)
           for text in remote_texts):
        print("Already in Buffer, skipping:", stamp, title)
        return False
    mutation = ("mutation { createPost(input: { text: " + json.dumps(desc[:4500])
                + " channelId: " + json.dumps(CHANNEL)
                + " schedulingType: automatic mode: addToQueue"
                + " metadata: { youtube: { title: " + json.dumps(title[:100])
                + ' categoryId: "24" madeForKids: false isAiGenerated: true } }'
                + " assets: [{ video: { url: " + json.dumps(media)
                + " } }] }) { ... on PostActionSuccess { post { id dueAt } }"
                + " ... on MutationError { message } } }")
    # If the API times out after accepting a post, never blindly resubmit it.
    queued[stamp] = {"status": "attempt_started", "title": title}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    result = graph(mutation)["createPost"]
    post = result.get("post")
    if not post or not post.get("id"):
        raise RuntimeError("Queueing result uncertain; review Buffer before retrying: " + repr(result))
    queued[stamp] = {"buffer_post_id": post["id"], "due_at": post.get("dueAt"), "title": title}
    STATE.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\\n")
    print("Queued exactly one video:", stamp, "Buffer ID:", post["id"])
    return True


def main():
    record = json.loads(STATE.read_text()) if STATE.exists() else {"queued": {}}
    queued = record.setdefault("queued", {})
    # New Night Files production uploads take priority over historical backfill.
    fresh = production_videos(queued)
    if fresh:
        remote = existing_posts()
        remote_texts = [p.get("text", "").lower() for p in remote if p.get("channelId") == CHANNEL]
        for stamp, mp4, meta in fresh:
            if queue_one(stamp, mp4, meta, queued, remote_texts, record):
                return
        print("No new production videos to queue")
        return
    videos = json.loads(BACKFILL.read_text())["videos"]
    selected = [v for v in videos if v.get("status") == "queued"
                and v.get("tiktok_published") is True
                and v.get("stashed") is True
                and not v.get("remade") and not v.get("youtube", {}).get("id")
                and not v.get("youtube_excluded")
                and "mrbeast" not in " ".join(str(v.get(k, "")) for k in
                    ("title", "yt_title", "caption")).lower().replace(" ", "")]
    selected.sort(key=lambda v: v["stamp"])
    if not selected:
        print("No eligible backfill videos")
        return
    release = gh("/releases/tags/backfill")
    assets = {x["name"]: x for x in release["assets"]}
    remote = existing_posts()  # Query the platform before sending anything.
    remote_texts = [p.get("text", "").lower() for p in remote if p.get("channelId") == CHANNEL]
    for item in selected:
        stamp = item["stamp"]
        if stamp in queued:
            print("Already tracked:", stamp)
            continue
        title = (item.get("yt_title") or item["title"]).strip()
        # Detect already scheduled/sent posts by title rather than trusting stale GitHub state.
        if any(title.lower() in t or item["title"].lower() in t for t in remote_texts):
            print("Already in Buffer, skipping:", stamp, title)
            continue
        pair = [assets.get(stamp + ".mp4"), assets.get(stamp + ".json")]
        if not all(pair):
            print("Missing MP4/metadata, skipping:", stamp)
            continue
        media = pair[0]["browser_download_url"]
        public_asset(media, "video")
        meta_url = pair[1]["browser_download_url"]
        meta = requests.get(meta_url, timeout=45)
        meta.raise_for_status()
        metadata = meta.json()
        title = (metadata.get("yt_title") or title).strip()
        desc = (metadata.get("yt_description") or item.get("caption") or "").strip()
        if not title:
            raise RuntimeError("Missing YouTube title")
        text = desc[:4500]
        mutation = ("mutation { createPost(input: { text: " + json.dumps(text)
                    + " channelId: " + json.dumps(CHANNEL)
                    + " schedulingType: automatic mode: addToQueue"
                    + " metadata: { youtube: { title: " + json.dumps(title[:100])
                    + " categoryId: \"24\" madeForKids: false isAiGenerated: true } }"
                    + " assets: [{ video: { url: " + json.dumps(media)
                    + " } }] }) { ... on PostActionSuccess { post { id dueAt } }"
                    + " ... on MutationError { message } } }")
        response = graph(mutation)["createPost"]
        post = response.get("post")
        if not post or not post.get("id"):
            raise RuntimeError("Queueing rejected: " + repr(response))
        queued[stamp] = {"buffer_post_id": post["id"], "due_at": post.get("dueAt"), "title": title}
        STATE.parent.mkdir(exist_ok=True, parents=True)
        STATE.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        print("Queued exactly one video:", stamp, "Buffer ID:", post["id"])
        return
    print("No new videos to queue")


if __name__ == "__main__":
    main()
