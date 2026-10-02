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
