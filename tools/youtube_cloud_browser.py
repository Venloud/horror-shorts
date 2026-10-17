"""Experimental no-YouTube-API uploader using an authenticated persistent browser.

Run only on a cloud VM with a persistent encrypted HOME and interactive browser access.
A human signs in to YouTube once in this SAME VM browser. Do not save browser
profiles, cookies, or credentials to GitHub Actions artifacts or repository files.

Default: dry run. Private uploads only while testing. This tool does NOT
automatically delete releases or modify the existing publisher history.
"""
import argparse
import json
import os
from pathlib import Path
import sys

import requests
from playwright.sync_api import sync_playwright

API = "https://api.github.com"
PROFILE = Path(os.environ.get("YT_BROWSER_PROFILE", str(Path.home() / ".config/nightfiles-youtube")))
REPO = os.environ.get("GITHUB_REPOSITORY", "Venloud/horror-shorts")
TOKEN = os.environ.get("GH_TOKEN", "")
TIMEOUT = 180_000


def headers(accept="application/vnd.github+json"):
    if not TOKEN:
        raise RuntimeError("GH_TOKEN required with read access to the repository")
    return {"Authorization": f"Bearer {TOKEN}", "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28"}


def find_buffer_pair():
    response = requests.get(f"{API}/repos/{REPO}/releases/tags/buffer",
                            headers=headers(), timeout=30)
    response.raise_for_status()
    assets = response.json()["assets"]
    by_stem = {}
    for a in assets:
        stem, dot, ext = a["name"].rpartition(".")
        if dot and ext in ("mp4", "json"):
            by_stem.setdefault(stem, {})[ext] = a
    pairs = sorted((stem, files) for stem, files in by_stem.items()
                   if "mp4" in files and "json" in files)
    if not pairs:
        raise RuntimeError("No complete video pair in GitHub Release buffer")
    return pairs[0]


def download(asset, dest):
    with requests.get(asset["url"], headers=headers("application/octet-stream"),
                      stream=True, timeout=600) as response:
        response.raise_for_status()
        with dest.open("wb") as out:
            for chunk in response.iter_content(1024 * 1024):
                out.write(chunk)


def upload_private(mp4, title, description):
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), headless=False, accept_downloads=False,
            args=["--no-first-run"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=TIMEOUT)
            if "accounts.google.com" in page.url:
                raise RuntimeError("YouTube login required in the cloud browser before upload")
            page.get_by_role("button", name="Create").click(timeout=TIMEOUT)
            page.get_by_text("Upload videos", exact=True).click(timeout=TIMEOUT)
            page.locator('input[type="file"]').set_input_files(str(mp4), timeout=TIMEOUT)
            title_box = page.locator("#textbox").first
            title_box.wait_for(timeout=TIMEOUT)
            title_box.fill(title[:100])
            page.locator("#textbox").nth(1).fill(description[:5000])
            page.get_by_text("No, it's not made for kids", exact=False).click(timeout=TIMEOUT)
            # Next: details, video elements, checks; UI can vary and checks may take time.
            for _ in range(3):
                page.get_by_role("button", name="Next", exact=True).click(timeout=TIMEOUT)
            page.get_by_text("Private", exact=True).last.click(timeout=TIMEOUT)
            # Requires explicit approval per run. No accidental public posting.
            print("Private video upload is staged. Review it in the browser.")
            input("Type CONFIRM after visually verifying the private destination: ")
            # Intentionally does not click Save. We must validate selectors and
            # upload-completion behavior on this account before automation.
            raise RuntimeError("Safe prototype only: final Save not implemented")
        finally:
            ctx.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-private", action="store_true",
                        help="Open browser and stage a private upload, never finalize")
    args = parser.parse_args()
    stamp, assets = find_buffer_pair()
    dest = Path(os.environ.get("YT_UPLOAD_WORKDIR", "/tmp/nightfiles-yt"))
    dest.mkdir(parents=True, exist_ok=True)
    mp4, meta_path = dest / f"{stamp}.mp4", dest / f"{stamp}.json"
    download(assets["mp4"], mp4)
    download(assets["json"], meta_path)
    meta = json.loads(meta_path.read_text())
    title = meta.get("yt_title") or meta.get("title", "")
    description = meta.get("yt_description") or meta.get("caption_text", "")
    print(f"Downloaded buffered video: {stamp}, {mp4.stat().st_size} bytes")
    print(f"Title: {title}")
    if not args.stage_private:
        print("DRY RUN: no browser opened, no YouTube upload attempted")
        return
    upload_private(mp4, title, description)


if __name__ == "__main__":
    main()
