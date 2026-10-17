"""Buffer bridge for public GitHub Release videos, dry-run unless --queue.

Requires BUFFER_ACCESS_TOKEN; public GitHub Release buffer video assets.
Posts remain in GitHub buffer; this utility NEVER deletes assets.
"""
import argparse
import json
import os
import sys

import requests

BUFFER = "https://api.buffer.com"
REPO = os.environ.get("GITHUB_REPOSITORY", "Venloud/horror-shorts")
API = "https://api.github.com"


def graphql(query):
    token = os.environ.get("BUFFER_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("BUFFER_ACCESS_TOKEN is missing")
    response = requests.post(BUFFER, headers={"Authorization": f"Bearer {token}"},
                             json={"query": query}, timeout=30)
    response.raise_for_status()
    body = response.json()
    if body.get("errors"):
        raise RuntimeError(str(body["errors"]))
    return body["data"]


def channels():
    orgs = graphql("query { account { organizations { id name } } }")["account"]["organizations"]
    found = []
    for org in orgs:
        query = "query { channels(input: { organizationId: " + json.dumps(org["id"]) + " }) { id name service isDisconnected isLocked } }"
        # Compatible fallback when account uses a schema without status fields.
        try:
            items = graphql(query)["channels"]
        except RuntimeError:
            query = "query { channels(input: { organizationId: " + json.dumps(org["id"]) + " }) { id name service } }"
            items = graphql(query)["channels"]
        found.extend(items)
    return found


def asset_pair():
    response = requests.get(f"{API}/repos/{REPO}/releases/tags/buffer", timeout=30)
    response.raise_for_status()
    assets = response.json().get("assets", [])
    by_stem = {}
    for asset in assets:
        stem, dot, ext = asset["name"].rpartition(".")
        if dot and ext in ("mp4", "json"):
            by_stem.setdefault(stem, {})[ext] = asset
    pairs = [(stem, pair) for stem, pair in sorted(by_stem.items()) if "mp4" in pair and "json" in pair]
    if not pairs:
        raise RuntimeError("No paired assets in public Release buffer")
    return pairs[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channels", action="store_true", help="Inspect linked Buffer channels")
    parser.add_argument("--queue", action="store_true", help="EXPLICITLY create queued post")
    parser.add_argument("--channel-id", help="Target Buffer YouTube channel ID")
    args = parser.parse_args()
    available = channels()
    for item in available:
        print(f"Channel: {item['name']} ({item['service']}): {item['id']}")
    if args.channels:
        return
    youtube = [c for c in available if c.get("service", "").lower() == "youtube" and not c.get("isDisconnected") and not c.get("isLocked")]
    if args.channel_id:
        youtube = [c for c in youtube if c["id"] == args.channel_id]
    if len(youtube) != 1:
        raise RuntimeError("Exactly one usable YouTube channel required, supply --channel-id")
    stamp, assets = asset_pair()
    video_url = assets["mp4"]["browser_download_url"]
    # Check a public HEAD request before exposing it to Buffer.
    response = requests.get(video_url, stream=True, timeout=30, allow_redirects=True)
    try:
        response.raise_for_status()
        if "video" not in response.headers.get("Content-Type", "").lower() and "octet-stream" not in response.headers.get("Content-Type", "").lower():
            raise RuntimeError("MP4 is not publicly accessible; Buffer requires a public media URL")
    finally:
        response.close()
    metadata_url = assets["json"]["browser_download_url"]
    metadata = requests.get(metadata_url, timeout=30)
    metadata.raise_for_status()
    info = metadata.json()
    title = info.get("yt_title") or info.get("title") or ""
    description = info.get("yt_description") or info.get("caption_text") or ""
    text = (title + "\n\n" + description).strip()
    print(f"Selected {stamp}; channel {youtube[0]['name']}; title {title}")
    if not args.queue:
        print("DRY RUN complete. Nothing queued or posted.")
        return
    query = (
        "mutation { createPost(input: { text: " + json.dumps(text) +
        " channelId: " + json.dumps(youtube[0]["id"]) +
        " schedulingType: automatic mode: addToQueue assets: [{ video: { url: " +
        json.dumps(video_url) +
        " } }] }) { ... on PostActionSuccess { post { id text } } ... on MutationError { message } } }"
    )
    result = graphql(query)["createPost"]
    if not result.get("post", {}).get("id"):
        raise RuntimeError(f"Buffer queue failed: {result}")
    print("Queued post ID:", result["post"]["id"])
    print("IMPORTANT: GitHub buffer item retained, no deduplication integration yet")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
