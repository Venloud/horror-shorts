# horror-shorts (Night Files)

A free, fully automated, faceless illustrated horror / true-crime / folklore channel: **2 videos a day** to TikTok and YouTube Shorts, built and posted by GitHub Actions.

## Current production flow

Generation and distribution are separate stages:

```
Buffer fill / media test
        ↓
   generate video
        ↓
   GitHub Release buffer
        ↓
 scheduled daily workflow
        ↓
 publish oldest buffered item
        ↓
 TikTok + YouTube independently
```

The scheduled workflow checks the production buffer first. If content is already waiting, it skips generation and publishes the oldest complete item. If the buffer is empty, it generates one video into the buffer and then publishes the next buffered item.

The separate `.github/workflows/buffer_fill.yml` producer can build inventory without publishing. The media-production test lane can also queue finished test output without immediately posting it.

A failed platform post does not delete the buffered item. A successful publish is removed by `pipeline/publish.py` so the same buffered item is not intentionally posted again.

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

- **PersonaLive**: optional recurring-character portrait animation adapter, disabled by default. It activates only when a local PersonaLive checkout, reference image path, and driving video are explicitly configured on a GPU-capable machine. GitHub-hosted CPU runs remain unchanged.
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
  ai_motion.py       optional AI motion, including the PersonaLive adapter
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

## Design system

Night Files UI surfaces use the repository-level `DESIGN.md` as their visual source of truth. It follows the DESIGN.md convention documented by VoltAgent's Awesome DESIGN.md collection: design tokens, typography, components, layout, depth, responsive behavior, and explicit do/don't rules. Before changing a dashboard, buffer viewer, monitoring page, or other UI, read `DESIGN.md` first.


## GitHub Actions workflow roles

Night Files separates repository validation, account connection, generation, and publishing into different workflows.

**Continuous Integration:** `.github/workflows/ci.yml`

This is the project's general **CI** workflow. GitHub runs it automatically on pushes to `main` and pull requests targeting `main`. It checks Python syntax, JSON configuration, Ruflo contracts when present, and critical repository structure.

**CI is not a TikTok connection workflow.** It does not exchange OAuth codes, store tokens, publish videos, or call TikTok/YouTube publishing APIs.

**TikTok connection:** `.github/workflows/connect-tiktok.yml`

This is the separate, manually triggered OAuth workflow. It exchanges the owner's TikTok authorization code for a refresh token and stores that token as a GitHub repository secret.

**Buffer generation:** `.github/workflows/buffer_fill.yml`

Generates inventory into the GitHub Release buffer without publishing.

**Scheduled publishing:** `.github/workflows/daily.yml`

Checks the buffer and publishes the oldest buffered item. It generates only when the buffer is empty.

**YouTube checks/backfill:** `.github/workflows/yt_check.yml` and `.github/workflows/yt_backfill.yml`

These are separate YouTube credential/backfill workflows and are not general CI.

For debugging, identify the workflow first. A `ci.yml` failure is repository validation; a `connect-tiktok.yml` failure is TikTok OAuth setup; a `buffer_fill.yml` failure is generation/buffering; and a `daily.yml` failure is scheduled distribution.
