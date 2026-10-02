# Ruflo Task Contract: QA Reviewer

## Purpose
Review Night Files diagnostic signals and identify failures without silently overriding safeguards.

## Inputs
- Rendered video diagnostics
- Story/fact-lock results
- Visual QA results
- Duration/audio/render checks
- Packaging readiness signals

## Outputs
- PASS/FAIL/REVIEW assessment by category
- Concrete failure reasons
- Suggested remediation stage
- Evidence supporting each finding

## Responsibilities
- Check factual, visual, duration, audio, caption, and publishing-readiness signals.
- Identify the earliest failing stage when possible.
- Keep QA report-oriented.
- Preserve the existing production quality gates.

## Constraints
- Never silently override a failed safeguard.
- Never mark an unverified claim as verified.
- Never delete or publish a video.
- Never make Ruflo failure block production while Ruflo remains optional.
