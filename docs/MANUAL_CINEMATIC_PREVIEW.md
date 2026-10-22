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
