# Night Files Buffer TikTok diagnosis — 2026-11-07 (America/New_York)

## Evidence and root cause

Base: fetched `origin/main` 1ab681ac68598eb4b99e36e2acce7b267830b539. The existing local checkout is on an older unrelated shared-library branch; this repair uses a detached current-main worktree to preserve it. No production dispatch or remote mutation was performed.

- [Recovery run 42437678217](https://github.com/Venloud/horror-shorts/actions/runs/42437678217), head/checkout 2f7ef838b0d990a9159f207805994979b644e638, job 128603127881, logged inventory exhaustion at 2026-11-08 02:29:15 UTC. The recovery code returned success after no eligible candidates; it never reached Buffer queries or createPost. Green established successful execution of a no-op, not successful delivery or healthy queue depth.
- Latest listed runs were CI 42445412499 (1ab681a), 42445396488 (7c62f05), 42445377949 (b40ecb3), all successful. These are validation runs, not queued-publication receipts. No newer production run was in the inspected latest-15 list.
- [Daily run 42406906980](https://github.com/Venloud/horror-shorts/actions/runs/42406906980) used the previous draft route. Its log confirms SEND_TO_USER_INBOX for The Pontianak, then archives stamp 2026-11-07_1936 and queues it to YouTube Buffer post 6aef86369214322f6813af5d. It is not a TikTok Buffer receipt.
- History confirms both rollout-date videos were already sent as TikTok inbox drafts: 2026-11-07_0637 (Flannan Isles, draft_sent 2026-11-07_0717) and 2026-11-07_1936 (Pontianak, draft_sent 2026-11-07_2012). The current duplicate guard intentionally refuses to publish these again via Buffer. An inbox draft does NOT establish public publication.
- Read-only release reconciliation: youtube-pending has 50 complete MP4/JSON pairs, production buffer has 0, backfill has 7. Running candidate selectors with release listings mocked into the current implementation gives 0 production candidates and 0 historical candidates. Legacy recovery candidates are also 0. Artifacts do exist (33 in metadata, latest page inspected), but their existence does not authorize replaying already-delivered or unverified videos.
- Existing `queued` ledger contains 33 queued statuses, 11 attempt_started statuses and 10 legacy records; no `tiktok_queued` receipts yet. These are lifetime delivery records, not current Buffer queue depth. Uncertain attempts must stay blocked until independently reconciled. This task did not clear or retry them.
- The rollout boundary is BUFFER_TIKTOK_FROM=2026-11-07. Older files are ineligible for new TikTok delivery, and the only two newer complete files are protected prior drafts. This explains no eligible TikTok video; do not lower the cutoff or erase draft receipts to fill the queue.

## Separate warning: service incident, not established token failure

The banner links to [Buffer's November 7 incident](https://status.buffer.com/incidents/01M6VQP2114MGETA3GX53KAXHE). Buffer identifies a TikTok-side photo/carousel issue and says videos are largely unaffected. Some items may appear publicly despite processing/failure labels. This does not explain a local no-candidate path, nor establish that Night Files credentials need reconnecting. No account-level channel health was independently checked during this task; no failed video createPost receipt is present in the cited run. User-provided Queue 0/empty slots are consistent with no new TikTok enqueue. Weekly sent-goal counts are not queue depth.

## Small repair

`tools/auto_buffer_backfill.py` now emits a structured outcome and Actions summary/output with separate new YouTube/TikTok enqueue counts. Normal periodic exhaustion remains a successful no-op with a warning, explicit no_eligible_video status, rollout/duplicate context, and uncertain-attempt count. It no longer says the remote queue is caught up. Counts do not imply public posting or channel health.

For exact Daily delivery, an accepted stamp with an unmet channel but no complete eligible release pair now exits 1 as missing_accepted_inventory. Missing .posted still reports no_accepted_video without fabricating a delivery. Existing prior-delivery and uncertain-attempt protections, write-ahead persistence, rollout date, channel IDs, config tiktok_mode=buffer, and delivery records are unchanged.

`tests/test_buffer_delivery.py` adds offline coverage for exhaustion, missing exact inventory, prior draft exclusion, missing accepted Daily video, real new-channel acknowledgment counts, and uncertain TikTok timeout preserving the independent YouTube receipt/write-ahead record.

## Manual action only if an account-specific expired-connection prompt appears

The global banner alone does not call for reconnecting. In the Buffer account that contains Night Files (not the Lab of Tory account), open profile/avatar → Channels (`https://publish.buffer.com/settings/channels`). If that exact TikTok channel displays Refresh/expired, the owner can click Refresh, sign in to the intended Night Files TikTok account and approve the requested permissions; confirm the intended channel name afterwards. Do not disconnect/delete the channel, retry posts or recreate its queue as part of diagnosis. See [Buffer's official refresh instructions](https://support.buffer.com/articles/refreshing-a-channel-in-buffer-7oDS4jk7l1). If no channel refresh prompt exists, use the incident updates/support rather than assuming OAuth failure.

## Safety and verification

No real post created/scheduled, Buffer queue altered, TikTok token refreshed, account reconnected, receipt edited, remote workflow dispatched, or change pushed. The code repair improves truthful failure/no-op reporting; it does not manufacture eligible content or fix the external service incident. Future normal authorized production must supply a newly accepted video for TikTok Buffer to have work.

Local CI dependencies were installed in a dedicated Python 3.11 environment at `C:/Users/van02/homebeacon/tools/night-files-ci` using the CI-declared packages (requests, pyyaml, pytest, Pillow, numpy, soundfile). Existing Cody FFmpeg/Node reused. Validation logs: `C:/Users/van02/homebeacon/night-files-buffer-ci`. Full results will be appended after completion; no remote CI dispatch implied.


### Executed CI result

Executed the local validation equivalents from `.github/workflows/ci.yml`: Python compilation, workflow-order checker, 17 pipeline pytest cases, all 13 unittest suites, Node syntax, JSON validation, music-rights checks, both Ruflo checks, and critical-file existence. No workflow dispatch or CI-history pruning was run. The Buffer delivery suite passes all 16 tests, including seven new regressions. `git diff --check` passes.

Initial full validation: 21 of 22 command/check groups passed. The production-pipeline suite ran 53 tests: 49 passed, three local Git fixture setup failures (Windows sandbox shared-memory permission), and one render error after the hung offline FFmpeg was explicitly stopped after roughly ten minutes. Retrying the three original Git fixture tests outside the sandbox with only a harness-level explicit Git Bash executable passed all three; no repository fixture logic was changed. A separate outside-sandbox placeholder-render retry progressed to 300/579 frames but stalled again during encoding and was explicitly stopped. That render/visual-QA check is NOT passed. Do not describe the local CI run as fully green. Current-main remote CI success is pre-patch evidence only, not validation of this repair.

Logs and per-command results: `C:/Users/van02/homebeacon/night-files-buffer-ci/results.json`, `night_files_pipeline.log`, `git-fixtures-explicit-bash.log`, `render-retry.log`. Initial results.json retains the initial failures rather than silently replacing them with retries. Local dependencies were installed in the dedicated Home Beacon CI environment, not in the runner or project dependencies. No unrelated renderer fix was attempted.

Changed files: `tools/auto_buffer_backfill.py`, `tests/test_buffer_delivery.py`, this diagnosis. Changes remain local/uncommitted in `C:/Users/van02/repos/horror-shorts-buffer-repair`; no branch, push, merge or deployment. Existing feature-branch checkout and config/data receipt files preserved.
