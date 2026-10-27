# MrBeast TikTok clipper

The reusable `clipper/` source is separate from Night Files' horror rendering pipeline. **Only inbox drafts are allowed.** Direct/public publishing is intentionally unavailable from `clipper/post.py`.

## Canonical workflows

The *existing* `main` workflows are:
- `.github/workflows/tiktok_clipper_preview.yml`, manual preview, never posts.
- `.github/workflows/tiktok_clipper_scheduled.yml`, scheduled **TikTok inbox drafts only**, never direct posting or YouTube.

**Both workflows now check out `main`.** The former `feature/mrbeast-split-tiktok` PR was merged and its branch safely removed on 2026-10-27. The existing `clipper/` modules on `main` were verified byte-for-byte identical to the former branch tip, and the CI workflow-order test checks both checkout refs and the draft-only publishing boundary. Never reintroduce the deleted checkout ref or create duplicate clipper workflows. The old `split_clipper.yml` and `split_clipper_test.yml` remain retired.

The scheduled flow loads source/background video assets, makes subtitles and a vertical render, checks size, then uses `clipper/post.py --mode draft`. TikTok inbox uploads do not prefill captions: copy the saved caption from the workflow artifacts. Video sources must be reused only with appropriate rights and platform permission.

## Local preview

`python clipper/render.py --source source.mp4 --background gameplay.mp4 --start 30 --duration 45`

The offline synthetic render test is `python clipper/test_smoke.py`. It requires `ffmpeg` and `ffprobe`, and tests a small synthetic render, **not** asset downloading, TikTok authentication, successful inbox receipt, copyright permission, or an approved finished video.

## Integration gate

Review code and source rights, run the offline smoke test and inspect the real MP4, then validate an authorized test TikTok inbox draft. Only after acceptance may the source join `main` and existing workflows have their checkout refs updated. Do not create another scheduled/preview workflow or publish directly.

## Duplicate delivery guard, October 27 2026

The scheduled workflow now reserves a unique source part in `data/clipper_delivery_ledger.json` through GitHub's Contents API BEFORE TikTok inbox upload. A known part is never automatically sent again, even on same-slot reruns, after a success, or if an upload status cannot be confirmed. Confirmation attaches TikTok `publish_id` to the reservation; an interrupted delivery stays `reserved` and requires manual reconciliation. GitHub Contents blob SHA compare-and-swap guards concurrent reservations. Because this guard blocks reused parts, exhaustively using the 57 available full-minute segments is intentionally terminal until the owner authorizes new footage or explicitly reconciles the ledger. `GH_PAT` must permit contents write; if not, delivery fails closed. The built-in GitHub token is read-only for this workflow. Existing historical inbox drafts were not automatically imported into the new ledger, and older sends can be duplicated unless their part IDs are reconciled first. The scheduled workflow remains inbox-draft-only and does not publish publicly.
