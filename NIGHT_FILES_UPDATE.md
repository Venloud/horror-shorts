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

Recommended order:

1. Keep the current generation and posting path working.
2. Prototype Remotion separately against one existing 61-68 second video.
3. Evaluate whether Remotion improves composition/caption control enough to replace parts of FFmpeg.
4. Only then consider a persistent character layer with PersonaLive.
5. Use MuMuAINovel ideas at the story-planning layer, not as a hard dependency.
6. Add automatic clip extraction only after the main video reliably posts.
7. Consider Ruflo last, when there are enough independent agents/tasks to justify orchestration.

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

