# Walter Murch's Rule of Six: Night Files editorial priorities

Status: active creative instructions for shot planning and graphics prompts; numeric weights are a conceptual hierarchy, NOT a deterministic grade or automatic publishing threshold. Owner requested 2026-10-24. This applies to **every** Night Files story, not just Aka Manto.

Source: Walter Murch, *In the Blink of an Eye*, "The Rule of Six"; available transcription at https://blogs.ischool.berkeley.edu/i290-viznarr-s12/the-rule-of-six-walter-murch/ and explanatory discussion at https://www.studiobinder.com/blog/walter-murch-rule-of-six/ .

## Six priorities, in order

1. **Emotion (51%)**: What's the audience supposed to feel *right now*? Preserve dread, curiosity, shock, relief or other story-appropriate feeling. A quieter shot or silence can be more emotional than an effect. Avoid making a frightening moment feel like a flashy advertisement.
2. **Story (23%)**: What new information, choice, action, consequence or change does the cut reveal? If an image, graphic, zoom or reaction adds neither emotion nor understanding, don't add it just to fill time.
3. **Rhythm (10%)**: Cut on the beat of the *meaning*, voice, musical phrasing or natural movement. Let a reveal breathe, accelerate only where the story accelerates. Do not repeat swoosh entrances or switch shots only because a timer elapsed.
4. **Eye trace (7%)**: Where was the viewer looking before the cut, and where should they look afterward? Use eye lines, leading lines, framing, caption positioning and composition to guide attention without an unnecessary search or jump across the vertical screen.
5. **Two-dimensional plane (5%)**: Compose consistent readable screen direction and shapes on the 9:16 frame. Respect gaze room, screen-side continuity, overlaid graphic/caption safe areas and 180-degree-like relationships where relevant. Rule of thirds, circular/radial shapes, leading lines, frame within frame and diagonals are available tools, not mandatory decorations.
6. **Three-dimensional space (4%)**: Respect where subjects, camera, objects and doors are in the represented place, and how they move through it. Re-establish geography with an appropriate shot when confusion would derail understanding. Spatial discontinuity may sometimes be sacrificed to preserve the stronger emotion and story, but don't accidentally teleport subjects or contradict the narration.

The weights are Murch's deliberately illustrative values, **not statistical measurements or literal factors for an AI quality score**. Favor higher-priority criteria when they conflict. Always strive to satisfy all six when possible. This priority order never overrides hard safeguards: factual integrity, safety, image rights and technical delivery.

## Reusable edit decision procedure

For each potential cut, graphic or camera move:
1. Identify the current emotional intention in one short phrase, and the next narrative fact or action.
2. Ask **whether any cut is needed**. A hold on an expressive frame may outperform another graphic.
3. Choose the next visual that best conveys emotion and advances the story. Determine the natural speaking/pacing beat.
4. Check the viewer's gaze position. Place the new subject and text where their attention can follow, leaving 9:16 caption and interface margins clear.
5. Choose a clean camera perspective, cut, dissolve, graphic pop, or hold to fit the scene. Preserve readable direction/space when useful.
6. Add **only meaningful** emphasis, movement or SFX. Prefer the complete semantic phrase ("CHOOSE RED", "COVERED IN BLOOD") over unrelated keywords ("CHOOSE COVERED"), and no arbitrary underlines.
7. Review adjacent shots together, not as isolated cards. Look for repeated swooshes, visual clutter, incoherent geography and lost emotional progression.

## Examples, not story-specific templates

- A choice or consequence: use a grounded decision composition, optionally the approved viewer-surrogate character where a matching *approved* pose exists, then cut to the consequence. Avoid covering the options with giant typographic filler.
- A message arriving: phone UI animation of only the sourced/story-stated text and one matching notification cue, without blocking the next spoken line.
- A confession or alarming new piece of evidence: perhaps a clean hold or slow push-in, a legible document close-up or short silence. A chaotic transition would weaken the intended feeling.
- A change of location: maintain eyeline/route continuity with a grounded establishing visual when confusion would harm clarity.
- Folklore suspense: remain in story world and label uncertain claims as legend; emotional impact doesn't license fabricated evidence.

## Relationship to the owner's other rules

- **Always-on kinetic captions:** serve the emotion and meaning; synchronize speech, never obscure story evidence.
- **Subtle moving pictures:** motion must serve emotional intention, not loop as visual wallpaper.
- **Restrained explanatory graphics:** prioritize a story image when it communicates better; create graphics only if they add meaning, evidence, a grounded choice or a useful focal point.
- **BGM and SFX:** emotion determines atmosphere, narration determines event timing; no needless whoosh loops.
- **Five composition techniques:** tools for eye trace, 2D framing and emotion, secondary to what the scene needs.
- **Mid-conversation storytelling:** begin inside the idea, explain with concrete events and hand the thought to the viewer naturally.

## Implementation scope and verification

Wired into the active `prompts/scene_plan.txt` for initial shot/image descriptions and the `GRAPHICS_PROMPT` in `pipeline/explainer.py` for model-picked story graphics. It guides AI planning **but does not automatically measure emotions, choose live cut points or certify final MP4 quality**. Existing deterministic rendering and safety guards remain. Follow-up engineering may introduce per-beat edit plans, transition-selection logic and visual QA with actual rendered videos. Tests must be offline and may not publish or mutate buffer/history.

**Creative review checklist:** Can you identify emotion and story advancement at each major cut? Is the graphic there for a reason? Does timing allow the critical sentence to land? Does the eye find the intended next subject? Do the composition and location stay understandable? Did you sacrifice meaningful storytelling just to preserve a fancy transition? If so, simplify it.
