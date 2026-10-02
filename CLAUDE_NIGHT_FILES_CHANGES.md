# Night Files, Claude Handoff, 2026-10-02

## Purpose

This file records the production changes made directly tonight so Claude Code has a durable handoff.

**Important:** Do NOT clear, purge, or recreate the `buffer` release just because it is empty. The buffer is intentionally left intact. The production builder will refill it.

## Production policy now

1. **Production-only builds.** The `build.yml` workflow no longer exposes the old `test` workflow_dispatch input.
2. **Every successful render is production.** `pipeline/main.py` no longer uses `--test` or `--no-upload` as an operational path.
3. **QA is report-only for production.** A QA failure is logged and alerted, but it does NOT discard the rendered video, skip the story, wait for quota, or block the buffer.
4. **QA still reports problems.** `summary.txt` continues to record PASS/FAIL details, and a QA report-only notification is attempted.
5. **A successfully rendered video goes to the production buffer even when QA reports problems.**
6. **Publishing remains protected against duplicate posts.** A video recorded as already posted is removed from the buffer rather than posted again.
7. **Do not interpret QA failure as permission to stop publishing.** QA is diagnostic, not a publishing gate.

## Changes made tonight

### 1. Build hold summary
Commit: `4594fd59`

Updated `.github/workflows/build.yml` so an active production hold writes a clear GitHub Step Summary showing videos waiting, target buffer size, the hold file, and that no generation/posting work was performed.

### 2. YouTube OAuth scope verification
Commit: `f6c67481`

Updated `.github/workflows/yt_check.yml` to request and verify both:
- `https://www.googleapis.com/auth/youtube.upload`
- `https://www.googleapis.com/auth/yt-analytics.readonly`

This verifies OAuth scope. It does **not** enable the YouTube Analytics API in Google Cloud.

### 3. Production build hold released
Commit: `92bc9d56`

Deleted `data/hold_builds.txt`.

**Do not recreate this hold file unless there is a deliberate decision to stop production generation.**

### 4. Test mode removed from the builder
Commit: `130adcb0fad44f98b3ce2d365fdf833f082c2669`

Updated `pipeline/main.py`:
- removed the operational `--test` / `--no-upload` path
- production builds are the only normal path
- successful renders continue toward the production buffer
- QA failure no longer causes the story to be skipped or stopped for low-quota visual issues

### 5. Test mode removed from GitHub Actions
Commits:
- `02e3e044ddf21f9148d6a0428c6fb8b37b21723c`
- `64306d78a0bba7d366d3437e6358a7385aa1b531`

Updated `.github/workflows/build.yml`:
- removed the `test` dispatch input
- removed test-only `fresh_images` and `inbox_file` inputs
- removed the old `ignore_hold` input
- removed test image-cache restore
- removed deferred-test handoff
- build now runs simply as `python main.py`
- production checkpoint/history saving no longer depends on the old test flag
- production artifact naming no longer has a test-build branch
- buffer check only asks whether the production buffer has fewer than 3 videos

### 6. Deferred test workflow removed
Commit: `41811166f959c91fe473b2dbdf4e4c99b019f09a1`

Deleted `.github/workflows/deferred_test.yml`.

There is no longer an automated deferred test-build path.

## Existing protections that were NOT removed

These were already fixed before the test-mode removal and should remain:

- Missed-slot deletion only happens after a successful make-up post.
- Duplicate-post protection prevents a buffered video with a recorded `posted` history entry from being posted again.
- Buffer removal failure records `removal_pending` so the next run removes the already-posted video instead of reposting it.
- Daily workflow dispatch uses the GitHub Actions token first.
- Build and daily workflows share the `night-files` concurrency group.
- Analytics has its own concurrency group.
- `data/hold_builds.txt` is absent.
- The buffer must NOT be manually cleared.

## Current production flow

```
scheduled build every 3h
        |
        v
buffer < 3?
   | yes
   v
build story -> voice -> visuals -> render
        |
        v
QA REPORT ONLY
        |
        v
buffer.add(...)
        |
        v
normal publish slot / missed-slot recovery
        |
        v
TikTok + YouTube attempted independently
        |
        v
remove buffered video only after at least one platform succeeds
```

If a build itself crashes before a finished render reaches the buffer, that is still a real build failure and should be investigated. The "every video posts" rule applies to successfully rendered production videos, and QA is no longer allowed to be the reason one is withheld.

## Latest supplied artifact

The supplied Night Files artifact was:
- story: **The Corpse That Chewed Its Shroud**
- duration: **65.2s**
- QA gate: **PASSED**
- visuals: **14 distinct**, 6 archive/stock, 8 AI
- research sources: Wikipedia
- mode: lore

The generated story data identifies it as a folklore/legend story, not a true story.

## Claude instructions

1. Treat this file as the production-policy handoff.
2. Do not reintroduce a test-only production path without explicit approval.
3. Do not turn QA back into a hard publishing gate without explicit approval.
4. Do not clear the buffer as a fix.
5. Do not recreate `data/hold_builds.txt` unless explicitly instructed.
6. Preserve duplicate-post and removal-pending protections.
7. If a video is rendered successfully, the intended path is buffer -> publish, even if QA reports visual/content issues.
8. Fix underlying QA issues separately from the publishing path.
