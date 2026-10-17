"""Queue at most one eligible historical video through Buffer per run.

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
    query = ("query { posts(input: { organizationId: " + json.dumps(organization_id)
             + " filter: { status: [" + status + "], channelIds: ["
             + json.dumps(CHANNEL) + "] } }) { edges { node { id text channelId } } pageInfo { hasNextPage endCursor } } }")
    data = graph(query)["posts"]
    if data.get("pageInfo", {}).get("hasNextPage"):
        raise RuntimeError("More Buffer posts than one page; refusing to risk duplicates")
    return [edge["node"] for edge in data["edges"]]


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


def main():
    record = json.loads(STATE.read_text()) if STATE.exists() else {"queued": {}}
    queued = record.setdefault("queued", {})
    videos = json.loads(BACKFILL.read_text())["videos"]
    selected = [v for v in videos if v.get("status") == "queued"
                and v.get("tiktok_published") is True
                and v.get("stashed") is True
                and not v.get("remade") and not v.get("youtube", {}).get("id")]
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
        text = (title + "\\n\\n" + desc)[:4500]
        mutation = ("mutation { createPost(input: { text: " + json.dumps(text)
                    + " channelId: " + json.dumps(CHANNEL)
                    + " schedulingType: automatic mode: addToQueue assets: [{ video: { url: "
                    + json.dumps(media)
                    + " } }] }) { ... on PostActionSuccess { post { id dueAt } }"
                    + " ... on MutationError { message } } }")
        response = graph(mutation)["createPost"]
        post = response.get("post")
        if not post or not post.get("id"):
            raise RuntimeError("Queueing rejected: " + repr(response))
        queued[stamp] = {"buffer_post_id": post["id"], "due_at": post.get("dueAt"), "title": title}
        STATE.parent.mkdir(exist_ok=True, parents=True)
        STATE.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\\n")
        print("Queued exactly one video:", stamp, "Buffer ID:", post["id"])
        return
    print("No new videos to queue")


if __name__ == "__main__":
    main()
