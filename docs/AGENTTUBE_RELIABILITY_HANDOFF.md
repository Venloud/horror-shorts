# AgentTube reliability experiment — Night Files (2026-10-08)

## WHY
AgentTube (https://github.com/darkzOGx/youtube-automation-agent) describes per-scene repair, persistent checkpoints, readiness probes, narration timing repair, and analytics-driven feedback. Night Files already has narration/image checkpoints in `pipeline/checkpoint.py`, an FFmpeg renderer, production validation, and `pipeline/analytics.py`. Replacing those would risk the live twice-daily pipeline. What is missing is an inspectable per-scene repair plan that preserves unaffected scenes.

## HOW
Isolated branch `experiment/agenttube-reliability`, no changes to `main`, scheduling, buffer, publishing, or production entrypoints.

- `pipeline/scene_repair.py inspect --story output/.../story.json --workdir output/...` produces a scene manifest with narration fingerprints and visual presence.
- `pipeline/scene_repair.py invalidate --manifest output/.../scene_repair_manifest.json --scene 3 --part visual` flags **only** the requested scene for regeneration.
- `tests/test_scene_repair.py` covers inventory, targeted invalidation, and invalid indices.
- No AgentTube code copied: adapted the architectural pattern with Python standard library.

## DID IT WORK?
Implementation committed on experimental branch. Offline test code added, but no GitHub Actions run or live video render verified as of this handoff. This is **bookkeeping only**, not a complete scene regeneration engine. It does not yet rewrite scene clips, re-time regenerated narration, change FFmpeg assembly, or enforce new QA gates.

## NEXT STEPS FOR CLAUDE / VANDAM / OTHER AGENTS
1. Run `python -m unittest discover -s tests -p 'test_scene_repair.py'` on the branch. Fix any failures.
2. Check real Night Files scene image naming and asset locations; current detection is provisional and may not match production filenames.
3. Extend the manifest with actual shot/clip paths, per-scene timings, hashes, and ffprobe media validation.
4. Add an opt-in scene re-render command that updates just the selected scene, then recomputes narration/caption timings. Validate assembled MP4 before considering integration.
5. Compare existing `checkpoint.py`, `render.qa_gate`, and `analytics.py` before changing anything. Avoid duplicate mechanisms.
6. Only merge after non-publishing render tests and explicit owner review. Keep Night Files production behavior unchanged.

## GUARDRAILS
Never alter production main, daily workflow, buffer, or publishing as part of this experiment. No simulated success claims. Log why a change was made, how it works, and whether it passed actual tests. Don't confuse a scene invalidation marker with scene regeneration.
