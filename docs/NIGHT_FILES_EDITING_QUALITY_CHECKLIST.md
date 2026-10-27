# Night Files editing quality checklist, owner approved 2026-10-24

These are permanent creative acceptance guidelines, not four effects that must all be maxed on every shot.

## Transition punctuation, owner directive 2026-10-25
- **Hard cut by default.** A cut or a hold needs no transition effect. Never insert a transition between every clip for decoration.
- **Dissolve only when time actually passes**, supported by narration or explicit timeline evidence. Mood, fog, a scene boundary, moving to a new place, or an unrelated graphic do not independently justify a dissolve.
- **Fade to black only at the actual ending**, and only if an ending fade strengthens closure. Never use fade-to-black between ordinary shots or scenes.
- Changes of place, action or idea may justify a new shot but normally still use a plain cut. Do not automatically add swoosh, slide, pop, wipe, flash, zoom transition or branded sweep.
- Treat animation *inside* a relevant graphic (a phone alert or factual map movement) separately from the transition *between* clips. Keep useful local animation without adding a decorative shot boundary.
- Reviewer gate: for every non-cut transition, state what changed, where narration establishes it, and what meaning the effect conveys. If that cannot be answered, replace it with a cut. An ordinary style preset cannot override this.

## Nonlinear easing, entry/exit and subtle interface overshoot, owner directive 2026-10-25

**Motion language:** Use natural, intentional motion rather than default linear-looking moves. Applies to explanatory graphics, UI inserts, pop-ups, evidence cards, kinetic text, captions, character/object micro-animations, camera/in-shot motion and transitions **only when that transition already has a narrative reason**.

- **Entry, ease-out when it feels right:** an entering title, UI alert, character/graphic or text phrase moves into its final position with noticeable early motion, then decelerates smoothly to rest. Avoid abrupt stops.
- **Exit, ease-in when it feels right:** an element leaving intentionally starts gently and accelerates out. Do not force every element to exit; a hold, immediate removal or actual hard cut may be best.
- **Small out-of-bounds displacement for interfaces:** when appropriate, let a UI element briefly **overshoot its designed resting position** and settle back with a restrained spring/damped curve. This is a tiny tactile movement, **not** a license to fly text out of the 9:16 frame, crop captions, hide evidence or shake continuously.
- **Nothing mechanically linear by default:** use well-chosen nonlinear keyframe interpolation for authored position, scale, opacity, size or other animated values. Ease-in-out suits continuous motions that both start and finish at rest. Continuous constant-speed motion is still acceptable when physically or informationally necessary (such as a clock sweep or grounded map travel). Never distort facts to force an effect.
- **No automatic motion quota:** only animate when the beat benefits, with restrained distance/overshoot and a clean final settle. Horror can need silence, tension and stillness rather than bounce. Test timing and safe-zone legibility at phone scale. Avoid repetitive effects, jitter, elastic rubber-banding and eye-trace disruption.
- **Respect the previous transition punctuation rule:** a hard cut is *not* animated and remains the default clip boundary. Dissolve only for narrated passage of time, black fade only at the ending; don't reintroduce slides, swooshes, zoom transitions or wipes by calling them easing.

**QA evidence:** For each deliberate entrance/exit/overshoot, verify what is moving, the meaning of that gesture, start/end positions, readability, timing, easing curve, whether a subtle settle is warranted, and whether a simple hold/cut is stronger. These rules govern future edits; adding them to documentation **does not claim renderer code has implemented every curve**.

## 1. Captions, always
- Every spoken word should be captioned and in sync with narration. Use engaging, polished animated text with readable contrast and safe placement.
- Vary emphasis, phrase grouping and entry motion when meaningful; avoid frantic animation for every word. Missing captions are a repair issue.
- Inspect both the classic ASS engine and the explainer/Remotion engine. A polish failure must retain captions.

## 2. Still-picture motion
- Gentle purposeful zoom-in, zoom-out, pan or parallax to create a cinematic feel from still images.
- Match movement direction and speed to story tension; use restraint, avoid mechanical repeat zooms, unnecessary shake and aggressive cropping.
- Respect face, subject and text safe areas; never fake 4K image detail or imply that upscaling proves historical accuracy.

## Night Files date timeline over imagery (2026-10-27)

For a narrated, validated year, use the existing `date_stamp` graphic **over the same scene's visible story image**, not a giant number on a disconnected blurred background. Show a restrained scale of nearby year ticks, animate the line across them using natural easing, stop at the correct year, and highlight that year alone in red. The nearby ticks are a visual time scale, **not evidence of historical events**. Preserve the existing caption safe zone, avoid overlaying the main subject when possible, and retain clean hard cuts and motivated SFX. Any true-story date must still pass the current spoken-number/fact-ledger checks. This is implemented in the current `main` renderer (`pipeline/noir.py` and `pipeline/explainer.py`) rather than a separate branch/editor.

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
- Offline unit tests, mock render checks and incomplete/rejected previews must not create buffer entries, publish, or alter posting history. **A complete production-valid video, including one made to test an editing change, MUST enter the normal publishing queue.** Its test origin is not an exemption. Publication still requires the existing publisher, permissions, duplicate checks, and schedule; a draft submission is not a public post.
- Keep permanent CI, buffer-fill, daily delivery, social connection and other owner-approved workflows. Remove only verified disposable test-only workflows after their run, never CI.

## General-purpose contextual graphic and sound direction
The bot is an editor for **any** story, not an Aka Manto template. First identify the narrated event, then decide whether an on-screen effect improves comprehension. Examples of a reusable event-to-presentation vocabulary:
- **Incoming text / phone alert:** show a convincing phone/screen insert, reveal only the message actually stated in the narration or provided source, animate its appearance, optionally add one subtle vibration/notification sound if a licensed matching SFX exists. Do not fabricate messages or private details.
- **Phone ringing / call:** show caller interface or incoming-call visual; sync a brief ring or buzz to the line, avoid ringing over speech or inventing caller identity.
- **Weather:** show rain, wind, lightning, fog only when the story establishes it; sync restrained rain/wind/thunder ambience if available.
- **Discovery / evidence:** use a clean, legible reveal, close-up, highlight, photo-scan or document insert only when the object or finding is supported. Never generate illegible fake evidence text.
- **Travel / location change:** a hard cut normally establishes a new place; an animated route *within* a map graphic is allowed only for grounded locations. Never invent routes or add a slide just because the setting changed.
- **Time shift / flashback:** use a restrained date, clock, lighting or transition cue to mark temporal change when necessary, not every scene.
- **Choice, warning, interruption:** use split emphasis, short graphic beat, or intentional silence only when narratively motivated.
- **Motion:** use thirds, circular/radial, leading lines, framing-within-frame, or diagonal composition when useful; never force all methods into one scene.

Choose from existing supported graphic templates/SFX and do not claim nonexistent effect implementations. When the exact asset or template is absent, use a clean existing alternative or no effect, never hallucinate a media capability. Text on screen must be sourced or verbatim from narration, legible, and separate from base image generation. Respect caption safe zones, audio ducking, and cooldowns to avoid overediting.


## Aka Manto preview lessons, generalized to every story (2026-10-24)

The actual Aka Manto preview, `explainer_polished(1).mp4`, and its generated scene JSON were reviewed with the owner. Positive: dark atmospheric artwork, increasingly cinematic treatment, bold mobile typography, and usable narration. Observed problems (not yet fixed in renderer code):

1. **Meaning before motion:** the impact card rendered “CHOOSE COVERED” and separately captioned “in blood.” This is grammatically and narratively incoherent. Emphasize complete semantic units, e.g. “CHOOSE RED” followed by “COVERED IN BLOOD,” with the key consequence emphasized. Never arbitrarily concatenate nonadjacent fragments of sentences, nor underline “mysterious,” “wearing,” or filler verbs merely because they appear near a cue.
2. **Emphasis intelligence:** choose the strongest noun, choice, threat, evidence, contrast or payoff **within its complete phrase**. Accents/underlines should mean something; don't underline every graphic. Ordinary spoken captions remain complete and synchronized.
3. **Transition grammar (superseded by 2026-10-25 owner directive above):** hard cut is the default. Dissolve only for genuine time passage. Fade to black only at the ending. Movement inside a contextual graphic is not a reason for a transition between clips.
4. **Contextual viewer surrogate:** for a direct binary choice, a decision composition can use approved host/character art with two visual options (e.g. hands open, one holding red and the other blue), only when a matching authorized pose exists. Never silently invent or replace owner-approved assets. Missing required pose -> propose asset for approval, then use a non-character decision graphic fallback. Apply this reusable visual grammar to doors, phone calls, conflicting testimony, travel routes, etc., not just this legend.
5. **One beat, one visual focal point:** do not stack huge title, subtitle, multiple underlines, motion, and a busy graphic in the same moment. Subject/image selection must explain the line, not merely resemble its mood.
6. **Shot and sound meaning:** allow deliberate stillness, purposeful camera motions and matching ambience rather than a constant Ken Burns move, generic whoosh or arbitrary sound cue.
7. **Consistency and grounding:** the same figure, prop, location and time should remain consistent. Ensure graphic claims use narrated facts or appropriately marked folklore, not invented messages or evidence.

### Offline acceptance tests to implement
- Impact-card semantic extraction must avoid “CHOOSE COVERED” and favor coherent full phrases; test red/blue, “open the door or don't,” dates, locations, and unrelated stories.
- Annotated emphasis spans must be inside the selected coherent phrase, favor its actual payoff and avoid function words.
- Transition planner defaults to hard cuts and never substitutes a decorative effect for variety. A dissolve requires an explicit time-passage cue on a scene boundary; test that mood, route/location and sudden action remain cuts, and that no fade to black occurs mid-story.
- If a decision cue exists and approved character/pose metadata allows, plan a viewer-surrogate composition, otherwise fall back gracefully without unauthorized art.
- Verify readability and caption safe area in 1080×1920 and inspect real frames, not only mocked frame plans.
- Verify optional SFX are event-matched, mixed beneath voice, and silence is allowed.
- During offline tests, no publishing, buffer mutation, history write, or parallel rendering engine. If the exercise produces a complete, fully validated video intended as a real Night Files output, route it through the standard buffered publishing process rather than leaving it as an isolated preview.

### Hugging Face Diffusers, optional research track, NOT installed or production-enabled
Project: https://github.com/huggingface/diffusers, Apache-2.0 library. Docs: https://huggingface.co/docs/diffusers/using-diffusers/text-img2vid
Potential uses: short image-to-video inserts from existing licensed/approved plates, controlled image generation, and local experiments comparing temporal consistency with current FFmpeg Ken Burns/parallax and other existing motion providers. Not a compositor, captioner or editor brain. Modern video pipelines can require significant GPU VRAM and runtime, not guaranteed free on GitHub Actions CPU. Check every chosen model's separate license, hardware usage, provenance, quality, caching, and cost. Run isolated GPU benchmarks and review output before opt-in; preserve the original still-image route as the default with no background installation or added CI GPU requirement.

## Walter Murch's Rule of Six: final editorial hierarchy

[Detailed and sourced Night Files implementation](WALTER_MURCH_RULE_OF_SIX.md).

At each major cut or graphic decision, rank: **Emotion (51%) > Story (23%) > Rhythm (10%) > Eye trace (7%) > 2D screen composition (5%) > 3D spatial continuity (4%)**. These values are Murch's illustrative priorities, not an objective formula or publishing score. Preserve story truth, safety and rights regardless of aesthetics. The rule explicitly ranks *feeling and meaning* above technical flourishes: a simple hold or hard cut beats a swoosh if it makes the moment land.

Practical audit questions: What should the viewer feel now? What changes in the story? Why cut at this exact moment? Where does their eye go next? Are captions/graphics legible and shot direction coherent? Does the place still make sense? Keep existing caption coverage, subtle camera motion, selective useful graphics and scene-matched sound. Never add a graphic to satisfy a quota or force one of the five composition patterns into every shot.

## Implemented in the universal editor (2026-10-25)

All of this lives in the ONE editor (`pipeline/explainer.py` "editorial intelligence" section, `pipeline/noir.py`
templates, `remotion/src/polish.jsx`); there is no per-story code and no second pipeline.

- **Root causes of the Aka Manto preview problems.** `CHOOSE COVERED`: the old impact fallback joined the scene's two
  LONGEST words. Meaningless underlines: the Remotion caption track underlined every spoken word, and the impact card
  always underlined its last line. Repeated swooshes: Remotion drew a magenta sweep on every cut, and every graphic
  wiped in with a whoosh.
- **Meaning-aware typography.** `key_phrases` returns complete phrases from one clause ("CHOOSE RED", "COVERED IN
  BLOOD"). It never glues words from different places. Each phrase's accent is its payoff word. With no meaningful
  phrase, the scene gets no impact card. Captions accent at most one payoff word per scene.
- **Transitions (updated 2026-10-25).** Hard cut by default. Dissolve only on a supported passage of time, never
  for atmosphere alone. Fade to black is an optional ending punctuation, not a scene boundary. No automatic slide,
  pop, swoosh, flash or wipe between shots. Stills may hold still on a reveal.
- **Viewer surrogate.** For a real either/or in the narration ("Red or blue?"), the `choice` graphic shows the
  approved P08 open-palms pose with one option over each palm. The pose is SHA-256-checked, and the artwork is never
  changed. Without P08, the two options appear alone. Other P poses are not picked automatically until the owner
  approves them.
- **Contextual graphics and sound.** A stated text message appears as a `phone` insert with one notification chime.
  Event sounds are timed to the word that describes the event. Hypothetical lines, the hook and moods get no sound;
  silence is allowed.
- **Local Hugging Face models only.** CLAP checks that each SFX file sounds like its label (`assets/sfx/clap_index.json`).
  CLIP picks which picture opens each scene. Depth Anything V2 adds a gentle near-layer parallax. Whisper is a
  report-only check of heard words against captions.

## Hugging Face Diffusers evaluation (2026-10-25)

Question: can Diffusers image-to-video (I2V) usefully animate selected existing story stills, compared with the
current Ken Burns, Depth Anything V2 parallax and ZeroGPU Space motion?

| Model (Diffusers) | Licence | Hardware / runtime (published) | Fit for Night Files |
|---|---|---|---|
| Stable Video Diffusion img2vid-xt | Stability AI Community License (commercial terms at stability.ai/license) | 25 frames at 576x1024; about 180 s per clip on an A100 80 GB (model card) | Short motion only (about 1-2 s). GPU required; not practical on a CPU runner. |
| Wan 2.1 I2V 14B (480p) | Apache-2.0 | About 13 GB VRAM even with Diffusers group offloading (Diffusers docs for the 14B models); 24 GB is the common claim | Best licence, heavy. Owner's own GPU only. |
| LTX-Video / LTX-2.x | LTX-2 Community License (free under USD 10M revenue; check the exact version's LICENSE) | 16 GB+ VRAM published; fp8 / offload variants exist | Fast on GPU; licence must be checked per version. |
| CogVideoX-2B / 5B I2V | CogVideoX licence (check per model) | GPU, 50 steps | Lower priority. |

**Verdict: not practical in the default production pipeline.** GitHub-hosted runners are CPU-only (4 vCPU, 16 GB RAM).
Every useful I2V model needs a GPU with about 13-24 GB VRAM, and minutes per short clip even on an A100. On CPU it
would take hours and break the 2-a-day schedule. AI video models also smear faces, add morphing, and can change
the approved look (the Oct 6 Lougawou hook-blur lesson). Current motion is free, fast and deterministic: Ken Burns,
Depth Anything V2 parallax (local, Apache-2.0) and the existing ZeroGPU Spaces route in `ai_motion.py`.

**Practical future option, if wanted:** an opt-in, isolated tool for the owner's own GPU (or a free Colab or Kaggle
GPU). It would turn 1-3 selected stills per video into 2 s inserts with Wan 2.1 I2V (Apache-2.0), reviewed by a
person before use, keeping the still and parallax path as the default and the fallback. Nothing is installed or
enabled in production or CI. A side-by-side comparison with Ken Burns and parallax needs that GPU; it was not run here.

Sources: Diffusers video guide https://huggingface.co/docs/diffusers/using-diffusers/text-img2vid ,
SVD model card https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt ,
LTX licence https://huggingface.co/Lightricks/LTX-2.3/blob/main/LICENSE ,
Wan 2.1 overview https://comfyui-wiki.com/en/tutorial/advanced/wan21-video-model (third-party VRAM figures,
unverified against Wan-AI's own card).

## Whisper narration diagnostics enabled (2026-10-25)

The existing `pipeline/explainer.py` local CPU `openai/whisper-base` transcription check is now enabled with `config.json: whisper_narration_check=true` for future complete explainer renders. It checks the real audio against the caption words (coverage, missing words, median timing offset), writes `narration_check` to the existing `visual_qa.json` report and story metadata, and never gates or blocks an otherwise acceptable publishable video. If model download, local inference, transcription, or audio decoding fail, record `status: unavailable` and the exception in the SAME existing QA report and proceed through the original full technical/visual/provenance gate. Successful checks record `status: checked`; these are diagnostic measurements, not factual validation. No new editor, story-specific source, paid inference API, upload mode or separate workflow.

Offline tests use a fake Whisper pipeline and normal shared-editor mocks across a folklore legend, fictional haunted house, and a historical mystery, plus error fallback and matched spoken-word timing. They do not generate or publish complete videos. Test logs do not certify real-world caption accuracy; review the next real rendered video report when model weights are available locally.

## Local CLIP: scene relevance and approved-asset selection (2026-10-24)

The already-present image-reuse library (`pipeline/library.py`) uses local `openai/clip-vit-base-patch32`. Night Files PR #27 extends that SAME model to the existing media and renderer without a second model or a story-specific editor.

- Real stock/archives: download up to three licensed/title-checked candidates, rank their visual similarity to the narration beat's own image prompt, then apply the original strict visual QA before accepting one; source attribution is preserved.
- AI images: score the generated picture against its own story-shot prompt; low scores trigger the existing rejected-image retry/fallback logic. CLIP does not validate real identity, historical accuracy, factual truth or rights.
- Explainer: optionally order surviving images inside a scene by semantic relevance, retaining the original hook order; do not move images between scenes or bypass acceptance gates.
- Approved reactions: only match assets with `status=approved`, valid manifest SHA-256 and usable transparency. Reuse the owner's already-existing art; a new pose (such as P08) can only become selectable when its explicit manifest entry has been approved and integrated, never by assuming a file exists.
- No paid API: use CPU-hosted Transformers locally, model weights from Hugging Face as a free download and existing model cache. If model download/inference fails, keep the established editor and QA. No pay-as-you-go inference/paid GPU dependency.
- Config: `clip_matching_enabled`, `clip_real_media_min_similarity`, `clip_generated_min_similarity`, `clip_approved_asset_matching`, `clip_approved_asset_min_similarity`, `clip_pose_min_gain` and `clip_reorder_min_margin`. Values are deliberately conservative initial heuristics, not an objective quality score; tune from manually checked, varied real output.
- Operational evidence: recorded per-candidate source/similarity and rejected fallback reasons. The offline tests mock CLIP vectors and use small local image files, without API calls or posting. An actual finished MP4 and a real free model inference must still be reviewed before claiming improved cinematic results.

## Owner's completed-video publishing decision (October 24, 2026)

Owner explicitly confirmed: **"every completed video should be published, including test videos."** The word *test* describes why a video was produced, not whether the finished video gets posted. A complete Night Files MP4 that passes the normal production gate is a real output, joins the ordinary buffer and progresses through established publishing slots and retries. Diagnostic frame sheets, mock unit tests, unfinished snippets and invalid renders are not completed videos and must not be posted. Keep factual/source/rights verification and existing delivery restrictions. Do not claim success until a destination actually confirms public publishing, not just a buffer entry or TikTok draft.

## Semantic visual method first, owner review of Hinterkaifeck, October 25, 2026

**Universal editor acceptance rule:** Select the visual *presentation method* before selecting an asset for each narration beat. Options include relevant supplied image/video, designed icon/diagram/object graphic, kinetic date or title, accurate map pin, uncluttered dark/neutral graphic canvas, overlay, archival evidence frame, or stillness. Never force all supplied project assets onto the timeline. An image is not the default answer to every spoken sentence. Keep matching priorities for *images that are actually needed*: project-specific, reusable general, licensed media, then AI generation.

Synchronize visual revelations exactly: show the farmhouse/footprints for the footprint hook, visually negate the return path with a clear arrow/X, use date typography and a grounded Bavarian location pin, stage newspapers and disappearing keys as simple readable graphics without fictitious evidence, show the barn image when the barn is spoken, and show the mattock with complementary title 'THE MURDER WEAPON' rather than duplicated captions. These are examples of treatment logic, **not mandatory props or a fixed Hinterkaifeck template**. Generic clue lists can be sequential icon/graphic overlays, not a parade of unrelated pictures.

Avoid tiny framed photos floating over mismatched filler backgrounds, cropped top/bottom art, overly repetitive panels, and image changes triggered merely by sentence boundaries. A clean black background with one meaningful graphic can be better than a generic generated scene. Sound effects require a source-supported visible/narrated event and accurate timing; do not add ticking clocks or opening doors at unrelated weapon/crime narration beats. Silence is valid. Hard cut by default, dissolve only to show elapsed time, fade to black only at the final ending; motion inside a graphic can use meaningful easing without becoming a decorative transition.

For each beat, plan: narration cue, chosen visual method and reason, data/asset provenance, optional meaningful overlay/title, sound cue or silence, and phone-safe composition. Review the full MP4 for comprehension, alignment, caption placement, SFX relevance and framing. Passing encoder/unit tests alone does not demonstrate editing acceptance. This rule is a specification for future improvements, **not proof it is currently implemented in the renderer**. See Vandam's canonical Rule 0B.

## Night Files only, automatic first-second photographic cover, October 26, 2026

Every **new** Night Files MP4 begins with exactly 1.0 second of a story-specific, realistic, high-contrast black-and-white 9:16 hero image. This is a **Night Files exception**, not a universal Vandam video rule. Prefer an original photorealistic cover created with the existing free Cloudflare Workers AI image capability and a prompt grounded in the actual hook; if its quota/provider fails, convert a scene-specific accepted image to monochrome. Do not replace real historical evidence with an invented photo claimed to be authentic, and never label generated reconstructions as archival documents.

Implementation lives in `pipeline/cover_frame.py`, called once from `pipeline/main.py` after music and before QA/buffering. The first 30 frames are the new cover. A hard cut at t=1.0s resumes the original video. Audio, synchronized captions and original total duration remain unchanged, including the mandatory 61-to-68-second gate. Store `cover_main.png`, `cover_thumb.jpg`, `cover_meta.json` in the current run's output, and record their role and source in `caption.json`. A candidate thumbnail is supplied, but TikTok/YouTube/Buffer might still choose a different thumbnail until the platform's actual cover-setting path is implemented and verified.

Do not affect other Vandam video projects, invoke paid image providers, alter scheduled publishing, or mutate media from existing buffer entries. The cover must be a clean full-frame image, not a collage, title card, or new decorative transition. If even the accepted scene media is unavailable, derive the cover from the actual current video's frame; do not import unrelated old story imagery.

Acceptance: verify first and thirty-first frames, natural colors after one second, 1080x1920 size, audio stream, the exact same runtime and the existing production QA gate.
