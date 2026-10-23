# MrBeast TikTok clipper

The reusable `clipper/` source is separate from Night Files' horror rendering pipeline. **Only inbox drafts are allowed.** Direct/public publishing is intentionally unavailable from `clipper/post.py`.

## Canonical workflows

The *existing* `main` workflows are:
- `.github/workflows/tiktok_clipper_preview.yml`, manual preview, never posts.
- `.github/workflows/tiktok_clipper_scheduled.yml`, scheduled **TikTok inbox drafts only**, never direct posting or YouTube.

These currently checkout `feature/mrbeast-split-tiktok` to load the clipper code. **Do not switch their checkout ref to `main` before that code is fully integrated, tested and approved.** The old `split_clipper.yml` and `split_clipper_test.yml` were removed from this PR because they would create duplicate/unsafe workflows.

The scheduled flow loads source/background video assets, makes subtitles and a vertical render, checks size, then uses `clipper/post.py --mode draft`. TikTok inbox uploads do not prefill captions: copy the saved caption from the workflow artifacts. Video sources must be reused only with appropriate rights and platform permission.

## Local preview

`python clipper/render.py --source source.mp4 --background gameplay.mp4 --start 30 --duration 45`

The offline synthetic render test is `python clipper/test_smoke.py`. It requires `ffmpeg` and `ffprobe`, and tests a small synthetic render, **not** asset downloading, TikTok authentication, successful inbox receipt, copyright permission, or an approved finished video.

## Integration gate

Review code and source rights, run the offline smoke test and inspect the real MP4, then validate an authorized test TikTok inbox draft. Only after acceptance may the source join `main` and existing workflows have their checkout refs updated. Do not create another scheduled/preview workflow or publish directly.
