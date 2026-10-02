# horror-shorts (Night Files)

A free, fully automated, faceless illustrated horror / true-crime / folklore channel: **2 videos a day** to TikTok and YouTube Shorts, built and posted by GitHub Actions.

## Current production flow

One scheduled workflow does the whole job:

```
daily.yml
   ↓
generate story
   ↓
voice
   ↓
real media + AI visuals
   ↓
render 61-68s video
   ↓
QA REPORT ONLY
   ↓
put successful render in buffer
   ↓
publish.py immediately
   ↓
TikTok + YouTube independently
```

There is **no separate build page/workflow** in the current production design. The GitHub Release buffer is storage and duplicate protection, not a separate production stage.

A successful render is not blocked by the QA report. If TikTok fails, YouTube is still attempted. If both platforms fail, the buffered video is retained for the next attempt instead of being deleted.

## Posting

- `.github/workflows/daily.yml` runs at **11:40 AM and 8:40 PM New York**.
- Each run generates one production video and immediately invokes `pipeline/publish.py`.
- TikTok currently uses the configured account mode in `config.json`. The current setting is `draft`, so it safely sends TikTok content to drafts until Direct Post access is approved.
- YouTube uploads are enabled and configured for public Shorts.
- Duplicate-post protection and `removal_pending` protection remain enabled.
- A successful render is never intentionally discarded just because QA reports a problem.

## Pipeline

- **Story.** Rotation `lore, mystery, lore, case, coldcase` (+ the owner's `inbox/`), written by Gemini with Groq as backup. True stories are fact-locked to their sources.
- **Voice.** Kokoro TTS, fitted to the 61-68 second target.
- **Visuals.** Real media first, then Cloudflare FLUX, free Hugging Face Spaces, and local fallback generation.
- **Render.** FFmpeg 1080x1920 with word-by-word captions, motion/effects, music ducking, and sound effects.
- **QA.** Diagnostic/reporting only in production. It does not become a publishing gate.
- **Analytics.** YouTube Shorts analytics are stored in `data/analytics.json`.

## External integrations

Night Files is integrating the external projects **one at a time**, rather than copying five full repositories into the production codebase.

### Remotion, active

Remotion is now part of the production composition path. It joins the generated shot clips with a frame-based React composition. If the Remotion stage fails, Night Files automatically falls back to the existing FFmpeg joiner so a temporary Remotion problem does not discard a successful render.

The remaining integrations are staged:

- **PersonaLive**: optional recurring-character animation stage, planned for a GPU-capable environment.
- **MuMuAINovel**: narrative planning and consistency ideas, without copying its GPL-3.0 application code into Night Files.
- **Auto Clip MVP**: alternate clip extraction after the primary video is rendered.
- **Ruflo**: orchestration after the individual stages are stable.

See **[NIGHT_FILES_UPDATE.md](NIGHT_FILES_UPDATE.md)** for the integration notes and search-query backlog.

## Repository layout

```
pipeline/
  main.py            generator: story -> voice -> visuals -> render -> QA -> buffer
  publish.py         publisher: buffer -> TikTok + YouTube -> history
  story.py           story generation, critic, fact checks
  mystery.py         mystery / lore / case prompts
  sources.py         source and inbox handling
  trends.py          trend/topic selection
  discover.py        research leads
  voice.py           narration + word timings
  media.py           real stock/archive media
  images.py          AI images + visual QA
  render.py          final FFmpeg render
  effects.py         motion/effects
  ai_motion.py       optional AI motion
  captions.py        caption generation
  buffer.py          GitHub Release buffer
  checkpoint.py      build resume support
  tiktok.py          TikTok publishing
  youtube.py         YouTube publishing
  notify.py          phone alerts
  analytics.py       analytics

config.json          production settings
data/                history, post counter, analytics
inbox/               owner-supplied links/scripts
.github/workflows/   daily, analytics, OAuth checks and maintenance
```
