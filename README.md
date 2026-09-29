# horror-shorts (Night Files)

A free, fully automated, faceless illustrated horror / true-crime / folklore channel: **2 videos a day** to
TikTok (drafts) and YouTube Shorts, built and posted by GitHub Actions. The full, current design notes live in
**[CLAUDE.md](CLAUDE.md)** (the main source); setup is in **[SETUP.md](SETUP.md)**.

## How it works

- **Buffer + publisher.** `build.yml` (every 3 h at :50 UTC) keeps up to 3 finished videos on the GitHub Release
  `buffer`. `daily.yml` (15:40 and 00:40 UTC = 11:40 AM / 8:40 PM New York) only posts the oldest one to TikTok
  and YouTube Shorts. An empty buffer at a slot starts a build and posts it as soon as it's ready (within 6 h).
- **Story.** Rotation `lore, mystery, lore, case, coldcase` (+ the owner's `inbox/`), written by Gemini with
  **Groq** (gpt-oss-120b) as backup. True stories are fact-locked to their source (fact ledger + fact check), get a
  critic pass, and never show a real victim's body. Trending topics (Wikipedia pageviews) are picked first.
- **Voice.** Kokoro TTS (`am_michael`), fitted to 50-60 s.
- **Visuals.** Real media first (Pexels / Pixabay stock video, Wikimedia Commons / Smithsonian archive photos,
  credited), then AI images: Cloudflare FLUX -> free Hugging Face Spaces -> local SD-Turbo (max 6). Every image
  gets a vision QA check (Gemini, Groq as backup).
- **Render.** FFmpeg 1080x1920: AI motion on the hook, 2.5D parallax, word-by-word captions, ducked music, real
  sound effects, and an A/B test of visual modes (classic / fast / analog). A QA gate checks every video.
- **Analytics.** `analytics.yml` saves per-Short YouTube stats to `data/analytics.json` by mode and visual mode.
- **Alerts.** ntfy phone notifications with the caption, pinned comment and YouTube link.

Every feature has an on/off flag in `config.json` (see CLAUDE.md); a failing optional feature never stops a video.

```
pipeline/
  main.py            builder: story -> voice -> real media -> images -> render -> QA gate -> buffer
  publish.py         publisher: buffer -> TikTok + YouTube Shorts -> history, post numbers
  story.py           stories, critic, fact check, captions (Gemini + Groq)
  mystery.py         real-story prompts (mystery / lore / true cases), fact lock
  sources.py         inbox, FBI cases, Wikipedia     trends.py   pageview trend picking
  discover.py        NTSB / old newspapers / folklore leads
  voice.py           Kokoro narration + word timings
  media.py           real stock video + archive photos (licenses, credits)
  images.py          AI images + vision QA
  render.py, effects.py, ai_motion.py, captions.py   the video
  buffer.py          GitHub Release buffer          checkpoint.py   resume a failed build
  tiktok.py, youtube.py, notify.py, analytics.py
config.json          all settings and feature flags
data/                history.json, counter.json (post numbers), analytics.json, topic lists
inbox/               owner's links / scripts (jump the queue)
.github/workflows/   build, daily, analytics, buffer_cleanup, yt_check, yt_upload_test, voice_samples,
                     connect-tiktok, get-sfx
```
