# YouTube browser uploader, experimental (NOT production ready)

Goal: upload Night Files video files to YouTube without YouTube Data API, on a cloud computer that runs while the owner's Windows PC is off.

Current status: **staging prototype only**. No YouTube video can be published by this code. No workflows, schedules, user-paused flags or existing uploaders have been changed.

## What already works in code

* Fetch oldest complete `.mp4` + `.json` pair from the existing GitHub Release `buffer`.
* Use the video's existing YouTube title and description.
* Open a persistent Chrome profile using Playwright on a cloud VM.
* Attempt to stage the video as **Private**, for interactive inspection only.

The actual YouTube Studio interface and Google account login behavior need testing on the chosen cloud VM. Selectors can change. YouTube may challenge or reject automated sign-in. The script intentionally stops before final Save or Publish, and must never be mistaken for a working automatic uploader.

## Necessary setup

1. Provision a continuously available cloud VM with a GUI / remote desktop, encrypted persistent disk, Chromium, Python, Playwright, and browser dependencies. Free ephemeral GitHub-hosted runners do not give a persistent authenticated desktop.
2. Set a least-privilege GitHub access token as `GH_TOKEN` on the VM, not in the repository. Set `GITHUB_REPOSITORY=Venloud/horror-shorts`.
3. Install dependencies: `pip install requests playwright`, then `python -m playwright install --with-deps chromium`.
4. Open the browser ON THAT VM and manually authenticate to your own YouTube account. Do not share credentials, browser cookies or the browser profile with an agent.
5. Run `python tools/youtube_cloud_browser.py` to test download-only mode.
6. Run `python tools/youtube_cloud_browser.py --stage-private` to inspect private-upload staging, with screen access to the cloud VM.
7. Before enabling automatic publishing, implement and test robust upload completion detection, duplicate detection, recording of YouTube video IDs in a durable store, retries, moderation handling, metadata checks, and post confirmation.
8. Add scheduling only after explicit owner approval, and after the previous production pause is lifted.

## Safety

* No public uploads until explicitly enabled by the owner.
* Never commit browser profiles, cookies, tokens, or session state.
* Never delete buffered video pairs merely because a browser click succeeded.
* Keep the original YouTube API integration untouched.
* Avoid posting a buffered item twice when TikTok and YouTube differ.
