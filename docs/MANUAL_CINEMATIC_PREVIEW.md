# Night Files manual cinematic visual-direction test

Use the [existing CI workflow](https://github.com/Venloud/horror-shorts/actions/workflows/ci.yml), not Buffer Fill or Daily Publish.

1. Open **Actions → Continuous Integration**.
2. Select **Run workflow**, branch **main**, then **Run workflow**.
3. Open the new run; it has two jobs: regular validations and **Manual Cinematic Video Preview, No Publishing**.
4. When finished, open the run's **Artifacts** section. Download **night-files-manual-cinematic-preview**.
5. Extract and watch `night-files-cinematic-preview.mp4` with audio. Review the contact sheet and `shot-list.json`.

### What it does
- Creates a short **fictional** mystery teaser: *The Last Photograph*.
- Reuses the main production `pipeline/explainer.py` Renderer, approved M and F character PNGs, and `pipeline/noir.py` motion templates.
- Demonstrates word-by-word subtitles, close-ups, a neutral full-body pose, evidence reveal, impact typography, and an animated question ending.
- Outputs 1080 × 1920 H.264 MP4 at 24 fps.
- Runs offline. **No credentials, social APIs, Cloudflare images, publishing, buffer or history changes.**
- Narration uses **espeak-ng solely as a timing placeholder**. It is deliberately NOT the production voice, so the test evaluates motion design and layout first.

### Important limits
- This is an isolated STYLE PREVIEW, **not** a production story or a viral-quality guarantee.
- Production TTS, full 61–68s pacing, audio/music mixing and final QA are not exercised by the preview.
- Static/approved images don't yet cover every action, so no new character poses are created.
- No Remotion replacement is introduced; the working PIL/FFmpeg + Noir layer is tested as-is.
- The experiment uses one reusable `tools/night_files_visual_preview.py` smoke fixture, not an alternate production renderer.
- Keep this test in the existing CI workflow. **After review**, address failures in the existing renderer or motion templates, rerun the isolated preview, and track integration/cleanup debt according to Vandam. Do not create a V2 or leave a competing pipeline.

### Review checklist
- Does the approved host consistently match M01/M05 and F02/F04/F08?
- Does the suit and approved red aura read clearly on mobile?
- Is the visual pacing dynamic but not cluttered?
- Are subtitles readable outside the character's face and TikTok unsafe zones?
- Are graphics/overlays genuinely timed, grounded in narration, and polished?
- What needs improvement in existing `explainer.py` and `noir.py`?

If the manual job fails, retrieve its logs from GitHub Actions, repair the actual failure, and rerun. A green ordinary CI check is not proof the video preview was watched or approved.

## Remotion-enhanced preview, October 22

Night Files now uses **one existing pipeline, two editing stages** when explicitly enabled:

1. `pipeline/explainer.py` renders the approved illustrated host at larger mobile-first sizes, static action poses, and original Noir evidence/clock/shadow graphics; FFmpeg creates the source MP4 and voice/SFX audio.
2. `pipeline/remotion_post.py` gives storyboard shot times and individual narration words to `remotion/render_polish.mjs`. Its new `NightFilesPolish` composition adds **spring-timed word highlights**, safe-area lower captions, animated edit cut swipes, progress rail, and upper-left editorial shot labels. FFmpeg remuxes the original finished soundtrack unchanged.

The existing `NightFilesJoin` composition is preserved and now has its missing Remotion root registration. No OpenMontage AGPL files or paid services are used. Original approved PNGs remain in `assets/character/host` unchanged.

**Safe preview:** the manual GitHub Actions job installs Node/Remotion from `remotion/package.json` and runs the shared Remotion editorial pass automatically. The artifact contains the **final post-Remotion** MP4 and contact sheet.

**Production defaults:** `remotion_polish` is **off by default**. To explicitly enable the same post-pass in an authorized non-production build, set `remotion_polish: true` in its configuration. The existing `explainer.render()` uses the shared adapter and fails clearly if Remotion is missing, instead of shipping an uncaptioned MP4. Do not enable scheduled production publishing without approval and a reviewed final MP4.

**Cleanup requirement:** do not maintain a second test renderer. Finish fixes inside the existing `explainer.py`/Noir layer and the one Remotion post-pass, test the final MP4, merge only with owner's approval, and update Vandam's reintegration record.
