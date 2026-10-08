# Testing the Flow: research, rationale, implementation plan and test journal

**Status: research and design documented; implementation and end-to-end testing NOT yet completed.**  
**Scope:** Night Files / Venloud/horror-shorts. This is a separate, manual test lane, not a production workflow.

## Why we started

The existing horror-shorts pipeline produces ~61–68 second narrated videos with Gemini/Groq stories, Kokoro voice, stock/archive assets, Cloudflare FLUX and other image fallbacks, FFmpeg rendering, captions and music. The user wants better cinematic movement without making every story conform to a video generator's 10-second clip limit. Generated video is *supporting footage* for the story, not the story format. Short shots can be trimmed and interleaved with existing footage.

The user wants to investigate free/low-cost Google Flow generation, preserve scarce quotas, and avoid breaking an already working automated production/publishing pipeline. The test lane must be fully separate, with checkpoints for repeated experiments, and must preserve any generated Gemini/Groq scripts and Cloudflare images for potential later production use.

## Research and options (not a reliability endorsement)

- **S candidate: Google Flow + [gflow-cli](https://github.com/ffroliva/gflow-cli)**. Unofficial browser automation/CLI/MCP; intended to generate and retrieve MP4s through an authenticated browser session. **Not yet validated in this repo**.
- **A candidate: [google-flow-suite](https://github.com/omid-io/google-flow-suite)**. Chrome extension/Playwright/REST/webhook approach; more moving parts. **Not yet validated**.
- **A candidate: [flow-py](https://github.com/eddie-fqh/flow-py)**. Python Playwright automation. **Not yet validated**.
- **A candidate: [google-flow-skill](https://github.com/DiegoLopez0208/google-flow-skill)**. Claude Code browser integration; useful for supervised local experiments, less certain for unattended GitHub runners. **Not yet validated**.
- Other options considered: [useapi/google-flow-api](https://github.com/useapi/google-flow-api) (third-party service; price/limits to verify), [flow-image-cli](https://github.com/SoKeiKei/flow-image-cli) (unofficial), TikTok Symphony (eligibility/API constraints), Higgsfield (cost), Artflow (no verified general-purpose video API), YouTube mobile AI generation (no verified export/API automation).
- Google Flow free-tier research previously suggested daily free credits (reported 50/day) and different costs per model/resolution. **Treat all credit counts, availability, commercial rights, quotas and allowed automation as unverified until checked against current official Google documentation and the account UI.** Free access to an open-source wrapper does not mean unlimited free generation or permission to automate the website.
- Official starting points: https://labs.google/fx/tools/flow and https://support.google.com/flow/answer/16526234 .
- Research was also committed separately to `Venloud/claudevandam/docs/AI_VIDEO_AUTOMATION_RESEARCH.md` (commit `22a1781`). Cross-check that document before making claims about limits.

## Verified existing code and working patterns inspected

- `.github/workflows/daily.yml`: scheduled production publishing, buffer check, conditional generation, Python/Node/system dependencies, checkpoint restore/save, artifacts and state pushes.
- `.github/workflows/buffer_fill.yml`: generation to production FIFO buffer, checkpoint restore/save, Cloudflare usage tracking, production readiness, artifact upload, history push, and possible make-up posting. **Do not invoke it from the test lane.**
- `pipeline/main.py`: explicitly production-only (`testing = False`), eventually calls `buffer.add(...)`, records production history, and may touch production checkpoints. **Never call `pipeline/main.py` directly for isolated tests.**
- `pipeline/checkpoint.py`: existing checkpoint methods and cache layout; module docstring says tests do not use these checkpoints. **Create a separate test checkpoint implementation/path, not production `cache/checkpoint`.**
- `pipeline/story.py`: Gemini/Groq story-writing logic and structured scenes; reusable building block with attention to side effects.
- `pipeline/sources.py`: `inbox/*.txt` supports `SCRIPT` headers, preserving exact narration for later production. Reusable test scripts should be saved as unique `SCRIPT` files without overwriting existing inbox items.
- `pipeline/images.py`: Cloudflare FLUX and fallback chain, quota accounting; test-mode behavior differs from production and can avoid Cloudflare. **Test the intended Cloudflare path explicitly and enforce a budget; do not assume setting TEST_MODE alone will generate Cloudflare images.**
- `README.md`: production overview and workflow responsibilities.

These findings are from source inspection, **not from running a new test**.

## Non-negotiable isolation and persistence requirements

1. Add a new **manually dispatched** workflow named **Testing the Flow**. No schedule, no publishing, no production buffer updates.
2. Reuse only the needed setup and individual story/voice/visual/render helpers from the working workflows. Do not run production `main.py`, `daily.yml`, `buffer_fill.yml` or `publish.py`.
3. Separate test state: e.g. `cache/testing-the-flow/<test-id>/`, separate Actions cache key namespace and/or durable test artifacts. Never restore/write production `ckpt-*` cache entries.
4. Save story JSON **immediately after Gemini/Groq generates it**, before any further expensive stage. Include model/provider and timestamp if known. On resume, reuse it. A new generation must never silently replace an existing script.
5. Preserve a uniquely named `SCRIPT` inbox-compatible text copy of the exact narration for later use. Preserve the richer story JSON separately. **Avoid automatic production ingestion until explicitly reviewed**; use a staging area or a deliberate safe promotion mechanism, with no duplicate filenames. If the user requests immediate inbox insertion, implement it safely with a distinct commit/PR and explain that production may consume it.
6. Save each successfully generated Cloudflare image immediately, along with prompt, scene/shot ID, source/provider, rights/provenance and checksum where possible. Make assets available for later production reuse **without changing the production library during tests**. Promote deliberately.
7. Store Google Flow generated clips and their prompt/model/credit estimates. Reuse successful clips after reruns, and retry only incomplete/failed stages. Avoid regeneration by default.
8. Save test checkpoints on failure and success; never delete successful assets automatically. Checkpoint writes should be atomic, validate files on resume, and use a stable test ID to prevent cross-run contamination.
9. Strict quotas: default to a no-spend/dry-run preflight, explicit per-run clip count and credit budget, and no automatic credit-consuming retry unless approved. Do not claim credit consumption from estimates alone.
10. Store only nonsecret metadata. Never print credentials, session cookies, browser profiles, OAuth tokens or API keys in logs or artifacts. Avoid publishing private content inadvertently.
11. No `push_state.sh`, `save_history`, `buffer.add`, make-up posting, TikTok/YouTube publishing, production counters or production checkpoint completion.
12. The user's complete story remains ~61–68 seconds (or whatever production specifies). A Google Flow clip is just an optional shot, not a forced 10-second script.

## Proposed stage and checkpoint contract

`preflight -> select-or-write-story -> save-story -> story-bible/shot-rules -> narration -> visual-plan -> Cloudflare/stocks -> Flow-clip-generation -> edit/render -> QA -> archive-test-output`.

Each stage records: status (`pending|started|success|failed|skipped`), start/end timestamps, input hashes, output paths, provider/model, retries, cost/credit estimates and error summary. Only mark a stage successful after validating the expected output. Reruns should resume the earliest missing or invalid stage, never rerun expensive stages solely because a downstream render failed.

**Important technical limitation:** GitHub Actions ephemeral runners cannot assume persistent browser login. An authenticated local Mac runner or a secure supported API may be needed. Do not commit cookies/browser profiles to the repository or upload them as artifacts.

## Test process / logs / failures / outcome

Maintain an append-only journal here or in `docs/testing-the-flow-runs/` for each attempt. Capture:
- Run ID, timestamp, commit SHA, branch, tool/version, execution environment (GitHub hosted vs local Mac).
- Objective and inputs: story ID, scene IDs, generation prompts, requested clip duration, model, budget and dry-run flag.
- Stage results, durations, files/checksums, API/browser errors, any retries and checkpoints restored/saved.
- Quota before/after **only when observed**; otherwise mark as unknown.
- QA results: video decodes, duration, dimensions, content suitability, continuity, whether visuals actually match narration.
- Script preservation: checkpoint path, unique inbox-staging path and promotion status.
- Cloudflare preservation: files, provenance, promotion status.
- Verdict: **PASS / PARTIAL / FAIL / NOT RUN**, with evidence links, cause, fix, and next action.

### Baseline record: 2026-10-08

**Verdict: NOT RUN.** Research and source inspection completed; no new workflow or Flow generation was executed as part of this documentation. Existing daily and buffer-fill workflows were inspected. A major hazard was identified: production `pipeline/main.py` is not a safe test entry point because it buffers and records history. A separate test entry point and isolated state are required. The Google Flow wrappers, real-world free quota, login/session persistence and MP4 retrieval are **untested** in this repo.

### Template for subsequent run entries

```markdown
## Run <ID> | <UTC timestamp> | <commit>
Objective:
Environment / wrapper version:
Story ID / checkpoint restored:
Budget / observed credits before:
Steps attempted:
Generated files and checksums:
Script staging and image archival:
Errors / logs (redacted):
Observed credits after:
QA:
Verdict: PASS | PARTIAL | FAIL
What went wrong:
What fixed it:
Next test:
```

## Definition of success

A manual test starts without touching production; Gemini/Groq story is saved immediately; any Cloudflare images and Flow clips survive a failed run; rerunning with the same test ID reuses valid outputs without additional generation; a valid 61–68 second test MP4 is produced when sufficient assets exist; scripts are available for later production via a deliberate inbox promotion; all evidence is logged; no production history, buffer, publisher or checkpoint is modified.

**Do not claim the integration works until a real test run demonstrates it.**


## Implementation journal: 2026-10-08, first safe scaffold

**Status: PARTIAL IMPLEMENTATION; NOT RUN.** Added `.github/workflows/testing_the_flow.yml` and `testing_flow/runner.py` to main. Manual workflow only, read-only GitHub token, separate test cache prefix `testing-flow-`, no production main.py, buffer or publishing calls. The first run defaults to **dry-run/no story API requests**. Opt-in `generate_story=true` invokes existing `story.write_story([])`, immediately writes a checkpoint JSON and an inbox-compatible `SCRIPT` text file plus rich story JSON to the test artifact. If the checkpoint is restored, it does not regenerate the script. Artifacts have **90-day retention**, not permanent repository storage. Promotion to `inbox/` is NOT yet implemented; users must not assume generated scripts are already in the production inbox. This is intentionally conservative to avoid production consuming a test script unexpectedly.

**Not implemented yet:** authenticated Google Flow wrapper and MP4 downloads, Cloudflare image generation/archive/promotion, narration/render, durable beyond-retention storage, per-stage checkpointing beyond story, actual validation on GitHub Actions, automatic inbox promotion. Google Flow integration requires testing session/auth strategy first. No success claims.

**Research: Fish Audio, 2026-10-08.** Official Fish Audio developer pages advertise a `s2.1-pro-free` API model, Python SDK and REST endpoint, and an initial fair-use free access window through **2026-11-30**, without SLA. Sources: https://fish.audio/developers/ and https://fish.audio/blog/s2-1-pro-free-api/ . Fish Audio's general free website plan says non-commercial only; the developer free API page describes additional commercial conditions. **Do not assume monetized Shorts rights without verifying the exact API model terms.** The official Fish Audio Python SDK is https://github.com/fishaudio/fish-audio-python . Potential role: experimental alternative to Kokoro narration, not a production voice replacement until tested for quality, timing, stability, and commercial rights. No Fish Audio calls made.

**Known risks:** The workflow has not been executed, and GitHub's event YAML and actual story dependencies need validation on first dry run. Do not enable story generation before confirming dry run and checkpoint/artifact behavior. GitHub cache entries are immutable and subject to eviction; uploaded artifacts expire after 90 days. Long-term script preservation requires a separate explicit promotion/storage implementation.


## Unofficial Google Flow integration shortlist, 2026-10-08

**Decision:** Evaluate existing third-party integrations before writing our own automation. Do not add a Google login secret, session cookie, paid subscription or Flow credit-spending action to hosted CI without separate approval.

1. **gflow-cli**, https://github.com/ffroliva/gflow-cli — alpha Python CLI/MCP for generating, batching and downloading via authenticated Chrome. Promising for local Mac runner, but ephemeral GitHub-hosted runner authentication remains unsolved. The tool's own documentation warns of UI drift and account risk.
2. **ParkSangGwon/google-flow-mcp**, https://github.com/ParkSangGwon/google-flow-mcp — local Chrome/CDP MCP with dry-run confirmation and on-disk resume records. Strong fit for checkpoint safety and explicit credit-spend approval. Does not establish unattended hosted CI support.
3. **eddie-fqh/flow-py**, https://github.com/eddie-fqh/flow-py — Python CLI/API and browser-mediated generation, credit checks, media downloads. Unofficial and UI-dependent.
4. **useapi/google-flow-api**, https://github.com/useapi/google-flow-api — examples for third-party hosted REST intermediary that advertises use of a user's Flow credits and $15/month useapi.net service charge, plus Google subscription. Good hosted-CI fit in principle, but paid and requires linking a Google account to an outside provider; user approval and trust review required.
5. **miyakejima/google-flow-mcp**, https://github.com/miyakejima/google-flow-mcp — local MCP with existing subscription and media download, additional candidate.

**Recommendation:** Try gflow-cli locally for a single no-credit auth/status test first, then explicitly approve one low-cost video generation only after confirming status, credit balance and export path. Keep generated media in testing-the-flow storage. If hosted CI is mandatory, separately evaluate the cost, security and service reliability of useapi.net before connecting an account.

**Verification status:** Repositories and documented claims identified; no tool installed or run against the user's account, no authentication, no credits spent, no MP4 produced. Do not mistake a README feature claim for a verified working integration. Existing production workflows remain unchanged.

**Baseline Test1:** GitHub Actions run 37728539150 successfully saved isolated seeded story, script, checkpoint cache and four artifact files; log says `flow: not_attempted_no_verified_adapter`. No actual Flow generation occurred.
