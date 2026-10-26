# Night Files editorial graphics and public YouTube media

Status: isolated experimental branch, **not deployed**. Nothing here repairs an existing Buffer post automatically or authorizes publishing.

## Visual method first

The editor now recognizes a small, source-grounded vocabulary of visual beats: footprint clues with no reported return route, missing keys, newspapers, correspondence, photographs, weapons and narrated locations. It selects native Pillow graphic scenes rather than requiring another photograph for every cue. The existing story-specific media chain remains the fallback and retains all existing provenance and factual checks. This first version is intentionally bounded; not every topic/event has a template. Narration wording and scene boundaries determine what is detected, and every actual rendered video still requires human visual/sound review.

## Why Buffer failed

Existing `tools/auto_buffer_backfill.py` supplied GitHub Release `browser_download_url` directly when scheduling. These are not a guaranteed stable public MP4 URL for the later publication time. Buffer may fetch the media much later, when redirects or assets no longer work. The source account is public but the failure can still happen. The queued Amelia Earhart stamp `2026-10-23_2249` already has a Buffer receipt, so **never blindly enqueue another copy**.

## Safer proposed upload path

The Buffer worker now uploads a hash-named, immutable MP4 to a public Cloudflare R2 bucket before creating a new Buffer post. It uses the same accepted GitHub Release MP4 and validates the HTTPS URL as a directly accessible video. It preserves the original Buffer idempotency ledger.

**Required owner-configured repository secrets**, not provisioned in chat:

* `CLOUDFLARE_ACCOUNT_ID`, already available
* `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY`, a new restricted R2 S3-compatible API key with upload and head permissions for the chosen bucket
* `R2_BUCKET`, the chosen bucket name
* `R2_PUBLIC_BASE_URL`, its public, durable HTTPS delivery domain

R2 storage may have usage charges, request permission and check current free limits before enabling. Do not reuse an unrelated Cloudflare Workers AI token for R2. Restrict bucket and credentials; do not commit tokens or URLs with signed query parameters. New post enqueue operations fail closed if required config is missing. If the owner does not approve R2, replace this storage option with a supported stable public upload mechanism before merging, not a temporary URL.

The automatically queued videos remain intact, and TikTok/YouTube routines are not replaced. Until these secrets are configured and verified, **do not merge this R2 change to production**, because it will block new Buffer posts rather than repair the issue.

## Repair the *existing* failed Amelia Earhart post

The immutable original Night Files MP4 should be available in the `youtube-pending` Release. Open the Buffer dashboard and locate the existing failed post by its original ID, recorded in `data/buffer_backfill_queue.json`. Verify that it was not publicly posted and that no second queued copy exists. Edit **that same post**, using either a direct MP4 upload via Buffer or a tested, permanent public URL. Then use Buffer's retry/reschedule once after the existing post's media has been updated. Do not remove the GitHub queue record, alter the original MP4 or start a new post automatically. Record actual publication only after confirmation on the platform.

## Acceptance tests required

1. Local visual treatment tests and real Pillow 1080x1920 graphic-render tests pass.
2. Existing Night Files test suite, including caption, transition and event SFX tests, passes.
3. Full actual isolated Hinterkaifeck video review verifies exact cue timing, proper crops and absence of irrelevant sound.
4. Source MP4 -> R2 mirror -> public GET over unauthenticated network -> same Buffer post delivery is proved end-to-end before production adoption.
5. A planned remote post and the existing failed Amelia Earhart post are reconciled individually; no duplicate video posts.
6. Preserve PR #38 project-assets integration, its unrelated branch/test evidence and all previously queued media. Resolve overlapping changes before merging.

No PR merge, automatic retry, paid API call or live publish is part of this branch.
