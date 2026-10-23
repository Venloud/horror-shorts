# Night Files full-body pose render standard

This is an additive render standard, not a replacement of owner-approved art or the 118-item catalog.

## Asset rules

* Every full-body P pose uses a transparent **1024 × 1536 RGBA** render canvas.
* Approved **M01** is the head-scale and alignment reference.
* Silhouette ground baseline is **y = 1460** on the 1536px canvas, with a transparent bottom margin.
* Prefer M01 head-center alignment. Keep complete hands, shoes and aura; never crop the pose to force alignment.
* Use a single uniform scale, NEVER stretch X and Y independently.
* Preserve original PNG bytes unchanged. Store source poses separately in `assets/character/host/poses/original/` only after approval and put derived assets under `assets/character/host/poses/render_ready/`.
* F expression close-ups and M05 are **not** full-body poses; do not normalize with this profile.
* Keep the source's existing red outline and translucent aura, do not synthesize additional glow.
* If the head-to-body proportion differs materially from M01, the drawing itself must be reviewed or redrawn. Resize cannot repair different anatomy.
* Do not register render copies as new approved source assets, or enable automatic P-series selection until approval.

## Generate and audit

```bash
python tools/normalize_character_poses.py \
  --reference assets/character/host/masters/M01_front_neutral.png \
  --inputs assets/character/host/poses/original/P*.png \
  --output-dir assets/character/host/poses/render_ready \
  --strict
```

Requirements: Pillow and NumPy, already used in the existing renderer. Strict mode **does not export** images needing review. Each run records input SHA256, output SHA256, uniform scale, head ratio deviation, head center, visible silhouette bounds, foot baseline and warnings in `normalization_report.json`. Original files are never opened for writing. Existing output files cannot be overwritten without `--overwrite`.

Test with:

```bash
python -m unittest discover -s tests -p test_character_pose_normalization.py
```

## QA and current state

Before approving a derived pose, inspect its alpha edges, fine red aura, head-to-body ratio, all extremities, head center and bottom anchor. A size warning or head drift warning means further review, not approval.

At implementation time P01 Standing, P02 Explaining with both hands, and P03 Presenting with one hand were generated in chat. They are **candidates only**, and have not been registered as approved P-series sources. A provisional local comparison found P01 and P02's proportions noticeably different from M01, while P03's extended hand forces a lateral offset; none should be silently marked passed. Final renders must be checked with the original approved M01 PNG located above, not a resized contact sheet.

This normalization addition intentionally leaves the story planner, the existing renderer, the approved library, Night Files scheduling and the independent MrBeast TikTok workflow untouched.
