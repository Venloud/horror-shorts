"""Backfill one existing Night Files video through Buffer, manual-only.

Default mode checks eligibility and public asset access, with no Buffer mutation.
An explicit --queue flag is required to queue one item. Queuing is not publishing.
"""
import argparse
import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
REPO = os.getenv("GITHUB_REPOSITORY", "Venloud/horror-shorts")
GH = "https://api.github.com"
BUFFER = "https://api.buffer.com"


def github(path):
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(GH + "/repos/" + REPO + path, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def graphql(query):
    token = os.environ["BUFFER_ACCESS_TOKEN"]
    resp = requests.post(BUFFER, headers={"Authorization": "Bearer " + token},
                         json={"query": query}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(str(data["errors"]))
    return data["data"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stamp", default="2026-09-26_0514")
    parser.add_argument("--queue", action="store_true")
    parser.add_argument("--channel-id")
    args = parser.parse_args()

    rows = json.loads((ROOT / "data/backfill.json").read_text())["videos"]
    item = next((v for v in rows if v["stamp"] == args.stamp), None)
    if not item or item["status"] != "queued" or not item.get("tiktok_published") or item.get("remade"):
        raise RuntimeError("Video is not confirmed eligible for backfill")
    if item.get("youtube", {}).get("id"):
        raise RuntimeError("Video has an existing YouTube video ID")
    if not item.get("stashed"):
        raise RuntimeError("Video is not marked stashed")

    rel = github("/releases/tags/backfill")
    assets = {a["name"]: a for a in rel["assets"]}
    if not {args.stamp + ".mp4", args.stamp + ".json"} <= assets.keys():
        raise RuntimeError("Missing paired release assets")
    media = assets[args.stamp + ".mp4"]["browser_download_url"]
    meta_link = assets[args.stamp + ".json"]["browser_download_url"]
    check = requests.get(media, stream=True, timeout=30)
    try:
        check.raise_for_status()
        content_type = check.headers.get("Content-Type", "")
        if not ("video/" in content_type or "octet-stream" in content_type):
            raise RuntimeError("Asset URL does not return public video data")
    finally:
        check.close()
    meta_resp = requests.get(meta_link, timeout=30)
    meta_resp.raise_for_status()
    meta = meta_resp.json()
    title = meta.get("yt_title") or item.get("yt_title") or item["title"]
    description = meta.get("yt_description") or item.get("caption") or ""
    if not title.strip():
        raise RuntimeError("Title is blank")
    print("Test candidate:", args.stamp, title)
    print("Media URL reachable. Buffer still needs to independently ingest it.")
    if not args.queue:
        print("DRY RUN, no posting or queuing attempted")
        return
    if not args.channel_id:
        raise RuntimeError("--channel-id required")
    # Deliberately only one explicit job, no recurring schedule.
    # No automatic retries, because a successful mutation may time out at the client.
    text = title + "\n\n" + description
    query = (
        "mutation { createPost(input: { text: " + json.dumps(text) +
        " channelId: " + json.dumps(args.channel_id) +
        " schedulingType: automatic mode: addToQueue assets: [{video: {url: " +
        json.dumps(media) +
        "}}] }) { ... on PostActionSuccess { post { id dueAt } }"
        " ... on MutationError { message } } }"
    )
    result = graphql(query)["createPost"]
    post = result.get("post")
    if not post or not post.get("id"):
        raise RuntimeError("Buffer did not acknowledge queue creation: " + str(result))
    print("BUFFER POST QUEUED:", post["id"], "dueAt:", post.get("dueAt"))
    print("Track this ID before running again. No GitHub state was modified.")


if __name__ == "__main__":
    main()
