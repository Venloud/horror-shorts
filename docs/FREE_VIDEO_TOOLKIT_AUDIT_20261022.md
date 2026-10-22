# Night Files, free motion-design tools sourced from Venloud's other repositories

Date: 2026-10-22. Owner direction: retain approved M/F character originals; improve editorial motion, typography, scene-grounded explanation graphics and evidence reveals. **Renovate existing `pipeline/explainer.py` and `pipeline/noir.py`. No alternate renderer or publishing workflow.**

## Sources inspected and licensing implications

| Repository | Relevant free capability | Decision |
| --- | --- | --- |
| [Venloud/bouriko-shorts](https://github.com/Venloud/bouriko-shorts) | Remotion React compositions, precise frame/voice timing, motion graphics; `remotion/render.mts` | **Reusable architecture**. Night Files already has Remotion 4; do not blindly copy or re-enable its failed `remotion_join`. The current compatible Pillow/FFmpeg branch can be reviewed first. |
| [Venloud/OpenMontage](https://github.com/Venloud/OpenMontage) | Production QA, dynamic visualization, parallax/camera ideas, reference-led composition | **Concept inspiration only.** Source license **AGPL-3.0**, not MIT. No OpenMontage source copied into this repo. OpenMontage demos often use *paid* image/video/voice APIs, so installing everything would violate a zero-cost test. |
| [Venloud/MoneyPrinterTurbo](https://github.com/Venloud/MoneyPrinterTurbo) | Subtitle styling, SFX/footage timing, audio normalization, asset caching, video assembly | **Future portable techniques**. Upstream code is MIT, but its AI services are not automatically free. Preserve attribution if any code is later copied. Existing Night Files FFmpeg and captions already cover basic assembly. |
| [Venloud/youtools](https://github.com/Venloud/youtools) | YouTube video downloader | **Not appropriate** for cinematic scene rendering or licensing-sensitive footage ingestion. Do not add it. |
| [Venloud/claudevandam](https://github.com/Venloud/claudevandam) | Skills, QA/handoff principles, mandatory prototype clean-up | **Process guidance**: test preview, document evidence, review actual MP4, merge through PR, then close integration debt. |

### Licensing
- Remotion is free for eligible individuals/small teams, with eligibility and use restrictions; verify at https://www.remotion.dev/docs/license if business status changes.
- FFmpeg, Python, Pillow and NumPy are free tools, but comply with each actual binary's codec distribution/license obligations.
- OpenMontage is AGPLv3; this implementation **does not include its source**.
- Commercial royalty-free asset/music terms are asset-specific; none added here.

## Implemented on the proposed feature branch

**New original reusable motion templates (all 0 API calls):**
- `photo_scan`: photo-shaped investigative graphic with sweeping scan line, focus circles, illustrative shadow symbols, and prominent **ILLUSTRATIVE RECONSTRUCTION** marking. Not a fake original photograph.
- `clock_stop`: animated clock hand visibly decelerates to a stop; optional time label is accepted only when grounded in the narration.
- `shadow_reveal`: animated sequence of count-grounded schematic silhouettes with **NOT ARCHIVAL FOOTAGE** label. Requires actual spoken count for the `shadow_reveal` template.

**Camera staging:** `cinematic_camera` supports subtle_push / subtle_pan / parallax_light on a composed scene before rendering captions. Default **OFF** for production (`explainer_cinematic_camera` config not enabled); the isolated manual preview enables it in memory only.

**Planning and rendering:** Storyboard supports the three templates through `GRAPHIC_TEXT` and `_valid_graphic`, which enforce scene/narration grounding, and no new cloud asset generation. Existing approved original PNGs and red aura untouched.

**Preview:** The existing `tools/night_files_visual_preview.py` fixture now exercises these effects, instead of showing mostly generic text cards. It stays offline, private to Actions artifacts, with eSpeak placeholder voice. No production posting, buffer changes, paid services, or duplicate workflows.

**Audio/SFX:** The existing Night Files FFmpeg/soundfile mixer now accepts an optional fourth `clip_seconds` field on an effect cue, with a short fade to avoid clicks. The offline preview selects camera shutter, whoosh, clock tick, and heartbeat from the repository's already-licensed SFX assets. Regular production triple-item events are unchanged. No new external audio packs added.

**Tests:** `tests/test_free_motion_toolkit.py` validates time-varying frames, camera opt-in, grounded shadow counts, missing/unsupported subjects, and length-limited existing SFX cues. CI validation and manual MP4 visual review are separate gates.

## Still pending, do not claim completed

- **Verified preview evidence:** [Actions run 39740729079](https://github.com/Venloud/horror-shorts/actions/runs/39740729079) completed both code checks and the manual MP4 job, with downloadable `night-files-manual-cinematic-preview` artifact. The 17.07-second, 1080×1920, 24 fps H.264/AAC MP4 and contact sheet were inspected. The scan/clock/shadow graphics appear; **the video is still an early motion-design prototype, not approved as cinematic or viral-standard**. The voice is still placeholder eSpeak, and the full SFX mix has not received subjective listening approval.
- **Final feature-branch checks:** [Actions run 39740760122](https://github.com/Venloud/horror-shorts/actions/runs/39740760122) passed CI and the new offline graphics/SFX regression tests. Preview-only job was returned to manual-only after isolated testing.
- Improve approved bust cropping and inconsistent character scale if preview still exposes them.
- Remotion integration into actual Night Files production is **not yet verified**. Do not silently switch `remotion_join` or install the full OpenMontage pipeline.
- Production still uses generic procedural fallbacks for missing P action poses. Preserve approved assets.
- After PR review and owner approval, integrate to main; remove/retire any temporary tests only after equivalent coverage lives in CI, per Vandam reintegration policy.

## Safe test sequence

1. Run CI on this **draft PR**. Resolve failures without merging.
2. Review graphics using the new manual preview helper locally or in an isolated branch-associated Actions run.
3. Compare actual output with previous 17-second baseline; capture specific visual shortcomings.
4. Merge only with owner approval. Then run the manual preview from main (and inspect actual MP4).
5. Document what remains unfinished. No unrequested production publishing.

This document records *implementation intent and test requirements*, not proof that a finished viral-quality video was produced.


## Remotion editorial layer, October 22 follow-through

The user requested direct implementation of improved shot composition and Remotion motion graphics *within this same Night Files pipeline*. Implemented on this draft PR:

- Existing `pipeline/explainer.py` now frames approved host at larger wide/medium sizes and crops only the **empty alpha padding** from approved close-up canvases before video-scale placement. The underlying user artwork and red aura bytes remain untouched. This last alpha-bounds positioning tweak awaits a fresh manual output review.
- Reused `remotion/src/index.jsx` and preserved `NightFilesJoin`; registered the root needed by CLI and added `NightFilesPolish` alongside it.
- Added `remotion/src/polish.jsx`: spring-in 2–3-word spoken captions with active-word underlines, chapter/editorial label, subtle grain, progressive timeline, and synchronized cut sweep.
- Added `pipeline/remotion_post.py` and `remotion/render_polish.mjs` as a guarded editing bridge from the existing source MP4 to Remotion and back to FFmpeg for **the exact original mixed soundtrack**. This is a *post-pass*, not a new story planner.
- Enabled Remotion captions in the existing isolated `tools/night_files_visual_preview.py`, and added Node+Remotion dependencies to the **existing** manual GitHub Actions job. The production `remotion_polish` opt-in stays **false**; normal Pillow captions remain untouched until explicit approval.
- Added `tests/test_remotion_post.py` for shot/frame timing, missing-input rejection, existing `NightFilesJoin`, and default-off safety. Original approved artwork remains unchanged.

**Actual Remotion verification:** [Actions run 39743096909](https://github.com/Venloud/horror-shorts/actions/runs/39743096909) passed CI **and** full 17.07s 1080×1920 H.264/AAC Remotion MP4 generation with intact voice/SFX. The artifact was downloaded, verified using ffprobe and inspected visually at 4.00 and 15.25 seconds. The character still floated high with empty lower space in that first Remotion render, so the next commit corrected close-up transparency positioning. A subsequent MP4 visual check for *that latest correction* is still required; do not imply it passed from the earlier artifact.

**Quality notes:** Compared with the first Python-only preview, motion-synchronized captions/cut treatment and character sizing improved. However, full cinematic/viral quality needs further editing choices, music, atmosphere, creative lighting and transition refinement. The temporary eSpeak narrator is not final. Keep PR draft/unmerged pending owner review and the last framing visual validation.

**Close-the-loop:** no second pipeline or V2; incorporate any subsequent fixes into the same approved renderer/Remotion post-pass. After merge approval, run a manual preview on main and remove any obsolete temporary media from build outputs, not approved source art.

## Owner-approved old-editor retirement (October 22)

The owner instructed us to stop maintaining separate old/new editing variants and keep the upgraded version on `main`. Retired the failed, disabled clip-by-clip `NightFilesJoin` path, `render_join.mjs`, its config switch and old fallback chain. The source renderer still uses Pillow/FFmpeg because that is the **first stage** of the new integrated video system, not a competing version. The Night Files explainer default now enables `remotion_polish` and the existing daily/buffer builder workflows install Remotion when requested. Preview remains safe and manual, and the older sample narrative remains only a test fixture. Existing publishing schedules, original art, approved assets and unrelated MrBeast clipper workflows are unchanged. Future edits should target `NightFilesPolish` and the shared source renderer; do not recreate the obsolete joiner.
