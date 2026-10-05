# Night Files Update Notes

Updated: 2026-10-02

## Immediate production goal

Keep the production path simple and reliable:

```
scheduled daily run
    -> generate
    -> render
    -> QA report only
    -> buffer
    -> publish immediately
```

The buffer must not be cleared as a troubleshooting step.

## Posting status

The daily workflow now calls `pipeline/publish.py` immediately after a successful `pipeline/main.py` run.

Posting behavior is intentionally independent by platform:

- TikTok is attempted using the mode in `config.json`.
- YouTube is attempted independently.
- If one platform fails, the other can still succeed.
- If neither succeeds, the video stays buffered for another attempt.
- A video already recorded as posted is never posted a second time.
- Buffer removal can be retried through the `removal_pending` protection.

Current TikTok setting:

```json
"tiktok_mode": "draft"
```

This should not be changed to pretend Direct Post is available. Public TikTok Direct Post depends on TikTok approval/audit.

## External projects to study

These are research/integration candidates, not repositories to blindly copy into Night Files.

1. Remotion
   - Programmatic video composition in React.
   - Possible use: deterministic scenes, captions, transitions, and reusable composition components.
   - https://github.com/remotion-dev/remotion

2. PersonaLive
   - Real-time portrait/avatar animation research.
   - Possible use: persistent narrator/character animation if Night Files adopts a recurring character.
   - https://github.com/GVCLab/PersonaLive

3. MuMuAINovel
   - AI novel/story generation project.
   - Possible use: narrative planning, story structure, scene planning, and longer-form story ideas.
   - https://github.com/deckergcs/MuMuAINovel

4. Auto Clip MVP
   - Candidate automatic clipping/captioning workflow.
   - Possible use: generate alternate hooks/clips from an already rendered Night Files video.
   - https://github.com/zamrojihandak-max/ai-content-factory-mvp
   - Alternate clip/caption MVP found during research:
     https://github.com/bensblueprints/video-clip-captioner-mvp

5. Ruflo
   - Multi-agent orchestration framework.
   - Possible use: future research -> writer -> visual planner -> QA -> packaging orchestration.
   - https://github.com/ruvnet/ruflo

## Integration order

Do not replace the working pipeline all at once.

### 1. Remotion, integrated

Night Files now uses Remotion for the **shot-joining/composition stage** when `remotion_join` is enabled in `config.json`.

The existing pipeline still creates and normalizes individual shot clips. Remotion then places those clips on a frame-accurate timeline and handles the transition overlap. The mature FFmpeg xfade implementation remains an automatic fallback if the Remotion render fails.

This is intentionally the first integration step. It gives Night Files a real Remotion composition layer without replacing the mature audio/effects/final-encoding system in one risky change.

### 2. PersonaLive, integrated as an optional adapter

PersonaLive is now connected to Night Files through the existing `pipeline/ai_motion.py` motion stage, but it is **disabled by default**. The adapter only runs when `persona_live.enabled` is enabled and a local PersonaLive checkout plus a driving video are configured. It invokes PersonaLive's offline inference script and returns the generated MP4 to the normal AI-motion path.

This does not add PersonaLive's heavyweight dependencies or model weights to GitHub Actions. GitHub-hosted CPU runs continue using the existing free Hugging Face motion path and 3D fallback. PersonaLive is intended for a GPU/self-hosted environment where the user explicitly provides the model installation and driving video.

The public PersonaLive project documents offline inference using a reference image and driving video, and its current README describes it as a real-time, streamable diffusion framework for portrait animation. urlPersonaLive READMEhttps://github.com/GVCLab/PersonaLive/blob/main/README.md

### 3. MuMuAINovel, integrated as a local story-bible stage

Night Files now uses a small deterministic `pipeline/story_bible.py` stage inspired by MuMuAINovel's outline, character/worldbuilding, timeline, and consistency concepts. It runs after the story is written and before shot planning.

The stage:
- creates canonical character names and fixed looks;
- records the story setting, threat, twist, and twist scene;
- builds a scene-by-scene timeline with narration, location, and mentioned characters;
- creates explicit continuity rules for visual planning;
- injects that bible into the shot-prompt rewrite so the image planner is less likely to change a character's look, location, or ending detail.

It adds **no extra AI call** and does not add MuMuAINovel's GPL-3.0 application code to Night Files. The existing Night Files writer remains responsible for production stories.

This is intentionally a lightweight integration of the useful narrative-planning ideas rather than a deployment of the full MuMuAINovel application.

### 4. Auto Clip MVP

Add this after the main render is stable. It should consume the finished Night Files MP4 and create alternate short clips/hooks without changing the primary post.

### 5. Ruflo, next implementation

Status: **NEXT, not yet implemented in Night Files production**.

Research checked against the current official Ruflo project. Ruflo is an agent meta-harness for Claude Code and Codex, with agent routing, swarms, memory, hooks, and workflow orchestration.

Night Files must **not** make Ruflo a required production dependency. Normal GitHub Actions runs must continue to work without Ruflo installed globally, an Anthropic API key added to GitHub Actions, a Ruflo daemon, a live multi-agent swarm, or a network-dependent orchestration service.

First Ruflo integration target:
1. Add a local, declarative orchestration map describing the existing Night Files stages: research -> story -> story bible -> shot rules -> visuals -> voice -> render -> QA -> buffer -> publish.
2. Add reusable task/agent role definitions for planner, researcher, writer, visual planner, QA reviewer, and packaging reviewer.
3. Make the integration read-only/non-blocking for production at first. The existing Python pipeline remains the source of execution truth.
4. Keep secrets unchanged. Ruflo must not require any new secret for the first integration.
5. Add a local doctor/validation step that verifies the orchestration files are syntactically valid and prints what would be delegated, without actually spawning agents during production.
6. Only after that validation is stable should we consider using Ruflo for selected non-production tasks such as topic research, story review, or QA analysis.

Why this shape:
- Ruflo's official Quick Start creates .claude/, .claude-flow/, and hook configuration and can initialize swarms and persistent memory, but those heavyweight pieces are not necessary for Night Files' first integration.
- Night Files is in the Oct 2-8 feature freeze, so this integration must not alter the production path until separately validated.
- The goal is to coordinate existing stages, not replace the proven generator or publisher.

Official references:
- https://github.com/ruvnet/ruflo
- https://github.com/ruvnet/ruflo/wiki/Quick-Start
- https://github.com/ruvnet/ruflo/wiki/Installation


### Ruflo first-stage integration design

Implementation rule: **do not install or execute Ruflo inside the normal production workflow yet**.

The first Night Files integration is intentionally a local orchestration manifest plus validator. It mirrors the real pipeline, records which role owns each stage, and can be consumed by Claude Code/Ruflo later.

Proposed files:
- `pipeline/ruflo_plan.json`: stage/role/dependency map.
- `pipeline/ruflo_check.py`: zero-dependency validator that checks the manifest and prints the delegation plan.
- `docs/RUFLO_INTEGRATION.md`: exact handoff rules, role descriptions, and future activation path.

## Search-query backlog

These are topic/search queries captured from the creator analytics screenshot for later research. Keep the original wording available so future trend analysis can compare it with normalized queries.

### Captured queries

- what is a grim reaper
- mona lisa painting
- mannanagal folklore
- Gol illegal fifs
- monalisa

### Normalized research variants

- what is a grim reaper
- grim reaper explained
- grim reaper folklore
- Mona Lisa painting history
- Mona Lisa mystery
- Mannananggal folklore
- Manananggal folklore
- Philippine folklore creatures
- illegal FIFA / FIFA illegal controversy

The screenshot appears to contain a typo or transcription issue in **"Gol illegal fifs"**. Keep the original query in the captured list, but use the normalized variants only after verifying what the source actually intended.

## Topic research rule

When a topic is selected for a Night Files story:

1. Search the exact query first.
2. Identify what people are actually asking about.
3. Look for a specific mystery, historical event, folklore creature, documented case, or unanswered question.
4. Verify factual claims with reliable sources before labeling a story true.
5. Do not copy another creator's script.
6. Convert the topic into an original Night Files hook and story.

## Quality target for future updates

The first 10 seconds should answer:

- What happened?
- Why should the viewer care?
- What specific mystery or question is unresolved?

Avoid generic openings such as "Have you ever wondered..." unless the actual question is immediately specific.



## Expanded Night Files topic backlog

These topic families are intended for future topic selection and hook generation. They should be treated as a research backlog, not as claims that every topic is factual.

### Haunted objects and cursed artifacts
- Dybbuk Box
- Annabelle and the real-world history behind the doll
- The Conjuring / Perron family case
- The Crying Boy paintings
- Robert the Doll
- The Hands Resist Him painting
- The Basano Vase
- The Black Aggie statue
- Hope Diamond stories

### Strange experiments and programs
- Russian Sleep Experiment, including its fictional origin
- Stanford Prison Experiment
- MKUltra
- Monster Study
- Little Albert experiment
- Third Wave experiment
- Philadelphia Experiment
- Remote-viewing programs
- Montauk Project
- Stargate Project

### Folklore creatures
- Manananggal
- Chupacabra
- Mothman
- Jersey Devil
- Wendigo
- Skinwalker folklore
- Black-Eyed Children
- Dover Demon
- Flatwoods Monster
- Fresno Nightcrawler
- Beast of Bray Road
- Loveland Frog
- Hopkinsville Goblins
- Enfield Horror
- Ozark Howler

### Historical mysteries and disappearances
- Mary Celeste
- Dyatlov Pass
- Somerton Man
- Sodder children
- Amelia Earhart
- Isdal Woman
- Lead Masks Case
- Hinterkaifeck
- Villisca Axe Murders
- Tamam Shud
- Dancing Plague of 1518
- London Monster
- Ambrose Bierce disappearance
- Man in the Iron Mask
- Princes in the Tower

### Ancient, biblical, and archaeological mysteries
- Ark of the Covenant
- Antikythera Mechanism
- Voynich Manuscript
- Cleopatra's lost tomb
- Ninth Legion
- Nazca Lines
- Derinkuyu underground city
- Terracotta Army
- Göbekli Tepe
- Atlantis
- Amber Room
- Oak Island
- Copper Scroll
- Phaistos Disc

### Places and location-driven mysteries
- Abandoned towns and villages
- Restricted islands
- Strange forests and disappearance legends
- Haunted roads
- Unexplained hotel rooms
- Staircases in remote woods
- Unexplored caves
- Island of the Dolls
- Locations associated with repeated eyewitness reports

### Search-first question topics
- What is the Grim Reaper?
- Why are people afraid of 666?
- Mona Lisa painting mysteries
- Why does the Wow! signal remain unexplained?
- What happened to Roanoke?
- Who was the Somerton Man?
- Why did the Dancing Plague happen?
- What really happened at Dyatlov Pass?
- What is the Manananggal?
- Was the Chupacabra ever actually found?
- Where could the Ark of the Covenant be?
- Who created the Voynich Manuscript?
- What was the Philadelphia Experiment?
- What happened to the Mary Celeste crew?
- Who built Göbekli Tepe?

## List, ranking, and countdown formats

The topic engine should also generate **list-style posts**, especially formats that create a clear reason to keep watching until the next item.

Example format from the creator's reference:

> Four archaeological discoveries that were never meant to see the light of day.

This is a **format/hook template**, not a factual claim. The individual discoveries still need research and verification.

### Ranking-style formats

Use numbered or ranked structures when the subjects can be compared using a clear, defensible criterion.

Examples:
- 4 archaeological discoveries that were never meant to see the light of day
- 5 ancient discoveries that raised more questions than answers
- 7 places archaeologists still cannot fully explain
- 5 historical mysteries with the strangest evidence
- 6 lost objects people are still searching for
- 5 abandoned places with disturbing histories
- 7 folklore creatures people once genuinely feared
- 5 experiments that changed what scientists understood about human behavior
- 4 archaeological sites that changed our understanding of the ancient world
- 6 discoveries that were found completely by accident
- 5 mysterious objects whose purpose is still debated
- 7 disappearances that remain unresolved
- 5 ancient texts nobody has fully decoded
- 4 historical discoveries that were hidden, buried, or deliberately concealed
- 5 strange artifacts found in places they should not have been
- 6 archaeological discoveries that sounded impossible before they were found

### Ranking hooks

Possible opening structures:

- "These are 5 of the strangest..."
- "Number 5 is strange. Number 1 is still unexplained."
- "Five discoveries changed what historians thought they knew."
- "These four finds were buried for centuries. Then someone uncovered them."
- "Here are five discoveries that raised more questions than answers."

Do not use fake rankings or imply an objective "best" or "worst" order when there is no defensible criterion. If a countdown is used, define the basis for the order in the research or script.

### Other repeatable list formats

Rotate list structures so every video does not feel like the same countdown:

1. **Top N / countdown**: ranked from #N to #1.
2. **N discoveries**: each item gets one surprising fact.
3. **N mysteries, one common thread**: separate cases connected by a theme.
4. **Then vs. now**: what people believed before a discovery and what changed afterward.
5. **N theories**: documented explanations for one mystery, clearly separating evidence from speculation.
6. **N clues**: strongest documented clues surrounding an unresolved case.
7. **N places**: locations connected by a specific historical or archaeological theme.
8. **N objects**: artifacts, manuscripts, paintings, or other unusual finds.
9. **N things you didn't know**: only when every item can be independently verified.
10. **From least to most mysterious**: only when the ordering criterion is explicitly explained.

### List-post research rules

For every item in a list:

- Verify the item's name and basic claim independently.
- Prefer primary sources, museums, archaeological institutions, academic sources, government records, or reputable historical references.
- Keep folklore, disputed interpretations, and speculation clearly labeled.
- Do not invent an ordering just to create drama.
- The title can promise a list, but the script should quickly deliver the first concrete fact.
- Avoid padding the list with weak items just to reach a target number.
- A 4-item list with strong evidence is better than a 10-item list with filler.

## Topic-selection rules

The topic engine should prefer subjects that can produce a **specific curiosity question** rather than generic horror.

Prefer:
- A named person, place, object, creature, experiment, event, or case.
- A concrete unanswered question.
- A strange documented detail that can appear in the first 10 seconds.
- Topics with enough reliable source material to verify claims.
- Topics that can be explained clearly at roughly third-grade reading level.

Avoid:
- Generic "scary story" prompts with no specific subject.
- Repeating the same famous case too frequently.
- Presenting folklore as established fact.
- Presenting fictional internet stories as true.
- Making a claim stronger than the available evidence.

### Hook transformation examples

Weak:
> Today we're talking about the Dyatlov Pass incident.

Stronger:
> Nine hikers entered the Russian mountains. All nine died. Then rescuers found their tent cut open from the inside.

Weak:
> The Chupacabra is a mysterious creature.

Stronger:
> Farmers in Puerto Rico began reporting animals with strange wounds. Then people started saying they had seen the same creature.

Weak:
> Have you heard of the Voynich Manuscript?

Stronger:
> Someone wrote a book centuries ago in a script nobody can reliably read. And nobody knows who wrote it.

The stronger examples are **hook templates**, not factual claims to publish without source verification.

## Content pillars for future topic rotation

Rotate across:
1. True mysteries
2. Unsolved disappearances
3. Haunted objects
4. Haunted locations
5. Folklore creatures
6. Strange experiments
7. Dark history
8. Ancient mysteries
9. Government / intelligence history
10. Unexplained phenomena
11. Creepy internet stories, clearly labeled when fictional or unverified
12. Weird science
13. Bizarre documented crimes
14. Lost places
15. Cursed-artifact legends

The generator should use the pillar as a constraint, then independently research and verify the selected topic before scripting it.


## Ruflo implementation update, 2026-10-02

Ruflo is no longer only a planned documentation item. The first implementation layer is now in the repository, while production remains unchanged.

### Implemented

The orchestration manifest remains at `pipeline/ruflo_plan.json` and the original safety validator remains at `pipeline/ruflo_check.py`.

Added the reusable task contracts under `docs/ruflo_tasks/`:

1. Planner, maps requested work to the existing Night Files stages.
2. Researcher, verifies source material and separates evidence from folklore/speculation.
3. Story writer, drafts narration under the existing hook, fact-lock, duration, and fiction rules.
4. Visual planner, maps narration to specific shots while preserving story-bible continuity and visual safety rules.
5. QA reviewer, reports failures and evidence without overriding safeguards.
6. Packaging reviewer, checks platform metadata without touching upload/authentication transport.

Added `pipeline/ruflo_task_check.py`, a dependency-free validator for those six contracts.

### Why this is the current implementation boundary

Ruflo is being integrated as an orchestration layer, not as a replacement for Night Files. The existing Python generator, renderer, QA, buffer, and publisher remain the production source of truth.

The first implementation intentionally does **not**:

- install Ruflo into GitHub Actions;
- add an Anthropic API key or any new secret;
- start a Ruflo daemon;
- start a swarm or MCP server;
- change TikTok or YouTube publishing;
- change the buffer release behavior;
- make production depend on network-based agent orchestration.

This means the new layer can be validated independently without increasing the failure surface of the daily production run.

### Validation requirements

Run:

```bash
python pipeline/ruflo_check.py
python pipeline/ruflo_task_check.py
```

Expected markers:

```
RUFLO CHECK: PASS
RUFLO TASK CHECK: PASS
```

### Exact current state

**Ruflo status: contract-ready, production-disabled.**

The next implementation is not another documentation-only pass. Once both validators pass, the next step is to execute one isolated Ruflo-style task outside the production workflow and compare its output against the existing Night Files pipeline before any production delegation is enabled.


## Ruflo implementation ledger, 2026-10-02

This section is cumulative. Every Ruflo-related commit made so far is recorded here so the repository remains self-documenting and the next implementation can start from a known state.

### Commits completed

1. `55dba71653467bce61c0e72867f5d189e2977548` - Add concrete Ruflo first-stage integration design. Established the first-stage architecture and explicitly kept Ruflo outside production.
2. `157a9875aa0945d0dfe8fc0fcaaeaa5ff3a6cbb9` - Document Ruflo integration plan and safety constraints. Recorded the activation sequence, production boundary, and safety rules.
3. `767242e1f811885ee513a7a3c2ea4359f6527e64` - Add Ruflo integration `pipeline/ruflo_plan.json`. Added the declarative stage/dependency/role map for research through publishing.
4. `9ff04cfce6cc7338525bc0efa49131fd6850f1b6` - Add Ruflo integration `pipeline/ruflo_check.py`. Added the zero-dependency manifest validator and delegation-graph check.
5. `a24cd4f27bc0789dd14b83850bf6ffd79561a93f` - Add Ruflo integration docs. Added the dedicated integration reference and activation boundaries.
6. `4879e18f0a60cdebcdddd1c3b4c1f7fa2cf74481` - Add planner task contract. Defined how Ruflo planning maps onto existing Night Files stages without replacing them.
7. `01cd3726fe82ff8de6663e3777f897daec2cb6bf` - Add researcher task contract. Defined source-backed research, evidence tracing, and folklore/speculation separation.
8. `9f3bda761e04662b2ddee12e5e58277612fdc55f` - Add story-writer task contract. Defined narration generation/revision under fact-lock, hook, duration, and fiction rules.
9. `a2b1bd4bb8775f97dd39c6725fb8fdaf8c8416b3` - Add visual-planner task contract. Defined shot planning, continuity, and visual safety requirements.
10. `f4099b098e1f32e8ea85af0f30a8114caa8ff01e` - Add QA-reviewer task contract. Defined diagnostic review and failure reporting without bypassing gates.
11. `4d05bc1c3d7efdb8ba362ade2e075125bd50af3f` - Add packaging-reviewer task contract. Defined metadata review while leaving TikTok/YouTube transport untouched.
12. `b7c6a6d9c8cf2737f7fcdc23c0244631cd561210` - Add Ruflo task-contract validator. Added `pipeline/ruflo_task_check.py` to verify all six contracts and their required sections.
13. `e4b61ac216553a1ce0501b16e5274db587aeb216` - Document implemented Ruflo task contracts. Expanded `docs/RUFLO_INTEGRATION.md` with exact files, validator behavior, and current activation state.
14. `0242173df1e81a52e07640c8716a8bce501f7f9b` - Record implemented Ruflo task contracts. Added the cumulative implementation update to `NIGHT_FILES_UPDATE.md`.
15. `6f6d428eb5396b1a1fac34ea2ee53f38262353eb` - Mark Ruflo contract layer implemented. Updated `CLAUDE.md` so future sessions treat the contract layer as implemented, production-disabled.

### Validation state before the next implementation

The repository state has been statically checked from the current GitHub files. The manifest and task-contract definitions are internally consistent. The validators are dependency-free and are designed not to start agents, swarms, MCP, daemons, or publishing.

### Ready state

**Current Ruflo state: contract-ready, production-disabled.**

**Next implementation:** isolated non-production Ruflo execution of exactly one task, with captured output and comparison against the existing Night Files result. Do not connect that execution to `daily.yml`, publishing, TikTok auth, YouTube auth, or the production buffer yet.

The next implementation is considered ready only if it preserves these properties:
- no new production secret unless a verified runtime requirement is discovered;
- no production workflow dependency;
- no automatic publishing;
- no bypass of research, fact-lock, visual QA, duration QA, or packaging safeguards;
- clear artifact/output location for comparison;
- failure of Ruflo remains non-fatal to production.


## Buffer-first publishing update, 2026-10-02

Implemented the missing queue-first behavior for Night Files.

### What changed

1. Added `pipeline/buffer_status.py`
   - Reports the number of complete video/caption pairs currently waiting in the GitHub Release buffer.
   - Used by both the scheduled publisher and the separate buffer-fill workflow.

2. Changed `.github/workflows/daily.yml`
   - Checks the production buffer before generation.
   - If the buffer contains one or more complete videos, generation is skipped.
   - The existing publish step then consumes the oldest buffered video.
   - If the buffer is empty, exactly one new video is generated into the buffer and the same run publishes the next buffered item.
   - This prevents the scheduled daily job from creating an unnecessary new video while content is already queued.

3. Added `.github/workflows/buffer_fill.yml`
   - Separate producer workflow.
   - Scheduled every six hours and manually dispatchable.
   - Default target is two complete waiting videos.
   - Generates at most one new video per workflow run when the buffer is below the target.
   - Never calls `publish.py`, TikTok, or YouTube.
   - Uploads the generated video, caption, story, and supporting content artifacts to the workflow run.

4. Changed `pipeline/media_production_test.py`
   - Removed the old test-only `buffer.add` block.
   - Media tests now use the real production buffer.
   - HyperFrames and Premiere MCP are still exercised, but the finished video is queued for the scheduled publisher instead of being discarded or immediately posted.

### Resulting flow

```
Buffer fill / media test
        |
        v
    Generate video
        |
        v
   GitHub Release buffer
        |
        |  scheduled daily run
        v
 Check buffer first
        |
        v
 Publish oldest item
        |
        v
 Remove successfully posted item
```

This is intentional: repeated testing can accumulate finished content without spamming TikTok or YouTube. The scheduled daily workflow remains the distribution gate.

### Commit ledger

- `5c2988c72b19731af2e58392e831f5dcb98e5976` - Add buffer status helper.
- `b51909f67eed808f5f7d3a0588e63df92ba17d54` - Make daily publish from buffer first.
- `ec08385afd8d9fc48f46997828bf63bc5e391dc7` - Add scheduled buffer fill workflow.
- `e05438119208c1e5387cc8a6421768aed193d182` - Queue media test output in production buffer.

### Safety boundary

No TikTok or YouTube credentials were added. The buffer-fill and media-test workflows do not publish. The existing `publish.py` remains the only consumer responsible for platform posting and buffer removal.

## DESIGN.md implementation, 2026-10-02

Added the repository-level DESIGN.md using the DESIGN.md convention highlighted by VoltAgent/awesome-design-md. The upstream collection provides plain-text design-system files for AI agents, covering visual theme, color roles, typography, component styling, layout, depth, responsive behavior, and design guardrails.

### Night Files implementation

- Added DESIGN.md at the repository root.
- The file is a Night Files-specific system, not a copied third-party brand identity.
- Defines dark production-control-room surfaces, restrained electric-blue interaction states, semantic status colors, typography, spacing, radii, dashboard components, video review panels, buffer UI, integration cards, and responsive behavior.
- Explicitly documents the buffer-first UX: Generate -> Buffer -> Scheduled Publisher -> TikTok / YouTube.
- Requires external-media provenance/license metadata in review surfaces.
- Explicitly states that yt-dlp downloading a file does not make the media copyright-free.
- Prohibits occult/illuminati decorative imagery and gratuitous gore in the application chrome.
- Adds an agent prompt rule telling future coding agents to read DESIGN.md before editing UI.

### Documentation cleanup

- README.md now points future UI work to DESIGN.md as the visual source of truth.
- CLAUDE.md now records the DESIGN.md integration and the UI/provenance rules.

### Commits

- 958189a327e75811b4c3d8fdf47964cbddb2346d - Add Night Files UI design system (DESIGN.md).
- 881d923c140f60e01b36e4df71b3326ea777aa9b - Document Night Files design-system source in README.md.
- 5fb633aeb49d0407b9db085f554affd922d6c115 - Document DESIGN.md integration in CLAUDE.md.

### Upstream reference

- VoltAgent/awesome-design-md: https://github.com/voltagent/awesome-design-md

## Buffer-first documentation correction, 2026-10-02

Corrected stale production-flow descriptions that still implied the scheduled workflow always generated and immediately published a new video.

### Changes

- `.github/workflows/daily.yml`: workflow header now states that scheduled runs publish the next buffered video and generate only when the buffer is empty.
- `README.md`: replaced the old single-workflow immediate-publish diagram with the actual producer -> buffer -> scheduled publisher architecture.
- README now documents the separate `buffer_fill.yml` producer and media-test producer behavior.
- README now states that failed platform publishing leaves the buffered item available and successful publishing removes it through `publish.py`.

### Commits

- `02da4a09832966aa64019422f65ed0ac846873ab` - Correct daily workflow description.
- `62968c2176356adae7e7a88d025e56cd36880257` - Correct README production-flow documentation.


## YouTube backfill eligibility fix, 2026-10-03

The YouTube backfill workflow was tested against a separate GitHub Actions log and the run did not upload a video. That run was blocked before YouTube upload because data/tiktok_posted.txt was absent. The repository already had a stronger inventory signal in data/backfill.json: queued videos retain tiktok_publish_id values from the TikTok publishing step.

### Implementation

- Updated pipeline/yt_backfill.py so the text inventory remains preferred when data/tiktok_posted.txt exists.
- Added an explicit configuration gate, yt_backfill_trust_publish_ids.
- Enabled that gate in config.json.
- When the text inventory is absent and the gate is enabled, each queued backfill item with a recorded tiktok_publish_id becomes eligible for the YouTube backfill.
- The match source is recorded as backfill.json:tiktok_publish_id in memory/state so the log explains why the video was selected.
- Videos without a recorded TikTok publish ID remain ineligible.
- Existing YouTube duplicate checks, QA checks, one-upload-per-run behavior, daily quota limit, publish-slot guard, and successful-asset cleanup remain unchanged.
- No TikTok or YouTube credentials were changed.

### Why this is separate from the latest buffer-fill failure

The later 2026-10-03 buffer-fill run is a different workflow and failed during image generation because scenes 5-8 had no usable image after the configured redraw/gap-filler limits. It reached the final error with exit code 1 and left the production buffer at 0. That failure is not a YouTube backfill failure and is not being conflated with this fix.

### Commits

- 81e51f8a54378dec61040d6395151fd3cd020c29 - Allow YouTube backfill from recorded TikTok publish IDs.
- 58fffb8bf3b03023ab210c0b04a8ff084e18391f - Enable YouTube backfill from recorded TikTok IDs.

### Expected next backfill behavior

A scheduled or manually dispatched yt_backfill run no longer requires data/tiktok_posted.txt when the explicit trust flag is enabled. It will use the recorded TikTok publish IDs already stored in data/backfill.json, then proceed through the existing YouTube eligibility and QA gates. A successful upload will be logged with the YouTube URL and recorded in data/backfill.json; the corresponding stashed MP4 and metadata assets are removed only after the upload succeeds.


## Buffer-fill image fallback fix, 2026-10-03

Reviewed the separate buffer-fill run. This was not a YouTube backfill failure. The run exhausted Cloudflare and Hugging Face image sources, then used all 6 configured local SD-Turbo gap-fill images. Four scenes still had no image, so the image pipeline correctly stopped instead of borrowing another scene's image. The build exited before rendering and nothing was added to the production buffer.

### Implementation

- Increased `local_image_max` from 6 to 12 so a low-cloud-quota buffer build can repair more completely empty scenes with the local SD-Turbo fallback.
- Increased `local_image_budget_minutes` from 12 to 18 to make the larger local fallback allowance real rather than merely increasing the image count cap.
- Increased `.github/workflows/buffer_fill.yml` timeout from 90 to 120 minutes. This gives CPU image generation enough headroom without changing the buffer producer's role or publishing behavior.
- Kept the existing same-scene-only virtual-shot rule. The pipeline still refuses to stretch an image from another scene over a missing scene.
- Kept Cloudflare, Hugging Face, real-media, QA, and existing quota logic unchanged.
- The buffer-fill workflow still generates at most one video per run and never calls TikTok or YouTube publishing.

### Why the previous run failed

The run reported 0 Cloudflare images, 0 Hugging Face images, 6 local SD images, 1 real-media asset, 2 rejected images, 5 virtual/cached images, and 4 of 9 scenes with no image. The image quota stop was therefore expected behavior under the old 6-image local cap. The fix increases the recovery capacity for exactly this low-provider-quota condition.

### Commits

- 9820a172bd6878bcadd6a6c15991dd2f13edeb36 - Increase buffer image fallback capacity.
- 5f6f7d10f2e3d9b48f266faea84f3e2d53cd810b - Give buffer fill more image fallback time.


## Image provider broker implementation, 2026-10-03

The buffer-fill image failure is now addressed with a quota-aware provider broker instead of continuing to raise the CPU SD-Turbo cap. The implementation preserves the existing image QA, checkpoint, renderer, real-media, and buffer architecture.

### Tier order
- Tier 1: existing Cloudflare Workers AI FLUX.1 schnell.
- Tier 2: optional Pollinations FLUX, activated only by POLLINATIONS_API_KEY or POLLINATIONS_KEY. It is capped per run and is not treated as unlimited free capacity.
- Tier 3: existing Hugging Face ZeroGPU FLUX Spaces, now preceded by a live get_zero_gpu_quota() preflight when HF_TOKEN and a compatible huggingface_hub version are available.
- Tier 4: existing local SD-Turbo CPU emergency fallback, still capped at 12 images and 18 minutes.
- Tier 5: existing same-scene virtual/cached crop fallback. Cross-scene borrowing remains prohibited.
- Tier 6: existing real-media/asset-library path remains upstream of AI generation and continues to carry provenance/rights metadata.

### Implementation
- Added pipeline/image_provider_broker.py.
- pipeline/images.py installs the broker after the existing provider functions are defined. The broker occupies the existing HF provider slot so the renderer and downstream QA logic do not need a rewrite.
- Pollinations 401/402/403 disables that provider for the rest of the run. Temporary failures fall through to HF.
- HF quota below 65 seconds is skipped before another Space generation request. If quota lookup is unavailable, the existing scheduler-side HF error handling remains authoritative.
- config.json records the provider tier order, Pollinations model/size/cap, and HF minimum quota threshold.
- buffer_fill.yml and daily.yml pass the optional POLLINATIONS_API_KEY secret to generation. No new mandatory secret exists.
- Full implementation details and expected log lines are in docs/IMAGE_PROVIDER_BROKER.md.

### Verification boundary
This change was reviewed against current Cloudflare, Hugging Face, and Pollinations documentation before implementation. No live generation run was executed by the code edit itself. The next validation must be the buffer-fill workflow and should verify provider selection, quota preflight, image counts, and creation of a real final.mp4 before any publishing workflow is considered.

## Free-provider + automation architecture implementation, 2026-10-03

Implemented the next architecture layer after researching MoneyPrinterTurbo, Video Factory, Content Machine, the owner-supplied awesome-freellm-apis catalog, and current NVIDIA APIs.

### Provider architecture
- Added pipeline/provider_registry.py as the declarative modality/provider inventory.
- Added pipeline/providers/nvidia.py for NVIDIA FLUX.2-klein-4b image generation, Cosmos3-Nano image-to-video/text-to-video, and NVIDIA NIM chat fallback.
- Added pipeline/providers/modelscope.py for ModelScope Qwen-Image async generation and OpenAI-compatible text fallback.
- Added pipeline/providers/__init__.py.
- Added pipeline/video_provider_broker.py for non-blocking NVIDIA Cosmos motion generation.
- Added pipeline/provider_doctor.py to report optional credential configuration without making generation requests.

### Image broker
The existing image broker now uses: Cloudflare -> NVIDIA FLUX.2-klein-4b -> ModelScope Qwen-Image -> Pollinations -> Hugging Face ZeroGPU -> local SD-Turbo -> existing same-scene/cached visual fallbacks. Missing credentials simply disable optional tiers.

### Video broker
pipeline/ai_motion.py now tries NVIDIA Cosmos3-Nano image-to-video when NVIDIA_API_KEY is configured. A failure immediately returns to the existing PersonaLive/Hugging Face/3D path.

### Text broker
pipeline/story.py now optionally appends NVIDIA NIM and ModelScope models after the existing Gemini/Groq chain. Existing retry and quota behavior remains the controlling layer.

### Run artifact architecture
Added pipeline/artifacts.py and integrated a run_manifest.json into pipeline/main.py. Each production run records provider configuration, stage states, output artifacts, and final status. This borrows the inspectable/resumable artifact pattern from Content Machine and the staged/checkpointed pattern from Video Factory without adding another runtime framework.

### Configuration and workflows
config.json now records image/video tiers and optional NVIDIA/ModelScope models. buffer_fill.yml, daily.yml, and daily_media_test.yml receive optional NVIDIA_API_KEY and MODELSCOPE_TOKEN secrets. Existing secrets remain unchanged.

### Owner homework
Nothing needs to be coded manually. The only optional manual setup is creating provider credentials:
- NVIDIA API key: required to activate NVIDIA image/video/text tiers. NVIDIA's current free/preview endpoints may require account or phone verification.
- ModelScope token: required to activate ModelScope image/text tiers.
- Pollinations API key: optional if you want that tier active.
- Existing HF, Cloudflare, Gemini, and Groq secrets remain as before.

If you do not add any new keys, Night Files still runs with the existing providers. Adding NVIDIA and ModelScope keys simply gives the broker more fallback capacity.

### Validation boundary
All changed files were fetched back from GitHub after implementation. No live provider generation was triggered during this code-edit pass, so actual account quotas, endpoint availability, and generated media quality remain runtime checks. The next validation should be buffer_fill.yml, followed by inspection of output/<stamp>/run_manifest.json.

See docs/FREE_PROVIDER_ARCHITECTURE.md for the full architecture and manual setup list.


## GitHub Actions workflow-role separation, 2026-10-03

Added an explicit repository CI layer and documented the boundary between validation, TikTok OAuth, generation, and publishing workflows.

### Implementation

- Added `.github/workflows/ci.yml`.
- CI runs automatically on pushes to `main` and pull requests targeting `main`.
- CI validates Python syntax with `compileall`.
- CI validates `config.json` and pipeline JSON manifests.
- CI runs the existing Ruflo validators when they are present.
- CI verifies critical Night Files production files exist.
- CI has only `contents: read` permissions.
- CI does not exchange OAuth codes, write repository secrets, publish videos, or call TikTok/YouTube publishing APIs.

### Workflow boundaries

- `ci.yml` = repository health and code validation.
- `connect-tiktok.yml` = one-time TikTok OAuth connection and refresh-token storage.
- `buffer_fill.yml` = generate content into the buffer without publishing.
- `daily.yml` = scheduled distribution of buffered content.
- `yt_check.yml` = YouTube credential validation.
- `yt_backfill.yml` = separate historical TikTok-to-YouTube backfill path.

This prevents an authentication failure from being mistaken for CI, and prevents a generation failure from being mistaken for a publishing failure.

### Documentation

- Added `docs/GITHUB_WORKFLOW_ROLES.md` with the workflow-by-workflow responsibilities and debugging boundaries.
- Added the same distinction to `README.md`.

### Commits

- `7f3ed48509c0cf8835a1fa855c623aa7ab07878a` - Add repository CI validation workflow.
- `b458634c308cc86ec012cb2f1537dc1a57a24bf5` - Document GitHub Actions workflow roles.
- `2e26c802dab5591c6254de0101d5ac6e2edf1ff3` - Document workflow roles in README.

### Validation boundary

The CI workflow itself was added but not executed by this edit operation. The first push to `main` should trigger it automatically. The workflow is intentionally non-publishing and cannot alter TikTok or YouTube credentials.


## Copyrighted music claim fix, 2026-10-03

> **CORRECTION, 2026-10-05 (Claude Code, owner-confirmed):** the claimed recording ("Everything In Its Right Place" by
> Radiohead) was `assets/music/everything_in_its_right_place.mp3`, which had already been removed on Oct 1 (18c9268);
> the claimed video was rendered before that. `unsolved_mystery.mp3` is the owner's own track and was deleted here by
> mistake. Restored Oct 5 together with the owner's `bk_grnde.mp3`; both rotate with the procedural ambient bed
> (`music_policy=approved_files`, `approved_music`, `music_rotation`). Radiohead and "Tonight You Belong To Me" stay
> deleted. The "Immediate fix" below is history, not the current state.

The YouTube screenshots supplied by the owner show a published Night Files video blocked globally because YouTube Content ID identified **“Everything In Its Right Place” by Radiohead**, with **Beggars Group Digital** listed as claimant. The claim is on the audio track and YouTube states the claimed content exceeds the copyright holder's length limits.

Repository inspection identified the previous Night Files music configuration pointing at `assets/music/unsolved_mystery.mp3`. The render selected a random file from `assets/music`, so that repository recording could enter every generated video.

### Immediate fix

- Removed `assets/music/unsolved_mystery.mp3`.
- Changed the default music policy to `procedural_only`.
- Removed the configured third-party track volume entry.
- Added a locally generated ambient music bed created by FFmpeg from synthesized tones/noise.
- The renderer now records `story["music_source"]` as `procedural_original` when using the safe fallback.
- Explicit third-party music can only be used if the configuration is deliberately changed to `approved_files` and the filename is listed in `approved_music`.
- Added `pipeline/music_rights_check.py`.
- Added the music-rights validator to `ci.yml`, so an accidental music file cannot silently re-enter the repository under the default policy.

### New safety boundary

Night Files no longer treats “a file exists in assets/music” as permission to use it.

Default behavior:

```text
music_policy = procedural_only
assets/music = empty
render -> original FFmpeg ambient bed
```

An approved recording requires an explicit configuration entry and an intentional policy change.

This prevents the exact failure shown in the YouTube claim screenshots from recurring through the old random-file selection path.

### Existing published video

The already-published video remains a separate platform-side issue. The screenshots show YouTube offering **Erase song** and **Dispute**. The repository fix prevents future builds from using the removed recording; it does not change an already-uploaded video's copyright state.

### Commits

- `dc97004cea9ee1a674955b08d5753a6a72490f0d` - prevent unapproved music and add original ambient fallback.
- `a4b9bbe68072cd093621982a5f897385e393fd35` - make music policy procedural-only by default.
- `c89e26b7d1b36c342ee148c60cc6ffa1b3e32825` - remove unapproved music recording.
- `b884835ba00a98e4b27c631c528fbc0d03eb7f3d` - add automated music provenance guard.
- `c7aa3343a731ee92d606d39a9111fb41db371a91` - enforce music provenance in CI.


## Story queue expansion, 2026-10-03

Added the requested Night Files story concepts to the production subgenre pool with dedicated prompt files.

### Added concepts

1. **The story of Queen Esther** - biblical/historical mystery. The prompt keeps the major events grounded in the Book of Esther and requires the script to distinguish biblical text from dramatic reconstruction.
2. **A book with a chilling mystery** - an original book that begins describing the reader's life.
3. **The stranger who knew me** - an original grounded psychological horror about a stranger who knows private details.
4. **The photograph with one extra person** - an old family photograph contains someone nobody remembers.
5. **The house that added a room** - an impossible new room appears inside a home.
6. **The voicemail from tomorrow** - a person's own phone number leaves a message about an event that has not happened.
7. **The last person in the library** - books continue being checked out after closing.
8. **The diary that wasn't mine** - a decades-old diary accurately describes the narrator's current life.
9. **The dream that remembered me** - a recurring dream changes in response to waking-life events.

### Implementation

Each concept has its own `prompts/fiction_*.txt` instruction file and is mapped explicitly through `config.json -> subgenre_prompts`.

The normal subgenre rotation already chooses the least-recently/least-often used subgenre, so these concepts enter the existing story pipeline rather than bypassing it.

### Content boundary

The Esther prompt is intentionally different from the fictional horror prompts. It is framed as a biblical/historical retelling and instructs the writer not to invent supernatural events, conspiracies, or unsupported historical facts and present them as scripture/history.

The other eight concepts are explicitly original fiction and retain the existing Night Files safety rules.

### Prompt files

- `prompts/fiction_esther.txt`
- `prompts/fiction_chilling_book.txt`
- `prompts/fiction_stranger.txt`
- `prompts/fiction_extra_photo.txt`
- `prompts/fiction_new_room.txt`
- `prompts/fiction_tomorrow_voicemail.txt`
- `prompts/fiction_last_library_person.txt`
- `prompts/fiction_diary_not_mine.txt`
- `prompts/fiction_dream_remembers.txt`

### Commit

- `81da9382df8cb4675e5fd559b91881b4d4a902c2` - add all nine concepts to the Night Files story pool and map them to dedicated prompts.


## Production readiness + hard media/provenance gate, 2026-10-03

Implemented the production-safety pattern from the reviewed youtube-automation-agent architecture without importing its Node/SQLite stack.

- Added `pipeline/production_readiness.py`. It is an offline preflight only: checks ffmpeg/ffprobe, required Python modules, target duration config, music policy, and reports missing runtime credentials as warnings. It never calls a provider and never spends quota.
- Added `pipeline/production_gate.py`. This is the hard buffer boundary. It rejects missing/zero-byte/suspiciously small/oversized MP4s, wrong duration, missing video/audio streams, wrong 1080x1920 output, and files that fail full FFmpeg video/audio decode.
- The same gate checks external media provenance. Any real/archive asset must carry a source/provider, HTTP(S) source URL, and license/rights field. The current procedural-only music policy is explicitly accepted; an approved-file policy requires an allowlist.
- `pipeline/main.py` now writes provenance into `caption.json`, runs the hard gate after render/packaging, writes `production_gate.json`, and only then calls `buffer.add()`. A failed gate cannot enter the durable FIFO buffer.
- `pipeline/publish.py` re-runs the final-media and buffer-provenance checks after downloading the buffered MP4 and before TikTok/YouTube posting. This protects the second boundary as well.
- `.github/workflows/daily.yml` and `.github/workflows/buffer_fill.yml` run the offline readiness preflight before generation. Buffer-fill artifacts now fail if the expected generated files are absent.
- No new secrets are required.

This specifically addresses the recent failure mode where a buffer-fill run could finish without a real `final.mp4` while artifact handling did not make that absence fatal. It also addresses the YouTube music-claim incident by making soundtrack policy and external-media evidence part of the production contract.

Commits:
- `f2d444d8ea9930bf49bdbd270b5937a633e5eb46` - add hard final media/provenance gate
- `6c16328c399a823f926b271c6fefafb5acbced4b` - carry provenance evidence into buffer metadata
- `a519b785e70e3c50b673441b82664ac11ae530d2` - add offline readiness preflight
- `03fa79ffecf24a762440897e56611d7c9a0f87b6` - keep readiness credential-safe
- `1b62bb9bc761c55498d51fd4ca0bf04547f858a2` - block invalid media before buffer admission
- `773d9aa375a0b7943a911bd1e3a7b72d6e40252` - revalidate buffered media before publishing
- `8ddb5affa1ab94dac2c4921881f0f3ba0fddc01e` - run readiness in daily generation lane
- `16046423c9b3b1e138fab6d6c6424d81c57c32fb` - run readiness in buffer-fill lane and require generated artifacts


### Production-gate artifact follow-up

- `d59253da10c7b209fc2c7ffcc021bb431c9aa197` - clarify main module's hard-gate behavior.
- `a742b645efb765655a0c3d14aa323f3fd3912bde` - publish `production_gate.json` with daily workflow artifacts.
- `36ad3c23b0cb63de3f64563ff95286c3f167efc5` - publish `production_gate.json` with buffer-fill artifacts.

The gate evidence is now downloadable from the same Actions run that produced the video.


- `cfd3a6aba6fbb3ce6fcc1d992e68569e260e361c` - clarify that readiness credential checks are warnings, not false claims of verified secrets.

## Persistent checkpoint/resume fix, 2026-10-03

The recent buffer-fill logs exposed a real gap in the checkpoint implementation. pipeline/checkpoint.py already had the correct idea: keep the story, narration, and finished images after a failed build. The problem was workflow persistence, not the checkpoint data model.

The failed image run explicitly reported that the story was kept and that the next build should continue it, but the buffer-fill workflow did not restore or save cache/checkpoint. The daily workflow restored a checkpoint but did not save the checkpoint cache after the run. That meant a failed run could not reliably hand its unfinished story to the next scheduled producer.

### What changed

- .github/workflows/buffer_fill.yml restores the newest ckpt-* cache before generation.
- .github/workflows/buffer_fill.yml detects cache/checkpoint/story.json without done.json.
- Unfinished checkpoints take priority over starting a new story.
- buffer_fill.yml saves cache/checkpoint after every run, including failures.
- buffer_fill.yml now uses the same night-files concurrency group as daily.yml.
- daily.yml detects an unfinished checkpoint after restoring it.
- daily.yml now generates when the buffer is empty OR a checkpoint is pending.
- daily.yml saves cache/checkpoint after every run, including failures.
- pipeline/checkpoint.py required no runtime change because resume(), save_story(), save_narration(), and finish() already implement the intended state machine.

### Resulting behavior

Run A starts Story X -> story.json saved -> narration saved -> images saved as they finish -> image/provider/render failure -> run fails -> checkpoint cache is saved.

Run B (daily or buffer-fill) -> checkpoint cache restored -> unfinished Story X detected -> Story X resumes -> no new Story Y is started -> completed narration/images are reused -> only missing work is attempted.

If Run B fails again, the checkpoint is saved again. If Run B succeeds, buffer.add() completes the durable queue entry and checkpoint.finish() clears the heavy checkpoint state and writes done.json.

This is specifically designed for the current image-quota failure mode. The recent run stopped at ImageQuotaWait and explicitly logged that the story is kept and the next build continues it. fileciteturn544file0L5-L8

### Commits

- 6c254577529d22d5e763093eda26aa9fe0c76c7a - persist and resume checkpoints in buffer-fill.
- c2f7ec3d481903b5a6e0f8b30b15dbffe5277f73 - let daily runs resume unfinished checkpoints.

### Important limitation

GitHub Actions cache is the persistence layer. A checkpoint is not a permanent artifact in the repository and is subject to GitHub Actions cache retention/eviction. As long as the checkpoint cache is available, the workflows restore it by the ckpt- prefix. A completed story is protected by done.json and by history duplicate checks.

### Validation status

The workflow files were updated directly and re-read from GitHub after the changes. The actual scheduled recovery path has not yet been executed on a failed production run, so the next real buffer-fill or daily run is the live validation.

## Separate background music + artifact completion boundary, 2026-10-03

The owner requested that the recent video remain usable because the visual/story result is strong, while removing only the copyrighted soundtrack that caused the YouTube claim. Background music is therefore restored as a normal production layer, but it is no longer fused into the core visual render.

### Music behavior

- The core render now produces the finished visual + narration/SFX video first.
- `pipeline/background_music.py` adds the background soundtrack as a separate post-render FFmpeg pass.
- Default soundtrack remains `procedural_original`: an ambient bed synthesized locally by FFmpeg, so no third-party recording is introduced.
- The existing `approved_files` policy remains available for deliberately approved local tracks. A track is never treated as safe merely because it exists in `assets/music`.
- The separate stage records `music_source`, `music_file`, and `music_stage=separate_post_render` in the story/manifest.
- The final production gate still runs after the music stage, so the actual shipped MP4 is the file being validated.

This means the next production run will have background music again without bringing back the copyrighted Radiohead recording.

### Checkpoint completion

A checkpoint is still kept when generation fails before a complete final video is preserved.

After the workflow successfully uploads a complete `final.mp4` artifact, the workflow now marks that checkpoint complete and writes `done.json`. This follows the owner's requested boundary: once the complete finished video is preserved as a workflow artifact, the unfinished story should not be regenerated on the next run.

Buffer admission still calls `checkpoint.finish()` normally. The artifact-completion path is a second completion boundary for cases where the MP4 was fully preserved but a later queue/publishing step failed.

GitHub distinguishes artifacts from caches: artifacts are for preserving workflow outputs, while caches are for reusable intermediate data. citeturn0search0turn0search1

### Important behavior

- Image/story failure before final MP4: checkpoint remains.
- Render/music/gate failure before final MP4: checkpoint remains.
- Valid final MP4 uploaded as workflow artifact: checkpoint is marked complete.
- Valid final MP4 admitted to the durable buffer: checkpoint is already completed by `main.py`.
- A completed story is never resumed just because an older cache entry still exists; `done.json` blocks resume.


## Separate background music + artifact completion boundary, 2026-10-03

The owner requested that the recent video remain usable because the visual/story result is strong, while removing only the copyrighted soundtrack. Background music is therefore restored as a normal production layer, but it is no longer fused into the core visual render.

### Music behavior

- The core render now produces the finished visual + narration/SFX video first.
- `pipeline/background_music.py` adds the background soundtrack as a separate post-render FFmpeg pass.
- Default soundtrack remains `procedural_original`: an ambient bed synthesized locally by FFmpeg, so no third-party recording is introduced.
- The existing `approved_files` policy remains available for deliberately approved local tracks. A track is never treated as safe merely because it exists in `assets/music`.
- The separate stage records `music_source`, `music_file`, and `music_stage=separate_post_render`.
- The production gate runs after the music stage, so the actual shipped MP4 is the file being validated.

This means the next production run will have background music again without bringing back the copyrighted recording.

### Checkpoint completion

A checkpoint is still kept when generation fails before a complete final video is preserved.

After the workflow successfully uploads a complete `final.mp4` artifact, the workflow now marks that checkpoint complete and writes `done.json`. Buffer admission still calls `checkpoint.finish()` normally.

This follows the requested boundary: once the complete finished video is preserved as a workflow artifact, the unfinished story should not be regenerated on the next run.

GitHub distinguishes artifacts from caches: artifacts preserve workflow outputs, while caches are intended for reusable intermediate data. citeturn0search0turn0search1

## Bloody Mary analytics cluster, 2026-10-03

YouTube Studio analytics now show a clear content signal around **Bloody Mary**:

- **Bloody Mary Mirror Legend #Shorts** is the channel's top Short in the supplied 28-day screenshots at **321 views**.
- Realtime also shows the Bloody Mary video continuing to receive views.
- Search terms include **bloody mary**, **bloody mary horror**, **bloody mary mirror**, **bloody mary ritual**, **bloody mary shorts**, **bloody mary story**, **what is the story of bloody mary**, and **what does bloody mary look like**.
- The search-term spread is broader than one exact title, which supports building a small Bloody Mary topic cluster instead of repeatedly making the same mirror video.

### Strategy change

Night Files now treats Bloody Mary as an analytics-priority cluster while preserving the existing duplicate/history protection. The goal is **more Bloody Mary, not eight copies of the same video**.

The cluster contains eight dedicated prompt types:

1. Fresh Bloody Mary folklore variant
2. One dark fun fact about the folklore/history
3. Where the Bloody Mary name came from
4. A lesser-known folklore variation
5. Why the mirror is central to the legend
6. An original fictional spin-off inspired by the legend
7. A fictional bathroom-rumor spin-off
8. A fictional aftermath spin-off

### Rotation behavior

config.json now contains:

- priority_subgenres: the eight Bloody Mary concepts.
- priority_subgenre_probability: 0.40.
- priority_subgenre_recent_window: 3.

On each normal story selection, there is a 40% opportunity to select a Bloody Mary concept. A priority concept that appeared inside the last three selected stories is blocked from immediate priority selection. If the priority lane is not selected or has no eligible candidate, the existing least-recently/least-often-used rotation remains in control.

This preserves the existing story-history system while deliberately responding to the strongest search signal currently visible in YouTube Studio.

### Content rules

The factual/folklore prompts explicitly distinguish legend from verified history. In particular, the origin prompt does not allow the popular association between Bloody Mary and a specific historical person to be presented as settled fact.

The fictional spin-offs are clearly original fiction and are instructed not to copy the standard mirror ritual story. The mirror explainer does not provide ritual instructions.

The existing Night Files safety rules remain in force: adult characters, no gore, sexual content, self-harm, suicide, harm to children, real people, real brands, or named towns.

### Implementation

Added:

- prompts/fiction_bloody_mary_legend.txt
- prompts/fiction_bloody_mary_fun_fact.txt
- prompts/fiction_bloody_mary_origins.txt
- prompts/fiction_bloody_mary_variations.txt
- prompts/fiction_bloody_mary_mirror.txt
- prompts/fiction_bloody_mary_spin_off.txt
- prompts/fiction_bloody_mary_school.txt
- prompts/fiction_bloody_mary_after.txt

Modified:

- config.json to map and prioritize the cluster.
- pipeline/story.py so the priority lane is analytics-driven but respects a three-story recent-repeat block and falls back to the original rotation.

### Commits

- f2549fe913423734a2ff72c351ee2aaefa162f6c - add fresh Bloody Mary folklore prompt.
- e1acfeb049f29bda6bae31df16fbcfe9c7a71dac - add Bloody Mary fun-fact prompt.
- f82208851ae483fb92a20f5d35c06debb448007d - add Bloody Mary origins prompt.
- c6346c7b99e9a9e5bd6d4186a80170a29c0f5d1f - add Bloody Mary variation prompt.
- 5ea0fd07f7cd4e8b16852643dd7ef1900c0256b9 - add mirror-focused prompt.
- 145853380f237781e508ab4a68f850c148fcd705 - add original fiction spin-off prompt.
- 3716e4046f8504be9ca65c242def960350ba44f2 - add fictional bathroom-rumor spin-off.
- 1ea0d41bf143d22781eceaface6d3ae483fb7a50 - add fictional aftermath spin-off.
- 30fd4103f342ffcb7c97f45388e27ca5eab8ba74 - map the cluster and add analytics priority settings.
- faddb433bbf8708384e440d56fe1a143711033c3 - implement priority topic selection with repeat protection.

### Validation boundary

The change is configuration/prompt/selection logic only. It does not alter rendering, music, buffer, publishing, or YouTube authentication. The next normal generation run is the live validation that the selected Bloody Mary prompt produces a distinct script and still passes the existing story critic, visual QA, production gate, and buffer flow.
