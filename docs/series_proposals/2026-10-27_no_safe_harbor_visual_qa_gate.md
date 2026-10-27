# No Safe Harbor, nonpublishing visual QA gate
Date: 2026-10-27
Owner authorization: scripts and proposed shot plans approved; nonpublishing verification permitted; absolutely no publishing until final videos are explicitly approved.

## Checks independently performed from repository files, not video
PASS: Production config retains occasional_trilogies.enabled=false (read from main).
PASS: series_rotation.py defines four distinct approvals concept/scripts/visuals/production, requires checksum-pinned scripts, and counts only public evidence carrying timestamp, HTTPS post URL, and confirmation source.
PASS: script review record contains all 3 episode narration drafts and all 3 corresponding shot plans.
PASS: script record now preserves owner approval and the explicit no-publish instruction.
PASS: all three scripts preserve original fictional apocalypse setting, five survivors, radio warning, resource scarcity and an immediate episode-level discovery.
These are STATIC source checks, not automated pytest or real audiovisual QA.

## Potential script or visual continuity issues to resolve in review
1. Episode 2 obtains fuel and accessible water from drifting trawler; actual shots must establish an accessible container, safe transfer and plausible quantity, without inventing extra supplies or an unverified absence of infected below decks.
2. Episode 3 mentions a distant alarm attracting infected, but its triggering source is not established in the approved script. Do not fabricate an alarm event in visuals. Flag for owner-authorized script adjustment or change in sound/action plan before rendering.
3. Episode 3 landing at an overrun port needs clear geography between fuel dock, maintenance shed, dinghy and anchored cruiser. Movement and retreat must be believable.
4. Storm, fuel and freshwater continuity across all parts must match the series bible; time labels must not imply unlimited power or impossible travel.

## Checks not performed, blocking media acceptance
- No actual MP4 nonpublishing preview rendered or inspected in this session.
- Narration duration and audio timing not measured.
- Per-shot characters, boat continuity, source licensing, shot matching, captions, crop/safe zones, cover timing, music/SFX and QA playback not verified.
- Existing project full test suite and GitHub Actions CI not executed by this document update.
- No actual public Night Files post timestamps/URLs independently confirmed as qualifying series evidence.
- Neither visual-assets approval nor final production/publication approval exists.

## Nonpublishing review acceptance checklist
For each of three episodes: render through existing Night Files editor only after assets are properly licensed and owner-approved process allows a preview; save MP4 and original shot asset lineage; confirm approx 60–75 seconds if narration naturally fits; first narration words align with opening visuals; 1-second cover; 9:16 framing; actual synced legible captions; sound balance and natural SFX; repeated characters and props consistent; hard cuts by default; no arbitrary fades or flashes; verify logical geography, continuity and episode-specific payoff; log objective QA observations and screenshots or review assets. Submit actual video outputs to owner. Do not enqueue videos, enable series gate, trigger production workflow, or publish while approval is pending.

Next required: render valid nonpublishing review videos in a runtime with the repository dependencies and approved media, perform actual visual/audio QA, get explicit owner visual signoff, then separately obtain production permission and verify public-post baseline. Until then fail closed.
