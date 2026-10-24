# Night Files editing quality checklist, owner approved 2026-10-24

These are permanent creative acceptance guidelines, not four effects that must all be maxed on every shot.

## 1. Captions, always
- Every spoken word should be captioned and in sync with narration. Use engaging, polished animated text with readable contrast and safe placement.
- Vary emphasis, phrase grouping and entry motion when meaningful; avoid frantic animation for every word. Missing captions are a repair issue.
- Inspect both the classic ASS engine and the explainer/Remotion engine. A polish failure must retain captions.

## 2. Still-picture motion
- Gentle purposeful zoom-in, zoom-out, pan or parallax to create a cinematic feel from still images.
- Match movement direction and speed to story tension; use restraint, avoid mechanical repeat zooms, unnecessary shake and aggressive cropping.
- Respect face, subject and text safe areas; never fake 4K image detail or imply that upscaling proves historical accuracy.

## 3. Graphics
- Treat each shot like a blank canvas; a graphic is a deliberate finishing touch, not obligatory clutter.
- Use typography, key dates, map cues, evidence or a reveal only when they clarify an actual story beat.
- Keep graphic text fully visible, legible and grounded in narrated facts; reduce frequency when imagery alone is stronger.

## 4. Background music and SFX
- Music supports tone beneath speech, with ducking and fades. No overpowering tracks.
- Use matching sound effects only for audible/meaningful scene events, e.g., rain ambience while describing pouring rain, if the proper licensed asset exists.
- Prefer silence when no matching sound exists. Limit overlapping stingers, repeated whooshes and irrelevant sound effects.

## Production and review contract
- Preserve existing caption, Ken Burns/parallax, explanatory-graphic, narration, rights-aware soundtrack and SFX systems. Improve rather than creating duplicate renderers.
- Render QA should identify missing captions, unreadable text, repeated motion, excess graphics and sound mismatch; do not declare semantic quality validated solely from technical unit tests.
- No test may create production buffer entries, publish, or alter posting history.
- Keep permanent CI, buffer-fill, daily delivery, social connection and other owner-approved workflows. Remove only verified disposable test-only workflows after their run, never CI.

## General-purpose contextual graphic and sound direction
The bot is an editor for **any** story, not an Aka Manto template. First identify the narrated event, then decide whether an on-screen effect improves comprehension. Examples of a reusable event-to-presentation vocabulary:
- **Incoming text / phone alert:** show a convincing phone/screen insert, reveal only the message actually stated in the narration or provided source, animate its appearance, optionally add one subtle vibration/notification sound if a licensed matching SFX exists. Do not fabricate messages or private details.
- **Phone ringing / call:** show caller interface or incoming-call visual; sync a brief ring or buzz to the line, avoid ringing over speech or inventing caller identity.
- **Weather:** show rain, wind, lightning, fog only when the story establishes it; sync restrained rain/wind/thunder ambience if available.
- **Discovery / evidence:** use a clean, legible reveal, close-up, highlight, photo-scan or document insert only when the object or finding is supported. Never generate illegible fake evidence text.
- **Travel / location change:** use a map move, line or location transition only with grounded locations, never invent routes.
- **Time shift / flashback:** use a restrained date, clock, lighting or transition cue to mark temporal change when necessary, not every scene.
- **Choice, warning, interruption:** use split emphasis, short graphic beat, or intentional silence only when narratively motivated.
- **Motion:** use thirds, circular/radial, leading lines, framing-within-frame, or diagonal composition when useful; never force all methods into one scene.

Choose from existing supported graphic templates/SFX and do not claim nonexistent effect implementations. When the exact asset or template is absent, use a clean existing alternative or no effect, never hallucinate a media capability. Text on screen must be sourced or verbatim from narration, legible, and separate from base image generation. Respect caption safe zones, audio ducking, and cooldowns to avoid overediting.


## Aka Manto preview lessons, generalized to every story (2026-10-24)

The actual Aka Manto preview, `explainer_polished(1).mp4`, and its generated scene JSON were reviewed with the owner. Positive: dark atmospheric artwork, increasingly cinematic treatment, bold mobile typography, and usable narration. Observed problems (not yet fixed in renderer code):

1. **Meaning before motion:** the impact card rendered “CHOOSE COVERED” and separately captioned “in blood.” This is grammatically and narratively incoherent. Emphasize complete semantic units, e.g. “CHOOSE RED” followed by “COVERED IN BLOOD,” with the key consequence emphasized. Never arbitrarily concatenate nonadjacent fragments of sentences, nor underline “mysterious,” “wearing,” or filler verbs merely because they appear near a cue.
2. **Emphasis intelligence:** choose the strongest noun, choice, threat, evidence, contrast or payoff **within its complete phrase**. Accents/underlines should mean something; don't underline every graphic. Ordinary spoken captions remain complete and synchronized.
3. **Transition grammar:** repeated swooshes are monotonous. Prefer restrained hard cuts and holds; assign dissolves to mood/time, slides to actual progression, pops to notifications or labels, and swooshes to rare intentional graphic beats. As a review heuristic, no one accent transition should dominate the video; do not enforce an arbitrary fixed percentage without perceptual review.
4. **Contextual viewer surrogate:** for a direct binary choice, a decision composition can use approved host/character art with two visual options (e.g. hands open, one holding red and the other blue), only when a matching authorized pose exists. Never silently invent or replace owner-approved assets. Missing required pose -> propose asset for approval, then use a non-character decision graphic fallback. Apply this reusable visual grammar to doors, phone calls, conflicting testimony, travel routes, etc., not just this legend.
5. **One beat, one visual focal point:** do not stack huge title, subtitle, multiple underlines, motion, and a busy graphic in the same moment. Subject/image selection must explain the line, not merely resemble its mood.
6. **Shot and sound meaning:** allow deliberate stillness, purposeful camera motions and matching ambience rather than a constant Ken Burns move, generic whoosh or arbitrary sound cue.
7. **Consistency and grounding:** the same figure, prop, location and time should remain consistent. Ensure graphic claims use narrated facts or appropriately marked folklore, not invented messages or evidence.

### Offline acceptance tests to implement
- Impact-card semantic extraction must avoid “CHOOSE COVERED” and favor coherent full phrases; test red/blue, “open the door or don't,” dates, locations, and unrelated stories.
- Annotated emphasis spans must be inside the selected coherent phrase, favor its actual payoff and avoid function words.
- Transition planner tracks recently used effects and selects a context-appropriate alternative, with no string of identical swoosh entrances.
- If a decision cue exists and approved character/pose metadata allows, plan a viewer-surrogate composition, otherwise fall back gracefully without unauthorized art.
- Verify readability and caption safe area in 1080×1920 and inspect real frames, not only mocked frame plans.
- Verify optional SFX are event-matched, mixed beneath voice, and silence is allowed.
- No publishing, buffer mutation, history write or new parallel rendering engine during tests.

### Hugging Face Diffusers, optional research track, NOT installed or production-enabled
Project: https://github.com/huggingface/diffusers, Apache-2.0 library. Docs: https://huggingface.co/docs/diffusers/using-diffusers/text-img2vid
Potential uses: short image-to-video inserts from existing licensed/approved plates, controlled image generation, and local experiments comparing temporal consistency with current FFmpeg Ken Burns/parallax and other existing motion providers. Not a compositor, captioner or editor brain. Modern video pipelines can require significant GPU VRAM and runtime, not guaranteed free on GitHub Actions CPU. Check every chosen model's separate license, hardware usage, provenance, quality, caching, and cost. Run isolated GPU benchmarks and review output before opt-in; preserve the original still-image route as the default with no background installation or added CI GPU requirement.

## Walter Murch's Rule of Six: final editorial hierarchy

[Detailed and sourced Night Files implementation](WALTER_MURCH_RULE_OF_SIX.md).

At each major cut or graphic decision, rank: **Emotion (51%) > Story (23%) > Rhythm (10%) > Eye trace (7%) > 2D screen composition (5%) > 3D spatial continuity (4%)**. These values are Murch's illustrative priorities, not an objective formula or publishing score. Preserve story truth, safety and rights regardless of aesthetics. The rule explicitly ranks *feeling and meaning* above technical flourishes: a simple hold or hard cut beats a swoosh if it makes the moment land.

Practical audit questions: What should the viewer feel now? What changes in the story? Why cut at this exact moment? Where does their eye go next? Are captions/graphics legible and shot direction coherent? Does the place still make sense? Keep existing caption coverage, subtle camera motion, selective useful graphics and scene-matched sound. Never add a graphic to satisfy a quota or force one of the five composition patterns into every shot.
