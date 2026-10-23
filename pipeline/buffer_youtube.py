"""Queue one saved Night Files video in Buffer.com without using Google's restricted API.

Required Actions secrets: BUFFER_API_KEY, BUFFER_YOUTUBE_CHANNEL_ID.
Safety: one queued video per run, no deletion of media, ledger on GitHub,
public video URL preflight, and no duplicate retries when outcome is uncertain.
"""
import json
import os
import sys
import urllib.parse

import requests

from common import ROOT

API = "https://api.buffer.com"
GH = "https://api.github.com"
LEDGER = "data/buffer_youtube_delivery.json"


def headers():
    return {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
            "Accept": "application/vnd.github+json"}


def github(method, path, **kw):
    r = requests.request(method, f"{GH}/repos/{os.environ['GITHUB_REPOSITORY']}/{path}",
                         headers=headers(), timeout=35, **kw)
    r.raise_for_status()
    return r.json()


def ledger():
    r = requests.get(f"{GH}/repos/{os.environ['GITHUB_REPOSITORY']}/contents/{LEDGER}",
                     headers=headers(), timeout=30)
    if r.status_code == 404:
        return {}, None
    r.raise_for_status()
    import base64
    return json.loads(base64.b64decode(r.json()["content"])), r.json()["sha"]


def save(entries, sha):
    import base64
    payload = {"message": "Record Buffer YouTube queue result",
               "content": base64.b64encode((json.dumps(entries, indent=2) + "\n").encode()).decode(),
               "branch": "main"}
    if sha:
        payload["sha"] = sha
    github("PUT", "contents/" + LEDGER, json=payload)


def buffer(query):
    r = requests.post(API, headers={"Authorization": "Bearer " + os.environ["BUFFER_API_KEY"],
                                    "Content-Type": "application/json"},
                      json={"query": query}, timeout=45)
    r.raise_for_status()
    result = r.json()
    if result.get("errors"):
        raise RuntimeError("Buffer GraphQL: " + str(result["errors"])[:350])
    return result["data"]


def main():
    for name in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "BUFFER_API_KEY", "BUFFER_YOUTUBE_CHANNEL_ID"):
        if not os.environ.get(name):
            raise RuntimeError("Missing required credential/config: " + name)
    channel_id = os.environ["BUFFER_YOUTUBE_CHANNEL_ID"]
    channel = buffer('query { channel(input: { id: ' + json.dumps(channel_id) +
                     ' }) { id service isQueuePaused } }')["channel"]
    if channel["service"].lower() != "youtube" or channel["isQueuePaused"]:
        raise RuntimeError("Buffer channel is not an active YouTube queue")
    entries, sha = ledger()
    releases = []
    for tag in ("youtube-pending", "buffer"):
        r = requests.get(f"{GH}/repos/{os.environ['GITHUB_REPOSITORY']}/releases/tags/{tag}",
                         headers=headers(), timeout=30)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        assets = {a["name"]: a for a in r.json().get("assets", [])}
        for name, a in assets.items():
            if not name.endswith(".mp4") or name[:-4] + ".json" not in assets:
                continue
            stamp = name[:-4]
            # Buffer already shows deliveries through October 18. Never bulk replay older inventory.
            if stamp[:10] < "2026-10-19":
                continue
            if stamp in entries:  # queued, sent, or uncertain. Never duplicate automatically.
                continue
            releases.append((stamp, a, assets[stamp + ".json"]))
    releases.sort(key=lambda x: x[0])
    if not releases:
        print("No eligible unqueued videos found.")
        return
    stamp, asset, metadata = releases[0]
    meta_url = metadata["url"]
    r = requests.get(meta_url, headers={**headers(), "Accept": "application/octet-stream"},
                     timeout=40)
    r.raise_for_status()
    meta = r.json()
    video_url = asset["browser_download_url"]
    u = urllib.parse.urlparse(video_url)
    if u.scheme != "https" or u.hostname not in ("github.com", "release-assets.githubusercontent.com"):
        raise RuntimeError("Refusing unsupported media URL")
    # Buffer must fetch the video without any auth, even hours after queueing.
    probe = requests.get(video_url, headers={"Range": "bytes=0-1023"},
                         stream=True, timeout=35, allow_redirects=True)
    try:
        if probe.status_code not in (200, 206):
            raise RuntimeError(f"Video is not publicly downloadable (HTTP {probe.status_code})")
        if probe.url.startswith("https://") is False:
            raise RuntimeError("Video redirect did not remain HTTPS")
    finally:
        probe.close()
    caption = (meta.get("yt_description") or meta.get("caption_text") or
               meta.get("yt_title") or meta.get("title") or "").strip()
    if not caption:
        raise RuntimeError("Missing caption")
    # Record the attempt BEFORE calling Buffer. Failure or timeout stays held for manual
    # review, because the API may have accepted the post before the connection dropped.
    entries[stamp] = {"status": "attempt_started", "title": meta.get("title"), "source": asset["name"]}
    save(entries, sha)
    query = ('mutation { createPost(input: { text: ' + json.dumps(caption) +
             ', channelId: ' + json.dumps(channel_id) +
             ', schedulingType: automatic, mode: addToQueue, assets: [{ video: { url: ' +
             json.dumps(video_url) + ' } }] }) { ... on PostActionSuccess { post { id } } ' +
             '... on MutationError { message } } }')
    response = buffer(query)["createPost"]
    post = response.get("post")
    if not post or not post.get("id"):
        raise RuntimeError("Buffer did not confirm queue insertion: " + str(response))
    # Refetch SHA after recording attempt. A lost final state remains safely held.
    latest, sha = ledger()
    latest[stamp] = {"status": "queued", "post_id": post["id"], "title": meta.get("title"),
                     "source": asset["name"]}
    save(latest, sha)
    print("Buffer confirmed queued YouTube video: " + stamp + " post_id=" + post["id"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Buffer delivery stopped safely: " + str(exc), file=sys.stderr)
        sys.exit(1)
