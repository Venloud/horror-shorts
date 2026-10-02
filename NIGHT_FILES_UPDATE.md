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

### 3. MuMuAINovel

Use its narrative-planning concepts first rather than copying its GPL-3.0 application code into Night Files. The current Night Files writer remains the production writer. The next integration can add a structured story outline / scene-plan stage inspired by its consistency, timeline, character, and quality-scoring features.

### 4. Auto Clip MVP

Add this after the main render is stable. It should consume the finished Night Files MP4 and create alternate short clips/hooks without changing the primary post.

### 5. Ruflo

Use Ruflo last as the orchestration layer once the individual stages are stable. It should coordinate existing Night Files stages rather than replace the proven generator/publisher immediately.

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
